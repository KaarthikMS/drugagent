"""
AgentCore Runtime entrypoint.

Thin by design. This file owns the request lifecycle -- instrumentation,
timing, failure accounting -- and nothing else. Routing, grounding and
every safety decision live below it, where they can be tested without a
runtime, a model, or an AWS account.

No prompt text, answer text or lab value is logged here or anywhere
else. Those are health data about an identifiable employee, and a log
line is the easiest place in a system to leak them (D7). Logs carry
event ids, durations and outcomes.
"""

from __future__ import annotations

import time

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from observability import cw_metrics, logger, metrics, tracer

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload, context):
    prompt = payload.get("prompt", "")

    metrics.request_counter.add(1)
    metrics.active_sessions.add(1)
    cw_metrics.put_metric("AgentRequests", 1)
    start = time.perf_counter()

    with tracer.start_as_current_span("agent.invoke") as span:
        # Length, never content. A prompt length is a number; a prompt
        # is a health question belonging to a named employee.
        span.set_attribute("prompt.length", len(prompt))

        try:
            response = await _handle(prompt)
            metrics.success_counter.add(1)
            cw_metrics.put_metric("AgentSuccess", 1)
            span.set_attribute("agent.success", True)
            yield response

        except Exception as exc:
            metrics.failure_counter.add(1)
            cw_metrics.put_metric("AgentFailure", 1)
            # exception() records the type and traceback. Neither
            # carries the prompt, and neither may be allowed to.
            logger.exception("agent invocation failed")
            span.record_exception(exc)
            span.set_attribute("agent.success", False)
            raise

        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            metrics.request_latency.record(elapsed_ms)
            metrics.active_sessions.add(-1)
            cw_metrics.put_metric("AgentLatency", elapsed_ms, unit="Milliseconds")
            logger.info("request completed in %.2f ms", elapsed_ms)


async def _handle(prompt: str) -> str:
    """The pipeline: tripwire -> guardrails -> agent -> severity gate.

    Assembled in step 6 of docs/implementation-plan.md, once the agent
    and the domain layer it depends on exist. Until then this refuses
    rather than answers -- degrading to "I cannot answer" is the correct
    failure mode in this domain, and it is the correct placeholder too.
    """
    raise NotImplementedError("agent pipeline is assembled in step 6")


if __name__ == "__main__":
    app.run()

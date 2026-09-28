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

from agents.pipeline import handle
from domain.response import render
from observability import cw_metrics, logger, metrics, tracer
from utils import Clients

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
            # Severity is a category, not content -- safe to trace, and
            # it is the field you want when reading back why a response
            # escalated.
            span.set_attribute("agent.severity", response["severity"])
            cw_metrics.put_metric("AgentEscalated", 1 if response["escalation"] else 0)
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


_clients: Clients | None = None


def _get_clients() -> Clients:
    """Connection pools, created once per process.

    Per-request clients would discard pooling and TLS session reuse,
    which on these APIs costs more than the requests themselves.
    """
    global _clients
    if _clients is None:
        _clients = Clients()
    return _clients


async def _handle(prompt: str) -> dict:
    """Answer one question, as structured fields.

    Fields rather than rendered text, because the caller has to be able
    to style the escalation block differently from the answer. An
    escalation rendered as ordinary prose is an escalation people skim
    past, and that decision belongs to whatever is displaying it.

    `rendered` is included for callers that cannot lay out fields --
    a CLI, a log line, a Slack message.
    """
    response = await handle(prompt, _get_clients())
    return {
        "answer": response.answer,
        "severity": response.severity.value,
        "escalation": response.escalation,
        "caveats": list(response.caveats),
        "citations": [
            {"title": c.title, "url": c.url, "jurisdiction": c.jurisdiction}
            for c in response.citations
        ],
        "requires_confirmation": response.requires_confirmation,
        "rendered": render(response),
    }


if __name__ == "__main__":
    app.run()

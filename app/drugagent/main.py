import time
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from observability import logger, tracer, request_counter, success_counter, failure_counter, request_latency, active_sessions, cw_metrics

app = BedrockAgentCoreApp()
log = app.logger

_orchestrator = None


def get_orchestrator():
    global _orchestrator

    if _orchestrator is None:
        from orchestrator.orchestrator import AgentOrchestrator

        _orchestrator = AgentOrchestrator()

    return _orchestrator

# --------------------------------------------------------------------
# Agent Entry Point
# --------------------------------------------------------------------

@app.entrypoint
async def invoke(payload, context):
    prompt = payload.get("prompt", "")
    request_counter.add(1)
    active_sessions.add(1)
    cw_metrics.put_metric("AgentRequests", 1)
    cw_metrics.put_metric("ActiveSessions", 1)
    start = time.perf_counter()
    logger.info(f"Incoming request: {prompt}")

    with tracer.start_as_current_span("Agent Invocation") as span:
        span.set_attribute("agent.name", "pharma-orchestrator")
        span.set_attribute("prompt.length", len(prompt))

        try:
            response = await get_orchestrator().invoke(prompt)
            success_counter.add(1)
            cw_metrics.put_metric("AgentSuccess", 1)
            span.set_attribute("agent.success", True)
            yield response

        except Exception as ex:
            failure_counter.add(1)
            cw_metrics.put_metric("AgentFailure", 1)
            logger.exception("Agent invocation failed")
            span.record_exception(ex)
            span.set_attribute("agent.success", False)
            raise

        finally:
            elapsed = (time.perf_counter() - start) * 1000
            request_latency.record(elapsed)
            active_sessions.add(-1)
            cw_metrics.put_metric("ActiveSessions", 0)
            cw_metrics.put_metric("AgentLatency", elapsed, unit="Milliseconds")
            logger.info(f"Request completed in {elapsed:.2f} ms")


if __name__ == "__main__":
    app.run()

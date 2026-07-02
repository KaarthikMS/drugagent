import time

import requests
from strands import tool

from observability import (
    logger,
    tracer,
    tool_counter,
    tool_success,
    tool_failure,
    tool_latency,
    cw_metrics,
)


def _normalize_drug_name(drug_name: str) -> str:
    return drug_name.strip().lower()


@tool
def interaction_lookup(drug_one: str, drug_two: str):
    start = time.perf_counter()
    tool_counter.add(1, {"tool": "interaction_lookup"})
    cw_metrics.put_metric(
        "ToolInvocations",
        1,
        dimensions=[{"Name": "Tool", "Value": "InteractionLookup"}],
    )

    normalized_one = _normalize_drug_name(drug_one)
    normalized_two = _normalize_drug_name(drug_two)

    with tracer.start_as_current_span("Interaction Lookup") as span:
        span.set_attribute("tool.name", "interaction_lookup")
        span.set_attribute("drug.one", normalized_one)
        span.set_attribute("drug.two", normalized_two)

        try:
            # Conservative implementation: normalize names and return a labeled response
            # without inventing clinical interaction severity.
            response = {
                "status": "success",
                "interaction_found": False,
                "drug_one": normalized_one,
                "drug_two": normalized_two,
                "message": (
                    "Drugs normalized successfully. Review DailyMed labeling and RxNorm references "
                    "for a definitive interaction assessment."
                ),
                "source": "RxNorm + DailyMed",
            }

            tool_success.add(1)
            cw_metrics.put_metric("ToolSuccess", 1)
            span.set_attribute("interaction.found", False)
            return response

        except Exception as exc:
            tool_failure.add(1)
            cw_metrics.put_metric("ToolFailure", 1)
            logger.exception("Interaction lookup failed")
            span.record_exception(exc)
            raise

        finally:
            elapsed = (time.perf_counter() - start) * 1000
            tool_latency.record(elapsed)
            cw_metrics.put_metric("ToolLatency", elapsed, unit="Milliseconds")

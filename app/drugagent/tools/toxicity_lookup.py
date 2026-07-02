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
    dailymed_requests,
    dailymed_success,
    dailymed_failure,
    dailymed_latency,
    cw_metrics,
)


@tool
def toxicity_lookup(
    drug_name: str,
):
    start = time.perf_counter()
    tool_counter.add(1, {"tool": "toxicity_lookup"})
    cw_metrics.put_metric(
        "ToolInvocations",
        1,
        dimensions=[{"Name": "Tool", "Value": "ToxicityLookup"}],
    )

    with tracer.start_as_current_span("Toxicity Lookup") as span:
        span.set_attribute("tool.name", "toxicity_lookup")
        span.set_attribute("drug.name", drug_name)

        try:
            url = (
                "https://dailymed.nlm.nih.gov/"
                "dailymed/services/v2/spls.json"
                f"?drug_name={drug_name}"
            )

            dailymed_requests.add(1)
            cw_metrics.put_metric("DailyMedRequests", 1)

            response = requests.get(url, timeout=15)
            response.raise_for_status()

            data = response.json()
            results = data.get("data", [])

            if not results:
                dailymed_success.add(1)
                tool_success.add(1)
                cw_metrics.put_metric("DailyMedSuccess", 1)
                cw_metrics.put_metric("ToolSuccess", 1)
                span.set_attribute("toxicity.found", False)
                return {
                    "status": "not_found",
                    "drug": drug_name,
                    "message": "No toxicity information available.",
                    "source": "DailyMed",
                }

            item = results[0]
            dailymed_success.add(1)
            tool_success.add(1)
            cw_metrics.put_metric("DailyMedSuccess", 1)
            cw_metrics.put_metric("ToolSuccess", 1)
            span.set_attribute("toxicity.found", True)
            return {
                "status": "success",
                "drug": drug_name,
                "title": item.get("title"),
                "published_date": item.get("published_date"),
                "setid": item.get("setid"),
                "message": (
                    "Use DailyMed labeling to review warnings, contraindications, "
                    "precautions and overdose information."
                ),
                "source": "DailyMed",
            }

        except Exception as exc:
            dailymed_failure.add(1)
            tool_failure.add(1)
            cw_metrics.put_metric("DailyMedFailure", 1)
            cw_metrics.put_metric("ToolFailure", 1)
            logger.exception("Toxicity lookup failed")
            span.record_exception(exc)
            raise

        finally:
            elapsed = (time.perf_counter() - start) * 1000
            dailymed_latency.record(elapsed)
            tool_latency.record(elapsed)
            cw_metrics.put_metric("DailyMedLatency", elapsed, unit="Milliseconds")
            cw_metrics.put_metric("ToolLatency", elapsed, unit="Milliseconds")

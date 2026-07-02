import time

import requests
from strands import tool

from opentelemetry.trace import Status, StatusCode

from observability import (
    logger,
    tracer,

    # OpenTelemetry Metrics
    tool_counter,
    tool_success,
    tool_failure,
    tool_latency,

    dailymed_requests,
    dailymed_success,
    dailymed_failure,
    dailymed_latency,

    drug_found,
    drug_not_found,

    # CloudWatch Metrics
    cw_metrics,
)

DRUG_ALIASES = {
    "paracetamol": "acetaminophen",
    "zinc sulphate": "zinc sulfate",
    "co-trimoxazole": "sulfamethoxazole trimethoprim",
}


def normalize_drug_name(drug_name: str):

    return DRUG_ALIASES.get(
        drug_name.strip().lower(),
        drug_name.strip().lower(),
    )


def find_best_match(
    normalized_name: str,
    matches: list,
):

    if not matches:
        return None

    exact_matches = []

    for item in matches:

        title = item.get(
            "title",
            "",
        ).lower()

        if normalized_name in title:
            exact_matches.append(item)

    if exact_matches:
        return exact_matches[0]

    return matches[0]


@tool
def drug_lookup(drug_name: str):

    overall_start = time.perf_counter()

    normalized_name = normalize_drug_name(
        drug_name
    )

    # ----------------------------------------------------
    # OpenTelemetry Metrics
    # ----------------------------------------------------

    tool_counter.add(
        1,
        {
            "tool": "drug_lookup",
        },
    )

    # ----------------------------------------------------
    # CloudWatch Metrics
    # ----------------------------------------------------

    cw_metrics.put_metric(
        "ToolInvocations",
        1,
        dimensions=[
            {
                "Name": "Tool",
                "Value": "DrugLookup",
            }
        ],
    )

    with tracer.start_as_current_span(
        "Drug Lookup"
    ) as span:

        span.set_attribute(
            "tool.name",
            "drug_lookup",
        )

        span.set_attribute(
            "drug.original",
            drug_name,
        )

        span.set_attribute(
            "drug.normalized",
            normalized_name,
        )

        span.add_event(
            "Drug lookup started"
        )

        logger.info(
            f"Looking up drug '{normalized_name}'"
        )

        try:

            # ----------------------------------------
            # DailyMed Request
            # ----------------------------------------

            dailymed_requests.add(1)

            cw_metrics.put_metric(
                "DailyMedRequests",
                1,
            )

            api_start = time.perf_counter()

            url = (
                "https://dailymed.nlm.nih.gov/"
                "dailymed/services/v2/spls.json"
                f"?drug_name={normalized_name}"
            )

            span.add_event(
                "Calling DailyMed API"
            )

            response = requests.get(
                url,
                timeout=15,
            )

            response.raise_for_status()

            api_latency = (
                time.perf_counter()
                - api_start
            ) * 1000

            dailymed_latency.record(
                api_latency
            )

            dailymed_success.add(1)

            cw_metrics.put_metric(
                "DailyMedSuccess",
                1,
            )

            cw_metrics.put_metric(
                "DailyMedLatency",
                api_latency,
                unit="Milliseconds",
            )

            span.set_attribute(
                "dailymed.latency_ms",
                api_latency,
            )

            span.add_event(
                "DailyMed response received"
            )

            data = response.json()

            matches = data.get(
                "data",
                [],
            )

            # ----------------------------------------
            # Drug NOT Found
            # ----------------------------------------

            if not matches:

                drug_not_found.add(1)

                tool_success.add(1)

                cw_metrics.put_metric(
                    "DrugNotFound",
                    1,
                )

                cw_metrics.put_metric(
                    "ToolSuccess",
                    1,
                )

                span.set_attribute(
                    "drug.found",
                    False,
                )

                logger.info(
                    f"No match found for '{normalized_name}'"
                )

                return {
                    "drug": drug_name,
                    "normalized_name": normalized_name,
                    "found": False,
                    "message": "Drug not found",
                    "source": "DailyMed",
                }

            # ----------------------------------------
            # Drug Found
            # ----------------------------------------

            selected = find_best_match(
                normalized_name,
                matches,
            )

            drug_found.add(1)

            tool_success.add(1)

            cw_metrics.put_metric(
                "DrugFound",
                1,
            )

            cw_metrics.put_metric(
                "ToolSuccess",
                1,
            )

            span.set_attribute(
                "drug.found",
                True,
            )

            span.set_attribute(
                "drug.title",
                selected.get(
                    "title",
                    "",
                ),
            )

            span.add_event(
                "Drug match found"
            )

            logger.info(
                f"Drug found: {selected.get('title')}"
            )

            return {
                "drug": drug_name,
                "normalized_name": normalized_name,
                "found": True,
                "title": selected.get("title"),
                "setid": selected.get("setid"),
                "published_date": selected.get(
                    "published_date"
                ),
                "source": "DailyMed",
            }

        except Exception as ex:

            tool_failure.add(1)

            dailymed_failure.add(1)

            cw_metrics.put_metric(
                "ToolFailure",
                1,
            )

            cw_metrics.put_metric(
                "DailyMedFailure",
                1,
            )

            logger.exception(
                "Drug lookup failed"
            )

            span.record_exception(
                ex
            )

            span.set_status(
                Status(
                    StatusCode.ERROR
                )
            )

            span.set_attribute(
                "tool.error",
                True,
            )

            return {
                "drug": drug_name,
                "found": False,
                "error": str(ex),
                "source": "DailyMed",
            }

        finally:

            elapsed = (
                time.perf_counter()
                - overall_start
            ) * 1000

            tool_latency.record(
                elapsed,
                {
                    "tool": "drug_lookup",
                },
            )

            cw_metrics.put_metric(
                "ToolLatency",
                elapsed,
                unit="Milliseconds",
            )

            span.set_attribute(
                "tool.latency_ms",
                elapsed,
            )

            span.add_event(
                "Drug lookup completed"
            )

            logger.info(
                f"Drug lookup completed in {elapsed:.2f} ms"
            )
"""
CloudWatch custom metrics.

Numbers only. Metric names and dimension values are chosen so that no
dimension can ever carry content -- a drug name as a dimension value
would publish what an identifiable employee asked about, at a cardinality
CloudWatch charges for besides (D7).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class CloudWatchMetrics:
    def __init__(self) -> None:
        self.client = None
        self.namespace = "PharmaAgent"

    def _get_client(self):
        # boto3 is imported on first use, not at module import. The
        # runtime's cold start pays for every top-level import, and a
        # process that never emits a metric should never pay for this.
        if self.client is None:
            import boto3

            self.client = boto3.client("cloudwatch")
        return self.client

    def put_metric(
        self,
        metric_name: str,
        value: float,
        unit: str = "Count",
        dimensions: list[dict[str, Any]] | None = None,
    ) -> None:
        """Publish one metric. Never raises.

        Telemetry failing must not fail the request that produced it --
        but it must not vanish either. The exception is logged with its
        type and the metric name, so a CloudWatch outage or a missing IAM
        permission is visible rather than silent.
        """
        metric: dict[str, Any] = {
            "MetricName": metric_name,
            "Timestamp": datetime.now(timezone.utc),
            "Value": value,
            "Unit": unit,
        }

        if dimensions:
            metric["Dimensions"] = dimensions

        try:
            self._get_client().put_metric_data(
                Namespace=self.namespace,
                MetricData=[metric],
            )
        except Exception:
            logger.warning("metric publish failed: %s", metric_name, exc_info=True)


cw_metrics = CloudWatchMetrics()

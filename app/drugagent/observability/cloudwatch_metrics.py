from datetime import datetime, timezone


class CloudWatchMetrics:

    def __init__(self):
        self.client = None
        self.namespace = "PharmaAgent"

    def _get_client(self):
        if self.client is None:
            import boto3

            self.client = boto3.client("cloudwatch")
        return self.client

    def put_metric(
        self,
        metric_name,
        value,
        unit="Count",
        dimensions=None,
    ):

        print(f"[CloudWatch] {metric_name} = {value}")

        metric = {
            "MetricName": metric_name,
            "Timestamp": datetime.now(timezone.utc),
            "Value": value,
            "Unit": unit,
        }

        if dimensions:
            metric["Dimensions"] = dimensions

        try:

            response = self._get_client().put_metric_data(
                Namespace=self.namespace,
                MetricData=[metric],
            )

            print(response)

        except Exception as e:

            print(f"[CloudWatch ERROR] {e}")


cw_metrics = CloudWatchMetrics()

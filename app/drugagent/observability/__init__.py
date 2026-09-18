"""
Observability: structured logs, traces and CloudWatch metrics.

Re-exported here so callers import from one place. Names are listed in
__all__ rather than imported implicitly -- a star import gives the
linter nothing to check and the reader nothing to look up.

Content never passes through this layer. Prompts, answers and lab values
are health data about an identifiable employee; logs carry event ids,
tool names, latency, severity and outcome (D7).
"""

from . import metrics
from .cloudwatch_metrics import cw_metrics
from .logger import logger
from .tracing import tracer

__all__ = ["cw_metrics", "logger", "metrics", "tracer"]

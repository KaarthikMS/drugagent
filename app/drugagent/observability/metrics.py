from opentelemetry import metrics

#
# AgentCore Runtime already creates the MeterProvider.
# Never create or override it.
#

meter = metrics.get_meter("drug-agent")

# ===========================================================
# Agent Metrics
# ===========================================================

request_counter = meter.create_counter(
    "agent_requests",
    description="Total agent requests",
)

success_counter = meter.create_counter(
    "agent_success"
)

failure_counter = meter.create_counter(
    "agent_failure"
)

active_sessions = meter.create_up_down_counter(
    "active_sessions"
)

request_latency = meter.create_histogram(
    "agent_latency_ms"
)

# ===========================================================
# Bedrock Metrics
# ===========================================================

bedrock_counter = meter.create_counter(
    "bedrock_invocations"
)

bedrock_latency = meter.create_histogram(
    "bedrock_latency_ms"
)

# ===========================================================
# Tool Metrics
# ===========================================================

tool_counter = meter.create_counter(
    "tool_invocations"
)

tool_success = meter.create_counter(
    "tool_success"
)

tool_failure = meter.create_counter(
    "tool_failure"
)

tool_latency = meter.create_histogram(
    "tool_latency_ms"
)

# ===========================================================
# DailyMed Metrics
# ===========================================================

dailymed_requests = meter.create_counter(
    "dailymed_requests"
)

dailymed_success = meter.create_counter(
    "dailymed_success"
)

dailymed_failure = meter.create_counter(
    "dailymed_failure"
)

dailymed_latency = meter.create_histogram(
    "dailymed_latency_ms"
)

# ===========================================================
# Business Metrics
# ===========================================================

drug_found = meter.create_counter(
    "drug_found"
)

drug_not_found = meter.create_counter(
    "drug_not_found"
)

# ===========================================================
# Token Metrics
# ===========================================================

prompt_tokens = meter.create_counter(
    "prompt_tokens"
)

completion_tokens = meter.create_counter(
    "completion_tokens"
)

total_tokens = meter.create_counter(
    "total_tokens"
)
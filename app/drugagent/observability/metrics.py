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

success_counter = meter.create_counter("agent_success")

failure_counter = meter.create_counter("agent_failure")

active_sessions = meter.create_up_down_counter("active_sessions")

request_latency = meter.create_histogram("agent_latency_ms")

# Deliberately NOT defined here: per-tool, per-Bedrock-call and token
# counters. Nothing emitted them, and a metric nothing emits is a
# dashboard panel that reads zero forever. Token usage is already
# published by the Strands OTel integration as
# `gen_ai.client.token.usage`, which is what the CDK dashboard plots.
#
# Add a counter back beside the code that increments it, not before.

"""
Bedrock model construction.

The model id is not written here. It lives in config.py, where it is one
constant with an environment override -- so the release model can be
chosen on evaluation evidence without touching code, and so this file
does not silently carry an id that was current a year ago.
"""

from __future__ import annotations

from strands.models.bedrock import BedrockModel

from config import (
    BEDROCK_REGION,
    GUARDRAIL_ID,
    GUARDRAIL_VERSION,
    MODEL_ID,
    MODEL_MAX_TOKENS,
    MODEL_TEMPERATURE,
)

# Shown to the user when a guardrail stops a request. Deliberately the
# same shape as every other refusal in this system: say what cannot be
# done, name what can, and point at a clinician.
GUARDRAIL_BLOCKED_INPUT = (
    "I can't help with that one. I can explain what a medicine or condition "
    "is, check whether an interaction is documented, and read lab results -- "
    "but I can't diagnose, recommend or change treatment, or give an opinion "
    "about someone else. Please speak to a doctor or pharmacist. If this is "
    "urgent, call 112."
)


def load_model() -> BedrockModel:
    """The chat model.

    MODEL_ID is an INFERENCE PROFILE id, not a bare model id. Most
    current models in ap-south-1 support only INFERENCE_PROFILE and
    reject the bare id with "on-demand throughput isn't supported".
    """
    config: dict = {
        "model_id": MODEL_ID,
        "region_name": BEDROCK_REGION,
        "temperature": MODEL_TEMPERATURE,
        "max_tokens": MODEL_MAX_TOKENS,
    }

    # Attached at construction only when configured, so local
    # development runs without one. The Python safety layer -- tripwire,
    # triage, severity gate -- is unaffected either way: it is the
    # guarantee, and the guardrail is a filter in front of it.
    if GUARDRAIL_ID:
        config.update(
            guardrail_id=GUARDRAIL_ID,
            guardrail_version=GUARDRAIL_VERSION,
            # "enabled" puts the assessment in the response, so a block
            # is visible in traces rather than an unexplained refusal.
            guardrail_trace="enabled",
            guardrail_redact_input=True,
            guardrail_redact_input_message=GUARDRAIL_BLOCKED_INPUT,
        )

    return BedrockModel(**config)

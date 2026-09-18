"""
Bedrock model construction.

The model id is not written here. It lives in config.py, where it is one
constant with an environment override -- so the release model can be
chosen on evaluation evidence without touching code, and so this file
does not silently carry an id that was current a year ago.
"""

from __future__ import annotations

from strands.models.bedrock import BedrockModel

from config import BEDROCK_REGION, MODEL_ID, MODEL_MAX_TOKENS, MODEL_TEMPERATURE


def load_model() -> BedrockModel:
    """The chat model.

    MODEL_ID is an INFERENCE PROFILE id, not a bare model id. Most
    current models in ap-south-1 support only INFERENCE_PROFILE and
    reject the bare id with "on-demand throughput isn't supported".
    """
    return BedrockModel(
        model_id=MODEL_ID,
        region_name=BEDROCK_REGION,
        temperature=MODEL_TEMPERATURE,
        max_tokens=MODEL_MAX_TOKENS,
    )

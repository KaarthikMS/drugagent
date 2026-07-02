from strands.models.bedrock import BedrockModel


def load_model() -> BedrockModel:
    return BedrockModel(
        model_id="anthropic.claude-3-haiku-20240307-v1:0"
    )
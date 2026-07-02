from tools.toxicity_lookup import toxicity_lookup

from prompts.toxicology_prompt import (
    TOXICOLOGY_SYSTEM_PROMPT,
)

from .base_agent import BaseAgent


_agent = None


def get_toxicology_agent():

    global _agent

    if _agent is None:

        _agent = BaseAgent(

            system_prompt=TOXICOLOGY_SYSTEM_PROMPT,

            tools=[toxicity_lookup],

        )

    return _agent
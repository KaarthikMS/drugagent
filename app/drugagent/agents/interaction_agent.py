from tools.interaction_lookup import interaction_lookup

from prompts.interaction_prompt import (
    INTERACTION_SYSTEM_PROMPT,
)

from .base_agent import BaseAgent


_agent = None


def get_interaction_agent():

    global _agent

    if _agent is None:

        _agent = BaseAgent(

            system_prompt=INTERACTION_SYSTEM_PROMPT,

            tools=[interaction_lookup],

        )

    return _agent
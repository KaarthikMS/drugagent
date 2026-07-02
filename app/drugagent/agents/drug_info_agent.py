from tools.drug_lookup import drug_lookup

from prompts.drug_info_prompt import PHARMA_SYSTEM_PROMPT

from .base_agent import BaseAgent


_agent = None


def get_drug_info_agent():

    global _agent

    if _agent is None:

        _agent = BaseAgent(

            system_prompt=PHARMA_SYSTEM_PROMPT,

            tools=[drug_lookup],

        )

    return _agent
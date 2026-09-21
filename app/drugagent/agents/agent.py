"""
Agent assembly.

One agent, eight tools. Not an orchestrator with specialists: tool
selection is what a tool-calling model is for, and the classifier this
replaced routed on substrings -- "what is metformin used for with
diabetes" matched both a drug keyword and an interaction keyword,
invoked two agents, and paid for two model calls on a substring match.

The agent is constructed per request because its tools are bound to a
per-request context (severity floors, citations, caveats collected as
tools run). The MODEL is process-wide and reused; only the cheap wrapper
is rebuilt.
"""

from __future__ import annotations

from functools import lru_cache

from strands import Agent

from models.load import load_model
from prompts import SYSTEM_PROMPT
from tools import ToolContext, build_tools


@lru_cache(maxsize=1)
def _model():
    """The Bedrock model, built once per process.

    Constructing it per request would rebuild a boto3 client each time
    and throw away connection reuse on the slowest call in the path.
    """
    return load_model()


def build_agent(context: ToolContext) -> Agent:
    """An agent bound to one request's tool context."""
    return Agent(
        model=_model(),
        system_prompt=SYSTEM_PROMPT,
        tools=build_tools(context),
    )

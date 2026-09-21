"""
The request pipeline.

    tripwire -> agent (+ tools) -> severity gate -> response

Separated from main.py so it can be run without the AgentCore runtime --
by a test, by the local dashboard, or by a script. The entrypoint owns
instrumentation; this owns the sequence.

The tripwire runs FIRST, before the model and before any redaction,
because redaction can remove the very words it matches on.
"""

from __future__ import annotations

from domain.models import AgentResponse, Severity
from domain.response import assemble
from domain.severity import check_tripwire
from tools import ToolContext
from utils import Clients


async def handle(prompt: str, clients: Clients) -> AgentResponse:
    """Answer one question. Never raises for an empty prompt."""
    if not prompt.strip():
        return assemble(
            "Ask me about a medicine, a condition, symptoms you have, or "
            "paste lab results.",
            model_severity=Severity.INFORMATIONAL,
        )

    tripwire = check_tripwire(prompt)
    context = ToolContext(clients=clients)

    # Imported here so the module can be imported without boto3 present
    # -- the domain tests must not need AWS to run.
    from agents.agent import build_agent

    agent = build_agent(context)
    result = await agent.invoke_async(prompt)

    return assemble(
        str(result),
        tripwire=tripwire,
        tool_floors=context.severity_floors,
        citations=context.citations,
        caveats=context.caveats,
        tools_used=context.tools_used,
        confirmation=context.confirmations[0] if context.confirmations else None,
    )

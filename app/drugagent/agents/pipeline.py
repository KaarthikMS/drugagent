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

from config import MAX_PROMPT_CHARS
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
            grounding=["greeting"],
        )

    if len(prompt) > MAX_PROMPT_CHARS:
        # Rejected before the tripwire and before the model. An
        # over-length prompt is not a question to be understood; it is
        # input to be refused, and refusing it here means no caller can
        # skip the check.
        return assemble(
            f"That message is too long ({len(prompt):,} characters). "
            f"Please keep it under {MAX_PROMPT_CHARS:,} — about one lab "
            "report or a few paragraphs. If you are pasting results, send "
            "one panel at a time.",
            model_severity=Severity.INFORMATIONAL,
            grounding=["length_check"],
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
        grounding=context.grounding,
        confirmation=context.confirmations[0] if context.confirmations else None,
    )

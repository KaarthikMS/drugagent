"""
Response assembly: the last thing that happens, and the part the model
cannot influence.

The model produces prose. This turns that prose into the response the
user sees, by attaching everything that must be present regardless of
what the model wrote:

    severity      the maximum across every component (D5)
    escalation    appended, or placed FIRST for an emergency
    caveats       whatever the tools required be said
    citations     what the answer is allowed to rest on

Placing the emergency block first is not formatting. Someone reading
urgent guidance under three paragraphs of drug information may not reach
it.
"""

from __future__ import annotations

import re

from domain.models import AgentResponse, Citation, Severity

# Some models wrap their output in pseudo-XML -- <thinking> reasoning,
# then <response> the answer. It is not part of the answer and reaches
# the user verbatim if left alone. Reasoning is DISCARDED rather than
# shown: it is unreviewed text that reads with the same authority as the
# grounded answer beside it.
_THINKING = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)
_WRAPPER = re.compile(r"</?(response|answer|output)>", re.IGNORECASE)


def clean(text: str) -> str:
    """Strip model scaffolding from an answer."""
    text = _THINKING.sub("", text)
    text = _WRAPPER.sub("", text)
    return text.strip()


from domain.severity import TripwireHit, escalation_text, max_severity

# Returned whenever the model answered without consulting a single
# tool. Written here, in code, for the same reason the escalation text
# is: a scope rule in the prompt is a suggestion, and this one was
# already ignored -- the assistant explained a Strands API and debugged
# a Python function before this check existed.
OFF_SCOPE_MESSAGE = (
    "I can only help with health questions -- medicines, conditions, "
    "symptoms, drug interactions, and lab results. I don't have anything "
    "reliable to say about this, so I'd rather not guess.\n\n"
    "Try asking me about a medicine (Indian brand names work), whether two "
    "medicines can be taken together, what a condition is, symptoms you're "
    "having, or paste lab results."
)


def assemble(
    answer: str,
    *,
    tripwire: TripwireHit | None = None,
    model_severity: Severity | None = None,
    tool_floors: list[Severity] | None = None,
    citations: list[Citation] | None = None,
    caveats: list[str] | None = None,
    confirmation: str | None = None,
    tools_used: list[str] | None = None,
) -> AgentResponse:
    """Combine everything into the final response.

    Severity is the maximum of the tripwire, the model's own judgement,
    and every floor a tool raised. No input can lower another, which is
    what lets each component stay ignorant of the others.

    An answer produced with NO tool call is replaced. Every question this
    system is for reaches at least one tool; a question that reaches none
    was answered from the model's own memory, which is ungrounded by
    definition and is also exactly what an off-topic answer looks like.
    Checking for tool use catches both with one rule, and unlike a list
    of banned subjects it needs no guess about what people will ask.

    The exception is a confirmation request -- "did you mean metformin?"
    is a legitimate reply with nothing looked up yet.
    """
    severity = max_severity(
        tripwire.floor if tripwire else None,
        model_severity,
        *(tool_floors or []),
    )

    reason = tripwire.reason if tripwire else None
    escalation = escalation_text(severity, reason)

    grounded = bool(tools_used) or confirmation is not None
    # The escalation is NOT dropped along with the answer. If the
    # tripwire fired, the urgent guidance stands regardless of whether
    # the model managed to look anything up.
    body = clean(answer) if grounded else OFF_SCOPE_MESSAGE

    return AgentResponse(
        answer=body,
        severity=severity,
        citations=tuple(citations or ()) if grounded else (),
        escalation=escalation,
        caveats=tuple(caveats or ()) if grounded else (),
        requires_confirmation=confirmation,
    )


def render(response: AgentResponse) -> str:
    """Flatten a response to text, for clients that cannot render fields.

    Emergency guidance goes above the answer; everything else below it.
    """
    parts: list[str] = []

    if response.severity is Severity.EMERGENCY and response.escalation:
        parts.append(f"**{response.escalation}**")

    parts.append(response.answer)

    if response.severity is not Severity.EMERGENCY and response.escalation:
        parts.append(response.escalation)

    for caveat in response.caveats:
        parts.append(f"_{caveat}_")

    if response.citations:
        sources = "\n".join(
            f"- [{c.title}]({c.url})" for c in response.citations if c.url
        )
        if sources:
            parts.append(f"**Sources**\n{sources}")

    return "\n\n".join(p for p in parts if p and p.strip())

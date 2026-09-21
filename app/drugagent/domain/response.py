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


def assemble(
    answer: str,
    *,
    tripwire: TripwireHit | None = None,
    model_severity: Severity | None = None,
    tool_floors: list[Severity] | None = None,
    citations: list[Citation] | None = None,
    caveats: list[str] | None = None,
    confirmation: str | None = None,
) -> AgentResponse:
    """Combine everything into the final response.

    Severity is the maximum of the tripwire, the model's own judgement,
    and every floor a tool raised. No input can lower another, which is
    what lets each component stay ignorant of the others.
    """
    severity = max_severity(
        tripwire.floor if tripwire else None,
        model_severity,
        *(tool_floors or []),
    )

    reason = tripwire.reason if tripwire else None
    escalation = escalation_text(severity, reason)

    return AgentResponse(
        answer=clean(answer),
        severity=severity,
        citations=tuple(citations or ()),
        escalation=escalation,
        caveats=tuple(caveats or ()),
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

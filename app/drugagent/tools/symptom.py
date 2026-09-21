"""Symptom triage: what a described symptom means, from a reviewed ruleset."""

from __future__ import annotations

from strands import tool

from domain.triage import SymptomReport, triage
from tools.registry import ToolContext


def make_symptom_triage(ctx: ToolContext):
    @tool
    async def symptom_triage(
        symptom: str,
        duration_hours: float | None = None,
        modifiers: list[str] | None = None,
    ) -> dict:
        """Assess how urgently a described symptom needs a real clinician.

        CALL THIS FIRST whenever the user describes something they are
        experiencing -- pain, fever, a rash, feeling unwell -- before
        looking anything up.

        Your job is to read their words and fill in the arguments. The
        assessment itself is not yours to make; this tool makes it.

        Args:
            symptom: the main symptom, e.g. "headache", "chest pain".
            duration_hours: how long it has lasted, in hours, if the user
                said. LEAVE THIS OUT if they did not -- do not guess. A
                missing duration is not a short one.
            modifiers: descriptive words the user used that change the
                picture: "sudden", "worst ever", "severe", "with fever",
                "vision changes", "pregnant", "spreading".

        Returns a dict with:
            urgency: informational | low | medium | high | emergency
            reasons: why. Relay these -- they explain the advice
            matched:  which rules applied
        """
        report = SymptomReport(
            symptom=symptom,
            duration_hours=duration_hours,
            modifiers=tuple(modifiers or ()),
        )
        result = triage(report)
        ctx.floor(result.floor)

        return {
            "urgency": result.floor.value,
            "reasons": list(result.reasons),
            "matched": list(result.matched),
        }

    return symptom_triage

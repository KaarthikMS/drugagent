"""Overdose and toxicity information, from three sources with caveats."""

from __future__ import annotations

import asyncio

from strands import tool

from config import MAX_SECTION_CHARS, SECTION_OVERDOSAGE, SECTION_PRESETS
from domain.models import Citation, Severity
from tools.registry import ToolContext, resolve_generic


def make_toxicity_lookup(ctx: ToolContext):
    @tool
    async def toxicity_lookup(generic_name: str) -> dict:
        """Look up overdose and adverse-effect information for a medicine.

        Use for questions about taking too much of a medicine, poisoning,
        or what its harmful effects are. Pass the GENERIC name.

        IMPORTANT: if the user says they have taken too much THEMSELVES,
        that is an emergency and is already being handled -- answer the
        urgent guidance first and keep this information brief.

        Returns a dict with:
            overdosage:       label text on overdose. Quote only from here
            adverse_reactions: label text on side effects
            reported_events:  counts of events REPORTED to FDA
            reported_events_caveat: YOU MUST INCLUDE THIS if you mention
                              reported_events at all. The counts are not
                              rates and do not show the drug caused
                              anything -- the most reported term for
                              paracetamol is "drug ineffective", and
                              "pain" is what people take it for
        """
        ctx.used("toxicity_lookup")
        generic_name = await resolve_generic(ctx, generic_name)
        label, events = await asyncio.gather(
            ctx.clients.openfda.get_label(
                generic_name,
                SECTION_PRESETS["toxicity"],
                # Most labels carry no overdosage section at all, and one
                # picked without this filter answers an overdose question
                # with no overdose text.
                require_section=SECTION_OVERDOSAGE,
            ),
            ctx.clients.openfda.event_counts(generic_name, limit=8),
        )

        # An overdose question is never merely informational, even asked
        # in the third person.
        ctx.floor(Severity.MEDIUM)

        result: dict = {"found": label is not None}
        if label:
            citation = Citation(
                title=f"{generic_name} — US prescribing information",
                url=label.source_url or "",
                jurisdiction=label.jurisdiction,
            )
            ctx.cite(citation)
            result["overdosage"] = label.sections.get("overdosage", "")[
                :MAX_SECTION_CHARS
            ]
            result["adverse_reactions"] = label.sections.get("adverse_reactions", "")[
                :MAX_SECTION_CHARS
            ]
            result["boxed_warning"] = label.sections.get("boxed_warning", "")[
                :MAX_SECTION_CHARS
            ]
            result["source"] = citation.url

        if events:
            result["reported_events"] = events.counts
            result["reported_events_caveat"] = events.caveat
            ctx.caveat(events.caveat)

        if label or events:
            ctx.ground("toxicity_lookup")

        if not label and not events:
            result["message"] = f"No toxicity information found for {generic_name}."

        return result

    return toxicity_lookup

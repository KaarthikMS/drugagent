"""Drug interaction checking. The highest-stakes tool in the set."""

from __future__ import annotations

import asyncio

from strands import tool

from config import SECTION_INTERACTIONS
from domain.interactions import cross_check
from domain.models import Citation, DrugRef
from tools.registry import ToolContext


def make_interaction_check(ctx: ToolContext):
    @tool
    async def interaction_check(drug_a: str, drug_b: str) -> dict:
        """Check whether an interaction between two medicines is documented.

        Use whenever the user asks about taking two or more medicines
        together. Pass GENERIC names from drug_normalize. For a
        combination product, call this once per ingredient.

        Returns a dict with:
            documented: true if an interaction is documented in either label
            message:    THE EXACT WORDING TO USE about whether anything was
                        found. Relay it. When documented is false it does
                        NOT mean the combination is fine, and the message
                        says so correctly
            evidence:   quoted label text. Quote only from here
            one_sided:  true if only one label could be retrieved, so the
                        check was narrower than intended
        """
        ctx.used("interaction_check")
        ref_a = DrugRef(name=drug_a)
        ref_b = DrugRef(name=drug_b)

        # Four independent fetches. Sequential awaits would multiply
        # latency by four on the query users are least patient about.
        label_a, label_b, classes_a, classes_b = await asyncio.gather(
            ctx.clients.openfda.get_label(
                drug_a, (SECTION_INTERACTIONS,), require_section=SECTION_INTERACTIONS
            ),
            ctx.clients.openfda.get_label(
                drug_b, (SECTION_INTERACTIONS,), require_section=SECTION_INTERACTIONS
            ),
            _classes(ctx, drug_a),
            _classes(ctx, drug_b),
        )

        result = cross_check(
            ref_a,
            ref_b,
            label_a.sections.get(SECTION_INTERACTIONS) if label_a else None,
            label_b.sections.get(SECTION_INTERACTIONS) if label_b else None,
            _cite(ctx, drug_a, label_a),
            _cite(ctx, drug_b, label_b),
            classes_a,
            classes_b,
        )
        ctx.floor(result.severity_floor)
        # The cross-check is grounding whichever way it came out: a
        # documented interaction quotes label text, and "not documented"
        # is itself a finding computed from two retrieved sections.
        ctx.ground("interaction_check")

        return {
            "documented": result.documented,
            "message": result.message,
            "evidence": [e.text for e in result.evidence],
            "shared_classes": list(result.shared_classes),
            "one_sided": result.one_sided,
            "sources": [e.citation.url for e in result.evidence if e.citation.url],
        }

    return interaction_check


async def _classes(ctx: ToolContext, name: str) -> tuple[str, ...]:
    """ATC class names for a drug. Empty on any failure.

    Class matching is what catches a label that warns about "NSAIDs" and
    never writes "ibuprofen". Losing it narrows the check; it must not
    fail the check.
    """
    ref = await ctx.clients.rxnorm.find_rxcui(name)
    if ref is None:
        return ()
    classes = await ctx.clients.rxclass.classes_for(ref.rxcui)
    return tuple(c.name for c in classes)


def _cite(ctx: ToolContext, name: str, label) -> Citation | None:
    if label is None:
        return None
    citation = Citation(
        title=f"{name} — US prescribing information",
        url=label.source_url or "",
        jurisdiction=label.jurisdiction,
    )
    ctx.cite(citation)
    return citation

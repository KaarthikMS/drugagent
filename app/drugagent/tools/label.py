"""Drug label lookup: what the prescribing information says."""

from __future__ import annotations

from strands import tool

from config import MAX_SECTION_CHARS, SECTION_PRESETS
from domain.models import Citation
from tools.registry import ToolContext, resolve_generic


def make_drug_label_lookup(ctx: ToolContext):
    @tool
    async def drug_label_lookup(generic_name: str, topic: str = "drug_info") -> dict:
        """Retrieve the official product label text for a medicine.

        Use for questions about what a medicine is for, how it is taken,
        who should not take it, and its warnings and side effects.

        Pass the GENERIC name from drug_normalize, not a brand name.

        Args:
            generic_name: generic/active ingredient name.
            topic: "drug_info" for uses and dosing, "toxicity" for
                overdose and adverse effects, "interaction" for
                interaction text.

        Returns a dict with:
            found:    false means no label exists -- say so, and do NOT
                      answer from your own knowledge
            sections: label text by section name. Quote ONLY from here
            source:   the citation to give the user
            jurisdiction: always "US" -- state this, because the user is
                      in India and formulations differ
        """
        generic_name = await resolve_generic(ctx, generic_name)
        sections = SECTION_PRESETS.get(topic, SECTION_PRESETS["drug_info"])
        label = await ctx.clients.openfda.get_label(generic_name, sections)
        if label is None:
            return {
                "found": False,
                "message": (
                    f"No product label was found for {generic_name}. "
                    "I cannot answer this from memory."
                ),
            }

        citation = Citation(
            title=f"{generic_name} — US prescribing information",
            url=label.source_url or "",
            jurisdiction=label.jurisdiction,
            published=label.effective_time,
        )
        ctx.cite(citation)
        ctx.caveat(
            "This is the US product label. Formulations and strengths "
            "available in India can differ."
        )

        return {
            "found": True,
            # Truncated HERE, not in the client. Domain logic searches
            # the full section; only what reaches the model is capped.
            "sections": {
                name: text[:MAX_SECTION_CHARS] for name, text in label.sections.items()
            },
            "source": {"title": citation.title, "url": citation.url},
            "jurisdiction": label.jurisdiction,
        }

    return drug_label_lookup

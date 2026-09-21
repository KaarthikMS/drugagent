"""Health condition information, in consumer language."""

from __future__ import annotations

from strands import tool

from domain.models import Citation
from tools.registry import ToolContext


def make_condition_lookup(ctx: ToolContext):
    @tool
    async def condition_lookup(condition: str) -> dict:
        """Look up what a medical condition is, in plain language.

        Use for "what is X", "what causes X", "how is X treated"
        questions about diseases and conditions -- not medicines.

        For a user describing symptoms they are experiencing right now,
        call symptom_triage FIRST, then this for background.

        Returns a dict with:
            found:    false means no grounding was retrieved. Say the
                      source was unavailable; do NOT answer from memory
            topics:   title, summary and url. Quote only from summary
        """
        ctx.used("condition_lookup")
        passages = await ctx.clients.retriever.search(condition, limit=2)
        if not passages:
            return {
                "found": False,
                "message": (
                    f"No health topic was found for '{condition}'. I cannot "
                    "answer this from memory."
                ),
            }

        for passage in passages:
            ctx.cite(
                Citation(
                    title=passage.title,
                    url=passage.url,
                    jurisdiction="US (MedlinePlus)",
                )
            )

        return {
            "found": True,
            "topics": [
                {"title": p.title, "summary": p.text[:1500], "url": p.url}
                for p in passages
            ],
        }

    return condition_lookup

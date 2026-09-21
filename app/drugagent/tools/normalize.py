"""Drug name normalisation: brands, typos, and what to call a drug."""

from __future__ import annotations

from strands import tool

from domain import brands
from tools.registry import ToolContext


def make_drug_normalize(ctx: ToolContext):
    @tool
    async def drug_normalize(name: str) -> dict:
        """Resolve a medicine name to its generic/active ingredient name.

        ALWAYS call this first for any medicine the user names, before
        any other drug tool. Other tools need the generic name; brand
        names and misspellings will not match anything without this.

        Handles Indian brand names (Dolo, Crocin, Combiflam, Augmentin,
        Shelcal, Pan-D and others), US brand names, and misspellings.

        Args:
            name: the medicine name exactly as the user typed it.

        Returns a dict with:
            resolved:    true if a name was found
            ingredients: list of active ingredient names to use in other tools
            combination: true if the product contains more than one drug --
                         when true you MUST consider every ingredient
            needs_confirmation: if present, ASK THE USER this question and
                         wait for an answer before using the result
            message:     present when the name was not recognised; relay it
        """
        match = brands.resolve(name)
        if match:
            return {
                "resolved": True,
                "ingredients": list(match.ingredients),
                "combination": match.is_combination,
                "source": "Indian brand name",
                "note": match.note,
            }

        ref = await ctx.clients.rxnorm.resolve(name)
        if ref is None:
            return {
                "resolved": False,
                "ingredients": [],
                "combination": False,
                "message": brands.UNKNOWN_BRAND_MESSAGE,
            }

        result = {
            "resolved": True,
            "ingredients": [ref.name],
            "combination": False,
            "rxcui": ref.rxcui,
            "source": "RxNorm",
        }
        if ref.requires_confirmation:
            # No threshold can tell a corrected typo from a different
            # drug -- prednisone and prednisolone are closer than metfrmn
            # and metformin (D16). So the user is asked.
            question = f'You typed "{name}". Did you mean {ref.name}?'
            ctx.confirm(question)
            result["needs_confirmation"] = question
        return result

    return drug_normalize

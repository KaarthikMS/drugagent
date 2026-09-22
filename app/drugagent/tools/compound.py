"""Compound chemistry and chemical hazard data."""

from __future__ import annotations

from strands import tool

from domain.models import Citation
from tools.registry import ToolContext

PUBCHEM_URL = "https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"


def make_compound_lookup(ctx: ToolContext):
    @tool
    async def compound_lookup(name: str, include_hazards: bool = False) -> dict:
        """Look up the chemistry of a compound: formula, weight, structure.

        Use for chemistry questions -- molecular formula, molecular
        weight, structure, IUPAC name. This is NOT a source of medical
        information: it knows nothing about doses, uses or safety in
        people.

        Args:
            name: compound or drug name.
            include_hazards: set true ONLY for chemical handling hazard
                questions. The hazard data describes laboratory handling
                of the raw chemical, not taking a tablet -- if you use
                it, you must say so.

        Returns:
            found, cid, formula, weight, iupac_name, smiles, source;
            hazards and scope_note when include_hazards is true.
        """
        ctx.used("compound_lookup")
        cid = await ctx.clients.pubchem.find_cid(name)
        if cid is None:
            return {"found": False, "message": f"No compound record found for {name}."}

        compound = await ctx.clients.pubchem.get_properties(cid, name)
        citation = Citation(
            title=f"{name} — PubChem compound {cid}",
            url=PUBCHEM_URL.format(cid=cid),
            jurisdiction="international",
        )
        ctx.cite(citation)
        ctx.ground("compound_lookup")

        result = {
            "found": True,
            "cid": cid,
            "formula": compound.formula if compound else None,
            "weight": compound.weight if compound else None,
            "iupac_name": compound.iupac_name if compound else None,
            "smiles": compound.smiles if compound else None,
            "source": citation.url,
        }

        if include_hazards:
            hazard = await ctx.clients.pubchem.get_hazards(cid)
            if hazard is None:
                # "No hazard data published" is not "not hazardous".
                result["hazards"] = []
                result["hazards_note"] = (
                    "No GHS hazard classification is published for this "
                    "compound. That is not a statement that it is harmless."
                )
            else:
                result["hazards"] = hazard.statements[:5]
                result["scope_note"] = hazard.scope_note
                ctx.caveat(hazard.scope_note)

        return result

    return compound_lookup

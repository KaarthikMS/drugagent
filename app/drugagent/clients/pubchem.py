"""
PubChem: compound chemistry and hazard classification.

PubChem answers chemistry, not therapeutics. It knows ibuprofen's
molecular weight and its GHS hazard classification; it does not know
what dose is safe for a person. A GHS statement was written for handling
a laboratory reagent, and it reads alarmingly when applied to a tablet
someone is about to swallow -- so hazard data carries a scope note, the
same way FAERS counts carry a caveat.

Two base paths that are not interchangeable:
    PUG-REST  identifiers and computed properties, flat responses
    PUG-View  curated content including GHS, a nested Section tree
"""

from __future__ import annotations

from dataclasses import dataclass, field

from clients.base import HttpClient
from config import PUBCHEM_REST_URL, PUBCHEM_VIEW_URL

GHS_HEADING = "GHS Classification"

HAZARD_SCOPE_NOTE = (
    "GHS classification describes chemical handling hazards, not the effects "
    "of a medicine taken at a therapeutic dose."
)


@dataclass(frozen=True)
class Compound:
    """Chemistry for one compound."""

    cid: int
    name: str
    formula: str | None = None
    weight: str | None = None
    iupac_name: str | None = None
    smiles: str | None = None


@dataclass(frozen=True)
class Hazard:
    """GHS hazard statements, with the scope they apply to."""

    cid: int
    statements: list[str] = field(default_factory=list)
    scope_note: str = HAZARD_SCOPE_NOTE


class PubChemClient:
    def __init__(self) -> None:
        self._http = HttpClient(source="pubchem")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def find_cid(self, name: str) -> int | None:
        """Compound name -> CID. None means PubChem has no such compound."""
        data = await self._http.get_json(
            f"{PUBCHEM_REST_URL}/compound/name/{name}/cids/JSON"
        )
        cids = (data or {}).get("IdentifierList", {}).get("CID") or []
        return cids[0] if cids else None

    async def get_properties(self, cid: int, name: str = "") -> Compound | None:
        """Computed properties for a CID.

        The SMILES key is resolved by SEARCHING the response rather than
        by indexing it. PubChem renamed `CanonicalSMILES` to
        `ConnectivitySMILES` and answers a request for the old name with
        the new key and HTTP 200 -- no error, no warning. A client that
        did `props["CanonicalSMILES"]` would raise KeyError in production
        on a request that succeeded.
        """
        data = await self._http.get_json(
            f"{PUBCHEM_REST_URL}/compound/cid/{cid}/property"
            "/MolecularFormula,MolecularWeight,IUPACName,SMILES/JSON"
        )
        rows = (data or {}).get("PropertyTable", {}).get("Properties") or []
        if not rows:
            return None
        props = rows[0]
        smiles_key = next((k for k in props if k.endswith("SMILES")), None)
        return Compound(
            cid=cid,
            name=name,
            formula=props.get("MolecularFormula"),
            weight=props.get("MolecularWeight"),
            iupac_name=props.get("IUPACName"),
            smiles=props.get(smiles_key) if smiles_key else None,
        )

    async def get_hazards(self, cid: int) -> Hazard | None:
        """GHS statements from PUG-View. None means none are published.

        "No hazard data published" and "this compound is not hazardous"
        are different statements (principle 3). Hydrotalcite, an ordinary
        antacid, has a full PUG-REST record and a 404 on this heading.
        Returning None rather than an empty Hazard keeps the difference
        visible to the caller.
        """
        data = await self._http.get_json(
            f"{PUBCHEM_VIEW_URL}/data/compound/{cid}/JSON", {"heading": GHS_HEADING}
        )
        if not isinstance(data, dict):
            return None
        statements = self._collect_strings(data.get("Record", {}))
        return Hazard(cid=cid, statements=statements) if statements else None

    @staticmethod
    def _collect_strings(node: object, out: list[str] | None = None) -> list[str]:
        """Walk PUG-View's nested Section tree and pull out the text.

        The tree is keyed by human-readable TOCHeading strings and nests
        to an unpredictable depth, so a recursive walk is the only
        traversal that does not break when PubChem reorganises a page.
        """
        out = [] if out is None else out
        if isinstance(node, dict):
            if "String" in node and isinstance(node["String"], str):
                out.append(node["String"])
            for value in node.values():
                PubChemClient._collect_strings(value, out)
        elif isinstance(node, list):
            for item in node:
                PubChemClient._collect_strings(item, out)
        return out

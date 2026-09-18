"""
RxNorm: drug name normalisation.

Turns what a person typed into a concept the rest of the system can look
things up by. Three jobs, in order of how often they matter:

    brand -> generic       "Coumadin"  -> warfarin
    typo  -> canonical     "metformn"  -> metformin
    ingredient -> products 11289       -> 855288, 855296, ... (D4)

The third is not optional. RxNorm returns INGREDIENT concept ids;
openFDA labels carry PRODUCT (SCD) ids. Joining on the ingredient id
matches nothing, for every drug, always -- a total failure that looks
exactly like "drug not found".
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from clients.base import HttpClient
from config import RXNORM_BASE_URL

# A fuzzy match is NEVER accepted silently. The caller must confirm it
# with the user before the name is used, and that is not caution -- it is
# the only control that works here.
#
# The first design used RxNorm's own score with a threshold. That was
# wrong twice over. RxNorm's score is unbounded and scales with term
# length (warfarin 12.06, metformn 8.18), so a fixed number means
# nothing. And measuring string similarity instead does not rescue it:
#
#     0.909  prednisone -> prednisolone   DIFFERENT DRUG
#     0.875  metfrmn    -> metformin      typo
#
# A genuinely different drug scores HIGHER than a real typo. Prednisone
# and prednisolone differ in potency; losartan and valsartan are
# different molecules. No threshold separates those cases, because the
# information needed to separate them is not in the string.
#
# So similarity is used only to discard absurd suggestions, and the real
# gate is `requires_confirmation`. RxNorm does the heavy lifting anyway:
# genuine nonsense ("zzzznopedrug") returns no candidates at all.
APPROXIMATE_MIN_SIMILARITY = 0.6


@dataclass(frozen=True)
class DrugRef:
    """A drug the system has agreed on a name for.

    `approximate` is carried, not hidden: an answer resting on a fuzzy
    name match must be able to say so.
    """

    name: str
    rxcui: str
    approximate: bool = False
    query: str | None = None

    @property
    def requires_confirmation(self) -> bool:
        """True when the caller must ask the user before proceeding.

        An approximate match may be a typo corrected, or it may be a
        different drug entirely, and nothing in the match itself tells
        you which. Asking costs one turn; being wrong answers a question
        about a medicine the user is not taking.
        """
        return self.approximate


class RxNormClient:
    def __init__(self) -> None:
        self._http = HttpClient(source="rxnorm")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def find_rxcui(self, name: str) -> DrugRef | None:
        """Exact name lookup. None means RxNorm does not know this name.

        The trap: RxNorm answers HTTP 200 with `{"idGroup": {}}` for an
        unknown name -- it does not 404. base.py maps 404 to None, so a
        client that trusted the status code would read a missing key
        here and raise on a "successful" response.
        """
        data = await self._http.get_json(
            f"{RXNORM_BASE_URL}/rxcui.json", {"name": name}
        )
        ids = self._rxcuis(data)
        if not ids:
            return None
        return DrugRef(name=name, rxcui=ids[0], query=name)

    async def approximate_match(self, term: str) -> DrugRef | None:
        """Fuzzy lookup, for misspellings. None means no confident match.

        approximateTerm returns an rxcui and a score but NO name, so the
        canonical name needs a second call. Returning the id alone would
        leave the system unable to tell the user which drug it answered
        about -- which is the whole point of confirming a typo.
        """
        data = await self._http.get_json(
            f"{RXNORM_BASE_URL}/approximateTerm.json",
            {"term": term, "maxEntries": 1},
        )
        candidates = (data or {}).get("approximateGroup", {}).get("candidate") or []
        if not candidates:
            return None

        rxcui = candidates[0].get("rxcui")
        if not rxcui:
            return None

        # The canonical name is fetched before the match is judged:
        # approximateTerm returns a score and an id but no name, and a
        # suggestion the system cannot name is a suggestion it cannot
        # ask the user to confirm.
        name = await self.get_name(rxcui)
        if name is None:
            return None

        if self._similarity(term, name) < APPROXIMATE_MIN_SIMILARITY:
            return None

        return DrugRef(name=name, rxcui=rxcui, approximate=True, query=term)

    async def resolve(self, term: str) -> DrugRef | None:
        """Exact first, fuzzy as a fallback. The normal entry point."""
        return await self.find_rxcui(term) or await self.approximate_match(term)

    async def get_name(self, rxcui: str) -> str | None:
        """Canonical RxNorm name for a concept id.

        The endpoint is `properties.json`, plural. The singular
        `property.json?propName=RxNormName` reads more precisely and
        returns HTTP 400 -- which is how this line was written, and then
        corrected by a smoke test rather than by reading it again.
        """
        data = await self._http.get_json(
            f"{RXNORM_BASE_URL}/rxcui/{rxcui}/properties.json"
        )
        return ((data or {}).get("properties") or {}).get("name")

    async def get_related_products(self, rxcui: str) -> list[str]:
        """Ingredient rxcui -> product (SCD) rxcuis. The D4 hop.

        Empty list means the ingredient has no product-level concepts,
        which is a real answer -- not an error.
        """
        data = await self._http.get_json(
            f"{RXNORM_BASE_URL}/rxcui/{rxcui}/related.json", {"tty": "SCD"}
        )
        groups = (data or {}).get("relatedGroup", {}).get("conceptGroup") or []
        return [
            prop["rxcui"]
            for group in groups
            if group.get("tty") == "SCD"
            for prop in (group.get("conceptProperties") or [])
            if prop.get("rxcui")
        ]

    @staticmethod
    def _similarity(query: str, candidate: str) -> float:
        """Crude closeness of two drug names, for discarding absurdities only.

        Deliberately not a safety control -- see APPROXIMATE_MIN_SIMILARITY.
        """
        return SequenceMatcher(None, query.lower(), candidate.lower()).ratio()

    @staticmethod
    def _rxcuis(data: dict | list | None) -> list[str]:
        if not isinstance(data, dict):
            return []
        return data.get("idGroup", {}).get("rxnormId") or []

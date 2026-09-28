"""
NLM Clinical Tables: analyte text -> LOINC code, and autocomplete.

This client exists because of a gap the dataflow diagram hid. The lab
pipeline was specified as "LOINC code -> MedlinePlus Connect", which
reads perfectly and never says where the code comes from. A report
prints text:

    Hemoglobin        13.2 g/dL      13.0 - 17.0

The gap only appeared when the flow was traced end to end against real
data.

Responses are POSITIONAL JSON ARRAYS with no field names:

    [ total, [codes...], null, [[display...]...] ]

Index 0 is the hit count, 1 the codes, 3 the display strings. Nothing in
the response explains this, so it is documented here.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import CLINICALTABLES_BASE_URL
from utils.base import HttpClient

# A search returning more hits than this is too broad to pick from:
# "hemoglobin" alone matches 508 LOINC items whose top-ranked results
# are carboxyhaemoglobin variants, not the haemoglobin on a blood count.
AMBIGUOUS_ABOVE = 10


@dataclass(frozen=True)
class LoincMatch:
    """A candidate code for an analyte name, and whether to trust it.

    `confident` is False when the search was too broad to choose from.
    The lab pipeline attaches NO description in that case (D9's contract
    applied to test identity): silence about the test is recoverable, a
    confident description of the wrong test is not.
    """

    code: str
    display: str
    total_hits: int
    confident: bool


class ClinicalTablesClient:
    def __init__(self) -> None:
        self._http = HttpClient(source="clinicaltables")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def loinc_for(self, analyte: str) -> LoincMatch | None:
        """Analyte name -> LOINC candidate. None means no match at all.

        A returned match with `confident=False` is not a failure: it is
        a match the caller must not use for description lookup.
        """
        total, codes, displays = await self._search(
            "loinc_items", analyte, type="question"
        )
        if not codes:
            return None
        return LoincMatch(
            code=codes[0],
            display=displays[0] if displays else "",
            total_hits=total,
            confident=total <= AMBIGUOUS_ABOVE,
        )

    async def suggest_conditions(self, prefix: str, limit: int = 5) -> list[str]:
        """Condition-name autocomplete for the frontend input."""
        _, _, displays = await self._search("conditions", prefix, maxList=limit)
        return displays

    async def _search(
        self, table: str, terms: str, **extra
    ) -> tuple[int, list[str], list[str]]:
        """Unpack the positional array into something with names.

        "Nothing found" is HTTP 200 with a well-formed `[0, [], null, []]`
        -- sixth upstream, sixth convention for the same situation.
        """
        params = {"terms": terms, "maxList": 5, **extra}
        data = await self._http.get_json(
            f"{CLINICALTABLES_BASE_URL}/{table}/v3/search", params
        )
        if not isinstance(data, list) or len(data) < 4:
            return 0, [], []

        total = data[0] if isinstance(data[0], int) else 0
        codes = [str(c) for c in data[1]] if isinstance(data[1], list) else []
        displays = (
            [row[0] for row in data[3] if isinstance(row, list) and row]
            if isinstance(data[3], list)
            else []
        )
        return total, codes, displays

"""
openFDA: drug labels and adverse event reports.

Two endpoints with opposite reliability characteristics, deliberately in
one client so the difference stays visible:

    /drug/label.json   the manufacturer's label. Authoritative.
    /drug/event.json   FAERS. Spontaneous reports. NOT causality.

Everything retrieved here is a US label. The jurisdiction travels with
the result (D14), because a US label presented as though it described
the tablet in an Indian user's hand is a citation that does not support
its claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from clients.base import HttpClient
from config import (
    MAX_SECTION_CHARS,
    OPENFDA_API_KEY,
    OPENFDA_EVENT_URL,
    OPENFDA_LABEL_URL,
)

JURISDICTION = "US"
DAILYMED_URL = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"


@dataclass(frozen=True)
class Label:
    """One product label, reduced to the sections we asked for."""

    generic_name: str
    set_id: str | None
    effective_time: str | None
    sections: dict[str, str] = field(default_factory=dict)
    jurisdiction: str = JURISDICTION

    @property
    def source_url(self) -> str | None:
        return DAILYMED_URL.format(set_id=self.set_id) if self.set_id else None


@dataclass(frozen=True)
class EventCounts:
    """FAERS reaction counts, and the caveat that makes them readable.

    The caveat is a FIELD, not documentation. A response carrying counts
    without it is rejected downstream (D11), because a model handed this
    list unlabelled writes "the most common side effect is X" -- and for
    acetaminophen the top three reported terms are DRUG INEFFECTIVE,
    PAIN and FATIGUE. Pain is what people take it for.
    """

    drug: str
    counts: dict[str, int]
    caveat: str = (
        "These are counts of spontaneous reports submitted to FDA. Anyone may "
        "file one and nothing is verified. There is no denominator -- no count "
        "of people who took the drug without reporting anything -- so these "
        "numbers are not rates and do not show that the drug caused the event."
    )


class OpenFdaClient:
    def __init__(self) -> None:
        self._http = HttpClient(source="openfda")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_label(
        self, generic_name: str, sections: tuple[str, ...]
    ) -> Label | None:
        """Fetch one label, keeping only the requested sections.

        None means openFDA has no label for this name -- which must be
        reported as "not found", never answered from model recall.
        """
        data = await self._search(
            OPENFDA_LABEL_URL, f'openfda.generic_name:"{generic_name}"'
        )
        results = self._results(data)
        if not results:
            return None

        record = results[0]
        return Label(
            generic_name=generic_name,
            set_id=record.get("set_id"),
            effective_time=record.get("effective_time"),
            sections={
                name: text
                for name in sections
                if (text := self._section_text(record, name))
            },
        )

    async def mentions_in_section(
        self, generic_name: str, section: str, term: str
    ) -> bool:
        """Does this drug's named section mention this term?

        Field-scoped search, verified against nonsense controls before
        being trusted: `drug_interactions:"zzzznope"` returns NOT_FOUND
        while `drug_interactions:"aspirin"` returns the full 76 hits. The
        controls are what distinguish a working filter from an ignored
        one, since both look like a successful response.
        """
        data = await self._search(
            OPENFDA_LABEL_URL,
            f'openfda.generic_name:"{generic_name}" AND {section}:"{term}"',
        )
        return bool(self._results(data))

    async def event_counts(
        self, generic_name: str, limit: int = 10
    ) -> EventCounts | None:
        """Top reported reaction terms for a drug. See EventCounts."""
        data = await self._http.get_json(
            OPENFDA_EVENT_URL,
            self._params(
                {
                    "search": f'patient.drug.openfda.generic_name:"{generic_name}"',
                    "count": "patient.reaction.reactionmeddrapt.exact",
                    "limit": limit,
                }
            ),
        )
        results = self._results(data)
        if not results:
            return None
        return EventCounts(
            drug=generic_name,
            counts={r["term"]: r["count"] for r in results if "term" in r},
        )

    # ----------------------------------------------------------------

    async def _search(self, url: str, query: str, limit: int = 1) -> dict | list | None:
        return await self._http.get_json(
            url, self._params({"search": query, "limit": limit})
        )

    @staticmethod
    def _params(params: dict) -> dict:
        # The key only raises the rate limit; openFDA serves anonymous
        # requests at development volumes, so its absence is not an error.
        if OPENFDA_API_KEY:
            params["api_key"] = OPENFDA_API_KEY
        return params

    @staticmethod
    def _results(data: dict | list | None) -> list[dict]:
        return (data or {}).get("results", []) if isinstance(data, dict) else []

    @staticmethod
    def _section_text(record: dict, name: str) -> str:
        """Join a section's paragraphs and cap its length.

        Label sections are lists of strings, not strings. The cap exists
        so that one unusually long label cannot dominate the context
        window: an interaction section alone runs to ~6,500 characters,
        and an interaction query fetches two of them.
        """
        value = record.get(name)
        if not value:
            return ""
        text = " ".join(value) if isinstance(value, list) else str(value)
        return text[:MAX_SECTION_CHARS]

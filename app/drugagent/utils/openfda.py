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

from config import (
    OPENFDA_API_KEY,
    OPENFDA_EVENT_URL,
    OPENFDA_LABEL_URL,
)
from utils.base import HttpClient

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
        self,
        generic_name: str,
        sections: tuple[str, ...],
        require_section: str | None = None,
    ) -> Label | None:
        """Fetch one label, keeping only the requested sections.

        None means openFDA has no label for this name -- which must be
        reported as "not found", never answered from model recall.

        Several labels are fetched and the best single-ingredient match
        is chosen. Taking the first result returns a COMBINATION product
        whenever one happens to rank highest: a search for "metformin"
        returned the label for sitagliptin-and-metformin, whose dosing
        text describes a different medicine than the one asked about.

        `require_section` filters SERVER-SIDE for labels that actually
        carry a section. It exists because most labels do not: only 19
        of 719 aspirin labels have `drug_interactions`, so fetching a
        handful and hoping is a coin flip. Without it, an interaction
        check silently became one-sided.
        """
        query = f'openfda.generic_name:"{generic_name}"'
        results: list[dict] = []

        if require_section:
            data = await self._search(
                OPENFDA_LABEL_URL, f"{query} AND _exists_:{require_section}", limit=5
            )
            results = self._results(data)

        if not results:
            # Fall back to any label. A label without the section still
            # answers "does this drug exist", and the caller can see the
            # section is empty -- which is different from inventing one.
            data = await self._search(OPENFDA_LABEL_URL, query, limit=5)
            results = self._results(data)

        if not results:
            return None

        record = self._best_match(results, generic_name, sections)
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
    def _best_match(
        results: list[dict], generic_name: str, sections: tuple[str, ...]
    ) -> dict:
        """Pick the most useful label among several candidates.

        Two failures this avoids, both observed:

        A COMBINATION product outranking the single drug. openFDA spells
        a combination as ONE generic_name string -- "SITAGLIPTIN AND
        METFORMIN HYDROCHLORIDE" -- so the array length is 1 either way
        and cannot separate them. The separator in the name is the
        signal. Taking the first result answered a metformin dosing
        question with a sitagliptin combination's dosing.

        A label that LACKS the section asked for. OTC labels often carry
        no drug_interactions section at all, which turns a two-sided
        interaction check into a one-sided one without anything failing.
        """
        wanted = generic_name.lower()

        def score(record: dict) -> tuple[int, int, int]:
            names = [
                n.lower()
                for n in (record.get("openfda", {}) or {}).get("generic_name") or []
            ]
            name = names[0] if names else ""
            # A combination is spelled EITHER as one joined string
            # ("OXYCODONE AND ACETAMINOPHEN") or as several array
            # entries. Checking only the first element returned an
            # oxycodone overdose answer to a paracetamol question.
            is_combination = len(names) > 1 or any(
                sep in n for n in names for sep in (" and ", ",", "/")
            )
            missing_sections = sum(1 for sec in sections if not record.get(sec))
            # Lower sorts first. Section coverage is weighted above
            # name shape: a single-ingredient label with none of the
            # requested text is worth less than a usable one.
            return (
                missing_sections,
                int(is_combination),
                0 if name.startswith(wanted) else 1,
            )

        return min(results, key=score)

    @staticmethod
    def _results(data: dict | list | None) -> list[dict]:
        return (data or {}).get("results", []) if isinstance(data, dict) else []

    @staticmethod
    def _section_text(record: dict, name: str) -> str:
        """Join a section's paragraphs. NOT truncated here.

        Label sections are lists of strings, not strings.

        Truncation belongs to the caller that sends text to a model, not
        to the client that retrieves it. Capping here silently broke the
        interaction check: warfarin's drug_interactions section is 6,477
        characters, the cap was 4,000, and "aspirin" appears past that
        point -- so warfarin plus aspirin came back "not documented",
        which is the precise failure this system was built to prevent.

        Searching truncated text answers a question about the truncation,
        not about the label.
        """
        value = record.get(name)
        if not value:
            return ""
        return " ".join(value) if isinstance(value, list) else str(value)

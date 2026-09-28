"""
MedlinePlus: consumer health topics, and lab test descriptions by code.

Two services, two formats, one client:

    wsearch  health topic search. XML ONLY -- there is no JSON option.
    Connect  code lookup (LOINC, ICD-10, RxCUI). JSON, on request.

This is the only prose source in the system and the only one without an
exact key for the common case: "what is hypothyroidism" is answered by
search, not by an index (D2). Its recall is therefore the measurement
that decides whether a vector store ever earns its cost here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from config import LOINC_OID, MEDLINEPLUS_CONNECT_URL, MEDLINEPLUS_SEARCH_URL
from utils.base import HttpClient

# Search results wrap matched words in highlighting markup, escaped into
# the XML: <span class="qt0">Hypothyroidism</span>. Passed through
# unstripped it becomes part of the answer text and part of every
# citation title.
_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Topic:
    """One health topic, ready to cite."""

    title: str
    url: str
    summary: str


@dataclass(frozen=True)
class TestInfo:
    """Consumer-language description of a lab test, keyed by LOINC."""

    loinc: str
    title: str
    url: str


class MedlinePlusClient:
    def __init__(self) -> None:
        self._http = HttpClient(source="medlineplus")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def search_topics(self, term: str, limit: int = 3) -> list[Topic]:
        """Health topic search. Empty list means nothing matched.

        "Nothing matched" arrives as HTTP 200 with valid XML and
        <count>0</count> -- not a 404, and not an empty object. Fourth
        upstream, fourth convention.
        """
        root = await self._http.get_xml(
            MEDLINEPLUS_SEARCH_URL,
            {"db": "healthTopics", "term": term, "retmax": limit},
        )
        if root is None or int(root.findtext("count", "0")) == 0:
            return []

        topics = []
        for document in root.iter("document"):
            fields = {
                el.get("name"): self._clean(el)
                for el in document.iter("content")
                if el.get("name")
            }
            title = fields.get("title", "")
            if title:
                topics.append(
                    Topic(
                        title=title,
                        url=document.get("url", ""),
                        summary=fields.get("FullSummary", ""),
                    )
                )
        return topics

    async def lookup_loinc(self, loinc: str) -> TestInfo | None:
        """LOINC code -> consumer description. None means unmapped.

        Not every analyte on a report has a MedlinePlus topic, and an
        unmapped code must produce nothing rather than the nearest
        available description -- which would belong to a different test.
        """
        data = await self._http.get_json(
            MEDLINEPLUS_CONNECT_URL,
            {
                "mainSearchCriteria.v.cs": LOINC_OID,
                "mainSearchCriteria.v.c": loinc,
                "knowledgeResponseType": "application/json",
            },
        )
        entries = (data or {}).get("feed", {}).get("entry") or []
        if not entries:
            return None

        entry = entries[0]
        links = entry.get("link") or []
        return TestInfo(
            loinc=loinc,
            title=(entry.get("title") or {}).get("_value", ""),
            url=links[0].get("href", "") if links else "",
        )

    @staticmethod
    def _clean(element) -> str:
        """Text of an element, with highlighting markup removed.

        itertext() is needed as well as the regex: the markup arrives
        both as escaped text and as parsed child elements depending on
        the field, so neither approach alone gets all of it.
        """
        return _TAG.sub("", "".join(element.itertext())).strip()

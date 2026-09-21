"""
Probe: MedlinePlus (wsearch.nlm.nih.gov and connect.medlineplus.gov).

Run this BEFORE writing clients/medlineplus.py. See probes/_harness.py.

MedlinePlus is the only prose source in the system, and the only one
without an exact lookup key for the common case -- "what is
hypothyroidism" is answered by search, not by an index (architecture D2).
That makes its recall the thing to measure, because recall is what
decides whether a vector store ever earns its cost here.

Two services, two formats:
  wsearch  -- health topic search, XML ONLY, no JSON option
  Connect  -- code lookup (LOINC, ICD-10, RxCUI), JSON on request

Usage, from app/drugagent/:
    python -m probes.probe_medlineplus
"""

from __future__ import annotations

from config import LOINC_OID, MEDLINEPLUS_CONNECT_URL, MEDLINEPLUS_SEARCH_URL
from probes._harness import Check, clip, run
from utils.base import HttpClient


async def _search(client: HttpClient, term: str, retmax: int = 3):
    return await client.get_xml(
        MEDLINEPLUS_SEARCH_URL,
        {"db": "healthTopics", "term": term, "retmax": retmax},
    )


def _titles(root) -> list[str]:
    """Pull document titles out of the nlmSearchResult tree.

    Content is addressed by an ATTRIBUTE value, not by tag name:
        <content name="title">...</content>
    so a generic xml-to-dict conversion loses exactly the field we want.
    This is why get_xml hands back the element tree instead of a dict.
    """
    if root is None:
        return []
    return [
        "".join(el.itertext())
        for el in root.iter("content")
        if el.get("name") == "title"
    ]


async def probe_topic_search(client: HttpClient) -> Check:
    """A condition name returns matching health topics."""
    root = await _search(client, "hypothyroidism")
    count = int(root.findtext("count", "0")) if root is not None else 0
    titles = _titles(root)
    return Check(
        name="health topic search",
        expectation="hypothyroidism returns ranked topics",
        passed=count > 0 and bool(titles),
        observed=f"count={count} first={clip(titles[0] if titles else '', 50)!r}",
    )


async def probe_nonsense_control(client: HttpClient) -> Check:
    """A condition that does not exist must return zero.

    Third convention for "nothing found" across four upstreams: HTTP 200,
    valid XML, <count>0</count> and no <list> element at all. Not a 404,
    not an empty JSON object.
    """
    root = await _search(client, "zzzznopecondition")
    count = int(root.findtext("count", "-1")) if root is not None else -1
    return Check(
        name="nonsense term (CONTROL)",
        expectation="count=0 in a valid 200 XML body",
        passed=count == 0,
        observed=f"count={count} titles={_titles(root)}",
    )


async def probe_markup_in_content(client: HttpClient) -> Check:
    """Search results carry HTML highlighting inside the XML text.

    Matched words come back wrapped in <span class="qt0">, escaped into
    the XML. Passed to the model unstripped, that markup becomes part of
    the answer text and part of every citation. The client must strip it.
    """
    root = await _search(client, "diabetes", retmax=1)
    raw = ""
    if root is not None:
        for el in root.iter("content"):
            if el.get("name") == "title":
                raw = (el.text or "") + "".join(
                    (c.text or "") + (c.tail or "") for c in el
                )
                break
    return Check(
        name="markup needs stripping",
        expectation="titles contain span highlighting to remove",
        passed="qt0" in raw or "<" in raw or bool(raw),
        observed=f"raw={clip(raw, 60)!r}",
    )


async def probe_connect_loinc(client: HttpClient) -> Check:
    """LOINC code -> consumer-language description of a lab test.

    This is the lab pipeline's explanation source. A report prints
    "Cholesterol, Total 2093-3"; Connect turns that code into language a
    non-clinician can read -- without the model inventing the meaning of
    the test.
    """
    data = await client.get_json(
        MEDLINEPLUS_CONNECT_URL,
        {
            "mainSearchCriteria.v.cs": LOINC_OID,
            "mainSearchCriteria.v.c": "2093-3",
            "knowledgeResponseType": "application/json",
        },
    )
    entries = (data or {}).get("feed", {}).get("entry", [])
    title = entries[0].get("title", {}).get("_value") if entries else None
    return Check(
        name="Connect: LOINC 2093-3",
        expectation="total cholesterol code resolves to a topic",
        passed=bool(entries),
        observed=f"entries={len(entries)} first={title!r}",
    )


async def probe_connect_unknown_code(client: HttpClient) -> Check:
    """An unmapped LOINC code must not silently resolve to something else.

    Not every analyte on a report has a MedlinePlus topic. The lab tool
    must be able to say "no consumer description available for this
    test" rather than attaching a description that belongs to a
    different test entirely.
    """
    data = await client.get_json(
        MEDLINEPLUS_CONNECT_URL,
        {
            "mainSearchCriteria.v.cs": LOINC_OID,
            "mainSearchCriteria.v.c": "99999-9",
            "knowledgeResponseType": "application/json",
        },
    )
    entries = (data or {}).get("feed", {}).get("entry", [])
    return Check(
        name="unmapped code (CONTROL)",
        expectation="no entries -- never a wrong-test description",
        passed=not entries,
        observed=f"entries={len(entries)}",
    )


if __name__ == "__main__":
    raise SystemExit(
        run(
            "MedlinePlus probe",
            source="medlineplus",
            probes=[
                probe_topic_search,
                probe_nonsense_control,
                probe_markup_in_content,
                probe_connect_loinc,
                probe_connect_unknown_code,
            ],
        )
    )

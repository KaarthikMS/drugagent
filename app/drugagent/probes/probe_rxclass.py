"""
Probe: RxClass (rxnav.nlm.nih.gov/REST/rxclass).

Run this BEFORE wiring class matching into domain/interactions.py.
See probes/_harness.py.

Why this source exists in the design at all:

    A label warns about "NSAIDs" and never writes "ibuprofen".

Exact-string matching on a drug name misses every class-level warning,
which is most of them (architecture section 5). The alternative to
RxClass is a hand-maintained table of drug classes inside this
repository -- which goes stale silently, and whose staleness shows up as
a missed interaction rather than as a failing test.

RxClass answers both directions:
    drug  -> the classes it belongs to
    class -> the drugs in it

Usage, from app/drugagent/:
    python -m probes.probe_rxclass
"""

from __future__ import annotations

from config import RXCLASS_BASE_URL
from probes._harness import Check, clip, run
from utils.base import HttpClient

WARFARIN_IN = "11289"
IBUPROFEN_IN = "5640"
ATC_NSAID = "M01A"


async def _classes(client: HttpClient, rxcui: str, source: str | None = None) -> list:
    params = {"rxcui": rxcui}
    if source:
        params["relaSource"] = source
    data = await client.get_json(f"{RXCLASS_BASE_URL}/class/byRxcui.json", params)
    return (data or {}).get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", [])


async def probe_drug_to_class(client: HttpClient) -> Check:
    """A drug resolves to its classes, across several terminologies."""
    infos = await _classes(client, WARFARIN_IN)
    names = {
        i["rxclassMinConceptItem"]["className"]
        for i in infos
        if "rxclassMinConceptItem" in i
    }
    sources = sorted({i.get("relaSource") for i in infos})
    return Check(
        name="drug -> classes",
        expectation="warfarin classed as a vitamin K antagonist",
        passed=any("Vitamin K" in n for n in names),
        observed=f"sources={sources} classes={clip(str(sorted(names)), 60)}",
    )


async def probe_atc_filter(client: HttpClient) -> Check:
    """Restricting to one terminology works.

    Multiple sources answer at once by default -- ATC, SNOMEDCT, MeSH,
    VA, EPC. Mixing them produces duplicate and overlapping class names
    for the same drug. The client picks a source deliberately.
    """
    infos = await _classes(client, WARFARIN_IN, source="ATC")
    sources = {i.get("relaSource") for i in infos}
    ids = {i["rxclassMinConceptItem"]["classId"] for i in infos}
    return Check(
        name="relaSource filter",
        expectation="ATC only; includes B01AA",
        passed=sources == {"ATC"} and "B01AA" in ids,
        observed=f"sources={sources} ids={sorted(ids)}",
    )


async def probe_class_to_members(client: HttpClient) -> Check:
    """The reverse direction: which drugs are NSAIDs.

    This is the lookup that makes a label's "NSAIDs" warning resolvable
    to the specific drug a user asked about.
    """
    data = await client.get_json(
        f"{RXCLASS_BASE_URL}/classMembers.json",
        {"classId": ATC_NSAID, "relaSource": "ATC"},
    )
    members = (data or {}).get("drugMemberGroup", {}).get("drugMember", [])
    names = {m["minConcept"]["name"].lower() for m in members}
    return Check(
        name="class -> members",
        expectation="ATC M01A contains ibuprofen",
        passed="ibuprofen" in names,
        observed=f"{len(names)} members, ibuprofen={'ibuprofen' in names}",
    )


async def probe_shared_class(client: HttpClient) -> Check:
    """The real question the interaction check will ask.

    Not "is aspirin in a class" but "does the class named in warfarin's
    label cover aspirin". Overlap between two drugs' class sets is what
    turns a class-level warning into a specific answer.
    """
    ibu = {
        i["rxclassMinConceptItem"]["classId"]
        for i in await _classes(client, IBUPROFEN_IN, source="ATC")
    }
    return Check(
        name="class overlap is computable",
        expectation="ibuprofen's ATC classes include the NSAID branch M01A",
        passed=any(c.startswith(ATC_NSAID) for c in ibu),
        observed=f"ibuprofen ATC={sorted(ibu)}",
    )


async def probe_nonsense_control(client: HttpClient) -> Check:
    """An rxcui that does not exist must return no classes.

    Fifth upstream, and RxClass has its own convention again: HTTP 200
    with an empty body object. Same host as RxNorm, different shape.
    """
    data = await client.get_json(
        f"{RXCLASS_BASE_URL}/class/byRxcui.json", {"rxcui": "999999999"}
    )
    infos = (data or {}).get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", [])
    return Check(
        name="unknown rxcui (CONTROL)",
        expectation="no classes returned -- proves the lookup filters",
        passed=not infos,
        observed=f"body={clip(str(data), 60)}",
    )


if __name__ == "__main__":
    raise SystemExit(
        run(
            "RxClass probe",
            source="rxclass",
            probes=[
                probe_drug_to_class,
                probe_atc_filter,
                probe_class_to_members,
                probe_shared_class,
                probe_nonsense_control,
            ],
        )
    )

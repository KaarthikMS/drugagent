"""
Probe: RxNorm (rxnav.nlm.nih.gov).

Run this BEFORE writing clients/rxnorm.py. See probes/_harness.py for
what a probe is and why every check carries a control.

Usage, from app/drugagent/:
    python -m probes.probe_rxnorm
"""

from __future__ import annotations

from config import RXNORM_BASE_URL
from probes._harness import Check, run
from utils.base import HttpClient

# --------------------------------------------------------------------
# Individual probes
#
# Each returns a Check rather than asserting, so one failure does not
# hide the results of everything after it. A probe run should tell you
# the whole state of an upstream in one pass.
# --------------------------------------------------------------------


async def probe_exact_name(client: HttpClient) -> Check:
    """A known drug name resolves to its ingredient rxcui."""
    data = await client.get_json(f"{RXNORM_BASE_URL}/rxcui.json", {"name": "warfarin"})
    ids = (data or {}).get("idGroup", {}).get("rxnormId", [])
    return Check(
        name="exact name -> rxcui",
        expectation="warfarin resolves to ingredient rxcui 11289",
        passed=ids == ["11289"],
        observed=f"rxnormId={ids}",
    )


async def probe_nonsense_control(client: HttpClient) -> Check:
    """The control. A name that cannot exist must not resolve.

    The trap: RxNorm answers HTTP 200 with `{"idGroup": {}}` -- no
    `rxnormId` key at all. It does not 404. Code that branches on the
    status code treats "no such drug" as success and then reads a
    missing key.
    """
    data = await client.get_json(
        f"{RXNORM_BASE_URL}/rxcui.json", {"name": "zzzznopedrug"}
    )
    ids = (data or {}).get("idGroup", {}).get("rxnormId", [])
    return Check(
        name="nonsense name (CONTROL)",
        expectation="no rxnormId key; HTTP 200 body, not a 404",
        passed=ids == [],
        observed=f"body={data!r}",
    )


async def probe_brand_to_generic(client: HttpClient) -> Check:
    """A brand name resolves. This is why normalisation exists at all.

    Employees say "Coumadin"; openFDA labels are indexed on the generic.
    Skipping this hop means every brand-name question finds nothing.
    """
    data = await client.get_json(f"{RXNORM_BASE_URL}/rxcui.json", {"name": "Coumadin"})
    ids = (data or {}).get("idGroup", {}).get("rxnormId", [])
    return Check(
        name="brand name -> rxcui",
        expectation="Coumadin resolves to some rxcui",
        passed=bool(ids),
        observed=f"rxnormId={ids}",
    )


async def probe_misspelling(client: HttpClient) -> Check:
    """Does RxNorm handle a typo, and through which endpoint?

    Open question, not a known answer: if /rxcui.json is strict, the
    client needs the approximate-match endpoint as a fallback, and the
    probe is what decides that.
    """
    exact = await client.get_json(f"{RXNORM_BASE_URL}/rxcui.json", {"name": "metformn"})
    exact_ids = (exact or {}).get("idGroup", {}).get("rxnormId", [])

    approx = await client.get_json(
        f"{RXNORM_BASE_URL}/approximateTerm.json",
        {"term": "metformn", "maxEntries": 1},
    )
    candidates = (approx or {}).get("approximateGroup", {}).get("candidate", []) or []
    top = candidates[0] if candidates else {}

    return Check(
        name="misspelling handling",
        expectation="exact fails; approximateTerm recovers 'metformin'",
        passed=not exact_ids and bool(top),
        observed=f"exact={exact_ids} approx_top={top}",
    )


async def probe_concept_name(client: HttpClient) -> Check:
    """Which endpoint returns the canonical name for an rxcui?

    Added after the client was written against a guessed URL. The
    singular `property.json?propName=RxNormName` reads more precisely
    and answers HTTP 400; `properties.json` is the one that works. The
    guess survived code review and unit tests, and was caught by a smoke
    test -- which is the argument for probing an endpoint before relying
    on it, not after.
    """
    data = await client.get_json(f"{RXNORM_BASE_URL}/rxcui/6809/properties.json")
    name = ((data or {}).get("properties") or {}).get("name")
    return Check(
        name="rxcui -> canonical name",
        expectation="properties.json (plural) returns name=metformin",
        passed=name == "metformin",
        observed=f"name={name!r}",
    )


async def probe_scd_hop(client: HttpClient) -> Check:
    """The two-hop join (architecture D4).

    RxNorm gives INGREDIENT rxcuis. openFDA labels carry PRODUCT (SCD)
    rxcuis. Joining on the ingredient id matches nothing, for every drug,
    always -- a total failure that looks exactly like "drug not found".
    This hop is what makes the ids comparable.
    """
    data = await client.get_json(
        f"{RXNORM_BASE_URL}/rxcui/11289/related.json", {"tty": "SCD"}
    )
    groups = (data or {}).get("relatedGroup", {}).get("conceptGroup", [])
    products = [
        prop
        for group in groups
        if group.get("tty") == "SCD"
        for prop in group.get("conceptProperties", [])
    ]
    rxcuis = [p["rxcui"] for p in products]
    return Check(
        name="ingredient -> SCD products (D4)",
        expectation="11289 expands to product rxcuis incl. 855288",
        passed="855288" in rxcuis,
        observed=f"{len(rxcuis)} products, first 3 = {rxcuis[:3]}",
    )


# --------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------


if __name__ == "__main__":
    raise SystemExit(
        run(
            "RxNorm probe",
            source="rxnorm",
            probes=[
                probe_exact_name,
                probe_nonsense_control,
                probe_brand_to_generic,
                probe_misspelling,
                probe_concept_name,
                probe_scd_hop,
            ],
        )
    )

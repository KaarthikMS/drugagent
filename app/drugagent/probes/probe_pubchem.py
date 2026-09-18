"""
Probe: PubChem (pubchem.ncbi.nlm.nih.gov).

Run this BEFORE writing clients/pubchem.py. See probes/_harness.py.

PubChem answers chemistry, not therapeutics. It knows ibuprofen's
molecular weight and its GHS hazard classification; it does not know
what dose is safe for a person. The compound and toxicity tools must
keep that line visible, because a GHS hazard statement written for a
laboratory reagent reads alarmingly when applied to a tablet.

Two base paths, not one:
  PUG-REST  -- identifiers and computed properties
  PUG-View  -- curated content, including GHS
They have different response shapes and are not interchangeable.

Usage, from app/drugagent/:
    python -m probes.probe_pubchem
"""

from __future__ import annotations

from clients.base import HttpClient
from config import PUBCHEM_REST_URL, PUBCHEM_VIEW_URL
from probes._harness import Check, clip, run

IBUPROFEN_CID = 3672


async def probe_name_to_cid(client: HttpClient) -> Check:
    """A compound name resolves to a CID, the key everything else needs."""
    data = await client.get_json(
        f"{PUBCHEM_REST_URL}/compound/name/ibuprofen/cids/JSON"
    )
    cids = (data or {}).get("IdentifierList", {}).get("CID", [])
    return Check(
        name="name -> CID",
        expectation=f"ibuprofen resolves to CID {IBUPROFEN_CID}",
        passed=IBUPROFEN_CID in cids,
        observed=f"CID={cids}",
    )


async def probe_nonsense_control(client: HttpClient) -> Check:
    """A compound that does not exist.

    Unlike RxNorm, PubChem answers a real 404 with a Fault body, which
    base.py maps to None. Two upstreams, two conventions for the same
    situation -- which is why each gets its own probe.
    """
    data = await client.get_json(
        f"{PUBCHEM_REST_URL}/compound/name/zzzznopecompound/cids/JSON"
    )
    return Check(
        name="nonsense name (CONTROL)",
        expectation="HTTP 404 -> None (not an empty 200 like RxNorm)",
        passed=data is None,
        observed=f"body={data!r}",
    )


async def probe_properties(client: HttpClient) -> Check:
    """Computed properties, and a lesson about trusting your own request.

    CanonicalSMILES was requested; PubChem returned ConnectivitySMILES.
    It renamed the property and answered with the new key rather than
    erroring. A client that does `result["CanonicalSMILES"]` raises
    KeyError in production on a request that returned HTTP 200.

    Read what came back. Never assume you got what you asked for.
    """
    data = await client.get_json(
        f"{PUBCHEM_REST_URL}/compound/cid/{IBUPROFEN_CID}/property"
        "/MolecularFormula,MolecularWeight,CanonicalSMILES,IUPACName/JSON"
    )
    props = (data or {}).get("PropertyTable", {}).get("Properties", [{}])[0]
    returned = sorted(k for k in props if k != "CID")
    return Check(
        name="properties + renamed key",
        expectation="formula/weight present; SMILES key is NOT CanonicalSMILES",
        passed="MolecularFormula" in props and "CanonicalSMILES" not in props,
        observed=f"keys={returned}",
    )


async def probe_ghs_hazard(client: HttpClient) -> Check:
    """GHS classification, via PUG-View rather than PUG-REST.

    PUG-View returns a deeply nested Record/Section tree keyed by
    human-readable TOCHeading strings, not a flat object. The client
    will need a recursive walk; that shape is established here rather
    than discovered halfway through writing the toxicity tool.
    """
    data = await client.get_json(
        f"{PUBCHEM_VIEW_URL}/data/compound/{IBUPROFEN_CID}/JSON",
        {"heading": "GHS Classification"},
    )
    record = (data or {}).get("Record", {})
    sections = record.get("Section", [])
    headings = [s.get("TOCHeading") for s in sections]
    return Check(
        name="GHS via PUG-View",
        expectation="nested Section tree keyed by TOCHeading",
        passed=bool(sections),
        observed=f"title={record.get('RecordTitle')!r} top_sections={clip(str(headings), 60)}",
    )


async def probe_ghs_absent(client: HttpClient) -> Check:
    """A real compound with no GHS data must degrade, not crash.

    CID 71749 is hydrotalcite, an ordinary antacid. PUG-REST has a full
    record for it; PUG-View answers 404 for the GHS heading, because no
    hazard classification has been published. Real drug, no hazard data.

    (The first draft of this probe used water, on the assumption that a
    harmless compound would carry no GHS data. Water has a full GHS
    record. The probe failed and the assumption was wrong -- which is
    the entire reason probes are written before clients.)

    The toxicity tool must distinguish "no hazard data published" from
    "this compound is not hazardous" -- principle 3, in a new costume.
    """
    data = await client.get_json(
        f"{PUBCHEM_VIEW_URL}/data/compound/71749/JSON",
        {"heading": "GHS Classification"},
    )
    sections = (data or {}).get("Record", {}).get("Section", [])
    return Check(
        name="missing GHS degrades (CONTROL)",
        expectation="real CID without hazard data -> None, not a crash",
        passed=data is None or not sections,
        observed=f"body={data!r} (absent data != safe)",
    )


if __name__ == "__main__":
    raise SystemExit(
        run(
            "PubChem probe",
            source="pubchem",
            probes=[
                probe_name_to_cid,
                probe_nonsense_control,
                probe_properties,
                probe_ghs_hazard,
                probe_ghs_absent,
            ],
        )
    )

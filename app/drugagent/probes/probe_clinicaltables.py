"""
Probe: NLM Clinical Tables (clinicaltables.nlm.nih.gov/api).

Run this BEFORE writing the lab reference path. See probes/_harness.py.

This source closes a gap the dataflow diagram hid. The lab pipeline was
specified as "LOINC code -> MedlinePlus Connect -> consumer description".
But a lab report prints:

    Hemoglobin        13.2 g/dL      13.0 - 17.0

Text. Not a code. Nothing else in the stack turns "Hemoglobin" into
"718-7", so Connect could never have been called. The gap only appeared
when the flow was traced end to end against real data.

Response shape is unusual and deliberate -- a positional JSON ARRAY:

    [ total, [codes...], null, [[display...]...] ]

No field names. Index 0 is the hit count, index 1 the codes, index 3 the
display strings. The client must document this; nothing about the
response explains itself.

Usage, from app/drugagent/:
    python -m probes.probe_clinicaltables
"""

from __future__ import annotations

from clients.base import HttpClient
from config import CLINICALTABLES_BASE_URL
from probes._harness import Check, clip, run


async def _search(client: HttpClient, table: str, terms: str, **extra) -> list:
    """One Clinical Tables query. Returns the raw positional array."""
    params = {"terms": terms, "maxList": 5, **extra}
    data = await client.get_json(f"{CLINICALTABLES_BASE_URL}/{table}/v3/search", params)
    return data if isinstance(data, list) else []


async def probe_response_shape(client: HttpClient) -> Check:
    """Establish the positional array shape before anything depends on it."""
    raw = await _search(client, "conditions", "hypothyro")
    ok = (
        len(raw) == 4
        and isinstance(raw[0], int)
        and isinstance(raw[1], list)
        and isinstance(raw[3], list)
    )
    return Check(
        name="positional array shape",
        expectation="[total, [codes], null, [[display]]] -- no field names",
        passed=ok,
        observed=clip(str(raw), 80),
    )


async def probe_loinc_lookup(client: HttpClient) -> Check:
    """Analyte name -> LOINC code. The missing link in the lab pipeline."""
    raw = await _search(client, "loinc_items", "hemoglobin", type="question")
    codes = raw[1] if len(raw) > 1 else []
    displays = [d[0] for d in raw[3]] if len(raw) > 3 else []
    return Check(
        name="analyte text -> LOINC",
        expectation="'hemoglobin' resolves to LOINC codes",
        passed=bool(codes),
        observed=f"total={raw[0] if raw else 0} first={codes[:2]} {clip(str(displays[:2]), 50)}",
    )


async def probe_loinc_ambiguity(client: HttpClient) -> Check:
    """The reason this lookup cannot be trusted blindly.

    'hemoglobin' matched 500+ LOINC items, and the top hits are
    carboxyhaemoglobin variants -- not the haemoglobin on a routine
    blood count. Picking result [0] would attach a description of the
    wrong test to a real patient value.

    The check passes when the match is ambiguous, because that ambiguity
    is the finding: the lab tool must say "no confident match" rather
    than guess (architecture D9's contract, applied to test identity).
    """
    raw = await _search(client, "loinc_items", "hemoglobin", type="question")
    total = raw[0] if raw else 0
    displays = [d[0] for d in raw[3]] if len(raw) > 3 else []
    return Check(
        name="LOINC match is ambiguous (CONTROL)",
        expectation="many hits; top result is NOT the routine test",
        passed=total > 50,
        observed=f"{total} hits; top={clip(str(displays[:3]), 60)}",
    )


async def probe_conditions(client: HttpClient) -> Check:
    """Condition-name autocomplete, for the frontend input."""
    raw = await _search(client, "conditions", "hypothyro")
    displays = [d[0] for d in raw[3]] if len(raw) > 3 else []
    return Check(
        name="condition autocomplete",
        expectation="'hypothyro' suggests Hypothyroidism",
        passed=any("hypothyroid" in d.lower() for d in displays),
        observed=f"{displays}",
    )


async def probe_nonsense_control(client: HttpClient) -> Check:
    """A term that matches nothing.

    Sixth upstream, sixth convention: HTTP 200 with a well-formed array
    whose count is 0. Not a 404, not an empty object, not a <count>0</count>.
    """
    raw = await _search(client, "conditions", "zzzznopecondition")
    total = raw[0] if raw else -1
    return Check(
        name="nonsense term (CONTROL)",
        expectation="total=0 inside a valid 200 array",
        passed=total == 0,
        observed=f"raw={raw}",
    )


if __name__ == "__main__":
    raise SystemExit(
        run(
            "NLM Clinical Tables probe",
            source="clinicaltables",
            probes=[
                probe_response_shape,
                probe_loinc_lookup,
                probe_loinc_ambiguity,
                probe_conditions,
                probe_nonsense_control,
            ],
        )
    )

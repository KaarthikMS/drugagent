"""
Probe: openFDA adverse events / FAERS (api.fda.gov/drug/event.json).

Run this BEFORE writing the event half of clients/openfda.py.
See probes/_harness.py.

FAERS is the most misreadable source in this system. It is a pile of
SPONTANEOUS REPORTS: anyone may file one, nothing is verified, and there
is no denominator -- no count of how many people took the drug without
reporting anything. A count of 4,000 is therefore not an incidence rate
and not evidence of causation.

These probes exist as much to characterise that trap as to establish the
query shape. Architecture D11 turns what they find into an enforced
caveat rather than a hope about wording.

Usage, from app/drugagent/:
    python -m probes.probe_openfda_event
"""

from __future__ import annotations

from config import OPENFDA_EVENT_URL
from probes._harness import Check, run
from utils.base import HttpClient


async def _count(client: HttpClient, search: str, field: str) -> list[dict]:
    """A counted aggregation. Returns term/count pairs, highest first."""
    data = await client.get_json(
        OPENFDA_EVENT_URL, {"search": search, "count": field, "limit": 5}
    )
    return (data or {}).get("results", [])


async def probe_event_counts(client: HttpClient) -> Check:
    """The query shape works and returns ranked reaction terms."""
    results = await _count(
        client,
        'patient.drug.openfda.generic_name:"acetaminophen"',
        "patient.reaction.reactionmeddrapt.exact",
    )
    top = [(r["term"], r["count"]) for r in results[:3]]
    return Check(
        name="reaction counts",
        expectation="ranked MedDRA reaction terms with counts",
        passed=bool(results),
        observed=f"top3={top}",
    )


async def probe_counts_are_not_causality(client: HttpClient) -> Check:
    """The trap, made visible.

    The highest-ranked term is routinely something like DRUG INEFFECTIVE
    or DEATH -- outcomes reported alongside the drug, not caused by it at
    that rate. If a model saw this list unlabelled it would compose
    "the most common side effect is X", which is false in a way that
    reads as authoritative.

    The check passes when the top term is NOT a plausible-sounding
    pharmacological side effect, because that is the case that proves
    the caveat is necessary.
    """
    results = await _count(
        client,
        'patient.drug.openfda.generic_name:"acetaminophen"',
        "patient.reaction.reactionmeddrapt.exact",
    )
    top_term = results[0]["term"] if results else ""
    non_causal = {
        "DRUG INEFFECTIVE",
        "DEATH",
        "OFF LABEL USE",
        "PRODUCT USE ISSUE",
        "TOXICITY TO VARIOUS AGENTS",
        "COMPLETED SUICIDE",
        "OVERDOSE",
    }
    return Check(
        name="counts are not causality (CONTROL)",
        expectation="top term is a reporting artefact, not a side effect",
        passed=top_term in non_causal,
        observed=f"top={top_term!r} -- D11 caveat is mandatory",
    )


async def probe_nonsense_control(client: HttpClient) -> Check:
    """A drug that does not exist must return no reports."""
    data = await client.get_json(
        OPENFDA_EVENT_URL,
        {
            "search": 'patient.drug.openfda.generic_name:"zzzznopedrug"',
            "count": "patient.reaction.reactionmeddrapt.exact",
        },
    )
    return Check(
        name="nonsense drug (CONTROL)",
        expectation="NOT_FOUND -- proves the search field filters",
        passed=data is None,
        observed=f"body={data!r}",
    )


async def probe_no_denominator(client: HttpClient) -> Check:
    """Confirm the response carries no exposure denominator.

    If openFDA reported how many people took the drug, a rate could be
    computed honestly. It does not. This check records that absence, so
    nobody later assumes the field was merely overlooked.
    """
    data = await client.get_json(
        OPENFDA_EVENT_URL,
        {
            "search": 'patient.drug.openfda.generic_name:"acetaminophen"',
            "count": "patient.reaction.reactionmeddrapt.exact",
        },
    )
    meta = (data or {}).get("meta", {})
    has_denominator = any(
        k in meta for k in ("exposure", "population", "prescriptions")
    )
    return Check(
        name="no denominator exists",
        expectation="meta carries no exposure count -- rates are impossible",
        passed=not has_denominator,
        observed=f"meta keys={sorted(meta.keys())}",
    )


if __name__ == "__main__":
    raise SystemExit(
        run(
            "openFDA FAERS probe",
            source="openfda-event",
            probes=[
                probe_event_counts,
                probe_counts_are_not_causality,
                probe_nonsense_control,
                probe_no_denominator,
            ],
        )
    )

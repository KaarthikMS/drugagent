"""
Probe: openFDA drug labels (api.fda.gov/drug/label.json).

Run this BEFORE writing clients/openfda.py. See probes/_harness.py.

This is the probe the whole interaction feature rests on. It reproduces
the control table in docs/architecture.md section 5 -- including the
nonsense terms, which are the only reason we know the field filter runs
at all.

Usage, from app/drugagent/:
    python -m probes.probe_openfda_label
"""

from __future__ import annotations

from config import (
    OPENFDA_LABEL_URL,
    SECTION_INTERACTIONS,
    SECTION_OVERDOSAGE,
)
from probes._harness import Check, clip, run
from utils.base import HttpClient


async def _search(client: HttpClient, query: str, limit: int = 1) -> dict | None:
    """One openFDA search. None means the API reported no matches."""
    return await client.get_json(OPENFDA_LABEL_URL, {"search": query, "limit": limit})


def _total(data: dict | None) -> int:
    """Hit count. Absent when the API answered NOT_FOUND."""
    return (data or {}).get("meta", {}).get("results", {}).get("total", 0)


# --------------------------------------------------------------------
# The control table
# --------------------------------------------------------------------


async def probe_baseline(client: HttpClient) -> Check:
    """Baseline: how many warfarin labels exist at all.

    Every later number is meaningless without this one to compare to.
    """
    total = _total(await _search(client, 'openfda.generic_name:"warfarin"'))
    return Check(
        name="baseline: warfarin",
        expectation="a non-zero label count",
        passed=total > 0,
        observed=f"total={total}",
    )


async def probe_true_positive(client: HttpClient) -> Check:
    """A documented interaction: warfarin labels that mention aspirin."""
    total = _total(
        await _search(
            client,
            f'openfda.generic_name:"warfarin" AND {SECTION_INTERACTIONS}:"aspirin"',
        )
    )
    return Check(
        name="true positive: warfarin+aspirin",
        expectation="warfarin labels mention aspirin",
        passed=total > 0,
        observed=f"total={total}",
    )


async def probe_nonsense_control(client: HttpClient) -> Check:
    """The control that gives the previous check meaning.

    A word that appears in no label must return nothing. If it returned
    the baseline count instead, the field filter is being ignored and
    every "documented interaction" result is an artefact -- which is
    indistinguishable from a true positive without this check.
    """
    data = await _search(
        client,
        f'openfda.generic_name:"warfarin" AND {SECTION_INTERACTIONS}:"zzzznope"',
    )
    return Check(
        name="nonsense control",
        expectation="NOT_FOUND -- proves the field filter runs",
        passed=data is None,
        observed=f"body={data!r}",
    )


async def probe_true_negative(client: HttpClient) -> Check:
    """A real pair with no documented interaction.

    Distinct from the nonsense control: 'aspirin' is a real term that
    does appear in other labels. This proves the filter discriminates
    between drugs, not merely between real and fake words.
    """
    data = await _search(
        client,
        f'openfda.generic_name:"metformin" AND {SECTION_INTERACTIONS}:"aspirin"',
    )
    return Check(
        name="true negative: metformin+aspirin",
        expectation="NOT_FOUND -- no documented interaction",
        passed=data is None,
        observed=f"body={data!r}",
    )


# --------------------------------------------------------------------
# Section retrieval
# --------------------------------------------------------------------


async def probe_section_size(client: HttpClient) -> Check:
    """How much text one interaction section actually is.

    This number sets the cost of every interaction query: two of these
    go into context. If it is in the thousands, passing whole sections
    to the model is not an option and span extraction is mandatory.
    """
    data = await _search(client, 'openfda.generic_name:"warfarin"')
    results = (data or {}).get("results", [])
    section = " ".join(results[0].get(SECTION_INTERACTIONS, [])) if results else ""
    return Check(
        name="interaction section size",
        expectation="thousands of chars -- span extraction is mandatory",
        passed=len(section) > 1000,
        observed=f"{len(section)} chars: {clip(section, 70)}",
    )


async def probe_overdosage_exists(client: HttpClient) -> Check:
    """The toxicity path needs the overdosage section to be populated.

    `_exists_` asks openFDA for labels where the field is present at
    all. A section named in the schema is not necessarily filled in on
    any given label, and a toxicity answer grounded in an empty section
    is an ungrounded answer.
    """
    data = await _search(
        client,
        f'openfda.generic_name:"acetaminophen" AND _exists_:{SECTION_OVERDOSAGE}',
    )
    results = (data or {}).get("results", [])
    section = " ".join(results[0].get(SECTION_OVERDOSAGE, [])) if results else ""
    return Check(
        name="overdosage section populated",
        expectation="acetaminophen labels carry overdosage text",
        passed=len(section) > 200,
        observed=f"total={_total(data)} chars={len(section)}: {clip(section, 60)}",
    )


async def probe_source_identity(client: HttpClient) -> Check:
    """Every answer needs a citable source, so the id must be retrievable.

    Without set_id there is no stable URL to cite, and principle 2
    ('cite only what was retrieved') becomes unenforceable.
    """
    data = await _search(client, 'openfda.generic_name:"warfarin"')
    results = (data or {}).get("results", [])
    first = results[0] if results else {}
    set_id = first.get("set_id")
    effective = first.get("effective_time")
    return Check(
        name="citable source identity",
        expectation="set_id present, for a stable DailyMed citation URL",
        passed=bool(set_id),
        observed=f"set_id={set_id} effective_time={effective}",
    )


if __name__ == "__main__":
    raise SystemExit(
        run(
            "openFDA label probe",
            source="openfda-label",
            probes=[
                probe_baseline,
                probe_true_positive,
                probe_nonsense_control,
                probe_true_negative,
                probe_section_size,
                probe_overdosage_exists,
                probe_source_identity,
            ],
        )
    )

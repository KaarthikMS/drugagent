"""
Live smoke tests: do the real APIs still behave as recorded?

Unit tests prove our parsing is right against a fixed response. They
cannot notice an upstream changing its shape -- and every client here
was written against observed behaviour, so a silent upstream change is
the failure mode that matters most.

These hit the network. Deselect with:

    pytest -m "not smoke"

Kept deliberately thin: one assertion per client, chosen so that failure
means "the contract moved", not "someone edited a label". They are a
canary, not a second copy of probes/.
"""

from __future__ import annotations

import pytest

from clients import Clients

pytestmark = pytest.mark.smoke


@pytest.fixture
async def clients():
    bundle = Clients()
    yield bundle
    await bundle.aclose()


async def test_rxnorm_resolves_and_hops(clients):
    """Normalisation and the D4 product hop still work end to end."""
    ref = await clients.rxnorm.resolve("warfarin")
    assert ref is not None and ref.rxcui == "11289"
    assert "855288" in await clients.rxnorm.get_related_products(ref.rxcui)


async def test_rxnorm_recovers_a_typo(clients):
    """A typo resolves, and comes back flagged for confirmation."""
    ref = await clients.rxnorm.resolve("metformn")
    assert ref is not None and ref.approximate is True
    assert ref.requires_confirmation is True
    assert "metformin" in ref.name.lower()


async def test_rxnorm_rejects_genuine_nonsense(clients):
    """RxNorm itself returns no candidates for a non-word.

    This is the gate that actually holds -- not a score threshold.
    """
    assert await clients.rxnorm.resolve("zzzznopedrug") is None


async def test_rxclass_returns_atc_only(clients):
    """The relaSource pin holds.

    If this fails with extra sources, MED-RT relations are back in the
    results and warfarin is once again "classed" as Alcoholism.
    """
    classes = await clients.rxclass.classes_for("11289")
    assert classes and all(c.source == "ATC" for c in classes)
    assert any(c.class_id.startswith("B01A") for c in classes)


async def test_openfda_label_and_interaction_filter(clients):
    """The field filter still filters -- the nonsense control, live."""
    label = await clients.openfda.get_label("warfarin", ("drug_interactions",))
    assert label and label.sections["drug_interactions"]
    assert await clients.openfda.mentions_in_section(
        "warfarin", "drug_interactions", "aspirin"
    )
    assert not await clients.openfda.mentions_in_section(
        "warfarin", "drug_interactions", "zzzznope"
    )


async def test_openfda_events_still_report_artefacts(clients):
    counts = await clients.openfda.event_counts("acetaminophen")
    assert counts and counts.counts


async def test_pubchem_properties_and_hazard(clients):
    cid = await clients.pubchem.find_cid("ibuprofen")
    assert cid == 3672
    compound = await clients.pubchem.get_properties(cid, "ibuprofen")
    assert compound.formula == "C13H18O2" and compound.smiles
    assert (await clients.pubchem.get_hazards(cid)) is not None


async def test_pubchem_absent_hazard_stays_absent(clients):
    """Hydrotalcite: a real drug with no published hazard data."""
    assert await clients.pubchem.get_hazards(71749) is None


async def test_medlineplus_topics_and_loinc(clients):
    topics = await clients.medlineplus.search_topics("hypothyroidism")
    assert topics and "<" not in topics[0].title
    assert await clients.medlineplus.lookup_loinc("2093-3") is not None
    assert await clients.medlineplus.lookup_loinc("99999-9") is None


async def test_clinicaltables_ambiguity_still_ambiguous(clients):
    """If this starts returning few hits, revisit the confidence rule."""
    match = await clients.clinicaltables.loinc_for("hemoglobin")
    assert match is not None and match.confident is False


async def test_dailymed_gives_dated_provenance(clients):
    spl = await clients.dailymed.find_spl("warfarin")
    assert spl and spl.set_id and spl.published


async def test_retriever_returns_citable_passages(clients):
    """D2's interface, exercised against the live backend."""
    passages = await clients.retriever.search("hypothyroidism")
    assert passages and all(p.url and p.text for p in passages)

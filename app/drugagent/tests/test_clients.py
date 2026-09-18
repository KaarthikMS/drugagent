"""
Client parsing: the traps recorded in probes/FINDINGS.md, pinned.

Each test here corresponds to a real observed behaviour of a real API.
They exist so that a refactor cannot quietly reintroduce a bug the
probes already found once.
"""

from __future__ import annotations

import pytest

from clients.clinicaltables import ClinicalTablesClient
from clients.medlineplus import MedlinePlusClient
from clients.openfda import OpenFdaClient
from clients.pubchem import PubChemClient
from clients.rxclass import DrugClass, RxClassClient
from clients.rxnorm import RxNormClient
from tests.conftest import json_response, not_found, xml_response


def _with(client_obj, http):
    client_obj._http = http
    return client_obj


# ---------------------------------------------------------------- RxNorm


@pytest.mark.asyncio
async def test_rxnorm_empty_200_is_not_found(mock_http):
    """The trap: unknown name -> HTTP 200 with `{"idGroup": {}}`.

    Not a 404. Code that branched on the status code would treat this as
    success and then read a key that is not there.
    """
    client = _with(
        RxNormClient(), mock_http({"rxcui.json": json_response({"idGroup": {}})})
    )
    assert await client.find_rxcui("zzzznopedrug") is None
    await client.aclose()


@pytest.mark.asyncio
async def test_rxnorm_exact_match(mock_http):
    client = _with(
        RxNormClient(),
        mock_http({"rxcui.json": json_response({"idGroup": {"rxnormId": ["11289"]}})}),
    )
    ref = await client.find_rxcui("warfarin")
    assert ref.rxcui == "11289" and ref.approximate is False
    await client.aclose()


@pytest.mark.asyncio
async def test_rxnorm_absurd_suggestion_is_discarded(mock_http):
    """A suggestion unrelated to what was typed is dropped.

    This is a sanity filter, not a safety control -- see
    APPROXIMATE_MIN_SIMILARITY for why no threshold can be one.
    """
    client = _with(
        RxNormClient(),
        mock_http(
            {
                "approximateTerm.json": json_response(
                    {"approximateGroup": {"candidate": [{"rxcui": "1", "score": "9"}]}}
                ),
                "properties.json": json_response({"properties": {"name": "warfarin"}}),
            }
        ),
    )
    assert await client.approximate_match("qqqq") is None
    await client.aclose()


@pytest.mark.asyncio
async def test_rxnorm_typo_match_demands_confirmation(mock_http):
    """A fuzzy match is never accepted silently.

    prednisone -> prednisolone scores 0.909 and is a DIFFERENT drug;
    metfrmn -> metformin scores 0.875 and is a typo. Nothing in the
    string separates them, so the user must be asked.
    """
    client = _with(
        RxNormClient(),
        mock_http(
            {
                "approximateTerm.json": json_response(
                    {
                        "approximateGroup": {
                            "candidate": [{"rxcui": "6809", "score": "8.1"}]
                        }
                    }
                ),
                "properties.json": json_response({"properties": {"name": "metformin"}}),
            }
        ),
    )
    ref = await client.approximate_match("metformn")
    assert ref.name == "metformin"
    assert ref.approximate is True
    assert ref.requires_confirmation is True
    await client.aclose()


@pytest.mark.asyncio
async def test_rxnorm_exact_match_needs_no_confirmation(mock_http):
    client = _with(
        RxNormClient(),
        mock_http({"rxcui.json": json_response({"idGroup": {"rxnormId": ["11289"]}})}),
    )
    ref = await client.find_rxcui("warfarin")
    assert ref.requires_confirmation is False
    await client.aclose()


@pytest.mark.asyncio
async def test_rxnorm_scd_hop_filters_by_tty(mock_http):
    """Only SCD concepts are products; other tty groups must be ignored."""
    client = _with(
        RxNormClient(),
        mock_http(
            {
                "related.json": json_response(
                    {
                        "relatedGroup": {
                            "conceptGroup": [
                                {"tty": "SBD", "conceptProperties": [{"rxcui": "999"}]},
                                {
                                    "tty": "SCD",
                                    "conceptProperties": [{"rxcui": "855288"}],
                                },
                            ]
                        }
                    }
                )
            }
        ),
    )
    assert await client.get_related_products("11289") == ["855288"]
    await client.aclose()


# --------------------------------------------------------------- RxClass


@pytest.mark.asyncio
async def test_rxclass_atc_hierarchy_overlap():
    """M01AE (propionic acid derivatives) sits under M01A (NSAIDs).

    Exact-id comparison would call ibuprofen and naproxen unrelated when
    both are NSAIDs, which is exactly the class-level match the
    interaction check depends on finding.
    """
    client = RxClassClient()
    shared = await client.shared_classes(
        [DrugClass("M01AE", "Propionic acid derivatives")],
        [DrugClass("M01A", "Anti-inflammatory")],
    )
    assert [c.class_id for c in shared] == ["M01AE"]
    await client.aclose()


@pytest.mark.asyncio
async def test_rxclass_unknown_rxcui_returns_empty(mock_http):
    """Unknown rxcui -> HTTP 200 with `{}`. Fifth convention."""
    client = _with(RxClassClient(), mock_http({"byRxcui.json": json_response({})}))
    assert await client.classes_for("999999999") == []
    await client.aclose()


# --------------------------------------------------------------- openFDA


@pytest.mark.asyncio
async def test_openfda_sections_are_lists_and_get_capped(mock_http):
    """Label sections are lists of strings, and can be enormous."""
    client = _with(
        OpenFdaClient(),
        mock_http(
            {
                "label.json": json_response(
                    {
                        "results": [
                            {
                                "set_id": "abc",
                                "effective_time": "20250617",
                                "drug_interactions": ["x" * 9000],
                            }
                        ]
                    }
                )
            }
        ),
    )
    label = await client.get_label("warfarin", ("drug_interactions",))
    assert len(label.sections["drug_interactions"]) == 4000
    assert label.jurisdiction == "US"
    assert "abc" in label.source_url
    await client.aclose()


@pytest.mark.asyncio
async def test_openfda_not_found_is_none(mock_http):
    client = _with(OpenFdaClient(), mock_http({"label.json": not_found()}))
    assert await client.get_label("zzzznope", ("indications_and_usage",)) is None
    await client.aclose()


@pytest.mark.asyncio
async def test_openfda_event_counts_carry_the_caveat(mock_http):
    """FAERS counts without their caveat are read as incidence rates."""
    client = _with(
        OpenFdaClient(),
        mock_http(
            {
                "event.json": json_response(
                    {"results": [{"term": "DRUG INEFFECTIVE", "count": 52232}]}
                )
            }
        ),
    )
    counts = await client.event_counts("acetaminophen")
    assert counts.counts["DRUG INEFFECTIVE"] == 52232
    assert "denominator" in counts.caveat
    await client.aclose()


# --------------------------------------------------------------- PubChem


@pytest.mark.asyncio
async def test_pubchem_finds_renamed_smiles_key(mock_http):
    """PubChem renamed CanonicalSMILES and answers 200 with the new key.

    Indexing the requested name would raise KeyError on a successful
    request, so the key is found by searching the response.
    """
    client = _with(
        PubChemClient(),
        mock_http(
            {
                "property": json_response(
                    {
                        "PropertyTable": {
                            "Properties": [
                                {
                                    "CID": 3672,
                                    "MolecularFormula": "C13H18O2",
                                    "ConnectivitySMILES": "CC(C)C",
                                }
                            ]
                        }
                    }
                )
            }
        ),
    )
    compound = await client.get_properties(3672, "ibuprofen")
    assert compound.smiles == "CC(C)C"
    await client.aclose()


@pytest.mark.asyncio
async def test_pubchem_absent_hazard_is_none_not_empty(mock_http):
    """ "No hazard data published" is not "not hazardous" (principle 3)."""
    client = _with(PubChemClient(), mock_http({"pug_view": not_found()}))
    assert await client.get_hazards(71749) is None
    await client.aclose()


# ----------------------------------------------------------- MedlinePlus


@pytest.mark.asyncio
async def test_medlineplus_strips_highlight_markup(mock_http):
    """Titles arrive wrapped in <span class="qt0"> highlighting."""
    body = (
        "<nlmSearchResult><count>1</count><list>"
        '<document url="https://medlineplus.gov/hypothyroidism.html">'
        '<content name="title">&lt;span class="qt0"&gt;Hypothyroidism&lt;/span&gt;</content>'
        '<content name="FullSummary">An underactive thyroid.</content>'
        "</document></list></nlmSearchResult>"
    )
    client = _with(MedlinePlusClient(), mock_http({"ws/query": xml_response(body)}))
    topics = await client.search_topics("hypothyroidism")
    assert topics[0].title == "Hypothyroidism"
    await client.aclose()


@pytest.mark.asyncio
async def test_medlineplus_zero_count_is_empty(mock_http):
    """Nothing found -> HTTP 200, valid XML, <count>0</count>."""
    client = _with(
        MedlinePlusClient(),
        mock_http(
            {
                "ws/query": xml_response(
                    "<nlmSearchResult><count>0</count></nlmSearchResult>"
                )
            }
        ),
    )
    assert await client.search_topics("zzzznope") == []
    await client.aclose()


@pytest.mark.asyncio
async def test_medlineplus_unmapped_loinc_is_none(mock_http):
    """An unmapped code must never borrow another test's description."""
    client = _with(
        MedlinePlusClient(), mock_http({"service": json_response({"feed": {}})})
    )
    assert await client.lookup_loinc("99999-9") is None
    await client.aclose()


# ------------------------------------------------------- Clinical Tables


@pytest.mark.asyncio
async def test_clinicaltables_broad_match_is_not_confident(mock_http):
    """ "hemoglobin" spans 508 LOINC items; the top hit is the wrong test.

    The match is still returned -- the caller needs to know one exists --
    but flagged so no description is attached to it.
    """
    client = _with(
        ClinicalTablesClient(),
        mock_http(
            {
                "loinc_items": json_response(
                    [508, ["97551-6"], None, [["COHgb MFr BldCV"]]]
                )
            }
        ),
    )
    match = await client.loinc_for("hemoglobin")
    assert match.total_hits == 508 and match.confident is False
    await client.aclose()


@pytest.mark.asyncio
async def test_clinicaltables_narrow_match_is_confident(mock_http):
    client = _with(
        ClinicalTablesClient(),
        mock_http(
            {"loinc_items": json_response([1, ["2093-3"], None, [["Cholesterol"]]])}
        ),
    )
    match = await client.loinc_for("total cholesterol")
    assert match.confident is True
    await client.aclose()


@pytest.mark.asyncio
async def test_clinicaltables_empty_array_is_no_match(mock_http):
    """Nothing found -> `[0, [], null, []]`. Sixth convention."""
    client = _with(
        ClinicalTablesClient(),
        mock_http({"loinc_items": json_response([0, [], None, []])}),
    )
    assert await client.loinc_for("zzzznope") is None
    await client.aclose()

"""
Interaction cross-check: the contract that must not fail.

Fixture label text, no network, no model. These tests would catch a
clinical defect -- specifically the one that shipped before: warfarin
plus aspirin returning clean.
"""

from __future__ import annotations

from domain.interactions import (
    DOCUMENTED_MESSAGE,
    NOT_DOCUMENTED_MESSAGE,
    ONE_SIDED_MESSAGE,
    cross_check,
    find_mentions,
)
from domain.models import Citation, DrugRef, Severity

WARFARIN = DrugRef(name="warfarin", rxcui="11289", ingredients=("warfarin sodium",))
ASPIRIN = DrugRef(name="aspirin", rxcui="1191", ingredients=("acetylsalicylic acid",))
METFORMIN = DrugRef(name="metformin", rxcui="6809")
IBUPROFEN = DrugRef(name="ibuprofen", rxcui="5640")

# Abridged from the real warfarin label.
WARFARIN_TEXT = (
    "DRUG INTERACTIONS Concomitant use of drugs that increase bleeding risk. "
    "Aspirin and other salicylates may increase the anticoagulant effect and "
    "the risk of bleeding. Monitor INR closely when starting or stopping."
)
ASPIRIN_TEXT = (
    "Drug Interactions: Anticoagulants. Patients taking oral anticoagulants "
    "are at increased risk of bleeding when aspirin is administered."
)
METFORMIN_TEXT = (
    "DRUG INTERACTIONS Carbonic anhydrase inhibitors may increase the risk of "
    "lactic acidosis. Drugs that reduce metformin clearance require dose "
    "adjustment."
)
NSAID_CLASS_TEXT = (
    "DRUG INTERACTIONS NSAIDs. Concomitant use of NSAIDs with anticoagulants "
    "increases the risk of serious gastrointestinal bleeding."
)

CITE_A = Citation(title="Warfarin label", url="https://example/a")
CITE_B = Citation(title="Aspirin label", url="https://example/b")


# ------------------------------------------------------- the known case


def test_warfarin_aspirin_is_documented():
    """The interaction the previous implementation returned clean for."""
    result = cross_check(WARFARIN, ASPIRIN, WARFARIN_TEXT, ASPIRIN_TEXT, CITE_A, CITE_B)
    assert result.documented is True
    assert result.severity_floor is Severity.HIGH
    assert result.evidence
    assert result.message == DOCUMENTED_MESSAGE


def test_metformin_aspirin_is_not_documented():
    result = cross_check(METFORMIN, ASPIRIN, METFORMIN_TEXT, ASPIRIN_TEXT)
    assert result.documented is False
    assert not result.evidence


# ------------------------------------------ the contract that must hold


def test_not_documented_never_says_safe():
    """The most dangerous sentence in the product, pinned.

    The message is written in code, not composed by the model, so this
    assertion is meaningful -- a prompt instruction could not be tested
    this way.
    """
    result = cross_check(METFORMIN, ASPIRIN, METFORMIN_TEXT, ASPIRIN_TEXT)
    assert "not evidence of absence" in result.message
    # Absolute vocabulary ban, not a judgement about phrasing. A
    # reassuring word in front of a skimming reader does its damage
    # regardless of the clause it sits in.
    lowered = result.message.lower()
    for forbidden in ("safe", "no risk", "fine to take", "no interaction exists"):
        assert forbidden not in lowered, f"message implies safety: {forbidden!r}"


def test_undocumented_still_reaches_the_escalation_threshold():
    """ "The labels do not say" is a pharmacist question, not reassurance."""
    result = cross_check(METFORMIN, ASPIRIN, METFORMIN_TEXT, ASPIRIN_TEXT)
    assert result.severity_floor is Severity.MEDIUM


# ------------------------------------------------------ both directions


def test_detection_works_when_only_a_mentions_b():
    result = cross_check(WARFARIN, ASPIRIN, WARFARIN_TEXT, "Nothing relevant here.")
    assert result.documented is True


def test_detection_works_when_only_b_mentions_a():
    """Labels are not symmetric; one direction halves detection."""
    result = cross_check(
        DrugRef(name="oral anticoagulants"), ASPIRIN, "Nothing relevant.", ASPIRIN_TEXT
    )
    assert result.documented is True


# ------------------------------------------------------- class matching


def test_class_level_warning_is_detected():
    """The label says "NSAIDs" and never says "ibuprofen"."""
    result = cross_check(
        WARFARIN,
        IBUPROFEN,
        NSAID_CLASS_TEXT,
        "Nothing relevant.",
        classes_b=("NSAIDs",),
    )
    assert result.documented is True
    assert "nsaids" in result.shared_classes


def test_without_class_the_same_pair_is_missed():
    """Shows what class matching buys, rather than asserting it exists."""
    result = cross_check(WARFARIN, IBUPROFEN, NSAID_CLASS_TEXT, "Nothing relevant.")
    assert result.documented is False


def test_ingredient_name_is_matched():
    text = "Interactions: acetylsalicylic acid increases bleeding risk."
    result = cross_check(WARFARIN, ASPIRIN, text, None)
    assert result.documented is True


# ----------------------------------------------------- partial retrieval


def test_missing_label_is_reported_as_one_sided():
    """A failed fetch is not "nothing found there"."""
    result = cross_check(METFORMIN, ASPIRIN, None, ASPIRIN_TEXT)
    assert result.one_sided is True
    assert ONE_SIDED_MESSAGE in result.message
    assert NOT_DOCUMENTED_MESSAGE in result.message


def test_both_labels_missing_is_not_one_sided():
    result = cross_check(METFORMIN, ASPIRIN, None, None)
    assert result.one_sided is False
    assert result.documented is False


# -------------------------------------------------------- span matching


def test_substring_matches_are_rejected():
    """ "ace" inside "acetaminophen" is not a mention of ACE inhibitors."""
    assert find_mentions("contains acetaminophen and placebo", ["ace"]) == []


def test_match_is_case_insensitive():
    assert find_mentions("ASPIRIN increases risk", ["aspirin"])


def test_span_is_bounded_not_the_whole_section():
    """Two 6,500-char sections per query is the cost being avoided."""
    text = "x" * 5000 + " aspirin " + "y" * 5000
    ((_, span),) = find_mentions(text, ["aspirin"])
    assert len(span) < 1000


def test_short_terms_are_not_used_for_matching():
    """A three-letter term matches everything and means nothing."""
    drug = DrugRef(name="abc")
    result = cross_check(WARFARIN, drug, "abc appears here", None)
    assert result.documented is False

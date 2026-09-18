"""
Severity: exhaustive, because this is the layer that must not fail.

No network, no model, no credentials. Every test here would catch a
clinical defect rather than a software one.
"""

from __future__ import annotations

import itertools

import pytest

from domain.models import Severity
from domain.severity import (
    TRIPWIRES,
    check_tripwire,
    escalation_text,
    max_severity,
    should_escalate,
)

ALL = list(Severity)


# ------------------------------------------------------------ ordering


def test_severity_order_is_what_the_rest_of_the_system_assumes():
    assert ALL == sorted(ALL, key=lambda s: s.rank)
    assert Severity.EMERGENCY > Severity.HIGH > Severity.MEDIUM
    assert Severity.MEDIUM > Severity.LOW > Severity.INFORMATIONAL


def test_comparison_is_by_rank_not_alphabetical():
    """Severity is a str Enum, so `>` could inherit string ordering.

    Alphabetically "emergency" < "high" < "informational" < "low", which
    is close enough to plausible to pass a casual reading and wrong in
    the one direction that matters.
    """
    assert Severity.EMERGENCY > Severity.INFORMATIONAL
    assert Severity.HIGH >= Severity.MEDIUM
    assert not (Severity.LOW > Severity.HIGH)
    assert sorted(ALL) == ALL


# --------------------------------------------------------- max_severity


@pytest.mark.parametrize("a,b", list(itertools.product(ALL, ALL)))
def test_max_is_exhaustive_over_every_pair(a, b):
    """Every combination, not a sample.

    Five levels is twenty-five pairs. Enumerating them costs nothing and
    removes the question of whether the interesting one was tested.
    """
    result = max_severity(a, b)
    assert result in (a, b)
    assert result.rank == max(a.rank, b.rank)


@pytest.mark.parametrize("floor", ALL)
def test_nothing_can_lower_a_raised_severity(floor):
    """The core property: no component can undo another's escalation."""
    assert max_severity(floor, Severity.INFORMATIONAL) is floor
    assert max_severity(Severity.INFORMATIONAL, floor) is floor


def test_none_is_ignored_not_treated_as_zero():
    """A component with no opinion must not be able to express one."""
    assert max_severity(None, Severity.HIGH) is Severity.HIGH
    assert max_severity(Severity.HIGH, None, None) is Severity.HIGH


def test_no_inputs_is_informational():
    assert max_severity() is Severity.INFORMATIONAL
    assert max_severity(None) is Severity.INFORMATIONAL


def test_six_components_combine_to_the_highest():
    """The real call shape: tripwire, model, triage, and three floors."""
    assert (
        max_severity(
            None,
            Severity.LOW,
            Severity.MEDIUM,
            None,
            Severity.EMERGENCY,
            Severity.INFORMATIONAL,
        )
        is Severity.EMERGENCY
    )


# -------------------------------------------------------------- tripwire


@pytest.mark.parametrize(
    "text,expected_reason",
    [
        ("I've had crushing chest pain for an hour", "acute coronary"),
        ("chest tightness since this morning", "acute coronary"),
        ("I can't breathe properly", "respiratory"),
        ("sudden shortness of breath", "respiratory"),
        ("my face is drooping and my speech is slurred", "stroke"),
        ("numbness in my left arm", "stroke"),
        ("worst headache of my life", "subarachnoid"),
        ("my throat is swelling after the tablet", "anaphylaxis"),
        ("I want to kill myself", "self-harm"),
        ("I just took too many paracetamol", "overdose"),
        ("I've taken 30 tablets", "overdose"),
        ("I'm vomiting blood", "haemorrhage"),
        ("he had a seizure just now", "neurological"),
    ],
)
def test_emergency_presentations_fire(text, expected_reason):
    hit = check_tripwire(text)
    assert hit is not None, f"tripwire missed: {text!r}"
    assert hit.floor is Severity.EMERGENCY
    assert expected_reason in hit.reason


@pytest.mark.parametrize(
    "text",
    [
        "What is metformin used for?",
        "Can I take ibuprofen with paracetamol?",
        "I've had a mild headache for three days",
        "what are the side effects of atorvastatin",
        "my cholesterol result was 210",
        "is amoxicillin safe during pregnancy",
    ],
)
def test_ordinary_questions_do_not_fire(text):
    """Over-escalation is acceptable; escalating everything is not.

    A tripwire that fires on routine questions trains users to ignore it,
    which costs exactly what a missed emergency costs.
    """
    assert check_tripwire(text) is None


def test_third_person_overdose_is_a_question_not_an_event():
    """ "What happens if someone takes too much" is information.

    "I just took too much" is an event in progress (D11).
    """
    assert check_tripwire("what happens if someone takes too much paracetamol") is None
    assert check_tripwire("I just took too much paracetamol") is not None


def test_negation_still_escalates_and_that_is_deliberate():
    """Documented limitation, pinned so it cannot change silently.

    Handling negation means adding a way for the tripwire to be talked
    out of firing. A tripwire that can be argued with is not a tripwire.
    """
    assert check_tripwire("I do not have chest pain") is not None


def test_every_tripwire_has_a_reason():
    """The reason reaches the user's answer, so it cannot be blank."""
    assert all(w.reason.strip() for w in TRIPWIRES)


# ------------------------------------------------------------ escalation


@pytest.mark.parametrize("severity", [Severity.INFORMATIONAL, Severity.LOW])
def test_below_threshold_produces_no_block(severity):
    assert not should_escalate(severity)
    assert escalation_text(severity) is None


@pytest.mark.parametrize(
    "severity", [Severity.MEDIUM, Severity.HIGH, Severity.EMERGENCY]
)
def test_at_or_above_threshold_always_produces_a_block(severity):
    assert should_escalate(severity)
    text = escalation_text(severity)
    assert text and text.strip()


def test_emergency_text_names_the_emergency_number():
    text = escalation_text(Severity.EMERGENCY)
    assert "112" in text
    assert "now" in text.lower()


def test_emergency_reason_is_carried_into_the_text():
    text = escalation_text(Severity.EMERGENCY, reason="possible stroke")
    assert "possible stroke" in text


def test_reason_is_not_leaked_into_lower_severities():
    """A MEDIUM block explaining a tripwire reason would be incoherent."""
    text = escalation_text(Severity.MEDIUM, reason="possible stroke")
    assert "possible stroke" not in text

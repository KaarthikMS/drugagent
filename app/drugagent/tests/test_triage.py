"""
Symptom triage ruleset.

Every test is a clinical judgement written down. A clinician reviewing
this file can check the rules against this file's expectations directly,
which is the entire argument for a ruleset over a prompt (D12).
"""

from __future__ import annotations

import pytest

from domain.models import Severity
from domain.triage import RULES, SymptomReport, triage


def s(symptom, **kw):
    return SymptomReport(symptom=symptom, **kw)


@pytest.mark.parametrize(
    "report,expected",
    [
        (s("headache", modifiers=("sudden", "worst")), Severity.EMERGENCY),
        (s("headache", modifiers=("vision changes",)), Severity.EMERGENCY),
        (s("chest pain"), Severity.EMERGENCY),
        (s("shortness of breath"), Severity.EMERGENCY),
        (s("abdominal pain", modifiers=("severe",)), Severity.EMERGENCY),
        (s("fever", modifiers=("pregnant",)), Severity.HIGH),
        (s("fever", duration_hours=96), Severity.HIGH),
        (s("vomiting", duration_hours=30), Severity.HIGH),
        (s("rash", modifiers=("fever",)), Severity.HIGH),
        (s("headache", duration_hours=96), Severity.MEDIUM),
        (s("cough", duration_hours=400), Severity.MEDIUM),
    ],
)
def test_red_flags_reach_their_floor(report, expected):
    assert triage(report).floor is expected


@pytest.mark.parametrize(
    "report",
    [
        s("headache", duration_hours=6),
        s("mild sore throat", duration_hours=24),
        s("cough", duration_hours=48),
        s("runny nose"),
    ],
)
def test_benign_presentations_stay_low(report):
    assert triage(report).floor is Severity.LOW


def test_no_match_is_low_not_informational():
    """Someone describing a symptom is not asking a reference question."""
    assert triage(s("hiccups")).floor is Severity.LOW


def test_worst_rule_wins_when_several_match():
    """A benign rule must never cancel a serious one."""
    result = triage(s("headache", duration_hours=96, modifiers=("sudden", "worst")))
    assert result.floor is Severity.EMERGENCY
    assert len(result.matched) >= 2


def test_unknown_duration_never_satisfies_a_duration_rule():
    """A missing duration is not a short one.

    Treating None as zero would silently downgrade "I have had this for
    a week" whenever the user did not give a number.
    """
    assert triage(s("fever")).floor is Severity.LOW
    assert triage(s("fever", duration_hours=96)).floor is Severity.HIGH


def test_duration_boundary_is_exclusive():
    """ "More than three days" means more than, not exactly."""
    assert triage(s("headache", duration_hours=72)).floor is Severity.LOW
    assert triage(s("headache", duration_hours=73)).floor is Severity.MEDIUM


def test_matched_rules_and_reasons_are_reported():
    """The reason reaches the user's answer, so it must be carried."""
    result = triage(s("chest pain"))
    assert result.matched and all(r.strip() for r in result.reasons)


def test_every_rule_is_reviewable():
    """A rule with no reason cannot be reviewed by a clinician."""
    assert all(rule.name and rule.reason for rule in RULES)
    assert all(rule.symptoms for rule in RULES)

"""
Lab parsing, unit reconciliation and flagging.

The highest-risk surface in the product. Every test here is a clinical
defect if it fails, and none of them touch a network or a model.
"""

from __future__ import annotations

import pytest

from domain.labs import (
    IN_RANGE_CAVEAT,
    classify,
    parse_report,
    parse_row,
    partial_reading_notice,
    severity_floor,
)
from domain.models import Analyte, AnalyteStatus, RangeSource, Severity
from domain.units import compatible, convert, normalise

REPORT = """\
Haemoglobin       13.2   g/dL     13.0 - 17.0
Glucose (F)       104    mg/dL    70 - 100
Creatinine        0.9    mg/dL    0.7 - 1.3
Potassium         6.9    mmol/L   3.5 - 5.1
"""


# --------------------------------------------------------------- units


def test_scale_conversion_is_substance_independent():
    """mg/dL -> g/dL is arithmetic for every substance."""
    mgdl, gdl = normalise("mg/dL"), normalise("g/dL")
    assert compatible(mgdl, gdl)
    assert convert(1000.0, mgdl, gdl) == pytest.approx(1.0)


def test_molar_conversion_is_refused_not_guessed():
    """The most dangerous conversion in the system, declined.

    Creatinine 1.2 mg/dL is 106 umol/L. Glucose 1.2 mg/dL is a different
    number entirely. Converting without knowing the analyte rescales a
    real clinical value and flags it with full confidence.
    """
    mgdl, umol = normalise("mg/dL"), normalise("umol/L")
    assert mgdl and umol
    assert not compatible(mgdl, umol)
    assert convert(1.2, mgdl, umol) is None


def test_micro_sign_variants_are_the_same_unit():
    """µ, μ and u are three characters meaning one thing."""
    assert normalise("µmol/L") == normalise("μmol/L") == normalise("umol/L")


def test_unknown_unit_stays_unknown():
    """A lab may print a unit this table does not know."""
    assert normalise("widgets/fortnight") is None
    assert normalise(None) is None


# --------------------------------------------------------------- parsing


def test_row_with_unit_and_range():
    row = parse_row("Haemoglobin       13.2   g/dL     13.0 - 17.0")
    assert isinstance(row, Analyte)
    assert row.name == "Haemoglobin"
    assert row.value == 13.2
    assert row.unit == "g/dL"
    assert (row.ref_low, row.ref_high) == (13.0, 17.0)
    assert row.ref_source is RangeSource.REPORT


def test_range_comes_from_the_report_not_a_table():
    """D9: the lab that ran the assay printed its own ranges."""
    row = parse_row("Glucose   104   mg/dL   70 - 100")
    assert row.ref_source is RangeSource.REPORT
    assert (row.ref_low, row.ref_high) == (70.0, 100.0)


def test_unreadable_row_is_returned_not_dropped():
    row = parse_row("=== COMPLETE BLOOD COUNT ===")
    assert not isinstance(row, Analyte)
    assert row.reason


def test_every_line_lands_somewhere():
    """The property that makes "we say what we could not read" real."""
    text = REPORT + "Some free text header\nAnother  ??  line\n"
    report = parse_report(text)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(report.analytes) + len(report.unparsed) == len(lines)


# ------------------------------------------------------------ flagging


@pytest.mark.parametrize(
    "value,expected",
    [
        (13.2, AnalyteStatus.WITHIN),
        (12.0, AnalyteStatus.BELOW),
        (18.0, AnalyteStatus.ABOVE),
        (13.0, AnalyteStatus.WITHIN),
        (17.0, AnalyteStatus.WITHIN),
    ],
)
def test_comparison_is_arithmetic(value, expected):
    """Boundaries included: 13.0 with a 13.0-17.0 range is within."""
    analyte = Analyte(name="Hb", value=value, unit="g/dL", ref_low=13.0, ref_high=17.0)
    assert classify(analyte).status is expected


def test_grossly_abnormal_is_critical_not_merely_high():
    analyte = Analyte(name="K", value=40.0, unit="mmol/L", ref_low=3.5, ref_high=5.1)
    assert classify(analyte).status is AnalyteStatus.CRITICAL


def test_missing_range_is_unverified_not_normal():
    """No range means no comparison was possible, not that it passed."""
    analyte = Analyte(name="Ferritin", value=42.0, unit="ng/mL")
    result = classify(analyte)
    assert result.status is AnalyteStatus.UNVERIFIED
    assert "reference range" in result.note


def test_irreconcilable_unit_is_unverified():
    """The mass/molar boundary, at the point it actually bites."""
    analyte = Analyte(
        name="Creatinine", value=1.2, unit="mg/dL", ref_low=60.0, ref_high=110.0
    )
    result = classify(analyte, range_unit="umol/L")
    assert result.status is AnalyteStatus.UNVERIFIED
    assert "reconcile" in result.note


def test_compatible_units_are_converted_before_comparing():
    analyte = Analyte(
        name="Protein", value=7000.0, unit="mg/dL", ref_low=60.0, ref_high=80.0
    )
    assert classify(analyte, range_unit="g/L").status is AnalyteStatus.WITHIN


def test_inverted_range_is_a_parse_failure_not_a_double_flag():
    analyte = Analyte(name="X", value=5.0, unit="%", ref_low=10.0, ref_high=2.0)
    result = classify(analyte)
    assert result.status is AnalyteStatus.UNVERIFIED
    assert "inverted" in result.note


# ------------------------------------------------------------ severity


def test_critical_value_forces_high():
    report = parse_report(REPORT)
    assert any(a.status is AnalyteStatus.CRITICAL for a in report.analytes)
    assert report.severity_floor is Severity.HIGH


def test_any_abnormal_reaches_the_escalation_threshold():
    analytes = [classify(Analyte("Glu", 104.0, "mg/dL", 70.0, 100.0))]
    assert severity_floor(analytes) is Severity.MEDIUM


def test_all_normal_does_not_escalate():
    analytes = [classify(Analyte("Hb", 14.0, "g/dL", 13.0, 17.0))]
    assert severity_floor(analytes) is Severity.INFORMATIONAL


def test_unverified_alone_does_not_escalate_or_reassure():
    """UNVERIFIED is neither abnormal nor normal."""
    analytes = [classify(Analyte("Ferritin", 42.0, "ng/mL"))]
    assert severity_floor(analytes) is Severity.INFORMATIONAL
    assert analytes[0].status is AnalyteStatus.UNVERIFIED


# ------------------------------------------------------------ contracts


def test_partial_reading_is_announced():
    report = parse_report(REPORT + "GARBAGE HEADER LINE\n")
    notice = partial_reading_notice(report)
    assert notice and "not checked" in notice


def test_complete_reading_has_no_notice():
    assert partial_reading_notice(parse_report(REPORT)) is None


def test_in_range_caveat_never_says_healthy():
    """ "Within range" is a population statistic, not a verdict."""
    lowered = IN_RANGE_CAVEAT.lower()
    for forbidden in (
        "you are healthy",
        "you're healthy",
        "all clear",
        "nothing wrong",
    ):
        assert forbidden not in lowered
    assert "do not rule out" in lowered


def test_single_space_separated_rows_parse():
    """Pasted text collapses column alignment to single spaces.

    Requiring two spaces made a pasted report parse to nothing -- and a
    report that parses to nothing is worse than one that fails loudly,
    because the model then reads the raw text and reports values with no
    flags computed at all.
    """
    report = parse_report(
        "Haemoglobin 13.2 g/dL 13.0 - 17.0\n"
        "Glucose 104 mg/dL 70 - 100\n"
        "Potassium 6.9 mmol/L 3.5 - 5.1"
    )
    assert len(report.analytes) == 3
    assert not report.unparsed
    # Potassium 6.9 against 3.5-5.1 lands far enough outside to be
    # CRITICAL, which forces HIGH. That is the right answer clinically:
    # a potassium of 6.9 is not a "discuss it sometime" result.
    assert report.severity_floor is Severity.HIGH


def test_multi_word_analyte_names_survive_backtracking():
    row = parse_row("Vitamin D 32 ng/mL 30 - 100")
    assert isinstance(row, Analyte)
    assert row.name == "Vitamin D"
    assert row.value == 32

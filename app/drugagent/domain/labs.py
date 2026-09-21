"""
Lab report parsing and flagging.

Turns the text of a report into typed values, compares each against its
reference range, and says plainly what it could not read.

Three rules run through everything here:

    Arithmetic, not judgement. The model never decides whether a value
    is high. It explains a flag that was computed (D10).

    The report's own ranges. Reference ranges vary by laboratory, assay,
    age and sex. The lab that ran the test prints its ranges next to the
    results; a hardcoded table would be wrong for every lab whose assay
    differs, and wrong in a way no test catches because the fixture
    would use the table's own numbers (D9).

    Nothing is dropped. A row the parser could not read is reported as
    unread. A partial reading presented as complete is a user believing
    their unmentioned result was normal.

No network, no model.
"""

from __future__ import annotations

import re

from domain.models import (
    Analyte,
    AnalyteStatus,
    LabReport,
    RangeSource,
    Severity,
    UnparsedRow,
)
from domain.units import compatible, convert, normalise

# How far outside the reference range counts as critical rather than
# merely abnormal, as a multiple of the range width.
#
# This is a heuristic standing in for analyte-specific critical values,
# which are the real clinical construct (a potassium of 6.5 is an
# emergency at a magnitude that would be unremarkable for a white cell
# count). It exists so that a grossly abnormal value cannot be reported
# in the same register as a marginal one.
#
# CLINICAL REVIEW REQUIRED: a per-analyte critical table should replace
# this before real users. Until then it errs toward escalating.
CRITICAL_RANGE_MULTIPLE = 1.0

# Matches: name, value, optional unit, optional reference range.
#   Haemoglobin      13.2   g/dL     13.0 - 17.0
#   Glucose (F)      104    mg/dL    70-100
_ROW = re.compile(
    r"""^\s*
    (?P<name>[A-Za-z][A-Za-z0-9 ()/,.'\-]*?)
    \s{2,}|\t
    """,
    re.VERBOSE,
)

_NUMBER = r"[-+]?\d+(?:[.,]\d+)?"
_RANGE = re.compile(
    rf"(?P<low>{_NUMBER})\s*(?:-|–|—|to)\s*(?P<high>{_NUMBER})", re.IGNORECASE
)
# A SINGLE space is enough of a separator. Requiring two matched the
# column alignment of a printed report and rejected the same data pasted
# from a browser, where the spacing collapses -- and a report that parses
# to nothing is worse than one that fails loudly, because the model then
# reads the raw text itself and reports values with no flags computed.
#
# The name is non-greedy, so backtracking handles multi-word analytes:
# "Vitamin D 32" tries name="Vitamin", fails to read "D" as a number,
# and retries with name="Vitamin D".
_VALUE_LINE = re.compile(
    rf"""^\s*
    (?P<name>[A-Za-z][A-Za-z0-9\ ()/,.'\-]*?)
    [\s:]+
    (?P<value>{_NUMBER})
    (?![\w.])
    \s*
    (?P<rest>.*)$
    """,
    re.VERBOSE,
)


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_row(line: str) -> Analyte | UnparsedRow:
    """Parse one line of a report.

    Returns an UnparsedRow rather than None for anything it cannot read,
    so the caller has no way to discard a line by accident.
    """
    stripped = line.strip()
    if not stripped:
        return UnparsedRow(raw=line, reason="blank")

    match = _VALUE_LINE.match(stripped)
    if not match:
        return UnparsedRow(raw=stripped, reason="no name/value pair found")

    value = _number(match.group("value"))
    if value is None:
        return UnparsedRow(raw=stripped, reason="value is not a number")

    rest = match.group("rest")
    range_match = _RANGE.search(rest)

    unit_text = rest
    if range_match:
        unit_text = rest[: range_match.start()]
    unit = (unit_text or "").strip() or None

    low = high = None
    source = RangeSource.NONE
    if range_match:
        low = _number(range_match.group("low"))
        high = _number(range_match.group("high"))
        if low is not None and high is not None:
            source = RangeSource.REPORT

    return Analyte(
        name=match.group("name").strip(),
        value=value,
        unit=unit,
        ref_low=low,
        ref_high=high,
        ref_source=source,
    )


def classify(analyte: Analyte, range_unit: str | None = None) -> Analyte:
    """Compare a value to its range. Pure arithmetic (D10).

    `range_unit` covers the case where the printed range carries its own
    unit. When it cannot be reconciled with the value's unit, the result
    is UNVERIFIED -- never a comparison performed anyway.
    """
    if analyte.value is None:
        return _with(analyte, AnalyteStatus.UNVERIFIED, "no numeric value")

    if analyte.ref_low is None or analyte.ref_high is None:
        return _with(analyte, AnalyteStatus.UNVERIFIED, "no reference range available")

    value = analyte.value
    if range_unit and range_unit != analyte.unit:
        value_unit = normalise(analyte.unit)
        target = normalise(range_unit)
        if not compatible(value_unit, target):
            # The mass/molar boundary lands here. Converting anyway would
            # need a molar mass this layer does not have, and a wrong
            # conversion flags a real value with full confidence.
            return _with(
                analyte,
                AnalyteStatus.UNVERIFIED,
                f"cannot reconcile {analyte.unit!r} with range unit {range_unit!r}",
            )
        converted = convert(value, value_unit, target)
        if converted is None:
            return _with(analyte, AnalyteStatus.UNVERIFIED, "unit conversion failed")
        value = converted

    low, high = analyte.ref_low, analyte.ref_high
    if low > high:
        # A range that runs backwards is a parsing failure, not a value
        # that is simultaneously too high and too low.
        return _with(analyte, AnalyteStatus.UNVERIFIED, "reference range is inverted")

    width = high - low
    margin = width * CRITICAL_RANGE_MULTIPLE

    if value < low:
        status = AnalyteStatus.CRITICAL if value < low - margin else AnalyteStatus.BELOW
    elif value > high:
        status = (
            AnalyteStatus.CRITICAL if value > high + margin else AnalyteStatus.ABOVE
        )
    else:
        status = AnalyteStatus.WITHIN

    return _with(analyte, status, None)


def _with(analyte: Analyte, status: AnalyteStatus, note: str | None) -> Analyte:
    return Analyte(
        name=analyte.name,
        value=analyte.value,
        unit=analyte.unit,
        ref_low=analyte.ref_low,
        ref_high=analyte.ref_high,
        ref_source=analyte.ref_source,
        status=status,
        loinc=analyte.loinc,
        note=note,
    )


def parse_report(text: str) -> LabReport:
    """Parse extracted report text into analytes and unread rows.

    Every input line ends up in exactly one of the two lists. That
    property is what makes "the answer says what it could not read"
    enforceable rather than aspirational.
    """
    analytes: list[Analyte] = []
    unparsed: list[UnparsedRow] = []

    for line in text.splitlines():
        if not line.strip():
            continue
        parsed = parse_row(line)
        if isinstance(parsed, UnparsedRow):
            unparsed.append(parsed)
        else:
            analytes.append(classify(parsed))

    return LabReport(
        analytes=tuple(analytes),
        unparsed=tuple(unparsed),
        severity_floor=severity_floor(analytes),
    )


def severity_floor(analytes: list[Analyte]) -> Severity:
    """The severity a report forces regardless of what the model says.

    A critical value is not a conversation, so it reaches HIGH. Any
    abnormal value reaches MEDIUM: an out-of-range result is exactly the
    case where the person who ordered the test should be the one
    interpreting it.
    """
    statuses = {a.status for a in analytes}
    if AnalyteStatus.CRITICAL in statuses:
        return Severity.HIGH
    if statuses & {AnalyteStatus.BELOW, AnalyteStatus.ABOVE}:
        return Severity.MEDIUM
    return Severity.INFORMATIONAL


# The statement appended to every lab response, in code rather than in
# the prompt. "Within range" describes a population statistic, not a
# person's health, and the gap between those two readings is where a
# reassured user stops investigating a real symptom.
IN_RANGE_CAVEAT = (
    "Reference ranges describe what is typical for a population, not what is "
    "right for you. Results inside the range do not rule out illness, and "
    "results outside it are often explained by something harmless. The "
    "clinician who ordered these tests is the one who can interpret them."
)


def partial_reading_notice(report: LabReport) -> str | None:
    """Told to the user whenever rows were not read. None when complete."""
    if not report.is_partial:
        return None
    return (
        f"{len(report.unparsed)} line(s) of this report could not be read, and "
        f"{len(report.analytes)} were. Anything not listed below was not "
        "checked -- do not read its absence as a normal result."
    )

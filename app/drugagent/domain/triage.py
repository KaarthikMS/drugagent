"""
Symptom triage: what a symptom description means, not what it says.

MedlinePlus explains what a headache is. It does not say that "sudden,
severe, worst of my life" is a subarachnoid-haemorrhage presentation
needing an emergency department now. That judgement is encoded here, as
explicit rules, for two reasons (D12):

    Reviewable   a clinician can read a rule and say whether it is
                 right. Nobody can read a prompt and say what it will do.
    Testable     every rule is a unit test with no model call.

The division of labour with the model is deliberate and consistent with
the rest of the system: the MODEL parses free text into
(symptom, duration, modifiers) -- that is language understanding, which
is what it is for. The RULESET decides what that tuple means.

The tripwire in severity.py and this module overlap on purpose. The
tripwire is a blunt scan of raw text that runs before anything else;
this runs on structured input and can express duration and combination.
Both feed the same maximum (D5), so neither can lower the other.

CLINICAL REVIEW REQUIRED before real users.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from domain.models import Severity


@dataclass(frozen=True)
class SymptomReport:
    """A symptom description, after the model has parsed it.

    Everything is optional except the symptom itself, because users
    volunteer what they volunteer. A missing duration must never be
    treated as a short one.
    """

    symptom: str
    duration_hours: float | None = None
    modifiers: tuple[str, ...] = ()
    age_years: int | None = None
    pregnant: bool | None = None


@dataclass(frozen=True)
class TriageRule:
    """One rule. All stated conditions must hold for it to fire."""

    name: str
    symptoms: tuple[str, ...]
    floor: Severity
    reason: str
    modifiers_any: tuple[str, ...] = ()
    longer_than_hours: float | None = None
    shorter_than_hours: float | None = None
    requires_duration: bool = False

    def matches(self, report: SymptomReport) -> bool:
        symptom = report.symptom.lower()
        if not any(s in symptom for s in self.symptoms):
            return False

        if self.modifiers_any:
            present = {m.lower() for m in report.modifiers}
            haystack = " ".join(present) + " " + symptom
            if not any(m in haystack for m in self.modifiers_any):
                return False

        if self.requires_duration and report.duration_hours is None:
            return False

        # An unknown duration never satisfies a duration condition. A
        # missing value is not a short one, and the alternative --
        # treating None as zero -- would silently downgrade "I have had
        # this for a week" reported without a number.
        hours = report.duration_hours
        if self.longer_than_hours is not None and (
            hours is None or hours <= self.longer_than_hours
        ):
            return False
        return self.shorter_than_hours is None or (
            hours is not None and hours < self.shorter_than_hours
        )


# --------------------------------------------------------------------
# The ruleset
#
# Ordered by severity, and evaluated in full -- every matching rule is
# collected and the maximum floor taken, so a later benign rule cannot
# cancel an earlier serious one.
# --------------------------------------------------------------------

RULES: tuple[TriageRule, ...] = (
    TriageRule(
        name="thunderclap headache",
        symptoms=("headache",),
        modifiers_any=("sudden", "worst", "thunderclap", "explosive"),
        floor=Severity.EMERGENCY,
        reason="sudden severe headache can indicate bleeding around the brain",
    ),
    TriageRule(
        name="headache with neurological signs",
        symptoms=("headache",),
        modifiers_any=(
            "vision",
            "confusion",
            "weakness",
            "numbness",
            "speech",
            "fever with neck stiffness",
            "neck stiffness",
        ),
        floor=Severity.EMERGENCY,
        reason="headache with neurological or meningeal signs",
    ),
    TriageRule(
        name="chest pain",
        symptoms=("chest pain", "chest tightness", "chest pressure"),
        floor=Severity.EMERGENCY,
        reason="chest pain is treated as cardiac until proven otherwise",
    ),
    TriageRule(
        name="breathlessness at rest",
        symptoms=(
            "breathless",
            "short of breath",
            "shortness of breath",
            "difficulty breathing",
        ),
        floor=Severity.EMERGENCY,
        reason="breathlessness at rest",
    ),
    TriageRule(
        name="abdominal pain with rigidity",
        symptoms=("abdominal pain", "stomach pain", "belly pain"),
        modifiers_any=("severe", "rigid", "rebound", "cannot move", "vomiting blood"),
        floor=Severity.EMERGENCY,
        reason="possible acute abdomen",
    ),
    TriageRule(
        name="fever in pregnancy",
        symptoms=("fever",),
        modifiers_any=("pregnant", "pregnancy"),
        floor=Severity.HIGH,
        reason="fever during pregnancy warrants prompt assessment",
    ),
    TriageRule(
        name="prolonged fever",
        symptoms=("fever", "temperature"),
        longer_than_hours=72,
        floor=Severity.HIGH,
        reason="fever lasting more than three days",
    ),
    TriageRule(
        name="persistent vomiting",
        symptoms=("vomiting", "throwing up"),
        longer_than_hours=24,
        floor=Severity.HIGH,
        reason="vomiting beyond a day risks dehydration",
    ),
    TriageRule(
        name="rash with fever",
        symptoms=("rash",),
        modifiers_any=("fever", "spreading", "blistering"),
        floor=Severity.HIGH,
        reason="rash with fever can indicate serious infection",
    ),
    TriageRule(
        name="prolonged headache",
        symptoms=("headache",),
        longer_than_hours=72,
        floor=Severity.MEDIUM,
        reason="headache persisting beyond three days",
    ),
    TriageRule(
        name="persistent cough",
        symptoms=("cough",),
        longer_than_hours=336,  # two weeks
        floor=Severity.MEDIUM,
        reason="cough persisting beyond two weeks",
    ),
)


@dataclass(frozen=True)
class TriageResult:
    """What the ruleset concluded, and which rules said so."""

    floor: Severity
    matched: tuple[str, ...] = ()
    reasons: tuple[str, ...] = field(default_factory=tuple)


def triage(report: SymptomReport) -> TriageResult:
    """Apply every rule and take the maximum floor.

    Every rule is evaluated, not just the first match. A rule that says
    "medium" must never be able to cancel one that said "emergency", and
    the only way to guarantee that is to combine rather than to choose.

    No match returns LOW, not INFORMATIONAL: somebody describing a
    symptom is not asking a reference question, and the baseline for a
    person who feels unwell is not "this is merely information".
    """
    matched = [rule for rule in RULES if rule.matches(report)]
    if not matched:
        return TriageResult(floor=Severity.LOW)

    return TriageResult(
        floor=max((rule.floor for rule in matched), key=lambda s: s.rank),
        matched=tuple(rule.name for rule in matched),
        reasons=tuple(rule.reason for rule in matched),
    )

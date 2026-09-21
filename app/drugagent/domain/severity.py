"""
Severity: deciding when a human clinician must be involved.

Six independent components can raise severity -- the tripwire, the
model's own classification, the triage ruleset, an interaction floor, a
critical lab value, a toxicity floor. They combine by MAXIMUM. Nothing
can lower what something else raised (D5).

That single property is why the system can carry six inputs without any
of them needing to know about the others, and it is why adding a seventh
later requires no re-reasoning.

Nothing in this file touches the network or a model. All of it is
testable with no credentials.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from config import ESCALATION_THRESHOLD
from domain.models import Severity

ESCALATE_AT = Severity(ESCALATION_THRESHOLD)


@dataclass(frozen=True)
class Tripwire:
    """One pattern that forces a severity floor before the model runs."""

    pattern: re.Pattern[str]
    reason: str
    floor: Severity = Severity.EMERGENCY


def _p(*alternatives: str) -> re.Pattern[str]:
    return re.compile("|".join(alternatives), re.IGNORECASE)


# --------------------------------------------------------------------
# The tripwire
#
# Deliberately blunt, and deliberately not clever. It runs BEFORE the
# model and overrides it, because model classification is good and will
# eventually miss one -- and the costs are not symmetric. A false
# escalation costs a user five minutes. A missed cardiac presentation
# costs more than this project.
#
# It also runs before Guardrails, because redaction can remove the very
# words it matches on.
#
# Known and accepted limitation: negation is not handled. "I do NOT have
# chest pain" escalates. Adding negation detection means adding a place
# where the tripwire can be talked out of firing, and a tripwire that can
# be argued with is not a tripwire.
#
# CLINICAL REVIEW REQUIRED before real users. These patterns cover
# presentations that are time-critical and commonly under-recognised; a
# clinician must confirm the list is right -- which is a review of a
# readable ruleset rather than of a prompt.
# --------------------------------------------------------------------

TRIPWIRES: tuple[Tripwire, ...] = (
    Tripwire(
        _p(
            r"\bchest (pain|pressure|tightness|discomfort)\b",
            r"\bcrushing (chest|pain)\b",
        ),
        "possible acute coronary syndrome",
    ),
    Tripwire(
        _p(
            r"\b(can'?t|cannot|unable to|difficulty|trouble) breath",
            r"\bshort(ness)? of breath\b",
            r"\bgasping\b",
            r"\bchoking\b",
        ),
        "respiratory compromise",
    ),
    Tripwire(
        _p(
            r"\bface (is )?droop",
            r"\bslurr(ed|ing) speech\b",
            r"\bweak(ness)? (on )?one side\b",
            r"\bnumb(ness)? (in|on) (my )?(left|right) (arm|leg|side)\b",
            r"\bsudden(ly)? (confus|blind|vision loss)",
        ),
        "possible stroke",
    ),
    Tripwire(
        _p(
            r"\bworst headache\b",
            r"\bthunderclap\b",
            r"\bsudden(ly)?,? (severe|worst) headache\b",
        ),
        "possible subarachnoid haemorrhage",
    ),
    Tripwire(
        _p(
            r"\banaphyla",
            r"\b(throat|tongue|lips?) (is |are )?swell",
            r"\bcan'?t swallow\b",
            r"\bhives all over\b",
        ),
        "possible anaphylaxis",
    ),
    Tripwire(
        _p(
            r"\b(kill|hurt|harm) (myself|my ?self)\b",
            r"\bsuicid",
            r"\bend my life\b",
            r"\bdon'?t want to (live|be alive)\b",
            r"\boverdosed? on purpose\b",
        ),
        "self-harm risk",
    ),
    Tripwire(
        # First person, present or recent tense. D11: an overdose
        # question asked ABOUT someone is information; asked about
        # oneself it is an event in progress. Paracetamol overdose in
        # particular is time-critical and initially asymptomatic, which
        # is exactly when a calm informational answer does harm.
        # The drug's name sits between the count and the unit --
        # "30 paracetamol tablets", not "30 tablets" -- so the number
        # and the noun cannot be required to be adjacent. Found by
        # testing the phrase a real person would type.
        _p(
            r"\bi (just |accidentally )?(took|swallowed|had) (too (much|many)|\d+\s*[\w\s]{0,25}?(tablets?|pills?|capsules?))",
            r"\bi('| ha)?ve (just )?(taken|swallowed) (too (much|many)|\d+\s*[\w\s]{0,25}?(tablets?|pills?|capsules?))",
            r"\bi think i('| ha)?ve overdosed?\b",
            r"\bi overdosed\b",
        ),
        "possible overdose in progress",
    ),
    Tripwire(
        _p(
            r"\b(vomiting|coughing up|passing) blood\b",
            r"\bblood in (my )?(stool|vomit|urine)\b",
            r"\bbleeding (that )?won'?t stop\b",
            r"\bblack,? tarry stool",
        ),
        "active haemorrhage",
    ),
    Tripwire(
        _p(r"\b(seizure|convulsion|fitting)\b", r"\bunconscious\b", r"\bpassed out\b"),
        "neurological emergency",
    ),
)


@dataclass(frozen=True)
class TripwireHit:
    """Why the tripwire fired. Carried so the answer can explain itself."""

    reason: str
    floor: Severity


def check_tripwire(text: str) -> TripwireHit | None:
    """Scan raw user text for an emergency presentation.

    Returns the FIRST match. There is no scoring and no weighing of
    multiple hits: one is already enough to escalate, and ranking them
    would add a place for the decision to go wrong.
    """
    for wire in TRIPWIRES:
        if wire.pattern.search(text):
            return TripwireHit(reason=wire.reason, floor=wire.floor)
    return None


def max_severity(*severities: Severity | None) -> Severity:
    """Combine severities. The maximum wins, always.

    None values are ignored so callers can pass an optional floor
    without branching -- a component that had no opinion must not be
    able to express one by accident.
    """
    present = [s for s in severities if s is not None]
    return max(present, default=Severity.INFORMATIONAL, key=lambda s: s.rank)


def should_escalate(severity: Severity) -> bool:
    """Does this severity require advising a real clinician?"""
    return severity >= ESCALATE_AT


# --------------------------------------------------------------------
# Escalation text
#
# Written by code, not by the model. Prompt-only escalation is
# unmeasurable and untestable: you cannot assert that a sentence was
# persuasive, and you find out it was not from a user, months later.
#
# India's national emergency number. An organisation deploying this
# elsewhere must change it, and keeping it as one constant makes that a
# one-line change rather than a search through prose.
# --------------------------------------------------------------------

EMERGENCY_NUMBER = "112"

_ESCALATION_TEXT: dict[Severity, str] = {
    Severity.MEDIUM: (
        "This is worth discussing with a doctor or pharmacist rather than "
        "acting on information alone."
    ),
    Severity.HIGH: (
        "Please speak to a doctor about this. The information above describes "
        "what is documented; it cannot account for your own history, other "
        "medicines you take, or how you are feeling now."
    ),
    Severity.EMERGENCY: (
        f"This may be a medical emergency. Call {EMERGENCY_NUMBER} or go to the "
        "nearest emergency department now. Do not wait to see whether it "
        "improves, and do not rely on anything else in this message."
    ),
}


def escalation_text(severity: Severity, reason: str | None = None) -> str | None:
    """The block appended to an answer. None below the threshold.

    An EMERGENCY block is placed FIRST in the response, before any
    answer, because a person reading urgent guidance under three
    paragraphs of drug information may not reach it.
    """
    if not should_escalate(severity):
        return None

    text = _ESCALATION_TEXT[severity]
    if reason and severity is Severity.EMERGENCY:
        return f"{text} (Flagged: {reason}.)"
    return text

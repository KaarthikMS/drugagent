"""
The vocabulary of the system.

Every type here is immutable and carries no behaviour that touches the
network, a model, or AWS. If a rule matters clinically, it is expressed
as a field rather than left to the wording of an answer -- a field can
be asserted on in a test, and a sentence cannot.

Three of these types exist specifically to make a dangerous statement
impossible to make by accident:

    InteractionResult.documented    "not documented" is not "safe"
    Analyte.status                  computed, never written by a model
    Citation.jurisdiction           a US label is not an Indian one
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    """How urgently a human clinician should be involved.

    Ordered, and the order is load-bearing: severity is combined by
    taking the maximum across every component that produced one (D5), so
    no part of the system can lower what another part raised.

    str-valued so it survives JSON without a conversion step -- the model
    returns one of these as a typed field, and a round trip through
    serialisation must not be able to corrupt it.
    """

    INFORMATIONAL = "informational"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EMERGENCY = "emergency"

    @property
    def rank(self) -> int:
        return _SEVERITY_ORDER.index(self)

    # All four comparisons are defined, and that is not redundancy.
    # Mixing `str` into an Enum inherits string ordering: defining only
    # __lt__ and __le__ leaves `>` and `>=` falling back to str, where
    # "emergency" > "high" is False because e sorts before h. The result
    # is a severity comparison that silently answers alphabetically --
    # and should_escalate() using `>=` would then refuse to escalate an
    # emergency. functools.total_ordering does not help here: it only
    # fills in operators the class does not already have, and str
    # supplies all of them.
    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank >= other.rank


_SEVERITY_ORDER: tuple[Severity, ...] = (
    Severity.INFORMATIONAL,
    Severity.LOW,
    Severity.MEDIUM,
    Severity.HIGH,
    Severity.EMERGENCY,
)


class AnalyteStatus(str, Enum):
    """Where a lab value sits against its reference range.

    UNVERIFIED is not a failure mode to be tidied away. It is the honest
    answer when a unit cannot be reconciled with the range printed
    beside it, and it must never be silently rendered as WITHIN.
    """

    BELOW = "below"
    WITHIN = "within"
    ABOVE = "above"
    CRITICAL = "critical"
    UNVERIFIED = "unverified"


class RangeSource(str, Enum):
    """Where the reference range came from.

    Reported to the user, because a range read off their own report and
    a range from anywhere else are not equally trustworthy (D9). Only
    the report is a source today -- a curated fallback table is
    deliberately not built, since a table would be wrong for every lab
    whose assay differs and wrong in a way no test catches.
    """

    REPORT = "report"
    NONE = "none"


@dataclass(frozen=True)
class Citation:
    """Something an answer may point at.

    `jurisdiction` exists because every label source in this system is
    American and every user is not (D14). A US label presented as though
    it described the tablet in the user's hand is a citation that does
    not support its claim.
    """

    title: str
    url: str
    jurisdiction: str = "US"
    published: str | None = None


@dataclass(frozen=True)
class DrugRef:
    """A drug the system has agreed on an identity for.

    `requires_confirmation` is set when the name was matched
    approximately. No threshold can distinguish a corrected typo from a
    different drug -- prednisone and prednisolone are closer than metfrmn
    and metformin -- so the user is asked (D16).
    """

    name: str
    rxcui: str | None = None
    query: str | None = None
    approximate: bool = False
    brand_resolved_from: str | None = None
    ingredients: tuple[str, ...] = ()

    @property
    def requires_confirmation(self) -> bool:
        return self.approximate


@dataclass(frozen=True)
class Evidence:
    """A span of retrieved text, and where it came from.

    Both fields are required. The model may only assert clinical content
    that appears in text a tool actually returned, and an assertion whose
    source cannot be named cannot be made (principle 2).
    """

    text: str
    citation: Citation


@dataclass(frozen=True)
class InteractionResult:
    """The outcome of checking two drugs against each other.

    `documented` is the most dangerous field in the codebase. False means
    "neither label mentions the other", which is NOT "these are safe
    together" -- labels are incomplete, and the previous implementation
    returned a clean result for warfarin plus aspirin.

    The distinction is structural: `message` is set by code, not composed
    by a model, so the wording cannot drift.
    """

    drug_a: DrugRef
    drug_b: DrugRef
    documented: bool
    evidence: tuple[Evidence, ...] = ()
    shared_classes: tuple[str, ...] = ()
    one_sided: bool = False
    severity_floor: Severity = Severity.INFORMATIONAL
    message: str = ""


@dataclass(frozen=True)
class Analyte:
    """One measured value from a lab report.

    `status` is computed by arithmetic and never written by a model
    (D10). `ref_source` records which reference the comparison used, and
    `loinc` is absent whenever the name could not be matched to a code
    confidently -- silence about a test is recoverable, a confident
    description of the wrong test is not.
    """

    name: str
    value: float | None
    unit: str | None
    ref_low: float | None = None
    ref_high: float | None = None
    ref_source: RangeSource = RangeSource.NONE
    status: AnalyteStatus = AnalyteStatus.UNVERIFIED
    loinc: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class UnparsedRow:
    """A line the parser could not read.

    Kept rather than dropped. If the extractor produced twelve rows and
    the parser understood nine, the answer says so -- a partial reading
    presented as complete is a user believing their unmentioned result
    was normal.
    """

    raw: str
    reason: str


@dataclass(frozen=True)
class LabReport:
    """A parsed report: what was understood, and what was not."""

    analytes: tuple[Analyte, ...] = ()
    unparsed: tuple[UnparsedRow, ...] = ()
    severity_floor: Severity = Severity.INFORMATIONAL

    @property
    def flagged(self) -> tuple[Analyte, ...]:
        return tuple(
            a
            for a in self.analytes
            if a.status
            in (AnalyteStatus.BELOW, AnalyteStatus.ABOVE, AnalyteStatus.CRITICAL)
        )

    @property
    def is_partial(self) -> bool:
        return bool(self.unparsed)


@dataclass(frozen=True)
class AgentResponse:
    """What the runtime returns, after the severity gate has run.

    `escalation` is appended by code when severity reaches the threshold,
    never by the model. Prompt-only escalation is unmeasurable and
    untestable; a field is both.
    """

    answer: str
    severity: Severity
    citations: tuple[Citation, ...] = ()
    escalation: str | None = None
    caveats: tuple[str, ...] = field(default_factory=tuple)
    requires_confirmation: str | None = None

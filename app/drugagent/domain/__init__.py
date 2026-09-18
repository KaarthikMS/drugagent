"""
Domain: everything that must be guaranteed.

Pure functions and immutable types. No network, no model, no AWS, no
credentials -- so every rule that carries clinical weight is testable
without any of them, and the test suite runs in under a second.

The layers outside this one are adapters. `clients/` fetches text,
`tools/` exposes capabilities to a model, `main.py` handles a request.
None of them decide anything: whether an interaction is documented,
whether a value is out of range, how urgently a clinician is needed --
all of that is decided here, where it can be proven.

    models       the vocabulary; typed, immutable
    severity     tripwire, maximum-wins combination, escalation text
    interactions bidirectional label cross-check
    triage       symptom red-flag ruleset
    labs         analyte parsing, range comparison, partial-read notice
    units        unit normalisation, and the mass/molar refusal
    brands       Indian brand -> generic ingredients
"""

from __future__ import annotations

from domain.models import (
    AgentResponse,
    Analyte,
    AnalyteStatus,
    Citation,
    DrugRef,
    Evidence,
    InteractionResult,
    LabReport,
    RangeSource,
    Severity,
    UnparsedRow,
)

__all__ = [
    "AgentResponse",
    "Analyte",
    "AnalyteStatus",
    "Citation",
    "DrugRef",
    "Evidence",
    "InteractionResult",
    "LabReport",
    "RangeSource",
    "Severity",
    "UnparsedRow",
]

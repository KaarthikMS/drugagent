"""
Unit normalisation for lab values.

Comparing a value to a range requires both to be in the same unit. Doing
that conversion wrongly is worse than not doing it at all, because a
wrong conversion produces a confident flag on a real patient value.

The hard boundary in this file is between two kinds of conversion:

    SCALE      mg/dL -> g/dL is arithmetic. 1 mg = 0.001 g, always,
               for every substance. Safe to do automatically.

    MOLAR      mg/dL -> umol/L depends on the substance's molar mass.
               Creatinine 1.2 mg/dL is 106 umol/L; glucose 1.2 mg/dL is
               something else entirely. The conversion is impossible
               without knowing WHICH analyte, and getting it wrong
               silently rescales a clinical number.

Molar conversion is therefore refused, not guessed. A value whose unit
cannot be reconciled with its range is reported as "could not be
verified" -- which is recoverable. A wrongly converted value is not.
"""

from __future__ import annotations

from dataclasses import dataclass

# Unicode micro sign, Greek mu, and the ASCII "u" people actually type
# all mean the same thing and none of them compare equal.
_MICRO_FORMS = ("µ", "μ")


@dataclass(frozen=True)
class Unit:
    """A parsed unit: a dimension, and a factor to that dimension's base."""

    text: str
    dimension: str
    factor: float


# Factors are relative to each dimension's base unit. Only conversions
# WITHIN a dimension are ever performed.
_UNITS: dict[str, tuple[str, float]] = {
    # Mass concentration, base g/L
    "g/l": ("mass_conc", 1.0),
    "g/dl": ("mass_conc", 10.0),
    "mg/l": ("mass_conc", 0.001),
    "mg/dl": ("mass_conc", 0.01),
    "ug/l": ("mass_conc", 1e-6),
    "ug/dl": ("mass_conc", 1e-5),
    "ng/ml": ("mass_conc", 1e-6),
    "ng/dl": ("mass_conc", 1e-8),
    "pg/ml": ("mass_conc", 1e-9),
    # Substance concentration, base mol/L. Reachable from mass_conc only
    # with a molar mass, which this module does not have.
    "mol/l": ("molar_conc", 1.0),
    "mmol/l": ("molar_conc", 0.001),
    "umol/l": ("molar_conc", 1e-6),
    "nmol/l": ("molar_conc", 1e-9),
    "pmol/l": ("molar_conc", 1e-12),
    "meq/l": ("molar_conc", 0.001),
    # Counts, base cells/L
    "/l": ("count_conc", 1.0),
    "10^9/l": ("count_conc", 1e9),
    "10^12/l": ("count_conc", 1e12),
    "10^3/ul": ("count_conc", 1e9),
    "10^6/ul": ("count_conc", 1e12),
    "cells/ul": ("count_conc", 1e6),
    "/ul": ("count_conc", 1e6),
    # Dimensionless
    "%": ("ratio", 1.0),
    "ratio": ("ratio", 1.0),
    # Enzyme activity
    "u/l": ("activity", 1.0),
    "iu/l": ("activity", 1.0),
    "u/ml": ("activity", 1000.0),
    # Pressure
    "mmhg": ("pressure", 1.0),
}


def normalise(raw: str | None) -> Unit | None:
    """Parse a unit string. None means unrecognised.

    Unrecognised is a legitimate outcome and must stay visible: a lab may
    print a unit this table does not know, and the correct response is to
    decline the comparison rather than to assume a default.
    """
    if not raw:
        return None

    text = raw.strip().lower().replace(" ", "")
    for micro in _MICRO_FORMS:
        text = text.replace(micro, "u")
    text = text.replace("x10", "10").replace("**", "^")

    entry = _UNITS.get(text)
    if entry is None:
        return None
    dimension, factor = entry
    return Unit(text=text, dimension=dimension, factor=factor)


def compatible(a: Unit | None, b: Unit | None) -> bool:
    """Can these two units be compared at all?"""
    return a is not None and b is not None and a.dimension == b.dimension


def convert(value: float, source: Unit, target: Unit) -> float | None:
    """Convert between units of the same dimension. None if impossible.

    The None case is the mass/molar boundary. Returning a number here by
    assuming a molar mass would be the single most dangerous line in the
    codebase: it would rescale a real clinical value and flag it with
    full confidence.
    """
    if source.dimension != target.dimension:
        return None
    return value * source.factor / target.factor

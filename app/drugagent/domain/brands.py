"""
Indian brand names -> generic ingredients.

Every upstream in this system is American. RxNorm normalises US drug
names; openFDA serves US labels. An employee in India types "Dolo 650"
or "Combiflam" and the whole stack returns nothing -- not a wrong answer,
silence, which reads as a broken product on day one (D14).

There is no authoritative Indian source to substitute. CDSCO publishes
approvals as year-wise web pages with no API; NLEM and the Jan Aushadhi
basket are PDFs; third-party compilations have no regulator behind them.
So this map is ours, and three properties make that acceptable:

    Reviewable        a pharmacist can read it. A scraped dataset
                      cannot be reviewed at all.
    Version-controlled  a change is a diff, with a reason.
    Inert             a mapping from a name to an ingredient asserts no
                      clinical content. Being wrong produces "not
                      found", not a wrong answer.

What this file must never become: a source of dosing, indication or
interaction information. It maps names. Everything clinical still comes
from a retrieved label, and the answer still states that the label is a
US one.

CLINICAL REVIEW REQUIRED. Combination products are the risk: Combiflam
is two ingredients, and treating it as one silently halves an
interaction check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Strength and form, which are not part of the name: "Dolo 650",
# "Shelcal 500", "Pan-D 40mg", "Augmentin 625 Duo".
_NOISE = re.compile(
    r"\b(\d+\s*(mg|mcg|g|ml|iu)?|duo|forte|plus|sr|xr|cr|dt|md|tablets?|caps?(ules?)?|syrup|suspension)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BrandEntry:
    """One brand, and the ingredients it actually contains."""

    ingredients: tuple[str, ...]
    note: str | None = None

    @property
    def is_combination(self) -> bool:
        return len(self.ingredients) > 1


# --------------------------------------------------------------------
# The map
#
# Scope: what roughly a hundred employees are likely to have in a
# cupboard, not a national formulary. Starting small and correct beats
# starting large and unreviewed -- every entry here is one a pharmacist
# can check in a minute.
#
# Ingredient names use the US generic spelling, because that is what
# RxNorm and openFDA are keyed on. "Paracetamol" is what the box says in
# India; "acetaminophen" is what the label search needs.
# --------------------------------------------------------------------

BRANDS: dict[str, BrandEntry] = {
    # Analgesics and antipyretics
    "dolo": BrandEntry(("acetaminophen",), "paracetamol; commonly the 650 mg strength"),
    "crocin": BrandEntry(("acetaminophen",), "paracetamol"),
    "calpol": BrandEntry(("acetaminophen",), "paracetamol"),
    "combiflam": BrandEntry(("ibuprofen", "acetaminophen"), "combination product"),
    "brufen": BrandEntry(("ibuprofen",)),
    "saridon": BrandEntry(
        ("acetaminophen", "propyphenazone", "caffeine"), "combination"
    ),
    "disprin": BrandEntry(("aspirin",)),
    "voveran": BrandEntry(("diclofenac",)),
    "zerodol": BrandEntry(("aceclofenac",)),
    # Gastro
    "pan": BrandEntry(("pantoprazole",)),
    "pan-d": BrandEntry(("pantoprazole", "domperidone"), "combination"),
    "pantop": BrandEntry(("pantoprazole",)),
    "omez": BrandEntry(("omeprazole",)),
    "rantac": BrandEntry(("ranitidine",), "withdrawn in many markets; verify"),
    "digene": BrandEntry(("aluminum hydroxide", "magnesium hydroxide"), "antacid"),
    "eno": BrandEntry(("sodium bicarbonate",)),
    "ondem": BrandEntry(("ondansetron",)),
    # Antibiotics
    "augmentin": BrandEntry(("amoxicillin", "clavulanate"), "combination"),
    "mox": BrandEntry(("amoxicillin",)),
    "azithral": BrandEntry(("azithromycin",)),
    "azee": BrandEntry(("azithromycin",)),
    "taxim": BrandEntry(("cefixime",)),
    "zifi": BrandEntry(("cefixime",)),
    "ciplox": BrandEntry(("ciprofloxacin",)),
    "flagyl": BrandEntry(("metronidazole",)),
    # Allergy and respiratory
    "cetzine": BrandEntry(("cetirizine",)),
    "allegra": BrandEntry(("fexofenadine",)),
    "montair": BrandEntry(("montelukast",)),
    "montair-lc": BrandEntry(("montelukast", "levocetirizine"), "combination"),
    "asthalin": BrandEntry(("albuterol",), "salbutamol"),
    "levolin": BrandEntry(("levalbuterol",)),
    # Cardiovascular and metabolic
    "ecosprin": BrandEntry(("aspirin",), "low-dose aspirin"),
    "telma": BrandEntry(("telmisartan",)),
    "amlong": BrandEntry(("amlodipine",)),
    "atorva": BrandEntry(("atorvastatin",)),
    "rosuvas": BrandEntry(("rosuvastatin",)),
    "glycomet": BrandEntry(("metformin",)),
    "glucophage": BrandEntry(("metformin",)),
    "januvia": BrandEntry(("sitagliptin",)),
    "thyronorm": BrandEntry(("levothyroxine",)),
    "eltroxin": BrandEntry(("levothyroxine",)),
    # Supplements
    "shelcal": BrandEntry(("calcium carbonate", "cholecalciferol"), "combination"),
    "becosules": BrandEntry(("b complex vitamins",), "multivitamin; not a single drug"),
    "limcee": BrandEntry(("ascorbic acid",)),
    "neurobion": BrandEntry(("b complex vitamins",), "multivitamin"),
}


@dataclass(frozen=True)
class BrandMatch:
    """A resolved brand name."""

    brand: str
    ingredients: tuple[str, ...]
    note: str | None = None

    @property
    def is_combination(self) -> bool:
        return len(self.ingredients) > 1


def normalise_brand(text: str) -> str:
    """Strip strength, form and packaging words from a brand name."""
    cleaned = _NOISE.sub(" ", text.lower())
    cleaned = re.sub(r"[^a-z\- ]", " ", cleaned)
    return " ".join(cleaned.split())


def resolve(text: str) -> BrandMatch | None:
    """Look up a brand. None means it is not in the map.

    None is a real answer and must reach the user as one: "I do not
    recognise that brand name; what is the generic name or active
    ingredient?" It must never become a guess, because a guessed
    ingredient is answered about with full confidence from a real label.

    Matching is exact on the cleaned name, never fuzzy. Indian brand
    names are dense with near-collisions -- Zifi and Zifi-CV are
    different products -- and D16 applies with more force here than it
    does to generics.
    """
    cleaned = normalise_brand(text)
    if not cleaned:
        return None

    entry = BRANDS.get(cleaned)
    if entry is None:
        # A trailing qualifier ("montair lc") is tried as a hyphenated
        # key, which is how combination variants are spelled in the map.
        entry = BRANDS.get(cleaned.replace(" ", "-"))
    if entry is None:
        return None

    return BrandMatch(brand=cleaned, ingredients=entry.ingredients, note=entry.note)


UNKNOWN_BRAND_MESSAGE = (
    "I do not recognise that as a brand name I can map to an active "
    "ingredient. Tell me the generic name or the active ingredient printed "
    "on the pack and I can look it up."
)

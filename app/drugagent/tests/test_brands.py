"""
Indian brand resolution (D14).

The map asserts no clinical content -- it maps names to ingredients. The
tests that matter are about what happens when it does NOT know a name,
and about combination products, where treating two ingredients as one
silently halves an interaction check.
"""

from __future__ import annotations

import pytest

from domain.brands import BRANDS, UNKNOWN_BRAND_MESSAGE, normalise_brand, resolve


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("Dolo 650", ("acetaminophen",)),
        ("dolo", ("acetaminophen",)),
        ("Crocin 500mg", ("acetaminophen",)),
        ("Shelcal 500", ("calcium carbonate", "cholecalciferol")),
        ("Augmentin 625 Duo", ("amoxicillin", "clavulanate")),
        ("Glycomet tablets", ("metformin",)),
        ("Ecosprin 75", ("aspirin",)),
    ],
)
def test_strength_and_form_are_not_part_of_the_name(typed, expected):
    match = resolve(typed)
    assert match is not None and match.ingredients == expected


def test_combination_products_keep_both_ingredients():
    """Combiflam is two drugs.

    Collapsing it to one would check an interaction against ibuprofen
    and silently skip paracetamol -- a half-answer presented as whole.
    """
    match = resolve("Combiflam")
    assert match.is_combination
    assert set(match.ingredients) == {"ibuprofen", "acetaminophen"}


def test_unknown_brand_returns_none_and_never_a_guess():
    """The most important behaviour in this module.

    A guessed ingredient is then answered about with full confidence
    from a real label, which is worse than not answering.
    """
    assert resolve("Zyxqwil 200") is None
    assert resolve("") is None


def test_unknown_brand_message_asks_rather_than_assumes():
    assert "generic name" in UNKNOWN_BRAND_MESSAGE
    assert "active ingredient" in UNKNOWN_BRAND_MESSAGE


def test_matching_is_exact_not_fuzzy():
    """Indian brand names are dense with near-collisions.

    Zifi and Zifi-CV are different products. D16 applies here with more
    force than it does to generic names.
    """
    assert resolve("zifi") is not None
    assert resolve("zifii") is None
    assert resolve("zif") is None


def test_generic_names_are_not_in_the_brand_map():
    """A generic goes straight to RxNorm; this map is for brands only."""
    assert resolve("metformin") is None
    assert resolve("paracetamol") is None


def test_normalisation_is_predictable():
    assert normalise_brand("Pan-D 40mg Tablets") == "pan-d"
    assert normalise_brand("DOLO 650") == "dolo"


def test_every_entry_has_at_least_one_ingredient():
    assert all(entry.ingredients for entry in BRANDS.values())


def test_ingredient_spellings_are_us_generic():
    """RxNorm and openFDA are keyed on US spellings.

    The box in India says paracetamol; the label search needs
    acetaminophen. Getting this backwards returns "not found" for the
    single most common medicine in the map.
    """
    all_ingredients = {i for e in BRANDS.values() for i in e.ingredients}
    assert "acetaminophen" in all_ingredients
    assert "paracetamol" not in all_ingredients
    assert "albuterol" in all_ingredients
    assert "salbutamol" not in all_ingredients

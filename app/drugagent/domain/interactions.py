"""
Interaction cross-checking.

Given two drugs and the interaction text from both labels, decide whether
an interaction is documented -- and say so in a way that cannot be
misread as a safety claim.

The single most dangerous failure in this domain is returning
"no interaction documented" and having it read as "these are safe
together". Labels are incomplete. The previous implementation returned
`interaction_found: False` unconditionally, with no API call at all, for
every input: warfarin plus aspirin -- a serious, well documented bleeding
interaction -- came back clean.

Three matching strategies, in order of how often each one is what
actually fires:

    class        the label says "NSAIDs" and never says "ibuprofen"
    ingredient   the label names an active ingredient, not the product
    name         the label names the drug outright

Class matching is first because it is the common case, not the exotic
one. Exact-name matching alone misses most documented interactions.

No network, no model. Pure functions over text.
"""

from __future__ import annotations

import re

from domain.models import (
    Citation,
    DrugRef,
    Evidence,
    InteractionResult,
    Severity,
)

# The contract sentence. Written once, here, in code -- not composed by
# the model, whose phrasing would drift between answers.
# The word "safe" does not appear here, deliberately. An earlier draft
# read "this is not the same as the combination being safe" -- correct
# in meaning, and it still puts the word in front of a worried reader
# who is skimming. Keeping the vocabulary out entirely makes the test a
# hard invariant rather than a judgement about phrasing.
NOT_DOCUMENTED_MESSAGE = (
    "No interaction between these two medicines is documented in either "
    "product label. Labels record interactions that are known, and absence "
    "of documentation is not evidence of absence. Read this as 'the labels "
    "do not say', not as a conclusion about the combination. A pharmacist "
    "can check it properly."
)

ONE_SIDED_MESSAGE = (
    "Only one of the two labels could be retrieved, so this check covered "
    "one direction rather than both."
)

DOCUMENTED_MESSAGE = (
    "An interaction is documented in the product labelling. The text below "
    "is quoted from the label itself."
)

# How much text to keep around a match. A drug_interactions section runs
# to ~6,500 characters and two are fetched per query; passing them whole
# means ~13k characters of context on every interaction question, and
# token cost that grows with the length of somebody else's label.
SPAN_CONTEXT_CHARS = 300


def _terms_for(drug: DrugRef, classes: tuple[str, ...]) -> list[str]:
    """Every string that would mean "this drug" inside a label.

    The drug's own name, its active ingredients, and the names of the
    classes it belongs to. Deduplicated and lowercased; short fragments
    are dropped because a two-letter term matches everything.
    """
    candidates = [drug.name, *drug.ingredients, *classes]
    seen: dict[str, None] = {}
    for candidate in candidates:
        cleaned = (candidate or "").strip().lower()
        if len(cleaned) > 3:
            seen.setdefault(cleaned, None)
    return list(seen)


def find_mentions(text: str, terms: list[str]) -> list[tuple[str, str]]:
    """Locate terms in label text, returning (term, surrounding span).

    Word-boundary matching, because substring matching produces
    nonsense: "ace" appears inside "acetaminophen" and "placebo", and a
    label that mentions ACE inhibitors is making a different claim than
    one that happens to contain those three letters.
    """
    found: list[tuple[str, str]] = []
    for term in terms:
        match = re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE)
        if match:
            start = max(0, match.start() - SPAN_CONTEXT_CHARS)
            end = min(len(text), match.end() + SPAN_CONTEXT_CHARS)
            found.append((term, text[start:end].strip()))
    return found


def cross_check(
    drug_a: DrugRef,
    drug_b: DrugRef,
    text_a: str | None,
    text_b: str | None,
    citation_a: Citation | None = None,
    citation_b: Citation | None = None,
    classes_a: tuple[str, ...] = (),
    classes_b: tuple[str, ...] = (),
    documented_floor: Severity = Severity.HIGH,
) -> InteractionResult:
    """Check both labels against each other.

    BOTH directions, always. Labels are not symmetric: warfarin's label
    may discuss aspirin while aspirin's label never names warfarin.
    Checking one direction halves the detection rate for no saving.

    `text_a is None` means that label could not be retrieved -- which is
    reported as a one-sided check, never quietly treated as "nothing
    found there".
    """
    terms_b = _terms_for(drug_b, classes_b)
    terms_a = _terms_for(drug_a, classes_a)

    evidence: list[Evidence] = []
    matched_terms: set[str] = set()

    # A's label mentioning B, and B's label mentioning A.
    for text, terms, citation in (
        (text_a, terms_b, citation_a),
        (text_b, terms_a, citation_b),
    ):
        if not text:
            continue
        for term, span in find_mentions(text, terms):
            matched_terms.add(term)
            evidence.append(
                Evidence(
                    text=span,
                    citation=citation or Citation(title="Product label", url=""),
                )
            )

    one_sided = (text_a is None) != (text_b is None)
    documented = bool(evidence)

    shared = tuple(
        term
        for term in matched_terms
        if term in {c.lower() for c in classes_a} | {c.lower() for c in classes_b}
    )

    if documented:
        message = DOCUMENTED_MESSAGE
    elif one_sided:
        # Order matters: a one-sided check that found nothing is weaker
        # than a two-sided one, and saying only "not documented" would
        # overstate what was actually checked.
        message = f"{ONE_SIDED_MESSAGE} {NOT_DOCUMENTED_MESSAGE}"
    else:
        message = NOT_DOCUMENTED_MESSAGE

    return InteractionResult(
        drug_a=drug_a,
        drug_b=drug_b,
        documented=documented,
        evidence=tuple(evidence),
        shared_classes=shared,
        one_sided=one_sided,
        # An undocumented result still reaches MEDIUM. The user asked
        # whether two medicines can be combined and the honest answer is
        # "the labels do not say" -- which is a question for a
        # pharmacist, not a reassurance.
        severity_floor=documented_floor if documented else Severity.MEDIUM,
        message=message,
    )

"""Response assembly: what must be true of every answer that ships."""

from __future__ import annotations

from domain.models import Citation, Severity
from domain.response import assemble, render
from domain.severity import TripwireHit


def test_tripwire_overrides_a_low_model_severity():
    """The model said low. The tripwire saw chest pain. Tripwire wins."""
    response = assemble(
        "Paracetamol is a painkiller.",
        tripwire=TripwireHit(
            reason="possible acute coronary syndrome", floor=Severity.EMERGENCY
        ),
        model_severity=Severity.LOW,
    )
    assert response.severity is Severity.EMERGENCY
    assert "emergency" in response.escalation.lower()


def test_tool_floor_raises_above_the_model():
    response = assemble("...", model_severity=Severity.LOW, tool_floors=[Severity.HIGH])
    assert response.severity is Severity.HIGH


def test_nothing_lowers_a_raised_severity():
    response = assemble(
        "...",
        model_severity=Severity.INFORMATIONAL,
        tool_floors=[Severity.EMERGENCY, Severity.LOW, Severity.INFORMATIONAL],
    )
    assert response.severity is Severity.EMERGENCY


def test_below_threshold_gets_no_escalation():
    response = assemble(
        "Metformin treats type 2 diabetes.", model_severity=Severity.INFORMATIONAL
    )
    assert response.escalation is None


def test_emergency_guidance_is_rendered_first():
    """Urgent guidance under three paragraphs may never be read."""
    text = render(
        assemble(
            "Here is some information about paracetamol.",
            tripwire=TripwireHit(
                reason="possible overdose in progress", floor=Severity.EMERGENCY
            ),
        )
    )
    assert text.index("emergency") < text.index("Here is some information")


def test_non_emergency_escalation_follows_the_answer():
    text = render(assemble("The answer.", model_severity=Severity.MEDIUM))
    assert text.index("The answer.") < text.index("worth discussing")


def test_caveats_and_sources_survive_rendering():
    text = render(
        assemble(
            "The answer.",
            citations=[Citation(title="Label", url="https://example/x")],
            caveats=["This is the US product label."],
        )
    )
    assert "US product label" in text
    assert "https://example/x" in text


def test_citation_without_url_is_not_rendered_as_a_source():
    """A source the user cannot open is not a source."""
    text = render(
        assemble("The answer.", citations=[Citation(title="Nowhere", url="")])
    )
    assert "Sources" not in text


def test_model_scaffolding_is_stripped():
    """<thinking> is unreviewed text that reads as authoritative."""
    response = assemble(
        "<thinking>I should look this up.</thinking><response>Metformin treats diabetes.</response>"
    )
    assert response.answer == "Metformin treats diabetes."
    assert "thinking" not in response.answer


def test_stripping_is_case_insensitive_and_multiline():
    response = assemble("<Thinking>\nline one\nline two\n</Thinking>\nThe answer.")
    assert response.answer == "The answer."

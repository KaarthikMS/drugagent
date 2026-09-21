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
            tools_used=["toxicity_lookup"],
        )
    )
    assert text.index("emergency") < text.index("Here is some information")


def test_non_emergency_escalation_follows_the_answer():
    text = render(
        assemble("The answer.", model_severity=Severity.MEDIUM, tools_used=["x"])
    )
    assert text.index("The answer.") < text.index("worth discussing")


def test_caveats_and_sources_survive_rendering():
    text = render(
        assemble(
            "The answer.",
            citations=[Citation(title="Label", url="https://example/x")],
            caveats=["This is the US product label."],
            tools_used=["drug_label_lookup"],
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
        "<thinking>I should look this up.</thinking>"
        "<response>Metformin treats diabetes.</response>",
        tools_used=["drug_label_lookup"],
    )
    assert response.answer == "Metformin treats diabetes."
    assert "thinking" not in response.answer


def test_stripping_is_case_insensitive_and_multiline():
    response = assemble(
        "<Thinking>\nline one\nline two\n</Thinking>\nThe answer.",
        tools_used=["x"],
    )
    assert response.answer == "The answer."


# ----------------------------------------------------- scope enforcement


def test_answer_with_no_tool_call_is_replaced():
    """The model answered from memory. That is never in scope.

    Before this check the assistant explained the Strands tools API and
    debugged a Python function -- both fluently, both with no tool call,
    both entirely outside what this system is for.
    """
    response = assemble("Here is the corrected Python function: def square(n)...")
    assert "only help with health questions" in response.answer
    assert "def square" not in response.answer


def test_a_grounded_answer_survives():
    response = assemble(
        "Metformin treats type 2 diabetes.", tools_used=["drug_label_lookup"]
    )
    assert response.answer == "Metformin treats type 2 diabetes."


def test_a_confirmation_question_survives_without_tools():
    """ "Did you mean metformin?" is a legitimate reply with nothing looked up."""
    response = assemble(
        "Did you mean metformin?", confirmation="Did you mean metformin?"
    )
    assert response.answer == "Did you mean metformin?"


def test_escalation_survives_an_off_scope_answer():
    """If the tripwire fired, urgent guidance stands regardless.

    The model failing to call a tool must not be able to suppress the
    emergency block.
    """
    response = assemble(
        "Let me tell you about Python decorators.",
        tripwire=TripwireHit(reason="possible stroke", floor=Severity.EMERGENCY),
    )
    assert response.severity is Severity.EMERGENCY
    assert "emergency" in response.escalation.lower()
    assert "only help with health questions" in response.answer


def test_citations_are_dropped_from_a_refusal():
    """A refusal citing sources would be claiming grounding it does not have."""
    response = assemble(
        "Some ungrounded answer.",
        citations=[Citation(title="Label", url="https://example/x")],
        caveats=["Some caveat."],
    )
    assert response.citations == ()
    assert response.caveats == ()

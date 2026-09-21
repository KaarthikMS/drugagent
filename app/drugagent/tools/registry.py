"""
Tool construction.

Tools need clients, and clients own connection pools that must be
created once per process. Rather than reach for module-level globals,
the tools are built as closures over one `ToolContext` -- so a test can
hand them fakes, and nothing in this package reads hidden state.

Every tool also records the severity floors and caveats it produced, on
the context, where the response assembler collects them. A floor that a
tool merely mentions in its text would be a floor the gate cannot see.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from clients import Clients
from domain.models import Citation, Severity


@dataclass
class ToolContext:
    """Per-request state shared by the tools.

    Not thread-safe and not meant to be: one context per request, created
    and discarded by the entrypoint.
    """

    clients: Clients
    severity_floors: list[Severity] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    confirmations: list[str] = field(default_factory=list)

    def floor(self, severity: Severity) -> None:
        self.severity_floors.append(severity)

    def cite(self, citation: Citation | None) -> None:
        if citation and citation.url and citation not in self.citations:
            self.citations.append(citation)

    def caveat(self, text: str) -> None:
        if text not in self.caveats:
            self.caveats.append(text)

    def confirm(self, question: str) -> None:
        if question not in self.confirmations:
            self.confirmations.append(question)


def build_tools(context: ToolContext) -> list:
    """Every tool, bound to one request's context."""
    from tools.compound import make_compound_lookup
    from tools.condition import make_condition_lookup
    from tools.interaction import make_interaction_check
    from tools.lab import make_lab_interpret
    from tools.label import make_drug_label_lookup
    from tools.normalize import make_drug_normalize
    from tools.symptom import make_symptom_triage
    from tools.toxicity import make_toxicity_lookup

    return [
        make_drug_normalize(context),
        make_drug_label_lookup(context),
        make_interaction_check(context),
        make_compound_lookup(context),
        make_toxicity_lookup(context),
        make_condition_lookup(context),
        make_symptom_triage(context),
        make_lab_interpret(context),
    ]


async def resolve_generic(ctx, name: str) -> str:
    """Best available US generic name for a drug.

    The tools are told to call drug_normalize first, and the model
    mostly does. When it does not, an Indian or non-US name reaches
    openFDA directly and finds nothing -- "paracetamol" is not a US
    generic name, so a toxicity question about the most common medicine
    in the country returned empty.

    A prompt instruction is not a guarantee (the same reason escalation
    is not a prompt instruction). This makes the tool correct whether or
    not the model followed directions.
    """
    from domain import brands

    match = brands.resolve(name)
    if match:
        return match.ingredients[0]

    ref = await ctx.clients.rxnorm.find_rxcui(name)
    if ref is None:
        return name

    # find_rxcui echoes back the name that was typed -- it resolves an
    # id, not a spelling. "paracetamol" resolves to rxcui 161, whose
    # canonical name is "acetaminophen", and only the canonical name
    # matches an openFDA label. Without this hop, a toxicity question
    # about the most widely used medicine in India found nothing.
    canonical = await ctx.clients.rxnorm.get_name(ref.rxcui)
    return canonical or name

"""Lab result interpretation. Flags are arithmetic; the model explains them."""

from __future__ import annotations

import asyncio

from strands import tool

from domain.labs import IN_RANGE_CAVEAT, parse_report, partial_reading_notice
from domain.models import Analyte, Citation
from tools.registry import ToolContext


def make_lab_interpret(ctx: ToolContext):
    @tool
    async def lab_interpret(report_text: str) -> dict:
        """Read lab results and flag values outside their reference range.

        Use when the user pastes lab or blood test results. Expects one
        result per line, ideally with the reference range the lab
        printed:

            Haemoglobin    13.2   g/dL    13.0 - 17.0
            Glucose (F)    104    mg/dL   70 - 100

        THE FLAGS ARE COMPUTED, NOT YOURS TO MAKE. Never decide whether a
        value is high or low yourself, never recompute one, and never
        comment on a value this tool marked "unverified" as though it
        were normal. Explain what the tool found, in plain language.

        Returns a dict with:
            analytes:  each value with a computed status --
                       within | below | above | critical | unverified
            unparsed:  lines that could NOT be read. You must tell the
                       user these were not checked
            partial_notice: exact wording to use when lines were missed
            caveat:    YOU MUST INCLUDE THIS in every lab answer
            urgency:   severity floor from the values themselves
        """
        ctx.used("lab_interpret")
        report = parse_report(report_text)
        ctx.floor(report.severity_floor)
        ctx.caveat(IN_RANGE_CAVEAT)

        descriptions = await _describe(ctx, report.analytes)

        notice = partial_reading_notice(report)
        if notice:
            ctx.caveat(notice)

        return {
            "analytes": [
                {
                    "name": a.name,
                    "value": a.value,
                    "unit": a.unit,
                    "range": (
                        f"{a.ref_low} - {a.ref_high}" if a.ref_low is not None else None
                    ),
                    "range_source": a.ref_source.value,
                    "status": a.status.value,
                    "note": a.note,
                    "about_this_test": descriptions.get(a.name),
                }
                for a in report.analytes
            ],
            "unparsed": [u.raw for u in report.unparsed],
            "partial_notice": notice,
            "caveat": IN_RANGE_CAVEAT,
            "urgency": report.severity_floor.value,
        }

    return lab_interpret


async def _describe(ctx: ToolContext, analytes: tuple[Analyte, ...]) -> dict[str, str]:
    """Plain-language description of each test, where one can be trusted.

    Two hops: the analyte name a report prints is matched to a LOINC
    code, and the code is looked up for consumer-language text.

    A WEAK match yields nothing at all. "Hemoglobin" alone spans 508
    LOINC items whose top-ranked results are carboxyhaemoglobin
    variants, not the haemoglobin on a blood count -- so taking the best
    guess would attach the wrong test's description to a real patient
    value. Silence about a test is recoverable; a confident description
    of a different test is not.
    """

    async def one(analyte: Analyte) -> tuple[str, str | None]:
        match = await ctx.clients.clinicaltables.loinc_for(analyte.name)
        if match is None or not match.confident:
            return analyte.name, None
        info = await ctx.clients.medlineplus.lookup_loinc(match.code)
        if info is None:
            return analyte.name, None
        ctx.cite(
            Citation(
                title=f"{info.title} — MedlinePlus",
                url=info.url,
                jurisdiction="US (MedlinePlus)",
            )
        )
        return analyte.name, info.title

    pairs = await asyncio.gather(*(one(a) for a in analytes))
    return {name: text for name, text in pairs if text}

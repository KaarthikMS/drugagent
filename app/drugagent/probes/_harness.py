"""
Shared probe scaffolding.

A probe is not a test. A test pins behaviour we already understand; a
probe establishes what the behaviour actually is, so a client is written
against observed reality rather than against documentation and hope.

Two rules hold for every probe in this package:

1. Every check carries a CONTROL that would fail if the upstream were
   ignoring our query. Without one, a green result proves nothing --
   openFDA returned the same 76 hits whether the filter matched or not,
   and only a nonsense term revealed whether the filter ran at all.

2. Checks return results instead of asserting. One `assert` failing
   hides every check after it, and a probe run should report the whole
   state of an upstream in a single pass.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from utils.base import HttpClient, UpstreamError


@dataclass
class Check:
    """One probe result. `expectation` is what makes it evidence."""

    name: str
    expectation: str
    passed: bool
    observed: str


ProbeFn = Callable[[HttpClient], Awaitable[Check]]


def run(title: str, source: str, probes: list[ProbeFn]) -> int:
    """Run every probe against one upstream and print a report.

    Returns a process exit code, so a failing probe fails CI rather than
    scrolling past in the output.
    """

    async def _main() -> list[Check] | None:
        client = HttpClient(source=source)
        try:
            # Sequential on purpose. Probes are diagnostic, and a polite
            # request rate against a public service costs us nothing
            # here. Concurrency belongs in the request path (D6), where
            # latency is a user-facing cost -- not in a hand-run script.
            return [await probe(client) for probe in probes]
        except UpstreamError as exc:
            print(f"PROBE ABORTED -- {exc}")
            return None
        finally:
            await client.aclose()

    checks = asyncio.run(_main())
    if checks is None:
        return 2

    width = max(len(c.name) for c in checks)
    print(f"\n{title}\n" + "=" * 78)
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"[{status}] {check.name:<{width}}  {check.expectation}")
        print(f"       {'':<{width}}  observed: {check.observed}")
    print("=" * 78)

    failed = [c for c in checks if not c.passed]
    print(f"{len(checks) - len(failed)}/{len(checks)} passed\n")
    return 1 if failed else 0


def clip(text: str, limit: int = 90) -> str:
    """Keep observed values readable. Label sections run to thousands of chars."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "..."

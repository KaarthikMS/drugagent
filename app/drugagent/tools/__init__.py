"""
Strands tools: what the model is allowed to do.

Each tool is a thin adapter. It calls a client for text and a domain
function for any decision, then returns a typed result. No tool decides
anything itself -- that is what makes the guarantees testable.

Tool DOCSTRINGS ARE THE ROUTING LOGIC. The model reads them to choose
what to call, so they are written as an API contract for the model, not
as notes for a human. A vague docstring is a routing bug.
"""

from __future__ import annotations

from tools.registry import ToolContext, build_tools

__all__ = ["ToolContext", "build_tools"]

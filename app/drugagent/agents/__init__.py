"""
Agent assembly and the request pipeline.

`agent.py` builds the Strands agent; `pipeline.py` owns the sequence a
request passes through -- tripwire, agent, severity gate.
"""

from agents.agent import build_agent
from agents.pipeline import handle

__all__ = ["build_agent", "handle"]

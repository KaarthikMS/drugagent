"""
Local demo server.

Not the deployment path -- that is AgentCore Runtime, via main.py. This
exists so the same pipeline can be driven from a browser during
development and demonstration, without deploying to show someone what it
does.

Auth is deliberately absent. Before this is exposed to anyone, Cognito
and API Gateway go in front of it (step 7). It binds to localhost.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from clients import Clients
from domain.response import render
from pipeline import handle

WEB = Path(__file__).parent / "web"
_clients: Clients | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _clients
    _clients = Clients()
    yield
    await _clients.aclose()


app = FastAPI(title="Health Assistant", lifespan=lifespan)


class Ask(BaseModel):
    prompt: str


@app.post("/api/ask")
async def ask(body: Ask) -> dict:
    """Answer one question.

    Returns the response as FIELDS, not only as rendered text, so the
    page can style the escalation block distinctly. An escalation
    rendered as ordinary prose is an escalation people skim past.
    """
    response = await handle(body.prompt, _clients)
    return {
        "answer": response.answer,
        "severity": response.severity.value,
        "escalation": response.escalation,
        "caveats": list(response.caveats),
        "citations": [
            {"title": c.title, "url": c.url, "jurisdiction": c.jurisdiction}
            for c in response.citations
        ],
        "requires_confirmation": response.requires_confirmation,
        "rendered": render(response),
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")

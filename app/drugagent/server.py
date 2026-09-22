"""
Dashboard server.

This does NOT run the agent. It serves the page and forwards each
question to the deployed AgentCore runtime, so what a user sees in the
browser is the same code path an employee would hit — same model, same
guardrail, same IAM role, same logs.

Running the pipeline in-process instead would test a different system.
That difference already cost us once: locally the agent ran with no
guardrail attached, so a missing `bedrock:ApplyGuardrail` permission
stayed invisible until the deployed runtime was invoked for the first
time.

Auth is deliberately absent HERE. The runtime itself is IAM-protected —
invoking it needs credentials in the account — but this page is not.
Cognito and API Gateway go in front before an employee uses it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

WEB = Path(__file__).resolve().parents[2] / "frontend"
STATE = (
    Path(__file__).resolve().parents[2] / "agentcore" / ".cli" / "deployed-state.json"
)

REGION = os.getenv("AWS_REGION", "ap-south-1")


def _runtime_arn() -> str:
    """The deployed runtime to call.

    Read from the CLI's deployed state rather than hardcoded, so the ARN
    cannot drift from what was actually deployed. An override exists for
    pointing the dashboard at a different target.
    """
    override = os.getenv("AGENT_RUNTIME_ARN")
    if override:
        return override

    state = json.loads(STATE.read_text())
    return state["targets"]["default"]["resources"]["runtimes"]["drugagent"][
        "runtimeArn"
    ]


app = FastAPI(title="Health Assistant")

# Explicit timeouts. Without them botocore waits 60s to connect and 60s
# to read, and a hung runtime holds a browser connection for two minutes
# with no way for the page to recover.
_client = boto3.client(
    "bedrock-agentcore",
    region_name=REGION,
    config=Config(
        connect_timeout=5,
        read_timeout=120,
        retries={"max_attempts": 2, "mode": "standard"},
    ),
)

# Session ids this server issued: the "dash-" prefix plus a uuid4 hex.
# Anything else is rejected rather than forwarded.
#
# A session id selects a conversation inside the runtime. Accepting an
# arbitrary caller-supplied string means accepting a request to join a
# conversation, which becomes reading someone else's history the moment
# AgentCore Memory is wired in (step 7). Validating the shape keeps the
# id unguessable; only Cognito makes it OWNED -- see the auth plan.
_SESSION_ID = re.compile(r"^dash-[0-9a-f]{32}$")


class Ask(BaseModel):
    # Bounded at the edge as well as in domain/. The domain check is the
    # guarantee; this one stops a 10 MB body being parsed at all.
    prompt: str = Field(max_length=8000)
    session_id: str | None = Field(default=None, max_length=64)


@app.post("/api/ask")
async def ask(body: Ask) -> dict:
    """Forward one question to the deployed runtime and return its answer."""
    # AgentCore requires a session id of at least 33 characters. A uuid4
    # hex string is 32, so a prefix is added rather than trimming the
    # entropy.
    session_id = body.session_id or ""
    if not _SESSION_ID.match(session_id):
        session_id = f"dash-{uuid.uuid4().hex}"

    try:
        result = _client.invoke_agent_runtime(
            agentRuntimeArn=_runtime_arn(),
            runtimeSessionId=session_id,
            payload=json.dumps({"prompt": body.prompt}).encode(),
        )
    except ClientError as exc:
        # The error CODE reaches the browser; the message does not. A
        # botocore message carries the runtime ARN, the account id and
        # the role name, and none of that belongs in a page that will
        # eventually be served to a hundred employees. The full
        # exception goes to the server log, where an operator can read
        # it.
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        logger.exception("runtime invocation failed (%s)", code)
        return {
            "answer": (
                "I could not reach the assistant just now. Please try again "
                "in a moment."
            ),
            "severity": "informational",
            "escalation": None,
            "caveats": [],
            "citations": [],
            "error_code": code,
            "session_id": session_id,
        }

    payload = _read(result)
    payload["session_id"] = session_id
    return payload


def _read(result: dict) -> dict:
    """Decode the runtime's response.

    The entrypoint is an async generator, so AgentCore streams it back as
    SERVER-SENT EVENTS, not as a JSON body:

        data: {"answer": "...", "severity": "medium", ...}

    Parsing the raw bytes as JSON fails on the `data: ` prefix, and the
    fallback path then rendered the entire JSON object to the user as
    though it were prose. Each line is unwrapped first.

    Chunks are joined and parsed once rather than rendered as they
    arrive: a half-rendered escalation block is worse than a slower one.
    """
    body = result.get("response")
    raw = b"".join(body) if body is not None else b""

    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return _error("The agent returned an empty response.")

    payload = _unwrap_sse(text)

    data = _loads(payload)
    # A generator yielding a dict is serialised once by the runtime and
    # again by the SSE frame, so the payload can be a JSON string
    # containing JSON. Unwrap until it stops being a string.
    for _ in range(3):
        if not isinstance(data, str):
            break
        data = _loads(data)

    if isinstance(data, dict) and "answer" in data:
        return data

    # Anything else is text: a runtime deployed before the structured
    # response existed, or an error string. Show it rather than failing.
    return _error(payload if isinstance(data, str) or data is None else str(data))


def _unwrap_sse(text: str) -> str:
    """Strip `data:` framing. Returns the text unchanged if unframed."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not any(ln.startswith("data:") for ln in lines):
        return text
    return "".join(ln[len("data:") :].strip() for ln in lines if ln.startswith("data:"))


def _loads(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _error(message: str | None, severity: str = "informational") -> dict:
    return {
        "answer": message or "The agent returned an unreadable response.",
        "severity": severity,
        "escalation": None,
        "caveats": [],
        "citations": [],
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")

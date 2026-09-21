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
import os
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

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
_client = boto3.client("bedrock-agentcore", region_name=REGION)


class Ask(BaseModel):
    prompt: str
    session_id: str | None = None


@app.post("/api/ask")
async def ask(body: Ask) -> dict:
    """Forward one question to the deployed runtime and return its answer."""
    # AgentCore requires a session id of at least 33 characters. A uuid4
    # hex string is 32, so a prefix is added rather than trimming the
    # entropy.
    session_id = body.session_id or f"dash-{uuid.uuid4().hex}"

    try:
        result = _client.invoke_agent_runtime(
            agentRuntimeArn=_runtime_arn(),
            runtimeSessionId=session_id,
            payload=json.dumps({"prompt": body.prompt}).encode(),
        )
    except ClientError as exc:
        # Surfaced rather than swallowed. An AccessDenied here means the
        # caller cannot invoke the runtime, and a generic "something went
        # wrong" would send you looking in the wrong place.
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        return {
            "answer": f"Could not reach the agent runtime ({code}).",
            "severity": "informational",
            "escalation": None,
            "caveats": [str(exc)],
            "citations": [],
            "session_id": session_id,
        }

    payload = _read(result)
    payload["session_id"] = session_id
    return payload


def _read(result: dict) -> dict:
    """Decode the runtime's response.

    The entrypoint is an async generator, so the body arrives as a
    stream of chunks. They are concatenated and parsed once, because the
    dashboard renders a complete answer rather than a partial one --
    a half-rendered escalation block is worse than a slower one.
    """
    body = result.get("response")
    raw = b"".join(body) if body is not None else b""

    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return _error("The agent returned an empty response.")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # A runtime deployed before the structured-response change
        # returns plain text. Render it rather than failing.
        return _error(text, severity="informational")

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return _error(data, severity="informational")

    if not isinstance(data, dict) or "answer" not in data:
        return _error(str(data), severity="informational")

    return data


def _error(message: str, severity: str = "informational") -> dict:
    return {
        "answer": message,
        "severity": severity,
        "escalation": None,
        "caveats": [],
        "citations": [],
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")

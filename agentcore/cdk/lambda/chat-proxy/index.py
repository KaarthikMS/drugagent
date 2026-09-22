"""
Chat proxy.

Sits between API Gateway and the AgentCore runtime, and exists for one
reason: InvokeAgentRuntime requires SigV4, and a browser cannot produce
it without holding AWS credentials. This function holds them instead.

It replaces the local FastAPI server, which did the same signing with a
developer's credentials and no authentication in front of it.

The line that matters is the session id. It is DERIVED from the
authenticated Cognito subject and never read from the request. A
client-supplied session id is a request to join a conversation, which
becomes reading someone else's history the moment AgentCore Memory is
enabled. Deriving it makes the conversation owned rather than merely
unguessable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
MAX_PROMPT_CHARS = int(os.environ.get("MAX_PROMPT_CHARS", "4000"))

# Explicit timeouts. The default waits 60s to connect and 60s to read,
# which outlives API Gateway's own 30s integration timeout and turns a
# slow runtime into a Lambda billed for nothing.
_client = boto3.client(
    "bedrock-agentcore",
    config=Config(connect_timeout=3, read_timeout=25, retries={"max_attempts": 1}),
)

CORS = {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
}


def handler(event, _context):
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    sub = claims.get("sub")
    if not sub:
        # Unreachable while the authorizer is attached. Checked anyway:
        # a misconfigured route that skipped the authorizer would
        # otherwise fall through to an empty session id shared by every
        # anonymous caller.
        return _reply(401, {"message": "Not authenticated."})

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _reply(400, {"message": "Malformed request."})

    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return _reply(400, {"message": "Empty prompt."})
    if len(prompt) > MAX_PROMPT_CHARS:
        # Also enforced in the agent's domain layer. Repeated here so an
        # oversized prompt is refused before it is paid for.
        return _reply(413, {"message": "That message is too long."})

    session_id = _session_for(sub)

    try:
        result = _client.invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            runtimeSessionId=session_id,
            payload=json.dumps({"prompt": prompt}).encode(),
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        # The code reaches the browser; the message does not. A botocore
        # message carries the runtime ARN, the account id and the role
        # name.
        logger.exception("invoke failed (%s)", code)
        return _reply(502, {"message": "The assistant is unavailable.", "code": code})

    return _reply(200, _decode(result))


def _session_for(sub: str) -> str:
    """A stable, per-user session id.

    Hashed so the Cognito subject itself never becomes an identifier in
    AgentCore's storage: the session id appears in logs and traces, and
    a raw `sub` there is a durable handle on a named employee.

    AgentCore requires at least 33 characters; a sha256 hex digest is 64.
    """
    return "u-" + hashlib.sha256(sub.encode()).hexdigest()


def _decode(result: dict) -> dict:
    """Unwrap the runtime's response.

    A generator entrypoint is streamed back as server-sent events --
    `data: {...}` -- not as a JSON body, and the dict it yields is
    serialised by the runtime and again by the frame. Both layers are
    peeled here so the browser receives fields it can style.
    """
    body = result.get("response")
    raw = b"".join(body) if body is not None else b""
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return _fallback("The assistant returned an empty response.")

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if any(ln.startswith("data:") for ln in lines):
        text = "".join(ln[5:].strip() for ln in lines if ln.startswith("data:"))

    data = _loads(text)
    for _ in range(3):
        if not isinstance(data, str):
            break
        data = _loads(data)

    if isinstance(data, dict) and "answer" in data:
        return data
    return _fallback(text)


def _loads(text):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _fallback(message: str) -> dict:
    return {
        "answer": message,
        "severity": "informational",
        "escalation": None,
        "caveats": [],
        "citations": [],
    }


def _reply(status: int, payload: dict) -> dict:
    return {"statusCode": status, "headers": CORS, "body": json.dumps(payload)}

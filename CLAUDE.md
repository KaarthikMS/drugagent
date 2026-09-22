# pharmaagent — working notes

An internal health assistant for Grootan employees, on Amazon Bedrock AgentCore.
This file is for whoever (or whatever) works on it next.

---

## The one rule

**Guarantees live in code, not in prompts.**

Anything that must be true — escalation fires, "no interaction documented" never
reads as "safe", a lab value is flagged by arithmetic — is enforced in Python
and covered by a test. The model writes language; it does not enforce policy.

`app/drugagent/domain/` holds those rules and imports no client, no model and no
AWS SDK. That is why 193 tests run in under a second with no credentials.

**If you are about to put a rule that must hold into the system prompt, it
belongs in `domain/` instead.** Every time this was tried, it failed:

| Tried in the prompt | What happened |
|---|---|
| "stay in scope" | It explained the Strands API, then debugged a Python function |
| "use tools for everything factual" | Tool errored 3×; it answered from memory anyway |
| Guardrail topic for self-harm methods | Blocked "I feel like I want to kill myself" — which must reach the tripwire |

---

## Read before changing anything architectural

1. **`docs/architecture.md` §4** — 18 decisions (D1–D18), each with the rejected
   alternative. Several exist because an earlier approach failed under test.
2. **`app/drugagent/probes/FINDINGS.md`** — what each upstream API actually
   returns, including six different ways of saying "nothing found".
3. **`agentcore/cdk/AUTH.md`** — the auth design and why each choice was made.

A proposal that re-opens a settled decision without engaging with its rejected
alternative will just be re-rejected.

---

## Verify, don't assume

This is the habit that found every real bug in this project. Green is not
verified; output is.

| Said | Was |
|---|---|
| `agentcore status` → `READY` | every invocation failing with AccessDenied |
| `cdk synth --quiet` → exit 0 | Lambda asset path did not exist |
| 182 unit tests passing | truncation made warfarin+aspirin read "not documented" |
| Guardrail topic reads correctly | blocked a person in crisis |

Probe, curl, synth, invoke — then report what came back.

---

## Layout

```
app/drugagent/
  main.py         AgentCore entrypoint — instrumentation only
  agents/         agent.py (Strands assembly), pipeline.py (the sequence)
  config/         every tunable value, and the model id
  models/         load.py — Bedrock model construction
  prompts/        prompt.py — the system prompt
  tools/          eight @tool adapters
  utils/          raw HTTP to six public APIs
  domain/         THE RULES — no network, no model, no AWS
  observability/  OTel + CloudWatch. Never content.
  probes/         live API verification with controls
  tests/          193 unit + 11 smoke

agentcore/
  agentcore.json  declarative source of truth (CDK generated from it)
  cdk/lib/        auth.ts, hosting.ts, cdk-stack.ts
  cdk/lambda/     chat-proxy, pre-signup
  guardrails/     health-assistant.json + the tuning findings

frontend/         static dashboard (S3 + CloudFront), auth.js = PKCE flow
docs/             architecture, dataflow, implementation-plan
```

Directory names match the other AgentCore project in this account
(`agents/ config/ models/ prompts/ tools/ utils/`). `domain/` is an addition.

---

## Commands

Everything `agentcore` runs from the **project root**. Everything `uv` runs from
`app/drugagent/`.

```bash
# deploy
agentcore validate && agentcore deploy
agentcore invoke --prompt "What is metformin used for?"
agentcore logs

# tests
cd app/drugagent
uv run pytest -m "not smoke"     # 193, no network, <1s
uv run pytest                    # adds live API checks

# is an upstream API still behaving?
uv run python -m probes.probe_openfda_label

# CDK — note the binary, not npx (npx silently no-ops in some shells)
cd agentcore/cdk && npx tsc && ./node_modules/.bin/cdk synth

# after deploying auth
scripts/write-frontend-config.sh
```

---

## Live resources (ap-south-1, account 668426476778)

| | |
|---|---|
| Runtime | `pharmaagent_drugagent-IbZZTt2EEG` |
| Guardrail | `4xo8hb0f7iyl` version **2** — pinned in `agentcore.json` envVars |
| Model | `apac.amazon.nova-lite-v1:0` — an inference profile id, not a bare model id |
| Stack | `AgentCore-pharmaagent-default` |

`apac.` keeps inference inside APAC. `global.` profiles route worldwide — a
data-residency choice, not a price one, for a system holding lab values.

---

## Traps that have already bitten

- **openFDA returns combination products.** A metformin question was answered
  with sitagliptin dosing; a paracetamol overdose question with oxycodone's.
  Fixed three times in three different ways — see `utils/openfda.py::_best_match`.
  If it recurs, filter on `openfda.generic_name.exact` at query time.
- **Never truncate label text in the client.** Domain logic searches the whole
  section; only what reaches the model is capped. Capping in the client made
  warfarin + aspirin read "not documented".
- **"Not found" is HTTP 200 for four of six upstreams.** Check for the key,
  never the status code.
- **`Severity` subclasses `str`**, so it inherits string comparison. All four
  comparison operators are defined deliberately — `"emergency" > "high"` is
  False alphabetically, and `should_escalate` uses `>=`.
- **Guardrail topics run on OUTPUT too.** "Prescribing and dose changes" matched
  the system's own answers, because a correct answer quotes label dosing text.
  All topics set `outputEnabled: false`.

---

## Still open

- **Deploy the pending work** — the oxycodone fix, scope enforcement, input
  bounds and the whole auth stack are committed but not live.
- **Clinical review** of `domain/severity.py` tripwires, `domain/triage.py`
  rules, `CRITICAL_RANGE_MULTIPLE`, and `domain/brands.py`. All are plain
  readable rules so a clinician can check them without reading code.
- **Org sign-off** on accepting employee health data.
- **AgentCore Memory** (step 7). Safe to enable now that the session id is
  derived from the Cognito subject rather than supplied by the client.
- Lab report file upload (PDF/photo) — currently paste-only.
- Online evaluators — escalation recall is the metric that matters.

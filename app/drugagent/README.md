# Health assistant agent

A health information assistant for employees: medicines, conditions, symptoms,
drug interactions, toxicity and lab results — grounded in official sources, with
deterministic escalation to a real clinician.

Design decisions and their rationale live in [`docs/`](../../docs): `architecture.md`,
`dataflow.md`, `implementation-plan.md`.

## Run it

```bash
uv sync --all-groups

# Local demo dashboard
uv run uvicorn server:app --port 8080     # → http://127.0.0.1:8080

# Tests
uv run pytest -m "not smoke"              # 182 tests, no network, <1s
uv run pytest                             # adds live API smoke tests

# Verify an upstream API still behaves as recorded
uv run python -m probes.probe_rxnorm
```

Requires AWS credentials with Bedrock access in `ap-south-1` for anything that
calls the model. The tests marked `not smoke` need neither credentials nor network.

## Layout

```
main.py         AgentCore Runtime entrypoint — instrumentation only
server.py       local demo server (not the deployment path)
pipeline.py     tripwire → agent → severity gate → response
agent.py        Strands agent assembly
config.py       every tunable value, and the model id

domain/         PURE LOGIC — no network, no model, no AWS
  models.py       typed vocabulary
  severity.py     tripwire, maximum-wins combination, escalation text
  interactions.py bidirectional label cross-check
  triage.py       symptom red-flag ruleset
  labs.py         analyte parsing, range comparison
  units.py        unit normalisation, mass/molar refusal
  brands.py       Indian brand → US generic ingredients
  response.py     final assembly; what the model cannot influence

clients/        raw HTTP to six public APIs
tools/          Strands @tool adapters over clients + domain
prompts/        system prompt
probes/         live API verification, with controls — see FINDINGS.md
observability/  OTel traces and metrics. Never content.
tests/          unit (mocked transport) + smoke (live)
```

## The one idea worth knowing

**Guarantees live in `domain/`, not in the prompt.**

Anything that must be true — escalation fires, "not documented" never reads as
"safe", a lab value is flagged by arithmetic — is enforced in Python and covered
by a test. The model writes language; it does not enforce policy.

That is why `domain/` has no imports from `clients/`, no model, and no AWS: the
rules that carry clinical weight are provable without any of them, and the whole
unit suite runs in under a second.

## Data sources

All public, no API key required.

| Source | Used for |
|---|---|
| RxNorm | drug name normalisation, brand → generic, typos |
| RxClass | ATC drug classes (a label says "NSAIDs", never "ibuprofen") |
| openFDA `/drug/label` | prescribing information |
| openFDA `/drug/event` | FAERS reports — counts, never rates |
| PubChem | compound chemistry, GHS hazard |
| MedlinePlus | conditions, and lab tests by LOINC code |
| NLM Clinical Tables | analyte name → LOINC code |

Every one was probed with positive, negative and **nonsense** controls before a
client was written against it. `probes/FINDINGS.md` records what each returned,
including six different ways of saying "nothing found".

## Before real users

- Clinical review of `domain/severity.py` (tripwires), `domain/triage.py` (rules),
  `CRITICAL_RANGE_MULTIPLE` in `domain/labs.py`, and `domain/brands.py`
- Cognito + API Gateway in front of the runtime (`server.py` has no auth)
- Bedrock Guardrails attached at invoke time
- Organisational sign-off on accepting health data

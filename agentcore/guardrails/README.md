# Guardrail — health assistant

`health-assistant.json` is the source of truth. Bedrock Guardrails are not part of
`agentcore.json` (the schema has no guardrails array), so they are created and
updated directly against the Bedrock API with this file as input.

## What this guardrail is for — and what it is not for

It does **scope control** and **PII redaction**. That is all.

Clinical safety — escalation, severity, "no interaction documented is not the same
as safe", lab flagging — is enforced in `app/drugagent/domain/` and covered by 182
tests. None of it is delegated here. A guardrail is a filter, not a policy engine:
it can stop a bad question reaching the model, and it cannot make a good answer
correct.

## The design decision that matters

**A naive health guardrail is dangerous, and the danger is on the input side.**

The obvious configuration blocks self-harm content on input. Do that, and a person
typing *"I want to kill myself"* receives a canned refusal instead of crisis
guidance — because Guardrails stops the message before the system ever sees it.

This system already handles that case properly: `domain/severity.py` has a
self-harm tripwire that forces `EMERGENCY` and returns crisis guidance, and it runs
*before* the model. That path is worth more than a filter, and a filter would
destroy it.

So the split is:

| | Input | Output | Why |
|---|---|---|---|
| Self-harm | **not filtered** | denied topic (methods only) | Distress must reach the tripwire; methods must never be written |
| Violence | `NONE` | `LOW` | Label text describes bleeding, overdose and death. That is the product |
| Sexual | `NONE` | `LOW` | Labels cover contraception and sexual dysfunction |
| Prompt attack | `HIGH` | n/a | Nothing legitimate looks like an injection |
| Hate | `MEDIUM` | `HIGH` | No clinical reason to carry it |

The denied topic is **"self-harm methods"**, not "self-harm" — lethal doses and
"which medicine kills" are refused, while a person expressing distress is answered.
That distinction is the entire point, and it is written into the topic definition
so a reviewer can check it.

## The other deliberate omission: AGE is not redacted

Bedrock can anonymise `AGE` as PII. It is left out on purpose. `domain/triage.py`
uses age and pregnancy to decide urgency — fever in pregnancy reaches `HIGH`, and a
redacted age silently downgrades it. Redacting a field the safety layer reads is a
safety change disguised as a privacy setting.

Names, emails, phone numbers and addresses **are** anonymised, plus Aadhaar and PAN
via regex, since employees will paste lab reports with their identifiers on them.

## Contextual grounding is not enabled

Bedrock's contextual grounding filter scores an answer against a declared grounding
source. Strands does not tag retrieved tool results as grounding source in the
Converse request, so the filter would have nothing to compare against — it would
either never fire or fire wrongly. Groundedness is instead measured in step 9's
evaluators, where the retrieved text is actually available.

## Create it

```bash
aws bedrock create-guardrail \
  --region ap-south-1 \
  --cli-input-json file://agentcore/guardrails/health-assistant.json
```

Note the `guardrailId` from the response, then publish a version:

```bash
aws bedrock create-guardrail-version \
  --region ap-south-1 \
  --guardrail-identifier <guardrailId> \
  --description "initial"
```

## Update it

Edit the JSON, then:

```bash
aws bedrock update-guardrail \
  --region ap-south-1 \
  --guardrail-identifier <guardrailId> \
  --cli-input-json file://agentcore/guardrails/health-assistant.json
```

`update-guardrail` changes the DRAFT. Publish a new version afterwards, and move
`GUARDRAIL_VERSION` when you want the runtime to pick it up — so a config change
cannot alter production behaviour without a deliberate second step.

## Attach it

Two environment variables on the runtime:

```
GUARDRAIL_ID=<guardrailId>
GUARDRAIL_VERSION=1
```

Unset in local development, where the Python safety layer still runs. `config.py`
reads both; `model/load.py` attaches them to the Bedrock model.

## Test it

```bash
aws bedrock-runtime apply-guardrail \
  --region ap-south-1 \
  --guardrail-identifier <guardrailId> \
  --guardrail-version DRAFT \
  --source INPUT \
  --content '[{"text":{"text":"Should I stop taking my blood pressure tablets?"}}]'
```

Expect `action: GUARDRAIL_INTERVENED`. Then run the same command with
`"I feel like I want to kill myself"` and expect **`NONE`** — that message must
reach the tripwire.

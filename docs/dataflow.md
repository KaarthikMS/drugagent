# Data flow — v1

Three documented flows: a simple drug question, an interaction question, and an
emergency. Together they exercise every layer.

---

## 1. Request lifecycle

Every request, regardless of type.

```mermaid
sequenceDiagram
    autonumber
    actor U as Employee
    participant FE as Frontend
    participant CG as Cognito
    participant GW as API Gateway
    participant RT as Runtime handler
    participant GD as Guardrails
    participant MM as Memory
    participant AG as Agent
    participant SG as Severity gate

    U->>FE: question
    FE->>CG: authenticate (org email)
    CG-->>FE: JWT (sub = user id)
    FE->>GW: POST /chat + JWT
    GW->>GW: validate JWT
    GW->>RT: payload + sub + trace id

    RT->>GD: input scan
    GD-->>RT: redacted text / refusal

    RT->>MM: load context (actorId = sub)
    MM-->>RT: distilled prior turns

    RT->>AG: question + context
    AG-->>RT: answer + severity + citations

    RT->>SG: evaluate
    SG-->>RT: escalation block if medium+

    RT->>GD: output scan
    RT->>MM: write distilled summary
    RT-->>GW: answer + citations + escalation
    GW-->>FE: stream response
    FE-->>U: rendered answer
```

Note what crosses each boundary. The raw question reaches Guardrails and the model.
It does **not** reach the logs, and only a distilled form reaches memory.

---

## 2. Simple drug question

> *"What is metformin used for?"*

```mermaid
sequenceDiagram
    autonumber
    participant AG as Agent
    participant T1 as drug_normalize
    participant T2 as drug_label_lookup
    participant RX as RxNorm
    participant FDA as openFDA

    AG->>T1: normalize("metformin")
    T1->>RX: /rxcui.json?name=metformin
    RX-->>T1: ingredient rxcui
    T1-->>AG: {canonical, rxcui, was_brand: false}

    AG->>T2: lookup(metformin, sections=[indications, dosage])
    T2->>FDA: /drug/label.json?search=openfda.generic_name:"metformin"
    FDA-->>T2: label with requested sections
    T2-->>AG: {found, spans[], source_url, set_id}

    Note over AG: composes answer from spans only
    AG-->>AG: severity = INFORMATIONAL
```

No escalation — `INFORMATIONAL` is below the medium threshold.

---

## 3. Interaction question

> *"Can I take warfarin with aspirin?"*

This is the flow that matters most.

```mermaid
sequenceDiagram
    autonumber
    participant AG as Agent
    participant T1 as drug_normalize
    participant T3 as interaction_check
    participant RX as RxNorm
    participant FDA as openFDA

    AG->>T1: normalize("warfarin")
    T1->>RX: /rxcui.json?name=warfarin
    RX-->>T1: 11289
    AG->>T1: normalize("aspirin")
    T1->>RX: /rxcui.json?name=aspirin
    RX-->>T1: 1191

    AG->>T3: check(warfarin, aspirin)

    par both labels fetched concurrently
        T3->>FDA: warfarin drug_interactions
        FDA-->>T3: ~6500 chars
    and
        T3->>FDA: aspirin drug_interactions
        FDA-->>T3: ~5000 chars
    end

    Note over T3: cross-check BOTH directions, in Python<br/>A mentions B? B mentions A?<br/>by name, ingredient, AND class

    alt either direction matches
        T3-->>AG: {documented: true, evidence: spans[], sources[]}
    else neither mentions the other
        T3-->>AG: {documented: false,<br/>"No interaction documented in either label"}
        Note over T3,AG: NEVER rendered as "safe together"
    end

    Note over AG: answer from evidence spans only
    AG-->>AG: severity = HIGH
```

### Why both directions

Labels are not symmetric. Warfarin's label may discuss aspirin while aspirin's label
never names warfarin, or vice versa. Checking one direction halves the detection rate
for no saving.

### Why class matching

A label may say *"NSAIDs"* and never write *"ibuprofen"*. Exact-string matching on the
drug name misses every class-level warning — which is most of them.

### Fetch both concurrently

Two independent HTTP calls. Sequential `await` doubles latency for no reason; use
`asyncio.gather`. This is why `httpx.AsyncClient` replaces `requests` — sync calls in
an async handler block the event loop and serialise everything.

---

## 4. Emergency path

> *"I've had crushing chest pain for an hour and my left arm is numb"*

```mermaid
flowchart TD
    Q["Incoming question"] --> TW{"Emergency keyword<br/>tripwire — Python"}

    TW -->|match| FORCE["severity = EMERGENCY<br/>forced, model not consulted<br/>for classification"]
    TW -->|no match| MODEL["Agent answers<br/>returns own severity"]

    MODEL --> SEV{"severity ?"}
    SEV -->|informational / low| PLAIN["Answer as-is"]
    SEV -->|medium / high| ESC["Answer + escalation block"]
    SEV -->|emergency| FORCE

    FORCE --> URGENT["Emergency guidance FIRST<br/>seek immediate care<br/>answer secondary or withheld"]

    PLAIN --> OUT["Response"]
    ESC --> OUT
    URGENT --> OUT

    style FORCE fill:#7f1d1d,color:#fff
    style URGENT fill:#7f1d1d,color:#fff
```

The tripwire runs **before** the model and overrides it. Model classification is good
but not perfect, and the cost of missing one cardiac presentation is not symmetric
with the cost of over-escalating a false positive.

---

## 5. What crosses each boundary

| Boundary | Carries | Never carries |
|---|---|---|
| Frontend → API Gateway | question, JWT | credentials in body |
| API Gateway → Runtime | question, Cognito `sub`, trace id | raw tokens |
| Runtime → Guardrails | raw question | — |
| Guardrails → Model | redacted question | direct identifiers |
| Runtime → Memory | distilled summary | raw message text |
| Runtime → Logs | event id, intent, latency, outcome | **question or answer text** |
| Runtime → Metrics | counts, durations | any content |
| Tools → External APIs | drug names only | user identity, any PHI |

The last row matters: openFDA and RxNorm receive drug names and nothing else. No user
identifier ever leaves the account.

---

## 6. Failure handling

| Failure | Behaviour |
|---|---|
| RxNorm unavailable | Fall back to raw name against openFDA; flag reduced confidence |
| openFDA unavailable | No grounding → refuse to answer clinically; say the source is unavailable |
| Drug not found | State not found; do **not** answer from model knowledge |
| Only one label retrieved | Report one-sided check explicitly; do not imply a full check |
| Guardrail refusal | Return refusal; no model call |
| Memory unavailable | Proceed stateless; degrade, do not fail |
| Model error | Generic failure; never a partial clinical answer |

The theme: **degrade to "I cannot answer", never to an ungrounded answer.** In this
domain a confident wrong answer is worse than no answer.

# Data flow

Seven documented flows. Together they exercise every layer and every safety control.

| # | Flow | Exercises |
|---|---|---|
| 1 | Request lifecycle | Auth, guardrails, memory, gate |
| 2 | Drug question | Normalisation, label retrieval, citation |
| 3 | Interaction question | Concurrency, bidirectional cross-check, the "not documented" contract |
| 4 | Condition / symptom question | Prose retrieval, triage ruleset |
| 5 | Toxicity question | Multi-source fan-out, FAERS caveat |
| 6 | Lab report | Upload, extract, parse, arithmetic, deletion |
| 7 | Emergency | Tripwire override |

---

## 1. Request lifecycle

Every text request, regardless of type.

```mermaid
sequenceDiagram
    autonumber
    actor U as Employee (local)
    participant FE as Frontend
    participant GW as API Gateway
    participant RT as Runtime handler
    participant TW as Tripwire
    participant GD as Guardrails
    participant MM as Memory
    participant AG as Agent
    participant SG as Severity gate

    Note over FE,GW: Unauthenticated -- see CLAUDE.md
    U->>FE: question
    FE->>GW: POST /chat + client-chosen session id
    GW->>RT: payload + session id + trace id

    RT->>TW: scan for emergency phrases
    TW-->>RT: severity floor (usually none)

    RT->>GD: input scan
    GD-->>RT: redacted text / refusal

    RT->>MM: load context (actorId = sub)
    MM-->>RT: distilled prior turns

    RT->>AG: question + context
    AG-->>RT: answer + severity + citations + tool floors

    RT->>SG: max(tripwire, model, tool floors)
    SG-->>RT: escalation block if medium+

    RT->>GD: output scan
    RT->>MM: write distilled summary
    RT-->>GW: answer + citations + escalation
    GW-->>FE: stream response
    FE-->>U: rendered answer
```

Note what crosses each boundary. The raw question reaches the tripwire, Guardrails and
the model. It does **not** reach the logs, and only a distilled form reaches memory.

The tripwire runs *before* Guardrails deliberately: redaction can remove the words the
tripwire matches on.

---

## 2. Drug question

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

A compound question (*"what is ibuprofen's molecular weight?"*) follows the same
shape through `compound_lookup` against PubChem, and carries no severity at all: it is
chemistry, not clinical advice.

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
    participant RC as RxClass
    participant FDA as openFDA

    AG->>T1: normalize("warfarin")
    T1->>T1: Indian brand alias map (D14)
    T1->>RX: /rxcui.json?name=warfarin
    RX-->>T1: 11289
    AG->>T1: normalize("aspirin")
    T1->>RX: /rxcui.json?name=aspirin
    RX-->>T1: 1191

    AG->>T3: check(warfarin, aspirin)

    T3->>RC: ATC classes for both (relaSource pinned)
    RC-->>T3: B01AA vitamin K antagonists / N02BA salicylates

    par both labels fetched concurrently
        T3->>FDA: warfarin drug_interactions
        FDA-->>T3: ~6500 chars
    and
        T3->>FDA: aspirin drug_interactions
        FDA-->>T3: ~5000 chars
    end

    Note over T3: cross-check BOTH directions, in Python<br/>A mentions B? B mentions A?<br/>by name, ingredient, AND class

    alt either direction matches
        T3-->>AG: {documented: true, evidence: spans[], sources[], severity_floor: HIGH}
    else neither mentions the other
        T3-->>AG: {documented: false,<br/>"No interaction documented in either label"}
        Note over T3,AG: NEVER rendered as "safe together"
    end

    Note over AG: answer from evidence spans only
```

### Why both directions

Labels are not symmetric. Warfarin's label may discuss aspirin while aspirin's label
never names warfarin, or vice versa. Checking one direction halves the detection rate
for no saving.

### Why class matching

A label may say *"NSAIDs"* and never write *"ibuprofen"*. Exact-string matching on the
drug name misses every class-level warning — which is most of them.

Class membership comes from RxClass rather than a table in this repository (D15), and
`relaSource` is pinned to ATC. Unfiltered, RxClass mixes in MED-RT `may_treat` and
`contraindication` relations: warfarin comes back "classed" as *Alcoholism* and
*Abortion, Threatened*. Those are real relations, and they are not drug classes.

### Fetch both concurrently

Two independent HTTP calls. Sequential `await` doubles latency for no reason; use
`asyncio.gather`. This is why `httpx.AsyncClient` replaces `requests` — sync calls in
an async handler block the event loop and serialise everything.

---

## 4. Condition and symptom question

> *"I've had a headache for three days"*

Two tools, and the second one is the safety-critical half.

```mermaid
sequenceDiagram
    autonumber
    participant AG as Agent
    participant T7 as symptom_triage
    participant TR as domain/triage.py
    participant T6 as condition_lookup
    participant MP as MedlinePlus

    AG->>T7: triage(symptom="headache", duration="3 days", modifiers=[])
    T7->>TR: match against red-flag ruleset
    alt red flag matched
        TR-->>T7: severity_floor = HIGH or EMERGENCY, matched_rule
    else no red flag
        TR-->>T7: severity_floor = LOW
    end
    T7-->>AG: {severity_floor, matched_rule, reason}

    AG->>T6: lookup("headache")
    T6->>MP: health topics search
    MP-->>T6: topic summary + url
    T6-->>AG: {spans[], source_url}

    Note over AG: answer from spans<br/>+ own severity classification
    Note over AG: gate takes MAX of triage floor<br/>and model severity
```

### Why triage is separate from lookup

MedlinePlus tells you what a headache *is*. It does not tell you that "sudden, severe,
worst of my life" is a subarachnoid-haemorrhage presentation that needs an emergency
department now. That judgement is encoded in `domain/triage.py` as explicit rules, so
a clinician can review it and a test can verify it.

The parsing of a free-text symptom description into `(symptom, duration, modifiers)`
is the model's job — language understanding. The decision about what that tuple means
is the ruleset's job. Split along that line consistently.

---

## 5. Toxicity question

> *"What happens if someone takes too much paracetamol?"*

```mermaid
sequenceDiagram
    autonumber
    participant AG as Agent
    participant T5 as toxicity_lookup
    participant FDA as openFDA
    participant PC as PubChem

    AG->>T5: toxicity("paracetamol")

    par three sources concurrently
        T5->>FDA: label overdosage section
        FDA-->>T5: manufacturer overdose guidance
    and
        T5->>FDA: /drug/event.json counts
        FDA-->>T5: reported event counts
    and
        T5->>PC: GHS classification
        PC-->>T5: hazard statements
    end

    Note over T5: attach caveats in Python:<br/>FAERS = spontaneous reports,<br/>no denominator, no causality

    T5-->>AG: {overdosage_spans[], event_counts{}, faers_caveat, ghs[], sources[]}

    Note over AG: response validator REJECTS an answer<br/>citing FAERS counts without the caveat
```

If the same question is asked in the first person present tense — *"I took too much
paracetamol"* — the tripwire fires at step 1 of the lifecycle and this flow never runs
as an information request. Paracetamol overdose is time-critical and initially
asymptomatic, which is exactly the case where a calm informational answer does harm.

---

## 6. Lab report

> *user uploads a PDF or a phone photo*

```mermaid
sequenceDiagram
    autonumber
    actor U as Employee
    participant FE as Frontend
    participant GW as API Gateway
    participant S3 as S3 (SSE-KMS)
    participant EX as Extractor
    participant PA as domain/labs.py
    participant CT as Clinical Tables
    participant AG as Agent
    participant SG as Severity gate

    U->>FE: select file
    FE->>GW: request presigned PUT
    GW-->>FE: presigned URL
    FE->>S3: PUT file directly
    Note over FE,S3: file never transits the API payload

    FE->>GW: POST /lab {object_key}
    GW->>EX: fetch object

    alt PDF with text layer
        EX->>EX: direct text extraction
    else scanned PDF or photo
        EX->>EX: render / decode → vision model
    end
    EX-->>PA: raw text + layout

    PA->>PA: redact name, DOB, patient id
    PA->>PA: parse rows → Analyte(name, value, unit, ref_low, ref_high, ref_source)
    PA->>PA: normalise units
    PA->>PA: compare — below / within / above / critical
    PA->>CT: analyte text -> LOINC (scored)
    CT-->>PA: candidates
    Note over PA: weak match -> NO description attached<br/>"hemoglobin" alone spans 508 LOINC items

    Note over PA: unparsed rows collected, NOT dropped<br/>unreconcilable unit → "could not be verified"

    PA-->>AG: {analytes[], flags[], unparsed[], severity_floor}
    Note over AG: explains flags in plain language<br/>does not produce them

    AG->>SG: max(model severity, critical-value floor)
    SG-->>AG: escalation block

    PA->>S3: DELETE object
    Note over S3: lifecycle rule is a backstop,<br/>not the deletion path
```

### The three things that must hold

| Must hold | Enforced where |
|---|---|
| Flags come from arithmetic, never from the model | `domain/labs.py` |
| Unparsed rows appear in the answer | `domain/labs.py`, response assembly |
| A weak LOINC match attaches no description | `domain/labs.py` |
| "Within range" never renders as "you are healthy" | Python-appended statement |

### Why the file bypasses the API payload

A presigned PUT sends the file browser → S3 directly. Routing a multi-megabyte photo
through API Gateway means base64 inflation, a payload size limit, the file in request
logs, and the file in memory in the handler. The presigned URL is scoped to one key,
one method, and a few minutes.

---

## 7. Emergency path

> *"I've had crushing chest pain for an hour and my left arm is numb"*

```mermaid
flowchart TD
    Q["Incoming question"] --> TW{"Emergency keyword<br/>tripwire — Python"}

    TW -->|match| FORCE["severity = EMERGENCY<br/>forced, model not consulted<br/>for classification"]
    TW -->|no match| MODEL["Agent answers<br/>returns own severity<br/>tools return severity floors"]

    MODEL --> MAX["severity = MAX(model, tool floors, triage floor)"]
    MAX --> SEV{"severity ?"}
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

**Maximum wins, always.** No component can lower a severity another component raised.
That property is a single function with exhaustive unit tests, and it is the reason
the system can carry six independent severity inputs without any of them being able
to undo another.

---

## 8. What crosses each boundary

| Boundary | Carries | Never carries |
|---|---|---|
| Frontend → API Gateway | question, JWT, object key | credentials in body, file bytes |
| Frontend → S3 | file bytes, presigned URL | user identity beyond the key |
| API Gateway → Runtime | question, session id, trace id | raw tokens |
| Runtime → Tripwire | raw question | — |
| Runtime → Guardrails | raw question | — |
| Guardrails → Model | redacted question | direct identifiers |
| Extractor → Parser | raw report text | — |
| Parser → Model | redacted analytes | name, DOB, patient id |
| Runtime → Memory | distilled summary | raw message text, lab values |
| Runtime → Logs | event id, tool names, latency, severity, outcome | **question, answer, analyte names or values** |
| Runtime → Metrics | counts, durations | any content |
| Tools → External APIs | drug names, symptom terms, analyte names, LOINC codes | user identity, values, any PHI |

The last row matters: openFDA, RxNorm, PubChem and MedlinePlus receive search terms and
nothing else. No user identifier ever leaves the account.

---

## 9. Failure handling

| Failure | Behaviour |
|---|---|
| RxNorm unavailable | Fall back to raw name against openFDA; flag reduced confidence |
| openFDA unavailable | No grounding → refuse to answer clinically; say the source is unavailable |
| PubChem unavailable | Omit chemistry detail; answer from label sources if present |
| MedlinePlus unavailable | No grounding for conditions/symptoms → refuse; **triage ruleset still runs** |
| RxClass unavailable | Fall back to name-and-ingredient matching; state the check was narrower |
| Clinical Tables unavailable | Values still parsed and flagged; no test descriptions attached |
| Brand name not in the alias map (D14) | Ask for the generic name; never guess a mapping |
| Drug or topic not found | State not found; do **not** answer from model knowledge |
| Only one label retrieved | Report one-sided check explicitly; do not imply a full check |
| Extraction yields no text | Ask for a clearer photo; do not guess |
| Analyte row unparseable | Surface it as unparsed; never drop it |
| Unit not reconcilable with range | "Could not be verified"; never compare anyway |
| File delete fails | Log the failure, alarm on it; lifecycle rule catches it within a day |
| Guardrail refusal | Return refusal; no model call |
| Memory unavailable | Proceed stateless; degrade, do not fail |
| Model error | Generic failure; never a partial clinical answer |

The theme: **degrade to "I cannot answer", never to an ungrounded answer.** In this
domain a confident wrong answer is worse than no answer.

Note the MedlinePlus row. Retrieval failing must not disable triage — the red-flag
ruleset is local Python with no dependency on any upstream. The system can lose every
external source and still tell someone with stroke signs to call an ambulance.

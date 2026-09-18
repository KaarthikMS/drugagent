# Upstream probe findings

Evidence that each external API behaves as the clients assume. Regenerate with:

```bash
python -m probes.probe_<name>      # from app/drugagent/
```

Recorded 2026-09-18. Every check carries a control that would fail if the
upstream were ignoring our query — without one, a green result proves nothing.

## Output

```

RxNorm probe
==============================================================================
[PASS] exact name -> rxcui              warfarin resolves to ingredient rxcui 11289
                                        observed: rxnormId=['11289']
[PASS] nonsense name (CONTROL)          no rxnormId key; HTTP 200 body, not a 404
                                        observed: body={'idGroup': {}}
[PASS] brand name -> rxcui              Coumadin resolves to some rxcui
                                        observed: rxnormId=['202421']
[PASS] misspelling handling             exact fails; approximateTerm recovers 'metformin'
                                        observed: exact=[] approx_top={'rxcui': '6809', 'rxaui': '10328664', 'score': '8.183039665222168', 'rank': '1', 'source': 'GS'}
[PASS] ingredient -> SCD products (D4)  11289 expands to product rxcuis incl. 855288
                                        observed: 10 products, first 3 = ['855288', '855296', '855302']
==============================================================================
5/5 passed


RxClass probe
==============================================================================
[PASS] drug -> classes              warfarin classed as a vitamin K antagonist
                                    observed: sources=['ATC', 'ATCPROD', 'DAILYMED', 'FDASPL', 'MEDRT', 'SNOMEDCT', 'VA'] classes=['ANTICOAGULANTS', 'Abortion, Threatened', 'Alcoholism', 'An...
[PASS] relaSource filter            ATC only; includes B01AA
                                    observed: sources={'ATC'} ids=['B01AA']
[PASS] class -> members             ATC M01A contains ibuprofen
                                    observed: 60 members, ibuprofen=True
[PASS] class overlap is computable  ibuprofen's ATC classes include the NSAID branch M01A
                                    observed: ibuprofen ATC=['C01EB', 'G02CC', 'M01AE', 'M02AA', 'N02AJ', 'R02AX']
[PASS] unknown rxcui (CONTROL)      no classes returned -- proves the lookup filters
                                    observed: body={}
==============================================================================
5/5 passed


openFDA label probe
==============================================================================
[PASS] baseline: warfarin                a non-zero label count
                                         observed: total=76
[PASS] true positive: warfarin+aspirin   warfarin labels mention aspirin
                                         observed: total=76
[PASS] nonsense control                  NOT_FOUND -- proves the field filter runs
                                         observed: body=None
[PASS] true negative: metformin+aspirin  NOT_FOUND -- no documented interaction
                                         observed: body=None
[PASS] interaction section size          thousands of chars -- span extraction is mandatory
                                         observed: 6477 chars: 7 DRUG INTERACTIONS Concomitant use of drugs that increase bleeding ri...
[PASS] overdosage section populated      acetaminophen labels carry overdosage text
                                         observed: total=889 chars=243: Overdose warning: In the case of overdose, get medical help ...
[PASS] citable source identity           set_id present, for a stable DailyMed citation URL
                                         observed: set_id=0cbce382-9c88-4f58-ae0f-532a841e8f95 effective_time=20250617
==============================================================================
7/7 passed


openFDA FAERS probe
==============================================================================
[PASS] reaction counts                     ranked MedDRA reaction terms with counts
                                           observed: top3=[('DRUG INEFFECTIVE', 52232), ('PAIN', 49501), ('FATIGUE', 45789)]
[PASS] counts are not causality (CONTROL)  top term is a reporting artefact, not a side effect
                                           observed: top='DRUG INEFFECTIVE' -- D11 caveat is mandatory
[PASS] nonsense drug (CONTROL)             NOT_FOUND -- proves the search field filters
                                           observed: body=None
[PASS] no denominator exists               meta carries no exposure count -- rates are impossible
                                           observed: meta keys=['disclaimer', 'last_updated', 'license', 'terms']
==============================================================================
4/4 passed


PubChem probe
==============================================================================
[PASS] name -> CID                     ibuprofen resolves to CID 3672
                                       observed: CID=[3672]
[PASS] nonsense name (CONTROL)         HTTP 404 -> None (not an empty 200 like RxNorm)
                                       observed: body=None
[PASS] properties + renamed key        formula/weight present; SMILES key is NOT CanonicalSMILES
                                       observed: keys=['ConnectivitySMILES', 'IUPACName', 'MolecularFormula', 'MolecularWeight']
[PASS] GHS via PUG-View                nested Section tree keyed by TOCHeading
                                       observed: title='Ibuprofen, (+-)-' top_sections=['Safety and Hazards']
[PASS] missing GHS degrades (CONTROL)  real CID without hazard data -> None, not a crash
                                       observed: body=None (absent data != safe)
==============================================================================
5/5 passed


MedlinePlus probe
==============================================================================
[PASS] health topic search      hypothyroidism returns ranked topics
                                observed: count=11 first='<span class="qt0">Hypothyroidism</span>'
[PASS] nonsense term (CONTROL)  count=0 in a valid 200 XML body
                                observed: count=0 titles=[]
[PASS] markup needs stripping   titles contain span highlighting to remove
                                observed: raw='<span class="qt0">Diabetes</span>'
[PASS] Connect: LOINC 2093-3    total cholesterol code resolves to a topic
                                observed: entries=2 first='Cholesterol'
[PASS] unmapped code (CONTROL)  no entries -- never a wrong-test description
                                observed: entries=0
==============================================================================
5/5 passed


NLM Clinical Tables probe
==============================================================================
[PASS] positional array shape              [total, [codes], null, [[display]]] -- no field names
                                           observed: [2, ['2142', '10247'], None, [['Hypothyroidism'], ['Myxedema']]]
[PASS] analyte text -> LOINC               'hemoglobin' resolves to LOINC codes
                                           observed: total=508 first=['97551-6', '31157-1'] ['COHgb MFr BldCV', 'COHgb Bld-mCnc']
[PASS] LOINC match is ambiguous (CONTROL)  many hits; top result is NOT the routine test
                                           observed: 508 hits; top=['COHgb MFr BldCV', 'COHgb Bld-mCnc', 'COHgb MFr.DF BldCoV']
[PASS] condition autocomplete              'hypothyro' suggests Hypothyroidism
                                           observed: ['Hypothyroidism', 'Myxedema']
[PASS] nonsense term (CONTROL)             total=0 inside a valid 200 array
                                           observed: raw=[0, [], None, []]
==============================================================================
5/5 passed

```

## What the probes changed

Two sources exist because of what the probes found, not because they were planned:

- **NLM Clinical Tables** — the lab flow was specified as "LOINC code → MedlinePlus
  Connect". Nothing mapped the analyte *text* a report prints to that code. The gap
  only appeared when the flow was traced end to end against real data.
- **RxClass** — replaced a hand-maintained drug-class table. A local table goes stale
  silently, and its staleness surfaces as a *missed interaction*, not a failing test.

One probe failed on its first run and was right to. The GHS-absent control used water,
assuming a harmless compound carries no hazard data. Water has a full GHS record.
Replaced with hydrotalcite (CID 71749): a real antacid with a PUG-REST record and a
404 on the hazard heading.

## Traps the clients must handle

| Trap | Where | Consequence if ignored |
|---|---|---|
| "Not found" is HTTP 200 with an empty body | RxNorm, RxClass, MedlinePlus, Clinical Tables | Missing key read as success |
| `relaSource` unpinned mixes MED-RT relations with classes | RxClass | Warfarin "classed" as *Alcoholism* |
| `CanonicalSMILES` silently renamed `ConnectivitySMILES` | PubChem | `KeyError` on an HTTP 200 |
| Response is a positional array, no field names | Clinical Tables | Index-based parsing, undocumented |
| Search results carry `<span class="qt0">` markup | MedlinePlus | Markup reaches the answer text |
| `hemoglobin` spans 508 LOINC items | Clinical Tables | Wrong test's description on a real value |
| FAERS has no denominator field | openFDA events | Counts read as incidence rates |
| OTC `overdosage` is a 243-char consumer blurb | openFDA labels | Thin grounding for toxicity answers |
| Interaction section is ~6,500 chars | openFDA labels | Two per query; span extraction is mandatory |

### Six upstreams, six ways to say "nothing found"

| Upstream | Response |
|---|---|
| RxNorm | HTTP 200, `{"idGroup": {}}` |
| RxClass | HTTP 200, `{}` |
| openFDA | HTTP 404, `{"error": {"code": "NOT_FOUND"}}` |
| PubChem | HTTP 404, `{"Fault": {...}}` |
| MedlinePlus | HTTP 200, valid XML, `<count>0</count>` |
| Clinical Tables | HTTP 200, `[0, [], null, []]` |

`base.py` maps 404 → `None`, which covers two. Every other client checks for the
**key**, never the status code.

## Rejected after verification

| Source | Result | Why not |
|---|---|---|
| RxNav Interaction API | HTTP 404 | Retired. Confirmed live, not from memory (D3). |
| Europe PMC, PubMed E-utilities | work, no key | Research abstracts are not consumer guidance. |
| openFDA `ndc` / `drugsfda` / `shortages` | work | Regulatory metadata; no employee question needs it. |
| WHO ICD-11 | HTTP 401 | Free, but OAuth for codes no employee sees. |
| CDSCO / Indian drug registries | no API | See architecture D14. |

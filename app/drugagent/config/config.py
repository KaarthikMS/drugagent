"""
Central configuration.

Every value that might need tuning, or that differs between environments,
lives here. Module-level constants are evaluated once at import time and
shared by all importers.
"""

from __future__ import annotations

import os
from typing import Final

# --------------------------------------------------------------------
# Service identity
# --------------------------------------------------------------------

SERVICE_NAME: Final = "pharma-health-assistant"

# --------------------------------------------------------------------
# Bedrock model
#
# Model ids here are INFERENCE PROFILE ids, not bare model ids. Most
# current models in ap-south-1 report inferenceTypesSupported =
# ["INFERENCE_PROFILE"] and reject the bare id with "on-demand
# throughput isn't supported".
#
# The `apac.` prefix keeps inference inside APAC regions. `global.`
# profiles (the only way to reach Claude Haiku 4.5+ in this region)
# route worldwide -- a data-residency choice, not a price one, and this
# system handles employee lab reports.
#
# Nova Lite is the development choice: cheapest with vision, so one
# model serves both chat and lab-report extraction. Tool-call routing
# across eight tools is its weak point; step 9 evaluation decides
# whether the release model changes. One constant, one swap.
# --------------------------------------------------------------------

BEDROCK_REGION: Final = os.getenv("BEDROCK_REGION", "ap-south-1")

MODEL_ID: Final = os.getenv("MODEL_ID", "apac.amazon.nova-lite-v1:0")

# Near-zero, not zero: stable clinical wording across identical
# questions matters more than sampling variety.
MODEL_MAX_TOKENS: Final = 2048
MODEL_TEMPERATURE: Final = 0.2

# Attached at invoke time so the guardrail can be rotated without a
# redeploy. Unset in local dev -- the Python safety layer still runs.
GUARDRAIL_ID: Final = os.getenv("GUARDRAIL_ID")
GUARDRAIL_VERSION: Final = os.getenv("GUARDRAIL_VERSION", "DRAFT")

# --------------------------------------------------------------------
# Upstream APIs
#
# All four are public US government services. No API key is required at
# development volumes; openFDA raises the rate limit if one is supplied.
# Every URL below was verified live, with a nonsense control, before it
# was written here -- see probes/.
# --------------------------------------------------------------------

RXNORM_BASE_URL: Final = "https://rxnav.nlm.nih.gov/REST"

# Same host as RxNorm, different service. RxClass answers "what class is
# this drug in" and "what drugs are in this class" from maintained
# terminologies (ATC, SNOMED, MeSH). Label interaction text names
# classes -- "NSAIDs" -- far more often than it names individual drugs,
# so class membership has to come from somewhere authoritative rather
# than a hand-kept list in our own code.
RXCLASS_BASE_URL: Final = "https://rxnav.nlm.nih.gov/REST/rxclass"

# Autocomplete-style lookup services. The lab pipeline needs these: a
# report prints "Hemoglobin", and MedlinePlus Connect needs a LOINC
# code. Nothing else in the stack maps text to that code.
CLINICALTABLES_BASE_URL: Final = "https://clinicaltables.nlm.nih.gov/api"

OPENFDA_LABEL_URL: Final = "https://api.fda.gov/drug/label.json"
OPENFDA_EVENT_URL: Final = "https://api.fda.gov/drug/event.json"
OPENFDA_API_KEY: Final = os.getenv("OPENFDA_API_KEY")  # optional

# PUG-REST serves identifiers and computed properties. Hazard data
# (GHS) lives only in PUG-View, which is a different base path with a
# different response shape -- they are not interchangeable.
PUBCHEM_REST_URL: Final = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_VIEW_URL: Final = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"

# The health-topic search answers XML only -- there is no JSON option.
# Connect does return JSON, but only when asked explicitly.
MEDLINEPLUS_SEARCH_URL: Final = "https://wsearch.nlm.nih.gov/ws/query"
MEDLINEPLUS_CONNECT_URL: Final = "https://connect.medlineplus.gov/service"

# OID for LOINC, required by Connect to say which coding system a lab
# test code belongs to.
LOINC_OID: Final = "2.16.840.1.113883.6.1"

# --------------------------------------------------------------------
# HTTP behaviour
#
# Read timeout is generous because openFDA label sections are large: a
# single drug_interactions section runs to ~6.5k characters, and an
# interaction query fetches two of them.
# --------------------------------------------------------------------

HTTP_CONNECT_TIMEOUT: Final = 5.0
HTTP_READ_TIMEOUT: Final = 20.0
HTTP_MAX_CONNECTIONS: Final = 20
HTTP_MAX_KEEPALIVE: Final = 10

RETRY_MAX_ATTEMPTS: Final = 3
RETRY_BACKOFF_MULTIPLIER: Final = 1.0
RETRY_BACKOFF_MIN: Final = 1.0
RETRY_BACKOFF_MAX: Final = 5.0

USER_AGENT: Final = f"{SERVICE_NAME}/1.0"

# --------------------------------------------------------------------
# openFDA label sections
#
# Field names verified against a live response. These are the sections
# that exist on a label and that we are permitted to ground answers in.
# --------------------------------------------------------------------

SECTION_INDICATIONS: Final = "indications_and_usage"
SECTION_DOSAGE: Final = "dosage_and_administration"
SECTION_CONTRAINDICATIONS: Final = "contraindications"
SECTION_WARNINGS: Final = "warnings_and_cautions"
SECTION_BOXED_WARNING: Final = "boxed_warning"
SECTION_ADVERSE: Final = "adverse_reactions"
SECTION_INTERACTIONS: Final = "drug_interactions"
SECTION_OVERDOSAGE: Final = "overdosage"

# --------------------------------------------------------------------
# Section presets
#
# Maps a kind of question to the label sections worth retrieving for it.
#
# This is a real trade-off, not boilerplate. Each extra section is more
# grounding for the model but also more tokens, more latency and more
# cost -- sections run to thousands of characters each. Too few and the
# model has no basis for the answer and will fall back on its own
# recall; too many and every query pays for text nobody reads.
#
# The rule applied below: include a section when its ABSENCE would make
# the answer unsafe, not when its presence would make it richer.
#
# boxed_warning appears in all three. It is the most serious warning a
# label carries, it is short, and an answer that omits it while quoting
# the same label is an answer that looks complete and is not.
#
# Only the sections a preset actually uses are named here. `description`,
# `mechanism_of_action`, `pregnancy`, `pediatric_use` and `geriatric_use`
# were declared and never referenced -- a constant nothing reads is a
# decision nobody made. Add one back beside the preset that needs it.
# --------------------------------------------------------------------

SECTION_PRESETS: Final[dict[str, tuple[str, ...]]] = {
    # "What is metformin for, and how is it taken?"
    # Contraindications included because "what is it used for" and "may
    # I use it" are one question in the user's head, and the answer that
    # covers only the first invites the second to be assumed.
    "drug_info": (
        SECTION_BOXED_WARNING,
        SECTION_INDICATIONS,
        SECTION_DOSAGE,
        SECTION_CONTRAINDICATIONS,
    ),
    # "What happens if I take too much?"
    # adverse_reactions is the largest section on most labels and is
    # included anyway: overdose questions are answered by what the drug
    # does in excess, and `overdosage` alone is thin on OTC labels --
    # acetaminophen's runs to 243 characters (see probes/FINDINGS.md).
    "toxicity": (
        SECTION_BOXED_WARNING,
        SECTION_OVERDOSAGE,
        SECTION_WARNINGS,
        SECTION_ADVERSE,
    ),
    # "Can I take these together?"
    # Narrow on purpose. Two labels are fetched per query and
    # drug_interactions alone runs to ~6,500 characters each, so this
    # preset is the one that most needs span extraction rather than
    # whole sections.
    "interaction": (
        SECTION_BOXED_WARNING,
        SECTION_INTERACTIONS,
        SECTION_CONTRAINDICATIONS,
    ),
}

# --------------------------------------------------------------------
# Truncation
#
# Applied per section before text reaches the model, so that one very
# long label cannot dominate the context window.
# --------------------------------------------------------------------

MAX_SECTION_CHARS: Final = 4000

# --------------------------------------------------------------------
# Input bounds
#
# An unbounded prompt is a cost and a latency problem before it is a
# security one: every character is paid for on every turn it stays in
# context. 4,000 characters is roughly a full lab panel with headers,
# which is the longest legitimate input this system takes.
#
# The limit is enforced in domain/, not in the web layer, so it holds
# for every caller -- the dashboard, `agentcore invoke`, and anything
# added later.
# --------------------------------------------------------------------

MAX_PROMPT_CHARS: Final = 4000

# --------------------------------------------------------------------
# Severity
# --------------------------------------------------------------------

ESCALATION_THRESHOLD: Final = "medium"

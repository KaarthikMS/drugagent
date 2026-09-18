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
ENVIRONMENT: Final = os.getenv("ENVIRONMENT", "dev")

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
VISION_MODEL_ID: Final = os.getenv("VISION_MODEL_ID", MODEL_ID)

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

# openFDA returns label text; DailyMed returns the version and publish
# date of the label that text came from. Citations need provenance, not
# just content.
DAILYMED_BASE_URL: Final = "https://dailymed.nlm.nih.gov/dailymed/services/v2"

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
SECTION_DESCRIPTION: Final = "description"
SECTION_MECHANISM: Final = "mechanism_of_action"
SECTION_PREGNANCY: Final = "pregnancy"
SECTION_PEDIATRIC: Final = "pediatric_use"
SECTION_GERIATRIC: Final = "geriatric_use"

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
# TODO(kaarthick): fill these in. See the discussion in chat.
# --------------------------------------------------------------------

SECTION_PRESETS: Final[dict[str, tuple[str, ...]]] = {
    "drug_info": (),
    "toxicity": (),
    "interaction": (),
}

# --------------------------------------------------------------------
# Truncation
#
# Applied per section before text reaches the model, so that one very
# long label cannot dominate the context window.
# --------------------------------------------------------------------

MAX_SECTION_CHARS: Final = 4000

# --------------------------------------------------------------------
# Severity
# --------------------------------------------------------------------

ESCALATION_THRESHOLD: Final = "medium"

# --------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------

MEMORY_TTL_DAYS: Final = 30
MEMORY_MAX_TURNS: Final = 10

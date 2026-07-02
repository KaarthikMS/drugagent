from agents.drug_info_agent import get_drug_info_agent
from agents.interaction_agent import get_interaction_agent
from agents.toxicology_agent import get_toxicology_agent

AGENT_REGISTRY = {
    "drug": get_drug_info_agent,
    "toxicity": get_toxicology_agent,
    "interaction": get_interaction_agent,
}

from dataclasses import dataclass

from observability import logger, tracer
from orchestrator.intent_classifier import IntentClassifier
from orchestrator.registry import AGENT_REGISTRY


@dataclass
class OrchestratorResult:
    intent: str
    response: str


class AgentOrchestrator:
    def __init__(self):
        self.classifier = IntentClassifier()

    def select_agents(self, question):
        intents = self.classifier.classify(question)
        agents = []
        for intent in intents:
            factory = AGENT_REGISTRY.get(intent)
            if factory:
                agents.append(factory())
        return agents

    async def invoke(self, question: str) -> str:
        intents = self.classifier.classify(question)

        with tracer.start_as_current_span("Agent Orchestrator") as span:
            span.set_attribute("orchestrator.intent_count", len(intents))
            span.set_attribute("orchestrator.question_length", len(question))

            results: list[OrchestratorResult] = []

            for intent in intents:
                factory = AGENT_REGISTRY.get(intent)
                if not factory:
                    continue

                agent = factory()
                with tracer.start_as_current_span(f"{intent.title()} Agent") as agent_span:
                    agent_span.set_attribute("agent.intent", intent)
                    response = await agent.invoke(question)
                    results.append(OrchestratorResult(intent=intent, response=response))

            if not results:
                return "I could not determine a relevant pharmaceutical specialist for that question."

            if len(results) == 1:
                return results[0].response

            return "\n\n".join(
                f"[{result.intent.upper()}]\n{result.response}"
                for result in results
            )

    async def invoke_stream(self, question: str):
        response = await self.invoke(question)
        yield response

"""
Retrieval interface for prose sources.

Conditions and symptoms are the one genuine prose case in this system
(D2). Everything else has a key -- a drug name, an rxcui, a CID, a LOINC
code -- and wants an index. Prose wants either a search API or
embeddings, and which one is right here is an empirical question that
has not been measured yet.

So the decision is deferred behind this interface rather than guessed at:

    MedlinePlusRetriever   live API. No ingestion, no idle cost, content
                           stays current. Recall is weaker than
                           embeddings over the same corpus.

    (future) S3 Vectors    if evaluation shows MedlinePlus recall is
                           inadequate. Purpose-built, roughly an order
                           of magnitude cheaper than OpenSearch
                           Serverless, higher latency -- irrelevant for
                           chat.

Swapping backends means writing one class here. Nothing above this layer
knows which one it is talking to, which is the entire point: OpenSearch
Serverless bills on provisioned capacity whether queried or not, and
that is not a defensible line item before the cheaper option has been
measured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from clients.medlineplus import MedlinePlusClient


@dataclass(frozen=True)
class Passage:
    """A retrieved span of prose, with somewhere to point at for it.

    `text` is what the model may use; `url` is what the answer cites.
    Both are required, because a passage without a source cannot be
    cited and an answer that cannot be cited cannot be given
    (principle 2).
    """

    text: str
    title: str
    url: str
    score: float | None = None


class Retriever(Protocol):
    """What the condition and symptom tools depend on. Nothing more."""

    async def search(self, query: str, limit: int = 3) -> list[Passage]: ...


class MedlinePlusRetriever:
    """Live-API retrieval. The current implementation."""

    def __init__(self, client: MedlinePlusClient | None = None) -> None:
        self._client = client or MedlinePlusClient()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, limit: int = 3) -> list[Passage]:
        """Empty list means no grounding was found.

        The caller must then say the source is unavailable rather than
        answer from model recall -- degrade to "I cannot answer", never
        to an ungrounded answer.
        """
        topics = await self._client.search_topics(query, limit=limit)
        return [
            Passage(text=topic.summary, title=topic.title, url=topic.url)
            for topic in topics
            if topic.summary
        ]

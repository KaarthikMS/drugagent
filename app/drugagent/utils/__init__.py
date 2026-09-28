"""
Upstream API clients.

Each client owns one pooled connection to one source. `Clients` holds
them together so the runtime creates them once and closes them once --
creating a client per request throws away connection pooling and TLS
session reuse, which on these APIs costs more than the request itself.

Nothing here contains logic. Clients fetch and shape; decisions live in
domain/, which has no network and no model and can be tested without
either.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from utils.clinicaltables import ClinicalTablesClient
from utils.medlineplus import MedlinePlusClient
from utils.openfda import OpenFdaClient
from utils.pubchem import PubChemClient
from utils.retrieval import MedlinePlusRetriever, Passage, Retriever
from utils.rxclass import RxClassClient
from utils.rxnorm import RxNormClient

__all__ = [
    "Clients",
    "ClinicalTablesClient",
    "MedlinePlusClient",
    "MedlinePlusRetriever",
    "OpenFdaClient",
    "Passage",
    "PubChemClient",
    "Retriever",
    "RxClassClient",
    "RxNormClient",
]


@dataclass
class Clients:
    """Every upstream, constructed once per process."""

    rxnorm: RxNormClient = field(default_factory=RxNormClient)
    rxclass: RxClassClient = field(default_factory=RxClassClient)
    openfda: OpenFdaClient = field(default_factory=OpenFdaClient)
    pubchem: PubChemClient = field(default_factory=PubChemClient)
    medlineplus: MedlinePlusClient = field(default_factory=MedlinePlusClient)
    clinicaltables: ClinicalTablesClient = field(default_factory=ClinicalTablesClient)

    @property
    def retriever(self) -> Retriever:
        """Prose retrieval, backend-agnostic by design (D2)."""
        return MedlinePlusRetriever(self.medlineplus)

    async def aclose(self) -> None:
        """Close every connection pool.

        Gathered rather than awaited in sequence: one upstream being
        slow to close should not delay the others, and shutdown is not
        a place to discover a new source of latency.
        """
        await asyncio.gather(
            self.rxnorm.aclose(),
            self.rxclass.aclose(),
            self.openfda.aclose(),
            self.pubchem.aclose(),
            self.medlineplus.aclose(),
            self.clinicaltables.aclose(),
        )

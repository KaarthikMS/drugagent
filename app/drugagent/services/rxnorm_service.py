"""
RxNorm Service

Provides access to the NIH RxNorm REST API.

Documentation:
https://lhncbc.nlm.nih.gov/RxNav/APIs/
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class RxNormService:
    BASE_URL = "https://rxnav.nlm.nih.gov/REST"

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
            headers={
                "Accept": "application/json",
                "User-Agent": "PharmaAgent/1.0",
            },
        )

    async def close(self):
        await self.client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=True,
    )
    async def _get(self, endpoint: str) -> dict[str, Any]:
        response = await self.client.get(f"{self.BASE_URL}/{endpoint}")
        response.raise_for_status()
        return response.json()

    async def find_rxcui(self, drug_name: str) -> dict:
        return await self._get(
            f"rxcui.json?name={drug_name}"
        )

    async def get_properties(self, rxcui: str) -> dict:
        return await self._get(
            f"rxcui/{rxcui}/properties.json"
        )

    async def get_related(self, rxcui: str) -> dict:
        return await self._get(
            f"rxcui/{rxcui}/related.json"
        )

    async def get_all_properties(self, drug_name: str) -> dict:
        rxcui = await self.find_rxcui(drug_name)

        ids = (
            rxcui.get("idGroup", {})
            .get("rxnormId", [])
        )

        if not ids:
            return {}

        return await self.get_properties(ids[0])
"""
DailyMed Service

Provides access to the NIH DailyMed REST API.

https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/

Responsibilities
----------------
- Search drugs
- Retrieve SPL metadata
- Retrieve drug label
- Normalize returned payload
- Handle retries
- Handle HTTP failures
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    retry,
   retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class DailyMedServiceError(Exception):
    """Base exception for DailyMed service."""


class DrugNotFoundError(DailyMedServiceError):
    """Raised when no drug exists."""


class DailyMedService:
    BASE_URL = "https://dailymed.nlm.nih.gov/dailymed/services/v2"

    def __init__(self) -> None:

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10,
                read=30,
                write=30,
                pool=30,
            ),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
            headers={
                "Accept": "application/json",
                "User-Agent": "PharmaAgent/1.0",
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=True,
    )
    async def _get(
        self,
        endpoint: str,
        params: dict | None = None,
    ) -> dict:

        url = f"{self.BASE_URL}/{endpoint}"

        logger.info("Calling DailyMed endpoint %s", endpoint)

        response = await self.client.get(
            url,
            params=params,
        )

        response.raise_for_status()

        return response.json()

    async def search_drug(
        self,
        drug_name: str,
    ) -> dict:

        payload = await self._get(
            "spls.json",
            {
                "drug_name": drug_name,
            },
        )

        data = payload.get("data", [])

        if not data:
            raise DrugNotFoundError(
                f"No DailyMed record found for '{drug_name}'"
            )

        return data[0]

    async def get_spl(
        self,
        set_id: str,
    ) -> dict:

        return await self._get(
            f"spls/{set_id}.json"
        )

    async def get_complete_drug_information(
        self,
        drug_name: str,
    ) -> dict[str, Any]:

        search = await self.search_drug(drug_name)

        set_id = search.get("setid")

        if not set_id:
            raise DailyMedServiceError(
                "DailyMed returned record without setid."
            )

        label = await self.get_spl(set_id)

        data = label.get("data", {})

        return {
            "drug_name": search.get("title"),
            "set_id": set_id,
            "spl_version": search.get("spl_version"),
            "published_date": search.get("published_date"),
            "manufacturer": data.get("labeler"),
            "product_type": data.get("product_type"),
            "route": data.get("route"),
            "active_ingredients": data.get("active_ingredients"),
            "boxed_warning": data.get("boxed_warning"),
            "indications": data.get(
                "indications_and_usage"
            ),
            "dosage": data.get(
                "dosage_and_administration"
            ),
            "contraindications": data.get(
                "contraindications"
            ),
            "warnings": data.get(
                "warnings"
            ),
            "adverse_reactions": data.get(
                "adverse_reactions"
            ),
            "drug_interactions": data.get(
                "drug_interactions"
            ),
            "pregnancy": data.get(
                "pregnancy"
            ),
            "lactation": data.get(
                "lactation"
            ),
            "pediatric_use": data.get(
                "pediatric_use"
            ),
            "geriatric_use": data.get(
                "geriatric_use"
            ),
            "mechanism_of_action": data.get(
                "mechanism_of_action"
            ),
            "pharmacodynamics": data.get(
                "pharmacodynamics"
            ),
            "pharmacokinetics": data.get(
                "pharmacokinetics"
            ),
        }

    async def get_indications(
        self,
        drug_name: str,
    ) -> dict:

        info = await self.get_complete_drug_information(
            drug_name
        )

        return {
            "drug": info["drug_name"],
            "indications": info["indications"],
        }

    async def get_dosage(
        self,
        drug_name: str,
    ) -> dict:

        info = await self.get_complete_drug_information(
            drug_name
        )

        return {
            "drug": info["drug_name"],
            "dosage": info["dosage"],
        }

    async def get_warnings(
        self,
        drug_name: str,
    ) -> dict:

        info = await self.get_complete_drug_information(
            drug_name
        )

        return {
            "drug": info["drug_name"],
            "warnings": info["warnings"],
            "boxed_warning": info["boxed_warning"],
            "contraindications": info["contraindications"],
        }

    async def get_adverse_reactions(
        self,
        drug_name: str,
    ) -> dict:

        info = await self.get_complete_drug_information(
            drug_name
        )

        return {
            "drug": info["drug_name"],
            "adverse_reactions": info["adverse_reactions"],
        }

    async def health_check(self) -> bool:
        try:
            await self._get("spls.json", {"pagesize": 1})
            return True
        except Exception:
            logger.exception("DailyMed health check failed")
            return False
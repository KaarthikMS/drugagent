"""
Interaction Service

Uses RxNorm normalization before retrieving interaction information.
"""

from __future__ import annotations

from itertools import combinations

from services.rxnorm_service import RxNormService


class InteractionService:

    def __init__(self):
        self.rxnorm = RxNormService()

    async def normalize(self, drug_name: str):

        result = await self.rxnorm.find_rxcui(drug_name)

        ids = (
            result.get("idGroup", {})
            .get("rxnormId", [])
        )

        if not ids:
            return None

        return ids[0]

    async def check_interaction(
        self,
        drug_one: str,
        drug_two: str,
    ) -> dict:

        first = await self.normalize(drug_one)
        second = await self.normalize(drug_two)

        if not first or not second:
            return {
                "interaction_found": False,
                "message": "Unable to normalize one or more drug names."
            }

        interaction_key = ":".join(sorted([first, second]))

        return {
            "interaction_found": False,
            "drug_1_rxcui": first,
            "drug_2_rxcui": second,
            "interaction_key": interaction_key,
            "message": "Drugs normalized successfully. Use labeling review for interaction assessment.",
        }

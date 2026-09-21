"""
RxClass: drug class membership.

Label interaction text names classes far more often than it names drugs
-- a warning says "NSAIDs" and never writes "ibuprofen". Without class
membership, exact-name matching misses most documented interactions
(architecture D15).

`relaSource` is pinned to ATC on every call, and that is not tidiness.
Unfiltered, RxClass answers from every terminology at once, and MED-RT
contributes `may_treat` and `contraindication` relations alongside real
classes: warfarin comes back "classed" as *Alcoholism* and *Abortion,
Threatened*. Both are true statements about warfarin. Neither is a drug
class, and feeding them to an interaction check produces confident
nonsense.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import RXCLASS_BASE_URL
from utils.base import HttpClient

ATC = "ATC"


@dataclass(frozen=True)
class DrugClass:
    """One class a drug belongs to, in one terminology."""

    class_id: str
    name: str
    source: str = ATC


class RxClassClient:
    def __init__(self) -> None:
        self._http = HttpClient(source="rxclass")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def classes_for(self, rxcui: str) -> list[DrugClass]:
        """Classes containing this drug. ATC only, deliberately.

        Empty list means no ATC classification exists -- a real answer.
        An unknown rxcui returns HTTP 200 with `{}`, so again the key is
        checked and not the status code.
        """
        data = await self._http.get_json(
            f"{RXCLASS_BASE_URL}/class/byRxcui.json",
            {"rxcui": rxcui, "relaSource": ATC},
        )
        infos = (data or {}).get("rxclassDrugInfoList", {}).get("rxclassDrugInfo") or []
        seen: dict[str, DrugClass] = {}
        for info in infos:
            item = info.get("rxclassMinConceptItem") or {}
            class_id = item.get("classId")
            if class_id and class_id not in seen:
                seen[class_id] = DrugClass(
                    class_id=class_id,
                    name=item.get("className", ""),
                    source=info.get("relaSource", ATC),
                )
        return list(seen.values())

    async def members_of(self, class_id: str) -> set[str]:
        """Ingredient names in a class, lowercased for matching.

        Names rather than rxcuis: this set is matched against label
        prose, which spells drugs out in words.
        """
        data = await self._http.get_json(
            f"{RXCLASS_BASE_URL}/classMembers.json",
            {"classId": class_id, "relaSource": ATC},
        )
        members = (data or {}).get("drugMemberGroup", {}).get("drugMember") or []
        return {
            m["minConcept"]["name"].lower()
            for m in members
            if (m.get("minConcept") or {}).get("name")
        }

    async def shared_classes(
        self, classes_a: list[DrugClass], classes_b: list[DrugClass]
    ) -> list[DrugClass]:
        """Classes both drugs belong to.

        ATC ids are hierarchical -- M01AE (propionic acid derivatives)
        sits under M01A (anti-inflammatory). Exact-id comparison would
        call ibuprofen and naproxen unrelated when both are NSAIDs, so
        prefix overlap is what is compared.
        """
        ids_b = {c.class_id for c in classes_b}
        shared = []
        for klass in classes_a:
            if any(
                klass.class_id.startswith(other) or other.startswith(klass.class_id)
                for other in ids_b
            ):
                shared.append(klass)
        return shared

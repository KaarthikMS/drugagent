"""
DailyMed: label provenance.

openFDA returns what a label says. DailyMed returns which version of
that label said it, and when it was published. A citation without a
version and a date is a citation to a moving target -- labels are
revised, and an answer quoted from one revision does not necessarily
hold in the next.
"""

from __future__ import annotations

from dataclasses import dataclass

from clients.base import HttpClient
from config import DAILYMED_BASE_URL

SPL_URL = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"


@dataclass(frozen=True)
class SplRef:
    """A citable, dated reference to one label."""

    set_id: str
    title: str
    version: int | None
    published: str | None

    @property
    def url(self) -> str:
        return SPL_URL.format(set_id=self.set_id)


class DailyMedClient:
    def __init__(self) -> None:
        self._http = HttpClient(source="dailymed")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def find_spl(self, drug_name: str) -> SplRef | None:
        """Most recent label for a drug name, or None."""
        data = await self._http.get_json(
            f"{DAILYMED_BASE_URL}/spls.json", {"drug_name": drug_name, "pagesize": 1}
        )
        records = (data or {}).get("data") or [] if isinstance(data, dict) else []
        if not records:
            return None
        record = records[0]
        return SplRef(
            set_id=record.get("setid", ""),
            title=record.get("title", ""),
            version=record.get("spl_version"),
            published=record.get("published_date"),
        )

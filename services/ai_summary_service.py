# services/ai_summary_service.py
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from notion_client import Client
from pydantic import BaseModel

logger = logging.getLogger("ai_summary")


class WeeklyPriorityItem(BaseModel):
    type: Optional[str] = None
    name: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    period: Optional[str] = None
    notion_page_id: Optional[str] = None
    notion_url: Optional[str] = None


class AISummaryService:
    """
    Čist worker za AI SUMMARY DATABASE (Notion).

    - čita Weekly priority stavke iz AI Summary DB
    - ne radi nikakav write / side-effect
    """

    def __init__(self, api_key: str, db_id: str) -> None:
        if not api_key:
            raise ValueError("NOTION_API_KEY is missing")
        if not db_id:
            raise ValueError("NOTION_AI_SUMMARY_DB_ID is missing")

        self._client = Client(auth=api_key)
        self._db_id = db_id

    # ----------------- helpers -----------------

    @staticmethod
    def _extract_text(prop: Dict[str, Any]) -> str:
        t = prop.get("type")

        if t == "title":
            arr = prop.get("title") or []
            return "".join(part.get("plain_text", "") for part in arr).strip()

        if t == "rich_text":
            arr = prop.get("rich_text") or []
            return "".join(part.get("plain_text", "") for part in arr).strip()

        if t in ("select", "status"):
            opt = prop.get(t)
            if isinstance(opt, dict):
                return (opt.get("name") or "").strip()

        if t == "multi_select":
            arr = prop.get("multi_select") or []
            names = [x.get("name", "") for x in arr if isinstance(x, dict)]
            return ", ".join([n for n in names if n]).strip()

        if t == "date":
            val = prop.get("date") or {}
            start = val.get("start")
            end = val.get("end")
            if start and end and start != end:
                return f"{start} — {end}"
            return start or ""

        if t == "number":
            num = prop.get("number")
            return "" if num is None else str(num)

        # fallback na string
        return str(prop.get(t) or "").strip()

    @staticmethod
    def _pick_first(props: Dict[str, Any], names: List[str]) -> Optional[str]:
        for n in names:
            if n in props:
                return AISummaryService._extract_text(props[n]) or None
        return None

    # ----------------- public API -----------------

    def get_this_week_priorities(self, limit: int = 20) -> List[WeeklyPriorityItem]:
        """
        Vraća listu Weekly priority stavki iz AI SUMMARY DB.

        Primarno:
        - filtrira po last_edited_time = this_week (Notion timestamp filter)

        Fallback:
        - ako nema ničega za ovu sedmicu, uzima zadnjih N zapisa bez filtera,
          sortiranih po last_edited_time desc.
        """
        if not self._db_id:
            return []

        sorts = [
            {
                "timestamp": "last_edited_time",
                "direction": "descending",
            }
        ]

        try:
            # Primarni upit – samo zapisi uređeni ove sedmice
            response = self._client.databases.query(
                database_id=self._db_id,
                page_size=limit,
                filter={
                    "timestamp": "last_edited_time",
                    "last_edited_time": {"this_week": {}},
                },
                sorts=sorts,
            )
            pages = response.get("results", [])

            # Fallback – nema ništa “this_week”: uzmi zadnje zapise bez datumske restrikcije
            if not pages:
                response = self._client.databases.query(
                    database_id=self._db_id,
                    page_size=limit,
                    sorts=sorts,
                )
                pages = response.get("results", [])

        except Exception as exc:
            logger.exception("Failed querying AI SUMMARY DB: %s", exc)
            return []

        results: List[WeeklyPriorityItem] = []

        for page in pages:
            if not isinstance(page, dict):
                continue

            props: Dict[str, Any] = page.get("properties") or {}

            # Name = prvi title property
            name: Optional[str] = None
            for _, prop_val in props.items():
                if isinstance(prop_val, dict) and prop_val.get("type") == "title":
                    name = self._extract_text(prop_val)
                    if name:
                        break

            type_val = self._pick_first(props, ["Tip", "Type", "Category"])
            status = self._pick_first(props, ["Status"])
            priority = self._pick_first(props, ["Prioritet", "Priority"])
            period = self._pick_first(props, ["Period", "Due", "Due / Period", "Week"])

            results.append(
                WeeklyPriorityItem(
                    type=type_val or "-",
                    name=name or "-",
                    status=status or "-",
                    priority=priority or "-",
                    period=period or "-",
                    notion_page_id=page.get("id"),
                    notion_url=page.get("url"),
                )
            )

        return results


# --------------- singleton accessor ---------------

_ai_summary_service: Optional[AISummaryService] = None


def get_ai_summary_service() -> AISummaryService:
    global _ai_summary_service

    if _ai_summary_service is not None:
        return _ai_summary_service

    api_key = os.getenv("NOTION_API_KEY")
    db_id = os.getenv("NOTION_AI_SUMMARY_DB_ID")

    _ai_summary_service = AISummaryService(
        api_key=api_key,  # type: ignore[arg-type]
        db_id=db_id,      # type: ignore[arg-type]
    )
    return _ai_summary_service

# routers/ai_summary_router.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services.ai_summary_service import (
    get_ai_summary_service,
    WeeklyPriorityItem,
)

router = APIRouter(
    prefix="/ceo",
    tags=["ceo-weekly-priority"],
)


@router.get("/weekly-priority-memory")
def get_weekly_priority_memory() -> dict:
    """
    API za WEEKLY PRIORITY MEMORY karticu na CEO dashboardu.

    - čita AI SUMMARY DB preko AISummaryService
    - READ-only, bez side-effects
    """
    try:
        service = get_ai_summary_service()
        items = service.get_this_week_priorities()
    except Exception as exc:
        # frontend treba da vidi realnu grešku, ne izmišljeno stanje
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load Weekly Priority Memory: {exc}",
        ) from exc

    # Frontend dobija čist JSON, spreman za tabelu
    return {
        "items": [item.dict() for item in items],
    }

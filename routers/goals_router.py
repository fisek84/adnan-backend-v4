from fastapi import APIRouter, HTTPException, Depends
import requests
import os
import json

from pydantic import BaseModel
from typing import Optional, List

from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate

# Will be injected from main.py
goals_service_global = None

router = APIRouter(prefix="/goals", tags=["Goals"])

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
GOALS_DB_ID = os.getenv("NOTION_GOALS_DB_ID")

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ==============================================
# FASTAPI DEPENDENCY
# ==============================================

def get_goals_service():
    if not goals_service_global:
        raise HTTPException(500, "GoalsService not initialized")
    return goals_service_global

# ==============================================
# RESPONSE MODEL
# ==============================================

class GoalResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    deadline: Optional[str]
    parent_id: Optional[str]
    priority: Optional[str]
    status: str
    progress: int
    children: List[str]

    class Config:
        from_attributes = True


# ==============================================
# CREATE GOAL (Notion)
# ==============================================

@router.post("/create")
def create_goal(payload: GoalCreate):
    try:
        notion_payload = {
            "parent": {"database_id": GOALS_DB_ID},
            "properties": {
                "Name": {
                    "title": [
                        {"text": {"content": payload.title}}
                    ]
                }
            }
        }

        url = "https://api.notion.com/v1/pages"
        resp = requests.post(url, headers=NOTION_HEADERS, data=json.dumps(notion_payload))

        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code,
                detail=resp.text
            )

        notion_data = resp.json()

        # Local create — optional
        if goals_service_global:
            goals_service_global.create_goal(payload)

        return {
            "status": "created",
            "notion_page_id": notion_data["id"],
            "notion_url": notion_data["url"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create goal: {e}")


# ==============================================
# UPDATE GOAL
# ==============================================

@router.patch("/{goal_id}")
def update_goal(goal_id: str, updates: GoalUpdate, goals_service=Depends(get_goals_service)):
    try:
        updated = goals_service.update_goal(goal_id, updates)
        return {"status": "updated", "goal": updated}
    except ValueError as e:
        raise HTTPException(404, str(e))


# ==============================================
# GET ALL GOALS (LOCAL BACKEND)
# ==============================================

@router.get("/all")
def get_all_local(goals_service=Depends(get_goals_service)):
    return {"goals": goals_service.get_all()}


# ==============================================
# NEW ROUTE FOR AI + PLUGIN
# ==============================================

@router.get("/goals/all")
async def get_all_goals(goals_service=Depends(get_goals_service)):
    return {"goals": goals_service.get_all()}
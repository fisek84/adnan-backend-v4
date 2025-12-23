from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ============================================================
# GOAL MODEL (Final, FIXED)
# ============================================================
class GoalModel(BaseModel):
    id: str
    notion_id: Optional[str] = None

    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None

    parent_id: Optional[str] = None  # OBAVEZNO
    priority: Optional[str] = None

    status: str
    progress: int = 0

    children: List[str] = []  # OBAVEZNO

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# TASK MODEL (Final, FIXED, NO DUPLICATES)
# ============================================================
class TaskModel(BaseModel):
    id: str
    notion_id: Optional[str] = Field(None, description="Notion page ID for sync/delete")

    # Basic fields
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None

    # Relations
    goal_id: Optional[str] = None

    # Meta
    priority: Optional[str] = None
    status: str
    order: int = 0

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        validate_assignment = True

    # --------------------------------------------------------
    # VALIDATORS (ONLY ONCE!)
    # --------------------------------------------------------
    @validator("deadline")
    def validate_deadline(cls, v):
        if v is None or v == "":
            return None
        try:
            datetime.fromisoformat(v)
        except ValueError:
            logger.error(f"Invalid deadline format: {v}")
            raise ValueError("Deadline must be ISO format YYYY-MM-DD")
        return v

    @validator("priority")
    def validate_priority(cls, v):
        if v is None:
            return None
        allowed = {"low", "medium", "high"}
        if v not in allowed:
            raise ValueError(f"Priority must be one of: {allowed}")
        return v

    @validator("status")
    def validate_status(cls, v):
        allowed = {"pending", "in_progress", "completed"}
        if v not in allowed:
            raise ValueError(f"Status must be one of: {allowed}")
        return v

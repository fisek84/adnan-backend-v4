from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    children: List[str] = Field(default_factory=list)  # OBAVEZNO

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
    )

    # --------------------------------------------------------
    # VALIDATORS (ONLY ONCE!)
    # --------------------------------------------------------
    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        try:
            datetime.fromisoformat(v)
        except ValueError:
            logger.error("Invalid deadline format: %s", v)
            raise ValueError("Deadline must be ISO format YYYY-MM-DD")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        allowed = {"low", "medium", "high"}
        if v not in allowed:
            raise ValueError(f"Priority must be one of: {allowed}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"pending", "in_progress", "completed"}
        if v not in allowed:
            raise ValueError(f"Status must be one of: {allowed}")
        return v

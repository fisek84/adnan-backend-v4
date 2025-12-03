from pydantic import BaseModel, Field, validator  # Dodajemo validator import
from typing import Optional
from datetime import datetime
import logging

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# GOAL MODEL (Final)
# ============================================================
class GoalModel(BaseModel):
    id: str
    notion_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    priority: Optional[str] = None
    status: str
    progress: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True  # Menjamo 'orm_mode' u 'from_attributes'


# ============================================================
# TASK MODEL (Final)
# ============================================================
class TaskModel(BaseModel):
    id: str
    notion_id: Optional[str] = Field(
        None, description="Notion page ID for sync/delete"
    )

    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None

    goal_id: Optional[str] = None
    priority: Optional[str] = None
    status: str
    order: int = 0

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        validate_assignment = True

    # --------------------------------------------------------
    # VALIDATORS
    # --------------------------------------------------------
    @validator("deadline")
    def validate_deadline(cls, v):
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except ValueError:
            logger.error(f"Invalid deadline format: {v}")
            raise ValueError("Deadline must be ISO format YYYY-MM-DD")
        logger.info(f"Valid deadline format: {v}")
        return v

    @validator("priority")
    def validate_priority(cls, v):
        if v is None:
            return v
        allowed = {"low", "medium", "high"}
        if v not in allowed:
            logger.error(f"Invalid priority value: {v}. Must be one of: {allowed}")
            raise ValueError(f"Priority must be one of: {allowed}")
        logger.info(f"Valid priority value: {v}")
        return v

    @validator("status")
    def validate_status(cls, v):
        allowed = {"pending", "in_progress", "completed"}
        if v not in allowed:
            logger.error(f"Invalid status value: {v}. Must be one of: {allowed}")
            raise ValueError(f"Status must be one of: {allowed}")
        logger.info(f"Valid status value: {v}")
        return v

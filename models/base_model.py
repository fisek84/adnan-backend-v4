from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime


# ============================================================
# GOAL MODEL (PRO)
# ============================================================
class GoalModel(BaseModel):
    id: str
    notion_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    parent_id: Optional[str] = None
    priority: Optional[str] = None
    status: str
    progress: int
    children: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        validate_assignment = True


# ============================================================
# TASK MODEL (PRO — REQUIRED FOR DELETE FIX)
# ============================================================
class TaskModel(BaseModel):
    id: str
    notion_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    goal_id: Optional[str] = None
    priority: Optional[str] = None
    status: str
    order: int = 0
    created_at: datetime
    updated_at: datetime

    # VALIDATIONS
    @validator("deadline")
    def validate_deadline(cls, v):
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except:
            raise ValueError("Deadline must be ISO format YYYY-MM-DD")
        return v

    @validator("priority")
    def validate_priority(cls, v):
        if v is None:
            return v
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

    class Config:
        from_attributes = True
        validate_assignment = True

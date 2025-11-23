from datetime import datetime
from pydantic import BaseModel, Field, validator
from typing import List, Optional


class GoalModel(BaseModel):
    """
    Core Goal object stored in memory and synced with Notion.
    Highly validated, structured, and API-safe.
    """

    id: str = Field(..., description="Unique Goal ID")
    title: str = Field(..., description="Goal title")
    description: Optional[str] = Field(
        "", description="Detailed description of the goal"
    )
    deadline: Optional[str] = Field(
        None,
        description="Deadline in ISO8601 format (YYYY-MM-DD)"
    )
    parent_id: Optional[str] = Field(
        None,
        description="ID of parent goal (if exists)"
    )
    priority: Optional[str] = Field(
        None,
        description="Priority level: low, medium, high"
    )
    status: str = Field(
        ..., description="Goal status: pending, in_progress, completed"
    )
    progress: int = Field(
        0, ge=0, le=100, description="Progress percentage (0–100)"
    )
    children: List[str] = Field(
        default_factory=list,
        description="IDs of child goals"
    )
    created_at: datetime = Field(
        ..., description="Timestamp when goal was created"
    )
    updated_at: datetime = Field(
        ..., description="Timestamp when goal was last updated"
    )

    # ---------------------------------------------------------
    # VALIDATIONS
    # ---------------------------------------------------------
    @validator("deadline")
    def validate_deadline(cls, v):
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except Exception:
            raise ValueError("Deadline must be in ISO format YYYY-MM-DD")
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
        orm_mode = True
        validate_assignment = True
        extra = "forbid"
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
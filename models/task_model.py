from datetime import datetime
from pydantic import BaseModel, Field, validator
from typing import Optional


class TaskModel(BaseModel):
    """
    Core Task model for Evolia Backend v4.
    - In-memory
    - Synced with Notion
    - Validated & structured
    """

    id: str = Field(..., description="Unique Task ID")
    title: str = Field(..., description="Task title")
    description: Optional[str] = Field(
        "", description="Task description"
    )
    goal_id: Optional[str] = Field(
        None, description="Linked goal ID"
    )
    deadline: Optional[str] = Field(
        None,
        description="Deadline in ISO8601 format (YYYY-MM-DD)"
    )
    priority: Optional[str] = Field(
        None,
        description="Priority: low, medium, high"
    )
    status: str = Field(
        "pending",
        description="Task status: pending, in_progress, completed"
    )
    order: int = Field(
        0, description="Sort order for tasks"
    )
    created_at: datetime = Field(
        ..., description="Timestamp when task was created"
    )
    updated_at: datetime = Field(
        ..., description="Timestamp when task was last updated"
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
        orm_mode = True
        validate_assignment = True
        extra = "forbid"
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
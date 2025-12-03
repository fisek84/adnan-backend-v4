from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime


class GoalUpdate(BaseModel):
    """
    Update model for Goal objects.
    All fields are optional — only provided ones will be updated.
    """

    title: Optional[str] = Field(
        None, description="Updated goal title"
    )

    description: Optional[str] = Field(
        None, description="Updated goal description"
    )

    deadline: Optional[str] = Field(
        None,
        description="Updated deadline in ISO8601 format (YYYY-MM-DD)"
    )

    parent_id: Optional[str] = Field(
        None,
        description="New parent goal relationship"
    )

    priority: Optional[str] = Field(
        None,
        description="Updated priority (low, medium, high)"
    )

    status: Optional[str] = Field(
        None,
        description="Updated status: pending, in_progress, completed"
    )

    progress: Optional[int] = Field(
        None,
        ge=0,
        le=100,
        description="Progress percentage (0–100)"
    )

    # -------------------------------------------
    # VALIDATIONS
    # -------------------------------------------

    @validator("deadline")
    def validate_deadline(cls, v):
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except Exception:
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
        if v is None:
            return v
        allowed = {"pending", "in_progress", "completed"}
        if v not in allowed:
            raise ValueError(f"Status must be one of: {allowed}")
        return v

    class Config:
        extra = "forbid"  # disallow unknown fields
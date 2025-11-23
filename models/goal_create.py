from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime


class GoalCreate(BaseModel):
    """
    Model for creating new Goal objects.
    Strict validation ensures clean data and stable sync with Notion.
    """

    title: str = Field(
        ...,
        description="Title of the goal"
    )

    description: Optional[str] = Field(
        "",
        description="Detailed description of the goal"
    )

    deadline: Optional[str] = Field(
        None,
        description="Deadline in ISO8601 format (YYYY-MM-DD)"
    )

    parent_id: Optional[str] = Field(
        None,
        description="Optional parent goal reference"
    )

    priority: Optional[str] = Field(
        None,
        description="Priority: low, medium, high"
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
        except ValueError:
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

    class Config:
        extra = "forbid"  # prevents accidental unknown fields
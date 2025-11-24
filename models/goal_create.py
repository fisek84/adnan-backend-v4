from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import Optional


class GoalCreate(BaseModel):
    """
    Input model for creating new Goal entries.
    Fully validated and safe for API + Notion sync.
    """

    title: str = Field(
        ...,
        description="Short title of the goal"
    )

    description: Optional[str] = Field(
        "",
        description="Optional long description of the goal"
    )

    deadline: Optional[str] = Field(
        None,
        description="Deadline in ISO8601 format (YYYY-MM-DD)"
    )

    why: Optional[str] = Field(
        None,
        description="Reason or purpose behind this goal"
    )

    context: Optional[str] = Field(
        None,
        description="Context or category (e.g. health, business, personal)"
    )

    priority: Optional[str] = Field(
        None,
        description="Priority level: low, medium, high"
    )

    parent_id: Optional[str] = Field(
        None,
        description="Optional parent goal reference (UUID or Notion ID)"
    )

    # ============================================================
    # VALIDATORS (Pydantic v2)
    # ============================================================

    @field_validator("deadline")
    def validate_deadline(cls, v):
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise ValueError("Deadline must be ISO format YYYY-MM-DD")
        return v

    @field_validator("priority")
    def validate_priority(cls, v):
        if v is None:
            return v
        allowed = {"low", "medium", "high"}
        if v not in allowed:
            raise ValueError(f"Priority must be one of: {allowed}")
        return v

    class Config:
        extra = "forbid"  # reject unknown fields
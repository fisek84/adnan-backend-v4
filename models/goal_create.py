from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import logging

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class GoalCreate(BaseModel):
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
            logger.error(f"Invalid deadline format: {v}")
            raise ValueError("Deadline must be ISO format YYYY-MM-DD")
        logger.info(f"Valid deadline format: {v}")
        return v

    @field_validator("priority")
    def validate_priority(cls, v):
        if v is None:
            return v
        allowed = {"low", "medium", "high"}
        if v not in allowed:
            logger.error(f"Invalid priority value: {v}. Must be one of: {allowed}")
            raise ValueError(f"Priority must be one of: {allowed}")
        logger.info(f"Valid priority value: {v}")
        return v

    class Config:
        extra = "forbid"  # reject unknown fields

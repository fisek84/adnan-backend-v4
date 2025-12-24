from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class GoalCreate(BaseModel):
    title: str = Field(..., description="Short title of the goal")

    description: Optional[str] = Field(
        "", description="Optional long description of the goal"
    )

    deadline: Optional[str] = Field(
        None, description="Deadline in ISO8601 format (YYYY-MM-DD)"
    )

    why: Optional[str] = Field(None, description="Reason or purpose behind this goal")

    context: Optional[str] = Field(
        None, description="Context or category (e.g. health, business, personal)"
    )

    priority: Optional[str] = Field(
        None, description="Priority level: low, medium, high"
    )

    parent_id: Optional[str] = Field(
        None, description="Optional parent goal reference (UUID or Notion ID)"
    )

    model_config = ConfigDict(extra="forbid")

    # ============================================================
    # VALIDATORS (Pydantic v2)
    # ============================================================

    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except ValueError:
            logger.error("Invalid deadline format: %s", v)
            raise ValueError("Deadline must be ISO format YYYY-MM-DD")
        logger.info("Valid deadline format: %s", v)
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"low", "medium", "high"}
        if v not in allowed:
            logger.error("Invalid priority value: %s. Must be one of: %s", v, allowed)
            raise ValueError(f"Priority must be one of: {allowed}")
        logger.info("Valid priority value: %s", v)
        return v

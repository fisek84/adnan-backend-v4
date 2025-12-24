from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class GoalUpdate(BaseModel):
    """
    Update model for Goal objects.
    All fields are optional — only provided ones will be updated.
    """

    title: Optional[str] = Field(None, description="Updated goal title")

    description: Optional[str] = Field(None, description="Updated goal description")

    deadline: Optional[str] = Field(
        None, description="Updated deadline in ISO8601 format (YYYY-MM-DD)"
    )

    parent_id: Optional[str] = Field(None, description="New parent goal relationship")

    priority: Optional[str] = Field(
        None, description="Updated priority (low, medium, high)"
    )

    status: Optional[str] = Field(
        None, description="Updated status: pending, in_progress, completed"
    )

    progress: Optional[int] = Field(
        None, ge=0, le=100, description="Progress percentage (0–100)"
    )

    model_config = ConfigDict(extra="forbid")

    # -------------------------------------------
    # VALIDATIONS
    # -------------------------------------------

    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except Exception:
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

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"pending", "in_progress", "completed"}
        if v not in allowed:
            logger.error("Invalid status value: %s. Must be one of: %s", v, allowed)
            raise ValueError(f"Status must be one of: {allowed}")
        logger.info("Valid status value: %s", v)
        return v

    @field_validator("progress")
    @classmethod
    def validate_progress(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v < 0 or v > 100:
            logger.error("Invalid progress value: %s. Must be between 0 and 100.", v)
            raise ValueError("Progress must be between 0 and 100.")
        logger.info("Valid progress value: %s", v)
        return v

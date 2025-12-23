from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
import logging  # Dodajemo logovanje

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
        if v is None:
            return v
        allowed = {"pending", "in_progress", "completed"}
        if v not in allowed:
            logger.error(f"Invalid status value: {v}. Must be one of: {allowed}")
            raise ValueError(f"Status must be one of: {allowed}")
        logger.info(f"Valid status value: {v}")
        return v

    @validator("progress")
    def validate_progress(cls, v):
        if v is None:
            return v
        if v < 0 or v > 100:
            logger.error(f"Invalid progress value: {v}. Must be between 0 and 100.")
            raise ValueError("Progress must be between 0 and 100.")
        logger.info(f"Valid progress value: {v}")
        return v

    class Config:
        extra = "forbid"  # disallow unknown fields

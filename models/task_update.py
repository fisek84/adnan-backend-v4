from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class TaskUpdate(BaseModel):
    """
    Update model for Task objects.
    All fields optional — only provided ones will be updated.
    """

    title: Optional[str] = Field(None, description="Updated title of the task")
    description: Optional[str] = Field(None, description="Updated task description")

    goal_id: Optional[str] = Field(
        None, description="Updated goal ID the task is linked to"
    )

    # 🔥 Needed for project -> task link updates
    project_id: Optional[str] = Field(
        None, description="Updated project ID the task belongs to"
    )

    deadline: Optional[str] = Field(
        None, description="Updated deadline (ISO8601 YYYY-MM-DD)"
    )
    priority: Optional[str] = Field(
        None, description="Task priority: low, medium, high"
    )
    status: Optional[str] = Field(
        None, description="Task status: pending, in_progress, completed"
    )

    # 🔥 Needed for sortable task lists
    order: Optional[int] = Field(None, description="Updated task sort order")

    handled_by: Optional[str] = Field(
        None, description="Updated responsible person (optional)"
    )

    model_config = ConfigDict(extra="forbid")

    # -------------------------------
    # VALIDATIONS
    # -------------------------------
    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        try:
            datetime.fromisoformat(value)
        except ValueError:
            logger.error("Invalid deadline format: %s", value)
            raise ValueError("Deadline must be ISO format YYYY-MM-DD")
        return value

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        allowed = {"low", "medium", "high"}
        if value not in allowed:
            logger.error(
                "Invalid priority value: %s. Must be one of: %s", value, allowed
            )
            raise ValueError(f"Priority must be one of: {allowed}")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        allowed = {"pending", "in_progress", "completed"}
        if value not in allowed:
            logger.error("Invalid status value: %s. Must be one of: %s", value, allowed)
            raise ValueError(f"Status must be one of: {allowed}")
        return value

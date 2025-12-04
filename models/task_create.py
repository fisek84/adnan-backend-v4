from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
import logging  # Add logging

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class TaskCreate(BaseModel):
    """
    Model for creating new Task objects.
    Provides strict validation to ensure data integrity.
    """

    title: str = Field(
        ...,
        description="Title of the new task"
    )

    description: Optional[str] = Field(
        "",
        description="Optional description for the task"
    )

    goal_id: Optional[str] = Field(
        None,
        description="Goal ID this task is associated with"
    )

    # 🔥 REQUIRED BY Projects → Tasks relation
    project_id: Optional[str] = Field(
        None,
        description="Project ID this task belongs to"
    )

    deadline: Optional[str] = Field(
        None,
        description="Deadline in ISO8601 format (YYYY-MM-DD)"
    )

    priority: Optional[str] = Field(
        None,
        description="Task priority: low, medium, high"
    )

    # Backend will assign default status ("pending") unless provided
    status: Optional[str] = Field(
        None,
        description="Task status (optional; backend sets default)"
    )

    # -------------------------------------------
    # VALIDATIONS
    # -------------------------------------------

    @validator("deadline")
    def validate_deadline(cls, v):
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)  # Validate ISO format
        except ValueError:
            logger.error(f"Invalid deadline format: {v}")
            raise ValueError("Deadline must be in ISO format YYYY-MM-DD")
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

    @validator("goal_id")
    def validate_goal_id(cls, v):
        if v is None:
            return v
        try:
            UUID(v)  # Ensuring that goal_id is a valid UUID string
        except ValueError:
            logger.error(f"Invalid goal_id format: {v}")
            raise ValueError("goal_id must be a valid UUID string")
        logger.info(f"Valid goal_id format: {v}")
        return v

    class Config:
        extra = "forbid"  # Reject unknown fields

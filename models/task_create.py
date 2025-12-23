from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class TaskCreate(BaseModel):
    title: str = Field(..., description="Title of the new task")
    description: Optional[str] = Field(
        "", description="Optional description for the task"
    )

    # NOW STRING, NOT UUID
    goal_id: Optional[str] = Field(
        None, description="Goal ID this task is associated with"
    )

    project_id: Optional[str] = Field(
        None, description="Project ID this task belongs to"
    )
    deadline: Optional[str] = Field(
        None, description="Deadline in ISO8601 format (YYYY-MM-DD)"
    )
    priority: Optional[str] = Field(
        None, description="Task priority: low, medium, high"
    )
    status: Optional[str] = Field(
        None, description="Task status (optional; backend sets default)"
    )

    @validator("deadline")
    def validate_deadline(cls, v):
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise ValueError("Deadline must be in ISO format YYYY-MM-DD")
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

    @validator("goal_id")
    def validate_goal_id(cls, v):
        if v is None:
            return v

        if not isinstance(v, str):
            raise ValueError("goal_id must be a string")

        if len(v.strip()) == 0:
            raise ValueError("goal_id cannot be empty")

        logger.info(f"Accepted goal_id (string): {v}")
        return v

    class Config:
        extra = "forbid"

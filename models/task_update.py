from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime


class TaskUpdate(BaseModel):
    """
    Update model for Task objects.
    All fields are optional — 
    only provided ones will be updated.
    """

    title: Optional[str] = Field(
        None, description="Updated title of the task"
    )
    description: Optional[str] = Field(
        None, description="Updated task description"
    )
    goal_id: Optional[str] = Field(
        None, description="Goal to which this task is assigned"
    )
    deadline: Optional[str] = Field(
        None,
        description="Updated deadline in ISO8601 format (YYYY-MM-DD)"
    )
    priority: Optional[str] = Field(
        None,
        description="Task priority level",
    )
    status: Optional[str] = Field(
        None,
        description="Task status: pending, in_progress, or completed",
    )

    # -------------------------------------------
    # VALIDATIONS
    # -------------------------------------------

    @validator("deadline")
    def validate_deadline(cls, value):
        if value is None:
            return value
        try:
            datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("Deadline must be ISO format YYYY-MM-DD")
        return value

    @validator("priority")
    def validate_priority(cls, value):
        if value is None:
            return value

        allowed = {"low", "medium", "high"}
        if value not in allowed:
            raise ValueError(f"Priority must be one of: {allowed}")
        return value

    @validator("status")
    def validate_status(cls, value):
        if value is None:
            return value

        allowed = {"pending", "in_progress", "completed"}
        if value not in allowed:
            raise ValueError(f"Status must be one of: {allowed}")
        return value
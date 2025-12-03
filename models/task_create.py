from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime


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

    class Config:
        extra = "forbid"

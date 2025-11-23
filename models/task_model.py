from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime


class TaskModel(BaseModel):
    id: str = Field(..., description="Unique task identifier")
    title: str = Field(..., description="Task title")
    description: Optional[str] = Field(
        "", description="Optional task description"
    )
    goal_id: Optional[str] = Field(
        None, description="ID of the Goal this task is linked to"
    )
    deadline: Optional[str] = Field(
        None, description="Deadline in ISO8601 format (YYYY-MM-DD)"
    )
    priority: Optional[str] = Field(
        None, description="Task priority: low, medium, high"
    )
    status: str = Field(
        ..., description="Task status: pending, in_progress, completed"
    )
    created_at: datetime = Field(
        ..., description="Timestamp when task was created"
    )
    updated_at: datetime = Field(
        ..., description="Timestamp when task was last updated"
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

    @validator("status")
    def validate_status(cls, v):
        allowed = {"pending", "in_progress", "completed"}
        if v not in allowed:
            raise ValueError(f"Status must be one of: {allowed}")
        return v

    class Config:
        orm_mode = True
        validate_assignment = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
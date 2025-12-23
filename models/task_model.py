from datetime import datetime
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class TaskCompensationContract(BaseModel):
    """
    Compensation / Rollback declaration for a TASK.
    FAZA 6 — KORAK 3
    """

    enabled: bool = Field(False, description="Is compensation supported for this task")

    compensation_type: Optional[str] = Field(
        None, description="Type of compensation (rollback, revert, cleanup, etc.)"
    )

    payload: Optional[Dict[str, Any]] = Field(
        None, description="Payload required to perform compensation"
    )

    class Config:
        extra = "forbid"


class TaskExecutionContract(BaseModel):
    """
    Execution Contract between TASK and AGENT.
    FAZA 6 — KORAK 1
    """

    agent_id: Optional[str] = Field(None, description="Assigned agent ID")
    agent_type: Optional[str] = Field(
        None, description="Agent type (notion, email, human, etc.)"
    )
    capability: Optional[str] = Field(None, description="Capability used for execution")

    execution_status: str = Field(
        "not_started",
        description="Execution status: not_started, running, success, failed",
    )

    started_at: Optional[datetime] = Field(
        None, description="Execution start timestamp"
    )
    finished_at: Optional[datetime] = Field(
        None, description="Execution finish timestamp"
    )

    error: Optional[str] = Field(None, description="Execution error if failed")

    # =========================
    # COMPENSATION (FAZA 6)
    # =========================
    compensation: TaskCompensationContract = Field(
        default_factory=TaskCompensationContract,
        description="Compensation / rollback declaration",
    )

    @validator("execution_status")
    def validate_execution_status(cls, v):
        allowed = {"not_started", "running", "success", "failed"}
        if v not in allowed:
            raise ValueError(f"Execution status must be one of: {allowed}")
        return v

    class Config:
        extra = "forbid"
        json_encoders = {datetime: lambda v: v.isoformat()}


class TaskModel(BaseModel):
    """
    Task model for Evolia Backend v4.
    """

    # Core identity
    id: str = Field(..., description="Unique Task ID")
    notion_id: Optional[str] = Field(None, description="Notion page ID")
    notion_url: Optional[str] = Field(None, description="Public Notion URL of the task")

    # Main fields
    title: str = Field(..., description="Task title")
    description: Optional[str] = Field("", description="Optional task description")

    goal_id: Optional[str] = Field(None, description="Linked goal ID")

    project_id: Optional[str] = Field(None, description="Linked project ID")

    deadline: Optional[str] = Field(None, description="Deadline (ISO8601 YYYY-MM-DD)")
    priority: Optional[str] = Field(
        None, description="Task priority: low, medium, high"
    )
    status: str = Field(
        "pending", description="Task status: pending, in_progress, completed"
    )
    order: int = Field(0, description="Sort order for tasks")

    # =========================
    # EXECUTION CONTRACT (FAZA 6)
    # =========================
    execution: TaskExecutionContract = Field(
        default_factory=TaskExecutionContract,
        description="Execution contract and accountability data",
    )

    created_at: datetime = Field(..., description="Task creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    @validator("deadline")
    def validate_deadline(cls, v):
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except Exception:
            logger.error(f"Invalid deadline format: {v}")
            raise ValueError("Deadline must be ISO format YYYY-MM-DD")
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
        from_attributes = True
        validate_assignment = True
        extra = "forbid"
        json_encoders = {datetime: lambda v: v.isoformat()}

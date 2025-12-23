from datetime import datetime
from pydantic import BaseModel, validator
from typing import Optional, List
import logging  # Dodajemo logovanje

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ProjectCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    status: Optional[str] = "Active"
    category: Optional[str] = None
    priority: Optional[str] = None

    start_date: Optional[str] = None
    deadline: Optional[str] = None

    project_type: Optional[str] = None
    summary: Optional[str] = ""
    next_step: Optional[str] = ""

    # Primary goal expected by backend + NotionSyncService
    primary_goal_id: Optional[str] = None

    parent_id: Optional[str] = None

    agents: List[str] = []
    tasks: List[str] = []

    handled_by: Optional[str] = None

    # Required by ProjectsService.create_project()
    progress: Optional[int] = 0

    # ======================================================
    # 🔥 VALIDATION: Title cannot be empty
    # ======================================================
    @validator("title")
    def title_cannot_be_empty(cls, v):
        if not v or v.strip() == "":
            logger.error("Project title cannot be empty.")
            raise ValueError("Project must have a title.")
        logger.info(f"Project title validated: {v}")
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

    @validator("deadline")
    def validate_deadline(cls, v):
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except ValueError:
            logger.error(f"Invalid deadline format: {v}")
            raise ValueError("Deadline must be in ISO format YYYY-MM-DD")
        logger.info(f"Valid deadline format: {v}")
        return v

    class Config:
        extra = "forbid"

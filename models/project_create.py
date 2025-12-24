from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    agents: List[str] = Field(default_factory=list)
    tasks: List[str] = Field(default_factory=list)

    handled_by: Optional[str] = None

    # Required by ProjectsService.create_project()
    progress: Optional[int] = 0

    model_config = ConfigDict(extra="forbid")

    # ======================================================
    # 🔥 VALIDATION: Title cannot be empty
    # ======================================================
    @field_validator("title")
    @classmethod
    def title_cannot_be_empty(cls, v: str) -> str:
        if not v or v.strip() == "":
            logger.error("Project title cannot be empty.")
            raise ValueError("Project must have a title.")
        logger.info("Project title validated: %s", v)
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

    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except ValueError:
            logger.error("Invalid deadline format: %s", v)
            raise ValueError("Deadline must be in ISO format YYYY-MM-DD")
        logger.info("Valid deadline format: %s", v)
        return v

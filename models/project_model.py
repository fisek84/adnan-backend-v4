from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ProjectModel(BaseModel):
    id: str
    notion_id: Optional[str]

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

    # 🔥 unified naming across all services
    primary_goal_id: Optional[str] = None

    parent_id: Optional[str] = None

    agents: List[str] = Field(default_factory=list)
    tasks: List[str] = Field(default_factory=list)

    handled_by: Optional[str] = None

    # 🔥 required by ProjectsService, NotionSyncService, to_dict()
    progress: Optional[int] = 0

    created_at: datetime
    updated_at: datetime

    # ------------------------------------------------------
    # CONFIGURATION (Pydantic v2)
    # ------------------------------------------------------
    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        extra="forbid",
    )

    @classmethod
    def log_project_creation(cls, project: "ProjectModel") -> None:
        logger.info("Creating project: %s with ID: %s", project.title, project.id)
        logger.debug("Project details: %s", project.model_dump())

    @classmethod
    def log_project_update(cls, project: "ProjectModel") -> None:
        logger.info("Updating project: %s with ID: %s", project.title, project.id)
        logger.debug("Updated project details: %s", project.model_dump())

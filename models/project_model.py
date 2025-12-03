from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import logging  # Dodajemo logovanje

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

    agents: List[str] = []
    tasks: List[str] = []

    handled_by: Optional[str] = None

    # 🔥 required by ProjectsService, NotionSyncService, to_dict()
    progress: Optional[int] = 0

    created_at: datetime
    updated_at: datetime

    # ------------------------------------------------------
    # CONFIGURATION
    # ------------------------------------------------------
    class Config:
        orm_mode = True
        validate_assignment = True
        extra = "forbid"
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

    @classmethod
    def log_project_creation(cls, project: "ProjectModel"):
        logger.info(f"Creating project: {project.title} with ID: {project.id}")
        logger.debug(f"Project details: {project.dict()}")

    @classmethod
    def log_project_update(cls, project: "ProjectModel"):
        logger.info(f"Updating project: {project.title} with ID: {project.id}")
        logger.debug(f"Updated project details: {project.dict()}")

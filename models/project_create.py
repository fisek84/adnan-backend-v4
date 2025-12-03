from pydantic import BaseModel, validator
from typing import Optional, List


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
            raise ValueError("Project must have a title.")
        return v

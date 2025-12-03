from pydantic import BaseModel
from typing import Optional, List


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None

    start_date: Optional[str] = None
    deadline: Optional[str] = None

    project_type: Optional[str] = None
    summary: Optional[str] = None
    next_step: Optional[str] = None

    # unified naming across Create/Model/Sync
    primary_goal_id: Optional[str] = None

    parent_id: Optional[str] = None

    agents: Optional[List[str]] = None
    tasks: Optional[List[str]] = None

    handled_by: Optional[str] = None

    # important — used in ProjectsService.update_project
    progress: Optional[int] = None

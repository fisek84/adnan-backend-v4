from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


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

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class GoalModel(BaseModel):
    id: str
    notion_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    parent_id: Optional[str] = None
    priority: Optional[str] = None
    status: str
    progress: int
    children: List[str] = []
    created_at: datetime
    updated_at: datetime


class TaskModel(BaseModel):
    id: str
    notion_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    goal_id: Optional[str] = None
    priority: Optional[str] = None
    status: str
    order: int = 0
    created_at: datetime
    updated_at: datetime
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class TaskModel(BaseModel):
    id: str
    notion_id: Optional[str] = None  # NEW — real Notion page ID
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    goal_id: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    order: int = 0
    created_at: datetime
    updated_at: datetime
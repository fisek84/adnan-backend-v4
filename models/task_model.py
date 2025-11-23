from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class TaskModel(BaseModel):
    id: str
    title: str
    description: Optional[str]
    goal_id: Optional[str]
    deadline: Optional[str]
    priority: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime

from pydantic import BaseModel
from typing import Optional

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    goal_id: Optional[str] = None
    deadline: Optional[str] = None
    priority: Optional[str] = None

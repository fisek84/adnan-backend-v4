from pydantic import BaseModel
from typing import Optional

class GoalCreate(BaseModel):
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    parent_id: Optional[str] = None
    priority: Optional[str] = None

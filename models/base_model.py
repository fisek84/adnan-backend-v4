from datetime import datetime
from pydantic import BaseModel
from typing import List, Optional

class GoalModel(BaseModel):
    id: str
    title: str
    description: Optional[str]
    deadline: Optional[str]
    parent_id: Optional[str]
    priority: Optional[str]
    status: str
    progress: int
    children: List[str]
    created_at: datetime
    updated_at: datetime

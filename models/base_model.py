from pydantic import BaseModel, Field
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
    
    # ❗ FIX: default_factory — sprječava mutabilni default bug
    children: List[str] = Field(default_factory=list)

    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
        validate_assignment = True
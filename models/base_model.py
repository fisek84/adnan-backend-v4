from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class GoalModel(BaseModel):
    id: str
    notion_id: Optional[str] = Field(
        None, description="Notion page ID for sync/delete"
    )

    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None

    parent_id: Optional[str] = None
    priority: Optional[str] = None
    status: str
    progress: int

    # FIX: safe list default
    children: List[str] = Field(default_factory=list)

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True  # pydantic v2 (replaces orm_mode)
        validate_assignment = True
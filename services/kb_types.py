from __future__ import annotations

from typing import List, Optional, TypedDict


class KBEntry(TypedDict):
    id: str
    title: str
    tags: List[str]
    applies_to: List[str]
    priority: float
    content: str
    updated_at: Optional[str]

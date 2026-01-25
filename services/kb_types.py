from __future__ import annotations

from typing import List, Optional, TypedDict

try:
    from typing import NotRequired
except Exception:  # pragma: no cover
    # Python <3.11 compatibility (best-effort)
    from typing_extensions import NotRequired  # type: ignore


class KBEntry(TypedDict):
    id: str
    title: str
    tags: List[str]
    applies_to: List[str]
    priority: float
    content: str
    updated_at: Optional[str]

    # Optional, best-effort enrichment (Notion KB)
    snippet: NotRequired[str]
    status: NotRequired[str]
    source: NotRequired[str]

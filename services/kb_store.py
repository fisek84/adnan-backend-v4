from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from services.kb_types import KBEntry


class KBStore(Protocol):
    async def get_entries(
        self, ctx: Optional[Dict[str, Any]] = None
    ) -> List[KBEntry]: ...

    def get_meta(self) -> Dict[str, Any]:
        """Returns metadata about the most recent `get_entries` call.

        Required keys:
        - source: "file" | "notion" | "file_fallback"
        - cache_hit: bool
        - last_sync: str | None
        """

        ...

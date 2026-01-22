from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class _CacheEntry:
    expires_at: float
    value: Dict[str, Any]


class SessionSnapshotCache:
    """Tiny in-memory TTL cache for chat-time read-only Notion snapshots.

    Keyed by (session_id, db_keys_csv). This avoids burning Notion budget on every
    /api/chat request in an active session.

    NOTE: In-memory per-process cache (works well on a single instance; in multi-replica
    deployments you can swap this for Redis later without changing the call sites).
    """

    def __init__(self) -> None:
        self._store: Dict[Tuple[str, str], _CacheEntry] = {}

    def get(self, *, session_id: str, db_keys_csv: str) -> Optional[Dict[str, Any]]:
        key = (session_id, db_keys_csv)
        ent = self._store.get(key)
        if not ent:
            return None
        now = time.monotonic()
        if ent.expires_at <= now:
            self._store.pop(key, None)
            return None
        return ent.value

    def set(
        self,
        *,
        session_id: str,
        db_keys_csv: str,
        value: Dict[str, Any],
        ttl_seconds: int,
    ) -> None:
        now = time.monotonic()
        ttl = int(ttl_seconds) if ttl_seconds is not None else 0
        if ttl <= 0:
            ttl = 60
        key = (session_id, db_keys_csv)
        self._store[key] = _CacheEntry(expires_at=now + float(ttl), value=value)


# SSOT singleton cache
SESSION_SNAPSHOT_CACHE = SessionSnapshotCache()

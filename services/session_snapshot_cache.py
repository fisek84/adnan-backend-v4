from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
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

    def _iso_to_epoch(self, s: Any) -> Optional[float]:
        if not isinstance(s, str) or not s.strip():
            return None
        txt = s.strip()
        # Tolerate common UTC forms.
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(txt).timestamp()
        except Exception:
            return None

    def _extract_last_sync(self, snap: Dict[str, Any]) -> Optional[str]:
        if not isinstance(snap, dict):
            return None
        v = snap.get("last_sync")
        if isinstance(v, str) and v.strip():
            return v.strip()
        payload = snap.get("payload") if isinstance(snap.get("payload"), dict) else None
        if isinstance(payload, dict):
            v2 = payload.get("last_sync")
            if isinstance(v2, str) and v2.strip():
                return v2.strip()
        return None

    def get(
        self,
        *,
        session_id: str,
        db_keys_csv: str,
        min_last_sync: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        key = (session_id, db_keys_csv)
        ent = self._store.get(key)
        if not ent:
            return None
        now = time.monotonic()
        if ent.expires_at <= now:
            self._store.pop(key, None)
            return None

        if isinstance(min_last_sync, str) and min_last_sync.strip():
            cached_sync = self._extract_last_sync(ent.value)
            cached_ts = self._iso_to_epoch(cached_sync)
            min_ts = self._iso_to_epoch(min_last_sync)
            if cached_ts is not None and min_ts is not None and cached_ts < min_ts:
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

    def clear(self) -> int:
        """Clear all cached snapshots.

        Returns number of entries removed.
        """
        n = len(self._store)
        self._store.clear()
        return int(n)


# SSOT singleton cache
SESSION_SNAPSHOT_CACHE = SessionSnapshotCache()

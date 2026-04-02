from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _utcnow().isoformat()


def _repo_root() -> Path:
    # services/.. == repo root
    return Path(__file__).resolve().parents[1]


def _store_path() -> Path:
    raw = (os.getenv("NOTION_ARMED_STORE_PATH") or "").strip()
    if raw:
        return Path(raw)
    return _repo_root() / "data" / "notion_armed_store.json"


def _parse_iso(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _as_bool(v: Any) -> bool:
    return bool(v is True)


def _ensure_dir(path: Path) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    _ensure_dir(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    tmp.write_text(data, encoding="utf-8")
    # Path.replace is atomic on Windows for same-volume rename.
    tmp.replace(path)


@dataclass
class _StoreState:
    loaded: bool = False
    healthy: bool = True
    error: Optional[str] = None
    data: Dict[str, Dict[str, Any]] = None  # principal_sub -> state
    path: Path = None

    def __post_init__(self) -> None:
        if self.data is None:
            self.data = {}
        if self.path is None:
            self.path = _store_path()


_LOCK = threading.RLock()
_STATE = _StoreState()


def _mark_unhealthy(err: Exception) -> None:
    _STATE.healthy = False
    _STATE.error = f"{type(err).__name__}:{err}"


def _require_healthy() -> None:
    if _STATE.healthy is not True:
        raise RuntimeError("notion_armed_store_unavailable")


def load() -> Dict[str, Any]:
    """Load store contents from disk into memory.

    Fail-closed: any load failure marks store unhealthy and raises.
    """
    with _LOCK:
        _STATE.path = _store_path()
        try:
            path = _STATE.path
            if not path.exists():
                _STATE.data = {}
                _STATE.loaded = True
                _STATE.healthy = True
                _STATE.error = None
                # Create empty file to make persistence explicit.
                _atomic_write_json(
                    path,
                    {"version": 1, "updated_at": _now_iso(), "principals": {}},
                )
                return {"ok": True, "loaded": True, "path": str(path)}

            raw = path.read_text(encoding="utf-8")
            parsed = json.loads(raw) if raw.strip() else {}
            principals = parsed.get("principals") if isinstance(parsed, dict) else None
            if principals is None:
                principals = {}
            if not isinstance(principals, dict):
                raise ValueError("invalid_store_format")

            cleaned: Dict[str, Dict[str, Any]] = {}
            for k, v in principals.items():
                if not isinstance(k, str) or not k.strip():
                    continue
                if not isinstance(v, dict):
                    continue
                cleaned[k.strip()] = dict(v)

            _STATE.data = cleaned
            _STATE.loaded = True
            _STATE.healthy = True
            _STATE.error = None
            return {"ok": True, "loaded": True, "path": str(path)}
        except Exception as exc:
            _mark_unhealthy(exc)
            _STATE.loaded = False
            raise


def flush() -> Dict[str, Any]:
    """Flush in-memory store contents to disk.

    Fail-closed: any flush failure marks store unhealthy and raises.
    """
    with _LOCK:
        _require_healthy()
        try:
            path = _STATE.path or _store_path()
            payload: Dict[str, Any] = {
                "version": 1,
                "updated_at": _now_iso(),
                "principals": dict(_STATE.data or {}),
            }
            _atomic_write_json(path, payload)
            return {"ok": True, "flushed": True, "path": str(path)}
        except Exception as exc:
            _mark_unhealthy(exc)
            raise


def _ensure_loaded() -> None:
    expected_path = _store_path()
    if _STATE.loaded and _STATE.healthy and _STATE.path == expected_path:
        return
    # Attempt a load; may raise and mark unhealthy.
    load()


def _apply_expiry(state: Dict[str, Any]) -> Dict[str, Any]:
    st = dict(state or {})
    if _as_bool(st.get("armed")) is not True:
        st.setdefault("armed", False)
        return st

    expires_at = _parse_iso(st.get("expires_at"))
    if expires_at is None:
        return st

    now = _utcnow()
    if now >= expires_at:
        st["armed"] = False
        st["armed_at"] = None
        st["expires_at"] = None
        st.setdefault("expired_at", now.isoformat())
        st.setdefault("status", "expired")
    return st


def get(principal_sub: str) -> Dict[str, Any]:
    """Get the current principal-bound Notion ARM state."""
    ps = (principal_sub or "").strip()
    if not ps:
        raise ValueError("principal_sub must be non-empty")

    with _LOCK:
        _ensure_loaded()
        _require_healthy()
        st = dict((_STATE.data or {}).get(ps) or {})
        st.setdefault("principal_sub", ps)
        st.setdefault("armed", False)
        st = _apply_expiry(st)
        return st


def set(principal_sub: str, armed_state: Dict[str, Any]) -> Dict[str, Any]:
    """Set the principal-bound Notion ARM state and persist it."""
    ps = (principal_sub or "").strip()
    if not ps:
        raise ValueError("principal_sub must be non-empty")
    if not isinstance(armed_state, dict):
        raise TypeError("armed_state must be a dict")

    with _LOCK:
        _ensure_loaded()
        _require_healthy()

        st = dict(armed_state)
        st["principal_sub"] = ps
        st.setdefault("armed", False)
        # Defensive normalization of important fields.
        if st.get("armed") is True:
            st.setdefault("armed_at", _now_iso())
        else:
            st["armed"] = False
            st.setdefault("armed_at", None)
            st.setdefault("expires_at", None)

        if not isinstance(_STATE.data, dict):
            _STATE.data = {}
        _STATE.data[ps] = st
        flush()
        return dict(st)


def clear(principal_sub: str) -> Dict[str, Any]:
    """Remove a principal entry from the store (persisted)."""
    ps = (principal_sub or "").strip()
    if not ps:
        raise ValueError("principal_sub must be non-empty")

    with _LOCK:
        _ensure_loaded()
        _require_healthy()
        if isinstance(_STATE.data, dict):
            _STATE.data.pop(ps, None)
        flush()
        return {"ok": True, "cleared": True, "principal_sub": ps}


def _force_unhealthy_for_tests() -> None:
    """Test-only helper to simulate store failure."""
    with _LOCK:
        _STATE.healthy = False
        _STATE.error = "forced"

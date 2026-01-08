# services/approval_state_service.py
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# ============================================================
# STORAGE (SURVIVES RELOAD/RESTART)
# ============================================================


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_approval_file() -> Path:
    env_path = (os.getenv("APPROVAL_STATE_PATH") or "").strip()
    if env_path:
        return Path(env_path).expanduser()
    base_path = _repo_root() / "adnan_ai" / "memory"
    return base_path / "approval_state.json"


_APPROVAL_FILE = _resolve_approval_file()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_utc_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _resolve_pending_ttl_seconds() -> int:
    raw_s = (os.getenv("APPROVAL_PENDING_TTL_SECONDS") or "").strip()
    raw_h = (os.getenv("APPROVAL_PENDING_TTL_HOURS") or "").strip()
    raw_d = (os.getenv("APPROVAL_PENDING_TTL_DAYS") or "").strip()

    def _to_int(x: str) -> Optional[int]:
        try:
            return int(x)
        except Exception:
            return None

    if raw_s:
        v = _to_int(raw_s)
        if v is not None:
            return v
    if raw_h:
        v = _to_int(raw_h)
        if v is not None:
            return v * 3600
    if raw_d:
        v = _to_int(raw_d)
        if v is not None:
            return v * 86400

    return 7 * 86400


_PENDING_TTL_SECONDS = _resolve_pending_ttl_seconds()


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.{os.getpid()}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


class ApprovalStateService:
    """
    CANONICAL APPROVAL STATE SERVICE (STRICT)

    HARD CANON:
    - approval is ALWAYS bound to execution_id
    - approval lifecycle is immutable except status transitions
    - expired approvals are terminal
    """

    _GLOBAL_APPROVALS: Dict[str, Dict[str, Any]] = {}
    _GLOBAL_LOCK: Lock = Lock()
    _LOADED_FROM_DISK: bool = False

    def __init__(self) -> None:
        self._approvals = ApprovalStateService._GLOBAL_APPROVALS
        self._lock = ApprovalStateService._GLOBAL_LOCK

        with self._lock:
            if not ApprovalStateService._LOADED_FROM_DISK:
                self._load_from_disk_locked()
                ApprovalStateService._LOADED_FROM_DISK = True
            self._expire_stale_pending_locked()

    # ============================================================
    # CREATE
    # ============================================================

    def create(
        self,
        *,
        command: str,
        payload_summary: Dict[str, Any],
        scope: str,
        risk_level: str,
        execution_id: str,
    ) -> Dict[str, Any]:
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise ValueError("execution_id is required")

        cmd_norm = str(command or "").strip()
        if not cmd_norm:
            raise ValueError("command is required")

        try:
            payload_key = json.dumps(payload_summary or {}, sort_keys=True, default=str)
        except Exception:
            payload_key = "{}"

        with self._lock:
            self._expire_stale_pending_locked()

            for approval in self._approvals.values():
                if (
                    approval.get("execution_id") == execution_id
                    and approval.get("command") == cmd_norm
                    and approval.get("payload_key") == payload_key
                    and approval.get("status") in ("pending", "approved")
                ):
                    return dict(approval)

            approval_id = str(uuid4())
            now = _utc_now_iso()

            approval = {
                "approval_id": approval_id,
                "execution_id": execution_id,
                "command": cmd_norm,
                "payload_summary": payload_summary or {},
                "payload_key": payload_key,
                "scope": str(scope or "").strip(),
                "risk_level": str(risk_level or "").strip() or "standard",
                "status": "pending",
                "created_at": now,
            }

            self._approvals[approval_id] = approval
            self._persist_to_disk_locked()
            return dict(approval)

    # ============================================================
    # DECISIONS
    # ============================================================

    def approve(
        self,
        approval_id: str,
        *,
        approved_by: str = "unknown",
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            self._expire_stale_pending_locked()
            approval = self._require(approval_id)

            if approval.get("status") == "expired":
                raise ValueError("Approval expired")

            if approval.get("status") != "pending":
                return dict(approval)

            approval["status"] = "approved"
            approval["approved_by"] = str(approved_by or "unknown")
            if isinstance(note, str) and note.strip():
                approval["note"] = note.strip()
            approval["decided_at"] = _utc_now_iso()
            self._persist_to_disk_locked()
            return dict(approval)

    def reject(
        self,
        approval_id: str,
        *,
        rejected_by: str = "unknown",
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            self._expire_stale_pending_locked()
            approval = self._require(approval_id)

            if approval.get("status") == "expired":
                return dict(approval)

            if approval.get("status") != "pending":
                return dict(approval)

            approval["status"] = "rejected"
            approval["rejected_by"] = str(rejected_by or "unknown")
            if isinstance(note, str) and note.strip():
                approval["note"] = note.strip()
            approval["decided_at"] = _utc_now_iso()
            self._persist_to_disk_locked()
            return dict(approval)

    # ============================================================
    # READ
    # ============================================================

    def is_fully_approved(self, approval_id: str) -> bool:
        with self._lock:
            self._expire_stale_pending_locked()
            a = self._approvals.get(approval_id)
            return bool(a and a.get("status") == "approved")

    def get(self, approval_id: str) -> Dict[str, Any]:
        with self._lock:
            self._expire_stale_pending_locked()
            return dict(self._require(approval_id))

    def list_approvals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            self._expire_stale_pending_locked()
            vals = list(self._approvals.values())
            if status:
                vals = [a for a in vals if a.get("status") == status]
            return [dict(a) for a in vals]

    def list_pending(self) -> List[Dict[str, Any]]:
        return self.list_approvals(status="pending")

    # ============================================================
    # TTL / EXPIRATION
    # ============================================================

    def _expire_stale_pending_locked(self) -> int:
        ttl = int(_PENDING_TTL_SECONDS or 0)
        if ttl <= 0:
            return 0

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=ttl)

        changed = 0
        for a in self._approvals.values():
            if a.get("status") != "pending":
                continue
            created_at = _parse_utc_iso(a.get("created_at"))
            if created_at and created_at < cutoff:
                a["status"] = "expired"
                a["expired_at"] = _utc_now_iso()
                a.setdefault("decided_at", a["expired_at"])
                a.setdefault("note", "expired_by_ttl")
                changed += 1

        if changed:
            self._persist_to_disk_locked()
        return changed

    # ============================================================
    # INTERNAL
    # ============================================================

    def _require(self, approval_id: str) -> Dict[str, Any]:
        a = self._approvals.get(approval_id)
        if not a:
            raise KeyError("Approval not found")
        return a

    def _load_from_disk_locked(self) -> None:
        try:
            if not _APPROVAL_FILE.exists():
                return
            with open(_APPROVAL_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, dict) and k not in self._approvals:
                    v.setdefault("approval_id", k)
                    v.setdefault("status", "pending")
                    v.setdefault("created_at", _utc_now_iso())
                    self._approvals[k] = v
        except Exception as e:
            logger.warning("ApprovalState load failed: %s", e)

    def _persist_to_disk_locked(self) -> None:
        try:
            _atomic_write_json(_APPROVAL_FILE, self._approvals)
        except Exception as e:
            logger.warning("ApprovalState persist failed: %s", e)


_APPROVAL_STATE_SINGLETON = ApprovalStateService()


def get_approval_state() -> ApprovalStateService:
    return _APPROVAL_STATE_SINGLETON

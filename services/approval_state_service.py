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
#
# Default path (repo-relative):
#   <repo_root>/adnan_ai/memory/approval_state.json
#
# Override (recommended for prod):
#   APPROVAL_STATE_PATH=/var/data/adnan_ai/approval_state.json
#
# Pending TTL (prod-friendly hygiene):
#   APPROVAL_PENDING_TTL_SECONDS=604800   (7 days)
#   APPROVAL_PENDING_TTL_HOURS=168
#   APPROVAL_PENDING_TTL_DAYS=7
#
# If TTL <= 0 -> expiration disabled (not recommended for prod)
#


def _repo_root() -> Path:
    # services/approval_state_service.py -> services -> repo root
    return Path(__file__).resolve().parents[1]


def _resolve_approval_file() -> Path:
    env_path = (os.getenv("APPROVAL_STATE_PATH") or "").strip()
    if env_path:
        return Path(env_path).expanduser()

    base_path = _repo_root() / "adnan_ai" / "memory"
    return base_path / "approval_state.json"


_APPROVAL_FILE = _resolve_approval_file()


def _utc_now_iso() -> str:
    # timezone-aware ISO (stable for logs + comparisons)
    return datetime.now(timezone.utc).isoformat()


def _parse_utc_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    # tolerate "Z"
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
    """
    Returns TTL in seconds for PENDING approvals.
    Priority: seconds -> hours -> days -> default(7 days).
    """
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

    # default: 7 days
    return 7 * 86400


_PENDING_TTL_SECONDS = _resolve_pending_ttl_seconds()


def _atomic_write_json(path: Path, data: Any) -> None:
    """
    Best-effort atomic write:
      - write to temp file in same directory
      - fsync
      - replace (atomic on most OS/filesystems)
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_name = f".{path.name}.{os.getpid()}.tmp"
    tmp_path = path.parent / tmp_name

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, path)


class ApprovalStateService:
    """
    CANONICAL APPROVAL STATE SERVICE

    - approval je VEZAN za execution_id
    - nema approvala bez execution_id
    - approval lifecycle: pending -> approved | rejected | expired

    NOTE (stabilnost testova):
    - svi instance-i dijele isti backing store (class-level), da se izbjegne
      "approval not found in pending list" kad različiti dijelovi koda kreiraju
      novu instancu servisa.

    NOTE (stabilnost runtime-a / reload):
    - approvals se persiste na disk (best-effort) da prežive uvicorn reload/restart.

    NOTE (produkcijska higijena):
    - pending approvals mogu isteći nakon TTL (env: APPROVAL_PENDING_TTL_*).
      Expired se NE prikazuju u pending listi.
    """

    _GLOBAL_APPROVALS: Dict[str, Dict[str, Any]] = {}
    _GLOBAL_LOCK: Lock = Lock()
    _LOADED_FROM_DISK: bool = False

    def __init__(self) -> None:
        self._approvals: Dict[str, Dict[str, Any]] = (
            ApprovalStateService._GLOBAL_APPROVALS
        )
        self._lock: Lock = ApprovalStateService._GLOBAL_LOCK

        # Best-effort load once per process
        with self._lock:
            if not ApprovalStateService._LOADED_FROM_DISK:
                self._load_from_disk_locked()
                ApprovalStateService._LOADED_FROM_DISK = True

            # Hygiene: expire stale pending on startup (best-effort)
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
            raise ValueError("execution_id is required for approval")

        cmd_norm = str(command or "").strip()
        if not cmd_norm:
            raise ValueError("command is required for approval")

        try:
            payload_key = json.dumps(payload_summary or {}, sort_keys=True, default=str)
        except Exception:
            payload_key = "{}"

        with self._lock:
            # Hygiene: expire stale pending before we decide replay
            self._expire_stale_pending_locked()

            # replay: ako već postoji pending ili approved za isti execution_id+command+payload
            for approval in self._approvals.values():
                if (
                    approval.get("command") == cmd_norm
                    and approval.get("payload_key") == payload_key
                    and approval.get("execution_id") == execution_id
                    and approval.get("status") in ("pending", "approved")
                ):
                    return dict(approval)

            approval_id = str(uuid4())
            now = _utc_now_iso()

            approval: Dict[str, Any] = {
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

            # expired approvals cannot be approved
            if approval.get("status") == "expired":
                raise ValueError("Approval expired")

            # idempotent
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

            # expired approvals cannot be rejected (they're already terminal)
            if approval.get("status") == "expired":
                return dict(approval)

            # idempotent
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
            approval = self._approvals.get(approval_id)
            return bool(approval and approval.get("status") == "approved")

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

    # Optional helper (non-breaking)
    def list_by_execution_id(self, execution_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            self._expire_stale_pending_locked()
            return [
                dict(a)
                for a in self._approvals.values()
                if a.get("execution_id") == execution_id
            ]

    # ============================================================
    # TTL / EXPIRATION
    # ============================================================

    def expire_stale_pending(self) -> int:
        """
        Public helper (safe to call anywhere).
        Returns number of newly expired approvals.
        """
        with self._lock:
            return self._expire_stale_pending_locked()

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
            if created_at is None:
                # if we cannot parse, be conservative: do not expire
                continue

            if created_at < cutoff:
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
        approval = self._approvals.get(approval_id)
        if not approval:
            raise KeyError("Approval not found")
        return approval

    def _load_from_disk_locked(self) -> None:
        try:
            _APPROVAL_FILE.parent.mkdir(parents=True, exist_ok=True)
            if not _APPROVAL_FILE.exists():
                return

            with open(_APPROVAL_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return

            # Merge disk approvals into memory (best-effort; disk nije viša vlast)
            for k, v in data.items():
                if not (isinstance(k, str) and isinstance(v, dict)):
                    continue

                # minimalna validacija shape-a
                v.setdefault("approval_id", k)
                v.setdefault("status", "pending")
                v.setdefault("created_at", _utc_now_iso())

                if k not in self._approvals:
                    self._approvals[k] = v

        except Exception as e:  # noqa: BLE001
            logger.warning("ApprovalState load_from_disk failed: %s", str(e))

    def _persist_to_disk_locked(self) -> None:
        try:
            _atomic_write_json(_APPROVAL_FILE, self._approvals)
        except Exception as e:  # noqa: BLE001
            logger.warning("ApprovalState persist_to_disk failed: %s", str(e))


# ============================================================
# CANONICAL SINGLETON
# ============================================================

_APPROVAL_STATE_SINGLETON = ApprovalStateService()


def get_approval_state() -> ApprovalStateService:
    return _APPROVAL_STATE_SINGLETON

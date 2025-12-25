# services/approval_state_service.py

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# ============================================================
# STORAGE (SURVIVES RELOAD/RESTART)
# ============================================================

_BASE_PATH = Path(__file__).resolve().parent.parent / "adnan_ai" / "memory"
_APPROVAL_FILE = _BASE_PATH / "approval_state.json"


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


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
    - approval lifecycle: pending -> approved | rejected

    NOTE (stabilnost testova):
    - svi instance-i dijele isti backing store (class-level), da se izbjegne
      "approval not found in pending list" kad različiti dijelovi koda kreiraju
      novu instancu servisa.

    NOTE (stabilnost runtime-a / reload):
    - approvals se persiste na disk (best-effort) da prežive uvicorn reload/restart.
    """

    _GLOBAL_APPROVALS: Dict[str, Dict[str, Any]] = {}
    _GLOBAL_LOCK: Lock = Lock()
    _LOADED_FROM_DISK: bool = False

    def __init__(self):
        self._approvals: Dict[str, Dict[str, Any]] = (
            ApprovalStateService._GLOBAL_APPROVALS
        )
        self._lock: Lock = ApprovalStateService._GLOBAL_LOCK

        # Best-effort load once per process
        with self._lock:
            if not ApprovalStateService._LOADED_FROM_DISK:
                self._load_from_disk_locked()
                ApprovalStateService._LOADED_FROM_DISK = True

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
            # replay: ako već postoji pending ili approved za isti execution_id+command+payload
            for approval in self._approvals.values():
                if (
                    approval.get("command") == cmd_norm
                    and approval.get("payload_key") == payload_key
                    and approval.get("execution_id") == execution_id
                    and approval.get("status") in ("pending", "approved")
                ):
                    return approval.copy()

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
            return approval.copy()

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
            approval = self._require(approval_id)

            # idempotent
            if approval.get("status") != "pending":
                return approval.copy()

            approval["status"] = "approved"
            approval["approved_by"] = str(approved_by or "unknown")

            if isinstance(note, str) and note.strip():
                approval["note"] = note.strip()

            approval["decided_at"] = _utc_now_iso()
            self._persist_to_disk_locked()
            return approval.copy()

    def reject(
        self,
        approval_id: str,
        *,
        rejected_by: str = "unknown",
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            approval = self._require(approval_id)

            # idempotent
            if approval.get("status") != "pending":
                return approval.copy()

            approval["status"] = "rejected"
            approval["rejected_by"] = str(rejected_by or "unknown")

            if isinstance(note, str) and note.strip():
                approval["note"] = note.strip()

            approval["decided_at"] = _utc_now_iso()
            self._persist_to_disk_locked()
            return approval.copy()

    # ============================================================
    # READ
    # ============================================================

    def is_fully_approved(self, approval_id: str) -> bool:
        with self._lock:
            approval = self._approvals.get(approval_id)
            return bool(approval and approval.get("status") == "approved")

    def get(self, approval_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._require(approval_id).copy()

    def list_approvals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            vals = list(self._approvals.values())
            if status:
                vals = [a for a in vals if a.get("status") == status]
            return [a.copy() for a in vals]

    def list_pending(self) -> List[Dict[str, Any]]:
        return self.list_approvals(status="pending")

    # Optional helper (non-breaking)
    def list_by_execution_id(self, execution_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                a.copy()
                for a in self._approvals.values()
                if a.get("execution_id") == execution_id
            ]

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
            _BASE_PATH.mkdir(parents=True, exist_ok=True)
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
                if "approval_id" not in v:
                    v["approval_id"] = k
                if "status" not in v:
                    v["status"] = "pending"
                if "created_at" not in v:
                    v["created_at"] = _utc_now_iso()

                if k not in self._approvals:
                    self._approvals[k] = v

        except Exception as e:
            logger.warning("ApprovalState load_from_disk failed: %s", str(e))

    def _persist_to_disk_locked(self) -> None:
        try:
            _atomic_write_json(_APPROVAL_FILE, self._approvals)
        except Exception as e:
            logger.warning("ApprovalState persist_to_disk failed: %s", str(e))


# ============================================================
# CANONICAL SINGLETON
# ============================================================

_APPROVAL_STATE_SINGLETON = ApprovalStateService()


def get_approval_state() -> ApprovalStateService:
    return _APPROVAL_STATE_SINGLETON

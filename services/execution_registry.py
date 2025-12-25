# services/execution_registry.py
"""
EXECUTION REGISTRY — CANONICAL (SSOT)

Problem koji rješava:
- Ako različiti dijelovi sistema kreiraju novu instancu ExecutionRegistry,
  bez globalnog backing store-a, resume() može reći "Execution not found".
- U praksi: uvicorn reload / hot reload / multi-import / novi orchestrator instance
  -> izgubi se state ako je registry samo in-memory po instanci.

Rješenje:
- Class-level GLOBAL store + lock (kao ApprovalStateService).
- Best-effort persist na disk (da preživi reload/restart).
- Registry čuva AICommand (kanonski objekat), i state (BLOCKED/COMPLETED...).

API koje koristi Orchestrator:
- register(cmd)
- get(execution_id)
- block(execution_id, decision)
- complete(execution_id, result)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional, Union, List

from models.ai_command import AICommand

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# STORAGE (SURVIVES RELOAD/RESTART) — best-effort
# ============================================================
_BASE_PATH = Path(__file__).resolve().parent.parent / "adnan_ai" / "memory"
_REGISTRY_FILE = _BASE_PATH / "execution_registry.json"


def _utc_ts() -> str:
    return datetime.utcnow().isoformat()


def _to_dict(cmd: AICommand) -> Dict[str, Any]:
    # pydantic v2
    if hasattr(cmd, "model_dump"):
        try:
            return cmd.model_dump()
        except Exception:
            pass
    # pydantic v1
    if hasattr(cmd, "dict"):
        try:
            return cmd.dict()
        except Exception:
            pass
    # fallback
    return {
        "command": getattr(cmd, "command", None),
        "intent": getattr(cmd, "intent", None),
        "params": getattr(cmd, "params", None)
        if isinstance(getattr(cmd, "params", None), dict)
        else {},
        "initiator": getattr(cmd, "initiator", None),
        "execution_id": getattr(cmd, "execution_id", None),
        "approval_id": getattr(cmd, "approval_id", None),
        "read_only": getattr(cmd, "read_only", None),
        "metadata": getattr(cmd, "metadata", None)
        if isinstance(getattr(cmd, "metadata", None), dict)
        else {},
    }


def _from_dict(data: Dict[str, Any]) -> Optional[AICommand]:
    if not isinstance(data, dict):
        return None
    try:
        return AICommand(**data)
    except Exception:
        # Ako je disk snapshot star i schema se promijenila, probaj minimalni rebuild
        try:
            minimal: Dict[str, Any] = {
                "command": data.get("command") or "unknown",
                "intent": data.get("intent"),
                "params": data.get("params")
                if isinstance(data.get("params"), dict)
                else {},
                "initiator": data.get("initiator") or "unknown",
                "read_only": bool(data.get("read_only", False)),
                "metadata": data.get("metadata")
                if isinstance(data.get("metadata"), dict)
                else {},
                "execution_id": data.get("execution_id"),
                "approval_id": data.get("approval_id"),
                "execution_state": data.get("execution_state"),
                "decision": data.get("decision")
                if isinstance(data.get("decision"), dict)
                else None,
                "result": data.get("result")
                if isinstance(data.get("result"), dict)
                else None,
                "validated": bool(data.get("validated", False)),
            }
            return AICommand(**minimal)
        except Exception:
            return None


# ============================================================
# CANONICAL REGISTRY
# ============================================================
class ExecutionRegistry:
    """
    CANONICAL EXECUTION REGISTRY (SSOT)

    Global store shape:
      execution_id -> {
        "command": <AICommand-as-dict>,
        "updated_at": "...",
      }

    U runtime-u vraćamo AICommand object.
    """

    _GLOBAL: Dict[str, Dict[str, Any]] = {}
    _LOCK: Lock = Lock()
    _LOADED_FROM_DISK: bool = False

    def __init__(self):
        self._store = ExecutionRegistry._GLOBAL
        self._lock = ExecutionRegistry._LOCK

        # Load once per process
        with self._lock:
            if not ExecutionRegistry._LOADED_FROM_DISK:
                self._load_from_disk_locked()
                ExecutionRegistry._LOADED_FROM_DISK = True

    # ------------------------------------------------------------
    # CORE API
    # ------------------------------------------------------------
    def register(self, cmd: AICommand) -> None:
        """
        Idempotent register.
        - Ako već postoji, merge-uje state iz postojeće verzije (disk/runtime)
          i osvježi command payload.
        """
        execution_id = getattr(cmd, "execution_id", None)
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise ValueError(
                "ExecutionRegistry.register requires AICommand.execution_id"
            )

        execution_id = execution_id.strip()
        now = _utc_ts()

        with self._lock:
            existing = self._store.get(execution_id)

            # Merge: ako postoje decision/result u store, nemoj ih izgubiti
            if isinstance(existing, dict):
                existing_cmd_dict = existing.get("command")
                existing_cmd = (
                    _from_dict(existing_cmd_dict)
                    if isinstance(existing_cmd_dict, dict)
                    else None
                )

                if existing_cmd is not None:
                    # Ako novi cmd nema decision/result/state, a stari ima — prenesi.
                    if (
                        getattr(cmd, "decision", None) is None
                        and getattr(existing_cmd, "decision", None) is not None
                    ):
                        cmd.decision = existing_cmd.decision
                    if (
                        getattr(cmd, "result", None) is None
                        and getattr(existing_cmd, "result", None) is not None
                    ):
                        cmd.result = existing_cmd.result
                    if (
                        getattr(cmd, "execution_state", None) is None
                        and getattr(existing_cmd, "execution_state", None) is not None
                    ):
                        cmd.execution_state = existing_cmd.execution_state
                    # approval_id: sačuvaj ako postoji na starom
                    if not getattr(cmd, "approval_id", None) and getattr(
                        existing_cmd, "approval_id", None
                    ):
                        cmd.approval_id = existing_cmd.approval_id

            self._store[execution_id] = {
                "command": _to_dict(cmd),
                "updated_at": now,
            }
            self._persist_to_disk_locked()

    def get(self, execution_id: str) -> Optional[Union[AICommand, Dict[str, Any]]]:
        """
        Vraća AICommand (preferirano).
        Ako ne može deserializovati, vraća raw dict command payload kao fallback.
        """
        eid = (execution_id or "").strip()
        if not eid:
            return None

        with self._lock:
            rec = self._store.get(eid)
            if not isinstance(rec, dict):
                return None

            cmd_dict = rec.get("command")
            if isinstance(cmd_dict, dict):
                cmd = _from_dict(cmd_dict)
                if cmd is not None:
                    return cmd
                return cmd_dict

            return None

    def block(self, execution_id: str, decision: Dict[str, Any]) -> None:
        eid = (execution_id or "").strip()
        if not eid:
            raise ValueError("ExecutionRegistry.block requires execution_id")

        with self._lock:
            rec = self._store.get(eid) or {}
            cmd_dict = rec.get("command") if isinstance(rec, dict) else None

            cmd = _from_dict(cmd_dict) if isinstance(cmd_dict, dict) else None
            if cmd is None:
                # Minimal placeholder
                cmd = AICommand(
                    command="unknown", initiator="unknown", params={}, read_only=False
                )

            cmd.execution_id = eid
            cmd.execution_state = "BLOCKED"
            if isinstance(decision, dict):
                cmd.decision = decision

                # propagate approval_id into cmd+metadata if present
                aid = decision.get("approval_id")
                if isinstance(aid, str) and aid.strip():
                    cmd.approval_id = aid.strip()
                    md = cmd.metadata if isinstance(cmd.metadata, dict) else {}
                    md["approval_id"] = aid.strip()
                    cmd.metadata = md

            self._store[eid] = {"command": _to_dict(cmd), "updated_at": _utc_ts()}
            self._persist_to_disk_locked()

    def complete(self, execution_id: str, result: Dict[str, Any]) -> None:
        eid = (execution_id or "").strip()
        if not eid:
            raise ValueError("ExecutionRegistry.complete requires execution_id")

        with self._lock:
            rec = self._store.get(eid) or {}
            cmd_dict = rec.get("command") if isinstance(rec, dict) else None

            cmd = _from_dict(cmd_dict) if isinstance(cmd_dict, dict) else None
            if cmd is None:
                cmd = AICommand(
                    command="unknown", initiator="unknown", params={}, read_only=False
                )

            cmd.execution_id = eid
            cmd.execution_state = "COMPLETED"
            if isinstance(result, dict):
                cmd.result = result

            self._store[eid] = {"command": _to_dict(cmd), "updated_at": _utc_ts()}
            self._persist_to_disk_locked()

    # ------------------------------------------------------------
    # OPTIONAL HELPERS (debug)
    # ------------------------------------------------------------
    def list_execution_ids(self) -> List[str]:
        with self._lock:
            return sorted(list(self._store.keys()))

    def snapshot(self) -> Dict[str, Any]:
        """
        READ-ONLY registry snapshot (bez velikih payload-a).
        """
        with self._lock:
            out: Dict[str, Any] = {}
            for eid, rec in self._store.items():
                if not isinstance(rec, dict):
                    continue
                cmd_dict = (
                    rec.get("command") if isinstance(rec.get("command"), dict) else {}
                )
                out[eid] = {
                    "command": cmd_dict.get("command"),
                    "intent": cmd_dict.get("intent"),
                    "initiator": cmd_dict.get("initiator"),
                    "execution_state": cmd_dict.get("execution_state"),
                    "approval_id": cmd_dict.get("approval_id")
                    or (cmd_dict.get("metadata") or {}).get("approval_id"),
                    "updated_at": rec.get("updated_at"),
                }
            return {"read_only": True, "executions": out}

    # ------------------------------------------------------------
    # DISK PERSISTENCE (best-effort)
    # ------------------------------------------------------------
    def _load_from_disk_locked(self) -> None:
        try:
            _BASE_PATH.mkdir(parents=True, exist_ok=True)
            if not _REGISTRY_FILE.exists():
                return

            with open(_REGISTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return

            # Merge disk into memory (best-effort, disk nije “authority”)
            for eid, rec in data.items():
                if not isinstance(eid, str) or not isinstance(rec, dict):
                    continue
                if eid not in self._store:
                    self._store[eid] = rec

        except Exception as e:
            logger.warning("ExecutionRegistry load_from_disk failed: %s", str(e))

    def _persist_to_disk_locked(self) -> None:
        try:
            _BASE_PATH.mkdir(parents=True, exist_ok=True)
            with open(_REGISTRY_FILE, "w", encoding="utf-8") as f:
                json.dump(self._store, f, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning("ExecutionRegistry persist_to_disk failed: %s", str(e))


# ============================================================
# CANONICAL SINGLETON (optional but recommended)
# ============================================================
_EXECUTION_REGISTRY_SINGLETON = ExecutionRegistry()


def get_execution_registry() -> ExecutionRegistry:
    return _EXECUTION_REGISTRY_SINGLETON

# services/memory_ops_executor.py
from __future__ import annotations

from typing import Any, Dict

from models.ai_command import AICommand
from services.memory_service import MemoryService


class MemoryOpsExecutor:
    """
    Deterministic memory write executor.
    CANON:
    - called ONLY post-approval by ExecutionOrchestrator
    - requires approval_id (enforced upstream)
    - append-only via MemoryService.write_audit_event (existing) until SQL event-store is added
    """

    def __init__(self, memory: MemoryService | None = None) -> None:
        if memory is not None:
            self.memory = memory
            return

        # Prefer the app-wide singleton so read snapshots reflect writes immediately.
        try:
            from dependencies import get_memory_service  # type: ignore

            self.memory = get_memory_service()
        except Exception:
            self.memory = MemoryService()

    async def execute(self, cmd: AICommand) -> Dict[str, Any]:
        # Deterministic, canonical implementation: validate + persist memory_write.v1
        # (post-approval only).
        approval_id = getattr(cmd, "approval_id", None)
        if not isinstance(approval_id, str) or not approval_id.strip():
            raise RuntimeError("MemoryOpsExecutor requires approval_id")

        md = getattr(cmd, "metadata", None)
        identity_id = None
        if isinstance(md, dict):
            identity_id = md.get("identity_id")

        if not isinstance(identity_id, str) or not identity_id.strip():
            raise RuntimeError("MemoryOpsExecutor requires metadata.identity_id")

        intent = (cmd.intent or cmd.command or "").strip() or "memory_write"
        payload = cmd.params if isinstance(getattr(cmd, "params", None), dict) else {}

        result = self.memory.upsert_memory_write_v1(
            payload,
            approval_id=approval_id.strip(),
            execution_id=getattr(cmd, "execution_id", None),
            identity_id=identity_id.strip(),
        )

        # Always append audit event (even for invalid payloads).
        try:
            self.memory.append_write_audit_event(
                {
                    "op": f"memory_write:{intent}",
                    "approval_id": approval_id,
                    "execution_id": getattr(cmd, "execution_id", None),
                    "identity_id": identity_id,
                    "payload": payload,
                    "stored_id": result.get("stored_id")
                    if isinstance(result, dict)
                    else None,
                    "ok": bool(isinstance(result, dict) and result.get("ok") is True),
                    "source": (md.get("source") if isinstance(md, dict) else None)
                    or "memory_write",
                }
            )
        except Exception:
            pass

        if isinstance(result, dict) and result.get("ok") is True:
            return {
                "ok": True,
                "stored_id": result.get("stored_id"),
                "memory_count": result.get("memory_count"),
                "last_write": result.get("last_write"),
                "errors": [],
            }

        # Fail-soft: stable error object with diagnostics.
        diagnostics = {}
        errors = ["memory_write_failed"]
        if isinstance(result, dict):
            errors = (
                result.get("errors")
                if isinstance(result.get("errors"), list)
                else errors
            )
            diagnostics = (
                result.get("diagnostics")
                if isinstance(result.get("diagnostics"), dict)
                else {}
            )

        return {
            "ok": False,
            "stored_id": None,
            "memory_count": None,
            "last_write": None,
            "errors": errors,
            "diagnostics": diagnostics,
        }

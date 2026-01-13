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
        self.memory = memory or MemoryService()

    async def execute(self, cmd: AICommand) -> Dict[str, Any]:
        # Minimal deterministic implementation: record an audit event only.
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
        payload = cmd.params or {}

        # Append-only audit (temporary SSOT until SQL memory_events lands)
        self.memory.append_write_audit_event(
            {
                "op": f"memory_write:{intent}",
                "approval_id": approval_id,
                "execution_id": getattr(cmd, "execution_id", None),
                "identity_id": identity_id,
                "payload": payload,
                "source": (md.get("source") if isinstance(md, dict) else None)
                or "memory_write",
            }
        )
        self.memory._save()

        return {"ok": True, "success": True, "intent": intent}

# services/system_read_executor.py

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from models.ai_command import AICommand
from services.action_dictionary import get_action_handler


class SystemReadExecutor:
    """
    SystemReadExecutor — CANONICAL (FAZA 13 / HORIZONTAL READ SCALING)

    Kanonska uloga:
    - JEDINO mjesto za izvršavanje READ system_query komandi (AICommand)
    - READ-ONLY (nema write-a)
    - NEMA agenata
    - NEMA governance-a
    - NEMA side-effecta
    - siguran za horizontalno skaliranje

    Dodatno:
    - CEO Console koristi snapshot() API da dobije ujednačen READ kontekst.
    - snapshot() NIKAD ne baca exception; vraća available=False na greškama.
    """

    STATE_COMPLETED = "COMPLETED"
    STATE_FAILED = "FAILED"

    # ============================================================
    # CEO Console Snapshot API (READ-only, fail-soft)
    # ============================================================

    def snapshot(self) -> Dict[str, Any]:
        """
        Returns a stable, consolidated READ-only snapshot for CEO Advisory / Console.

        Shape:
          {
            "available": bool,
            "generated_at": str,
            "identity_pack": dict,
            "mode": dict|None,
            "state": dict|None,
            "knowledge_snapshot": dict,
            "ceo_notion_snapshot": dict,
            "trace": dict
          }
        """
        generated_at = datetime.utcnow().isoformat()

        out: Dict[str, Any] = {
            "available": True,
            "generated_at": generated_at,
            "identity_pack": {},
            "mode": None,
            "state": None,
            "knowledge_snapshot": {},
            "ceo_notion_snapshot": {},
            "trace": {
                "service": "SystemReadExecutor",
                "generated_at": generated_at,
            },
        }

        errors = []

        # Identity pack (preferred)
        try:
            from services.identity_loader import load_ceo_identity_pack  # type: ignore

            out["identity_pack"] = load_ceo_identity_pack()
        except Exception as e:
            errors.append({"section": "identity_pack", "error": str(e)})
            out["identity_pack"] = {"available": False, "error": str(e)}

        # Mode/state (local reads)
        try:
            from services.adnan_mode_service import load_mode  # type: ignore

            out["mode"] = load_mode()
        except Exception as e:
            errors.append({"section": "mode", "error": str(e)})

        try:
            from services.adnan_state_service import load_state  # type: ignore

            out["state"] = load_state()
        except Exception as e:
            errors.append({"section": "state", "error": str(e)})

        # Global knowledge snapshot (in-memory + identity pack)
        try:
            from services.knowledge_snapshot_service import (  # type: ignore
                KnowledgeSnapshotService,
            )

            out["knowledge_snapshot"] = KnowledgeSnapshotService.get_snapshot()
        except Exception as e:
            errors.append({"section": "knowledge_snapshot", "error": str(e)})
            out["knowledge_snapshot"] = {"ready": False, "error": str(e)}

        # CEO Notion snapshot service (optional; may be unconfigured)
        try:
            from services.ceo_console_snapshot_service import (  # type: ignore
                CEOConsoleSnapshotService,
            )

            svc = CEOConsoleSnapshotService()
            out["ceo_notion_snapshot"] = svc.snapshot()
        except Exception as e:
            # Fail-soft: do not mark entire snapshot as unavailable.
            errors.append({"section": "ceo_notion_snapshot", "error": str(e)})
            out["ceo_notion_snapshot"] = {"available": False, "error": str(e)}

        if errors:
            out["trace"]["errors"] = errors

        # Mark as unavailable only if ALL primary sources are missing
        if not out.get("identity_pack") and not out.get("knowledge_snapshot"):
            out["available"] = False

        return out

    # ============================================================
    # Existing READ execution API (AICommand handlers)
    # ============================================================

    async def execute(
        self,
        *,
        command: AICommand,
        execution_contract: Dict[str, Any],
    ) -> Dict[str, Any]:
        execution_id = execution_contract["execution_id"]
        started_at = execution_contract["started_at"]
        finished_at = datetime.utcnow().isoformat()

        handler = get_action_handler(command.command)
        if not handler:
            return {
                "execution_id": execution_id,
                "execution_state": self.STATE_FAILED,
                "summary": "System read handler not found.",
                "started_at": started_at,
                "finished_at": finished_at,
                "response": None,
                "read_only": True,
            }

        try:
            result = handler(command.input or {})
        except Exception as e:
            return {
                "execution_id": execution_id,
                "execution_state": self.STATE_FAILED,
                "summary": str(e),
                "started_at": started_at,
                "finished_at": finished_at,
                "response": None,
                "read_only": True,
            }

        response = result.get("response") if isinstance(result, dict) else None

        return {
            "execution_id": execution_id,
            "execution_state": self.STATE_COMPLETED,
            "summary": (response or {}).get("summary"),
            "started_at": started_at,
            "finished_at": finished_at,
            "response": response,
            "read_only": True,
        }

# services/system_read_executor.py

from typing import Dict, Any
from datetime import datetime

from models.ai_command import AICommand
from services.action_dictionary import get_action_handler


class SystemReadExecutor:
    """
    SystemReadExecutor — CANONICAL (FAZA 13 / HORIZONTAL READ SCALING)

    Kanonska uloga:
    - JEDINO mjesto za izvršavanje READ system_query komandi
    - READ-ONLY (nema write-a)
    - NEMA agenata
    - NEMA governance-a
    - NEMA side-effecta
    - siguran za horizontalno skaliranje
    """

    STATE_COMPLETED = "COMPLETED"
    STATE_FAILED = "FAILED"

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

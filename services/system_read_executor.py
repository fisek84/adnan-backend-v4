from typing import Dict, Any
from datetime import datetime

from models.ai_command import AICommand
from services.action_dictionary import get_action_handler


class SystemReadExecutor:
    """
    SystemReadExecutor — SINGLE READ EXECUTION POINT

    Kanonska uloga:
    - jedino mjesto gdje se izvršava system_query
    - nema write-a
    - nema agenata
    - nema governance-a
    - nema side-effecta
    """

    STATE_COMPLETED = "COMPLETED"
    STATE_FAILED = "FAILED"

    async def execute(
        self,
        *,
        command: AICommand,
        execution_contract: Dict[str, Any],
    ) -> Dict[str, Any]:

        started_at = execution_contract["started_at"]

        handler = get_action_handler(command.command)
        if not handler:
            return {
                "execution_id": execution_contract["execution_id"],
                "execution_state": self.STATE_FAILED,
                "summary": "System read handler not found.",
                "started_at": started_at,
                "finished_at": datetime.utcnow().isoformat(),
            }

        result = handler(command.input or {})

        return {
            "execution_id": execution_contract["execution_id"],
            "execution_state": self.STATE_COMPLETED,
            "summary": result.get("response", {}).get("summary"),
            "started_at": started_at,
            "finished_at": datetime.utcnow().isoformat(),
            "response": result.get("response"),
        }

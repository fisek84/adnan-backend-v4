import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class AgentsService:
    """
    AgentsService — DEPRECATED (KANONSKI) — FAZA 10

    STATUS:
    - ZADRŽAN isključivo zbog kompatibilnosti
    - NE IZVRŠAVA nikakve akcije
    - SVI execution path-ovi moraju ići preko AgentRouter / OpenAI agenata

    KANON:
    - Pozivanje ovog servisa = ARHITEKTURNI BUG
    - Greška mora biti glasna i vidljiva
    """

    def __init__(self):
        logger.warning(
            "[AgentsService] INITIALIZED — DEPRECATED / NO-OP"
        )

    # ============================================================
    # PUBLIC ASYNC ENTRYPOINT (EXPLICITLY BLOCKED)
    # ============================================================
    async def execute(
        self,
        *,
        command: str,
        payload: Dict[str, Any],
        execution_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        logger.critical(
            "[AgentsService] BLOCKED execution attempt | command=%s payload=%s context=%s",
            command,
            payload,
            execution_context,
        )

        return {
            "success": False,
            "summary": "AgentsService is deprecated and blocked by canon.",
            "error": "deprecated_executor",
            "command": command,
        }

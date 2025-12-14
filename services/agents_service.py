import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class AgentsService:
    """
    AgentsService — DEPRECATED (KANONSKI)

    STATUS:
    - ZADRŽAN zbog kompatibilnosti
    - VIŠE NE IZVRŠAVA NIKAKVE AKCIJE
    - SVI execution path-ovi moraju ići preko OpenAI agenata

    Ako se ovaj servis pozove:
    - to je GREŠKA u arhitekturi
    - i mora biti VIDJIVA odmah
    """

    def __init__(self):
        logger.warning(
            "[AgentsService] INITIALIZED — DEPRECATED SERVICE (NO-OP)"
        )

    # ============================================================
    # PUBLIC ASYNC ENTRYPOINT (BLOCKED)
    # ============================================================
    async def execute(
        self,
        *,
        command: str,
        payload: Dict[str, Any],
        execution_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        logger.error(
            "[AgentsService] BLOCKED execution attempt | command=%s payload=%s context=%s",
            command,
            payload,
            execution_context,
        )

        return {
            "success": False,
            "summary": "AgentsService is deprecated. Execution is blocked.",
            "error": "deprecated_executor",
            "command": command,
        }

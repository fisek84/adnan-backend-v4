import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class NotionOpsEngine:
    """
    NotionOpsEngine — DEPRECATED (KANONSKI)

    STATUS:
    - ZADRŽAN radi kompatibilnosti
    - VIŠE NE IZVRŠAVA REALNE NOTION OPERACIJE
    - SVE WRITE operacije MORAJU ići preko OpenAI Notion Ops AGENTA

    Ako se ovaj engine pozove:
    - to je GREŠKA u arhitekturi
    - mora biti VIDJIVA odmah
    """

    def __init__(self):
        logger.warning(
            "[NotionOpsEngine] INITIALIZED — DEPRECATED / NO-OP"
        )

    # ============================================================
    # PUBLIC OPS ENTRYPOINT (BLOCKED)
    # ============================================================
    async def execute(
        self,
        *,
        command: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        logger.error(
            "[NotionOpsEngine] BLOCKED execution attempt | command=%s payload=%s",
            command,
            payload,
        )

        return {
            "success": False,
            "summary": "NotionOpsEngine is deprecated. Execution is blocked.",
            "error": "deprecated_ops_engine",
            "command": command,
        }
    
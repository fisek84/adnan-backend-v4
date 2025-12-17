# services/notion_ops_agent.py

from typing import Dict, Any
import logging

from services.notion_service import NotionService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class NotionOpsAgent:
    """
    NOTION OPS AGENT — CANONICAL WRITE EXECUTOR

    Pravila:
    - jedini agent koji pokreće write
    - NE gradi payload
    - NE zove Notion API direktno
    - SAMO delegira NotionService.execute(command)
    """

    def __init__(self, notion: NotionService):
        self.notion = notion

    async def execute(self, command) -> Dict[str, Any]:
        if not command.intent:
            raise RuntimeError("Write command missing intent")

        logger.info(
            "NotionOpsAgent executing intent=%s execution_id=%s",
            command.intent,
            command.execution_id,
        )

        # KANONSKI: sva write logika je u NotionService
        return await self.notion.execute(command)

"""
ACTION EXECUTION SERVICE — KANONSKI (FAZA 3.5)

- jedino mjesto gdje se WRITE izvršava
- agent je GLUP izvršilac
- Backend Mozak je vlasnik znanja
"""

from typing import Dict, Any

from services.agent_router.openai_assistant_executor import OpenAIAssistantExecutor
from services.notion_schema_registry import NotionSchemaRegistry


class ActionExecutionService:
    """
    System Write Executor (Agent-only).
    """

    AGENT_COMMAND = "perform_notion_action"

    def __init__(self):
        self.openai_executor = OpenAIAssistantExecutor()

    # ============================================================
    # EXECUTE WRITE (KANONSKI)
    # ============================================================
    async def execute(
        self,
        *,
        intent: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Prima DOMAIN INTENT i izvršava ga preko agenta.
        """

        # --------------------------------------------------------
        # MAP INTENT → NOTION PAYLOAD (MOZAK)
        # --------------------------------------------------------
        notion_action = self._map_intent_to_notion(intent, payload)

        # --------------------------------------------------------
        # SEND TO AGENT (NO INTELLIGENCE)
        # --------------------------------------------------------
        try:
            agent_result = await self.openai_executor.execute(
                {
                    "command": self.AGENT_COMMAND,
                    "payload": notion_action,
                }
            )
        except Exception as e:
            return {
                "success": False,
                "reason": "Agent execution failed",
                "error": str(e),
            }

        return {
            "success": True,
            "agent_result": agent_result,
        }

    # ============================================================
    # INTENT → NOTION (KANONSKI MOST)
    # ============================================================
    def _map_intent_to_notion(
        self,
        intent: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:

        # ---------- TASKS ----------
        if intent == "create_task":
            return {
                "operation": "create_page",
                "db": "tasks",
                "payload": NotionSchemaRegistry.build_create_page_payload(
                    db_key="tasks",
                    properties={
                        "Name": payload["title"],
                        "Status": payload.get("status", "pending"),
                        "Priority": payload.get("priority"),
                        "Description": payload.get("description"),
                    },
                    relations={
                        "Goal": [payload["goal_id"]]
                        if payload.get("goal_id")
                        else []
                    },
                ),
            }

        # ---------- GOALS ----------
        if intent == "create_goal":
            return {
                "operation": "create_page",
                "db": "goals",
                "payload": NotionSchemaRegistry.build_create_page_payload(
                    db_key="goals",
                    properties={
                        "Name": payload["name"],
                        "Status": payload.get("status", "active"),
                        "Priority": payload.get("priority"),
                        "Description": payload.get("description"),
                    },
                ),
            }

        raise ValueError(f"Unknown execution intent: {intent}")

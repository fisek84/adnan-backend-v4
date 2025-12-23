"""
ACTION EXECUTION SERVICE — KANONSKI (EXECUTION ADAPTER)

- izvršava DOMAIN intent preko "glupog" agenta (OpenAI Assistant)
- ne radi governance/approval
- ne radi UX semantiku
- write side-effects moraju ići kroz WriteGateway (SSOT), ovaj servis je adapter
"""

from typing import Dict, Any

from services.agent_router.openai_assistant_executor import OpenAIAssistantExecutor
from services.notion_schema_registry import NotionSchemaRegistry
from services.failure_handler import FailureHandler


class ActionExecutionService:
    """
    Agent-backed executor for mapped actions (e.g. Notion).
    """

    AGENT_COMMAND = "perform_notion_action"

    def __init__(self):
        self.openai_executor = OpenAIAssistantExecutor()
        self.failure_handler = FailureHandler()

    # ============================================================
    # EXECUTE (INTENT → AGENT ACTION)
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

        if not intent:
            return self.failure_handler.classify(
                source="execution",
                reason="Execution intent is required",
            )

        if not isinstance(payload, dict):
            return self.failure_handler.classify(
                source="execution",
                reason="Execution payload must be a dict",
            )

        # --------------------------------------------------------
        # MAP INTENT → NOTION ACTION (MOZAK)
        # --------------------------------------------------------
        try:
            notion_action = self._map_intent_to_notion(intent, payload)
        except Exception as e:
            return self.failure_handler.classify(
                source="execution",
                reason=str(e),
                metadata={"intent": intent, "payload": payload},
            )

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
            return self.failure_handler.classify(
                source="agent",
                reason="Agent execution failed",
                metadata={"error": str(e)},
            )

        # --------------------------------------------------------
        # AGENT RESULT VALIDATION (KANONSKI)
        # --------------------------------------------------------
        if not agent_result:
            return self.failure_handler.classify(
                source="agent",
                reason="Agent returned empty result",
                metadata={"intent": intent},
            )

        return {
            "success": True,
            "execution_state": "SUCCESS",
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

        # =====================================================
        # TASKS
        # =====================================================
        if intent == "create_task":
            title = payload.get("title")
            if not title:
                raise ValueError("create_task requires 'title'")

            relations = {}
            if payload.get("goal_id"):
                relations["Goal"] = [payload["goal_id"]]

            return {
                "operation": "create_page",
                "database": "tasks",
                "payload": NotionSchemaRegistry.build_create_page_payload(
                    db_key="tasks",
                    properties={
                        "Name": title,
                        "Status": payload.get("status", "pending"),
                        "Priority": payload.get("priority"),
                        "Description": payload.get("description"),
                    },
                    relations=relations or None,
                ),
            }

        # =====================================================
        # GOALS (KANONSKI ALIAS)
        # =====================================================
        if intent in {"create_goal", "goal_write"}:
            name = payload.get("name") or payload.get("title")
            if not name:
                raise ValueError("create_goal requires 'name' or 'title'")

            return {
                "operation": "create_page",
                "database": "goals",
                "payload": NotionSchemaRegistry.build_create_page_payload(
                    db_key="goals",
                    properties={
                        "Name": name,
                        "Status": payload.get("status", "active"),
                        "Priority": payload.get("priority"),
                        "Description": payload.get("description"),
                    },
                ),
            }

        # =====================================================
        # UNKNOWN INTENT
        # =====================================================
        raise ValueError(f"Unknown execution intent: {intent}")

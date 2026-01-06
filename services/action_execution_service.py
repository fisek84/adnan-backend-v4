"""
ACTION EXECUTION SERVICE — LEGACY (LLM EXECUTION DISABLED)

- historijski: izvršavao DOMAIN intent preko "glupog" agenta (OpenAI Assistant)
- danas: LLM-based Notion Ops write path je onemogućen u skladu sa ustavom
- governance/approval i write side-effects idu preko:
    - CEO Console → /api/execute/raw → approval → Notion Ops Executor → NotionService
- ovaj servis zadržava samo INTENT → NOTION mapiranje i vraća strukturiranu grešku
"""

from typing import Dict, Any

from services.notion_schema_registry import NotionSchemaRegistry
from services.failure_handler import FailureHandler


class ActionExecutionService:
    """
    Legacy agent-backed executor za mapirane akcije (npr. Notion).

    CANON (nakon ustava):
    - LLM više NE SMIJE biti na write path-u prema Notion-u.
    - Ovaj servis više NE izvršava akcije preko OpenAI Assistants / perform_notion_action.
    - Služi samo kao most za mapiranje intent → notion_action i vraća
      jasnu poruku da je execution ugašen.
    """

    def __init__(self):
        # Legacy OpenAIAssistantExecutor je uklonjen iz ove klase.
        self.failure_handler = FailureHandler()

    # ============================================================
    # EXECUTE (INTENT → NOTION ACTION) — LEGACY DISABLED
    # ============================================================
    async def execute(
        self,
        *,
        intent: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Prima DOMAIN INTENT i mapira ga na Notion akciju,
        ali više NE izvršava akciju preko LLM agenta.

        Svaki poziv vraća strukturiranu grešku da je ovaj execution put onemogućen
        i da write side-effects moraju ići preko canonical approval-based Notion Ops Executor-a.
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
        # MAP INTENT → NOTION ACTION (MOZAK OSTaje)
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
        # LLM-BASED EXECUTION JE ONEMOGUĆEN (CANON)
        # --------------------------------------------------------
        return self.failure_handler.classify(
            source="execution",
            reason=(
                "ActionExecutionService.execute (LLM-based Notion Ops) je onemogućen. "
                "Write path mora ići preko approval-based Notion Ops Executor-a "
                "(/api/execute/raw → approval → NotionService)."
            ),
            metadata={
                "intent": intent,
                "payload": payload,
                "notion_action": notion_action,
                "legacy_path": "disabled",
            },
        )

    # ============================================================
    # INTENT → NOTION (KANONSKI MOST — LOGIKA OSTaje)
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

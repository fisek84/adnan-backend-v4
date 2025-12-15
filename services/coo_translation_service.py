# services/coo_translation_service.py

"""
COO TRANSLATION SERVICE (CANONICAL)

Uloga:
- JEDINA dozvoljena granica između UX jezika i sistemskog jezika
- prevodi Intent + context → AICommand
- vrši FINALNU validaciju prije executiona

Ovdje se:
- NE izvršava
- NE priča sa agentima
- NE piše memorija
"""

from typing import Optional, Dict, Any

from models.ai_command import AICommand
from services.intent_classifier import IntentClassifier
from services.intent_contract import Intent
from services.action_dictionary import (
    is_valid_command,
    get_action_definition,
)


class COOTranslationService:

    def __init__(self):
        self.intent_classifier = IntentClassifier()

    # =========================================================
    # MAIN ENTRYPOINT
    # =========================================================
    def translate(
        self,
        raw_input: str,
        *,
        source: str,
        context: Dict[str, Any],
    ) -> Optional[AICommand]:
        """
        Returns:
        - AICommand (validated=True)
        - None (REJECT)
        """

        # -----------------------------------------------------
        # 1. INTENT CLASSIFICATION (DETERMINISTIC)
        # -----------------------------------------------------
        intent: Intent = self.intent_classifier.classify(
            raw_input,
            source=source,
        )

        # Low confidence → reject
        if intent.confidence < self.intent_classifier.DEFAULT_CONFIDENCE_THRESHOLD:
            return None

        # Non-executable intents → handled by UX
        if not intent.is_executable:
            return None

        # -----------------------------------------------------
        # 2. MAP INTENT → SYSTEM COMMAND
        # -----------------------------------------------------
        command_name = self._map_intent_to_command(intent)
        if not command_name:
            return None

        if not is_valid_command(command_name):
            return None

        definition = get_action_definition(command_name)

        # Source validation
        if source not in definition.get("allowed_sources", []):
            return None

        # Executor is REQUIRED for execution
        executor = context.get("executor")
        if not executor:
            return None

        # -----------------------------------------------------
        # 3. BUILD AICommand (SYSTEM LANGUAGE)
        # -----------------------------------------------------
        ai_command = AICommand(
            command=command_name,
            intent=intent.type.value,
            source=source,
            input=self._build_payload(intent, context),
            params={},
            metadata={
                "context_type": context.get("context_type", "system"),
                "executor": executor,
            },
            validated=True,
        )

        return ai_command

    # =========================================================
    # INTERNAL HELPERS
    # =========================================================
    def _map_intent_to_command(self, intent: Intent) -> Optional[str]:
        """
        Deterministic mapping.
        NO heuristics.
        """

        allowed = intent.allowed_commands
        if not allowed:
            return None

        # If only one allowed → choose it
        if len(allowed) == 1:
            return allowed[0]

        # Multiple allowed commands not supported yet
        return None

    def _build_payload(
        self,
        intent: Intent,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build execution payload from intent + context.
        """

        payload: Dict[str, Any] = {}

        # Always keep raw text for traceability
        payload["raw_text"] = intent.payload.get("raw_text")

        # Pass-through contextual bindings
        if "current_goal_id" in context:
            payload["goal_id"] = context["current_goal_id"]

        if "current_task_id" in context:
            payload["task_id"] = context["current_task_id"]

        return payload

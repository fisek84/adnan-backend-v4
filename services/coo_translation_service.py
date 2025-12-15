"""
COO TRANSLATION SERVICE (CANONICAL)

Uloga:
- JEDINA dozvoljena granica između UX jezika i sistemskog jezika
- prevodi Intent + context → AICommand
- FINALNI hard-gate prije executiona
- NIKAD ne izvršava
- NIKAD ne preskače approval

FAZA 2: READ-ONLY
FAZA 3: WRITE dozvoljen ISKLJUČIVO uz approval_id
"""

from typing import Optional, Dict, Any

from models.ai_command import AICommand
from services.intent_classifier import IntentClassifier
from services.intent_contract import Intent, IntentType
from services.action_dictionary import is_valid_command


class COOTranslationService:

    READ_ONLY_COMMAND = "system_query"

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
        - None (REJECT / HARD BLOCK)
        """

        # -----------------------------------------------------
        # 1. INTENT CLASSIFICATION
        # -----------------------------------------------------
        intent: Intent = self.intent_classifier.classify(
            raw_input,
            source=source,
        )

        if intent.confidence < self.intent_classifier.DEFAULT_CONFIDENCE_THRESHOLD:
            return None

        if not intent.is_executable:
            return None

        # -----------------------------------------------------
        # 2. READ PATH (FAZA 2)
        # -----------------------------------------------------
        if intent.type == IntentType.SYSTEM_QUERY:
            command_name = self.READ_ONLY_COMMAND

            if not is_valid_command(command_name):
                return None

            return AICommand(
                command=command_name,
                intent=intent.type.value,
                input=self._build_payload(intent, context),
                params={},
                metadata={
                    "context_type": context.get("context_type", "system"),
                },
                validated=True,
            )

        # -----------------------------------------------------
        # 3. WRITE PATH (FAZA 3 — HARD GATE)
        # -----------------------------------------------------
        approval_id = context.get("approval_id")
        if not approval_id:
            # Bez approvala — Translation NE SMIJE raditi
            return None

        command_name = intent.type.value

        if not is_valid_command(command_name):
            return None

        return AICommand(
            command=command_name,
            intent=intent.type.value,
            input=self._build_payload(intent, context),
            params={},
            metadata={
                "context_type": context.get("context_type", "system"),
                "approval_id": approval_id,
            },
            validated=True,
        )

    # =========================================================
    # INTERNALS
    # =========================================================
    def _build_payload(
        self,
        intent: Intent,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:

        payload: Dict[str, Any] = {
            "raw_text": intent.payload.get("raw_text")
        }

        if "current_goal_id" in context:
            payload["goal_id"] = context["current_goal_id"]

        if "current_task_id" in context:
            payload["task_id"] = context["current_task_id"]

        return payload

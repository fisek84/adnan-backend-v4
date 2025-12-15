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
    IDENTITY_COMMAND = "system_identity"
    INBOX_COMMAND = "system_notion_inbox"
    INBOX_DELEGATION_PREVIEW_COMMAND = "system_inbox_delegation_preview"

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
        # 2. READ — IDENTITY
        # -----------------------------------------------------
        if intent.type in {
            IntentType.IDENTITY,
            IntentType.GREETING,
            IntentType.WHO_ARE_YOU,
        }:
            if not is_valid_command(self.IDENTITY_COMMAND):
                return None

            return AICommand(
                command=self.IDENTITY_COMMAND,
                intent=intent.type.value,
                input={"raw_text": intent.payload.get("raw_text")},
                params={},
                metadata={"context_type": "system"},
                validated=True,
            )

        # -----------------------------------------------------
        # 3. READ — NOTION INBOX / DELEGATION PREVIEW
        # -----------------------------------------------------
        if intent.type in {
            IntentType.STATUS,
            IntentType.FOCUS,
            IntentType.SYSTEM_QUERY,
        }:
            text = (intent.payload.get("raw_text") or "").lower()

            # --- DELEGATION PREVIEW (NOVO) ---
            if any(k in text for k in ["delegir", "šta ćemo", "sta cemo", "šta sa inbox", "inbox deleg"]):
                if not is_valid_command(self.INBOX_DELEGATION_PREVIEW_COMMAND):
                    return None

                return AICommand(
                    command=self.INBOX_DELEGATION_PREVIEW_COMMAND,
                    intent=intent.type.value,
                    input={"raw_text": intent.payload.get("raw_text")},
                    params={},
                    metadata={"context_type": "system"},
                    validated=True,
                )

            # --- STANDARD INBOX ---
            if any(k in text for k in ["inbox", "notion", "zadac", "task", "za tebe"]):
                if not is_valid_command(self.INBOX_COMMAND):
                    return None

                return AICommand(
                    command=self.INBOX_COMMAND,
                    intent=intent.type.value,
                    input={"raw_text": intent.payload.get("raw_text")},
                    params={},
                    metadata={"context_type": "system"},
                    validated=True,
                )

        # -----------------------------------------------------
        # 4. READ — GENERIC SYSTEM QUERY
        # -----------------------------------------------------
        if intent.type == IntentType.SYSTEM_QUERY:
            if not is_valid_command(self.READ_ONLY_COMMAND):
                return None

            return AICommand(
                command=self.READ_ONLY_COMMAND,
                intent=intent.type.value,
                input=self._build_payload(intent, context),
                params={},
                metadata={"context_type": context.get("context_type", "system")},
                validated=True,
            )

        # -----------------------------------------------------
        # 5. WRITE PATH (FAZA 3 — HARD GATE)
        # -----------------------------------------------------
        approval_id = context.get("approval_id")
        if not approval_id:
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

from typing import Dict, Any, Optional

from services.decision_engine.identity_reasoning import IdentityReasoningEngine
from services.decision_engine.context_classifier import ContextClassifier
from services.decision_engine.final_response_engine import FinalResponseEngine
from services.decision_engine.playbook_engine import PlaybookEngine

from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.memory_service import MemoryService


class ContextOrchestrator:
    """
    CEO-level orchestrator.

    FAZA 2: chat kontinuitet
    FAZA 4–6: SOP → playbook → execution plan → delegation
    FAZA 20: NON-SOP semantic business objects
    """

    def __init__(
        self,
        identity: Dict[str, Any],
        mode: Dict[str, Any],
        state: Dict[str, Any],
    ):
        self.identity = identity
        self.mode = mode
        self.state = state

        # Engines
        self.reasoner = IdentityReasoningEngine(identity, mode, state)
        self.classifier = ContextClassifier()
        self.response_engine = FinalResponseEngine(identity)
        self.playbook_engine = PlaybookEngine()

        # Services
        self.decision_engine = AdnanAIDecisionService()
        self.memory_engine = MemoryService()

        self._last_human_answer: Optional[str] = None

    # ============================================================
    # MAIN ORCHESTRATION
    # ============================================================
    async def run(self, user_input: str) -> Dict[str, Any]:

        identity_reasoning = self.reasoner.generate_reasoning(user_input)
        classification = self.classifier.classify(
            user_input,
            identity_reasoning,
        )

        context_type = classification.get("context_type")

        if context_type == "identity":
            result = self._handle_identity(user_input, identity_reasoning)

        elif context_type == "chat":
            result = self._handle_chat(user_input)

        elif context_type == "memory":
            result = self._handle_memory(user_input)

        elif context_type == "sop":
            result = self._handle_sop(
                user_input=user_input,
                identity_reasoning=identity_reasoning,
                context=classification,
            )

        elif context_type in {"business", "notion", "agent"}:
            result = self._delegate_operation(user_input)

        elif context_type == "meta":
            result = self._handle_meta(user_input)

        else:
            result = {
                "type": "unknown",
                "response": "Nepoznat kontekst.",
            }

        final_output = self.response_engine.format_response(
            identity_reasoning=identity_reasoning,
            classification=classification,
            result=result,
        )

        if context_type in {"chat", "identity"}:
            self._last_human_answer = final_output.get("final_answer")

        return {
            "success": True,
            "context_type": context_type,
            "result": result,
            "final_output": final_output,
        }

    # ============================================================
    # NON-SOP BUSINESS DELEGATION (FIX)
    # ============================================================
    def _delegate_operation(self, user_input: str) -> Dict[str, Any]:

        decision = self.decision_engine.process_ceo_instruction(user_input)
        command = decision.get("command")
        payload = decision.get("payload", {})

        lower = user_input.lower()

        # -----------------------------
        # GOAL SEMANTIC OBJECT
        # -----------------------------
        if command == "create_database_entry" and any(
            k in lower for k in ["cilj", "goal", "objective"]
        ):
            title = payload.get("title") or user_input.split(":")[-1].strip()

            payload = {
                "database_key": "goals",
                "properties": {
                    "Name": {
                        "title": [
                            {
                                "text": {
                                    "content": title
                                }
                            }
                        ]
                    },
                    "Status": {
                        "select": {
                            "name": "Active"
                        }
                    }
                },
            }

        return {
            "type": "delegation",
            "context": "business",
            "delegation": {
                "command": command,
                "payload": payload,
            },
        }

    # ============================================================
    # OTHER HANDLERS (UNCHANGED)
    # ============================================================
    def _handle_identity(self, user_input: str, reasoning: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "identity",
            "response": "Ja sam Adnan.AI — digitalni CEO sistema Evolia.",
        }

    def _handle_chat(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "chat",
            "response": user_input,
        }

    def _handle_memory(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "memory",
            "response": self.memory_engine.process(user_input),
        }

    def _handle_meta(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "meta",
            "response": {"input": user_input},
        }

    def _handle_sop(
        self,
        user_input: str,
        identity_reasoning: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:

        playbook_result = self.playbook_engine.evaluate(
            user_input=user_input,
            identity_reasoning=identity_reasoning,
            context=context,
        )

        if playbook_result.get("type") != "sop_execution":
            return {
                "type": "sop",
                "response": "SOP nije moguće izvršiti.",
            }

        return {
            "type": "delegation",
            "context": "sop",
            "delegation": {
                "sop": playbook_result.get("sop"),
                "plan": playbook_result.get("execution_plan"),
            },
        }

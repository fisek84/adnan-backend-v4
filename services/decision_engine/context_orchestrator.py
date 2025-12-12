from typing import Dict, Any, Optional

from services.decision_engine.identity_reasoning import IdentityReasoningEngine
from services.decision_engine.context_classifier import ContextClassifier
from services.decision_engine.final_response_engine import FinalResponseEngine
from services.decision_engine.playbook_engine import PlaybookEngine
from services.decision_engine.sop_mapper import SOPMapper

from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.memory_service import MemoryService


class ContextOrchestrator:
    """
    CEO-level orchestrator.

    FAZA 2: chat kontinuitet
    FAZA 4–6: SOP → playbook → execution plan → delegation
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

        # FAZA 2 — last human-facing answer
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

        # --------------------------------------------------------
        # ROUTING
        # --------------------------------------------------------
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
            result = self._delegate_operation(
                user_input=user_input,
                context_type=context_type,
            )

        elif context_type == "meta":
            result = self._handle_meta(user_input)

        else:
            result = {
                "type": "unknown",
                "response": "Nepoznat kontekst.",
            }

        # --------------------------------------------------------
        # FINAL RESPONSE
        # --------------------------------------------------------
        final_output = self.response_engine.format_response(
            identity_reasoning=identity_reasoning,
            classification=classification,
            result=result,
        )

        # --------------------------------------------------------
        # FAZA 2 — STORE LAST HUMAN ANSWER
        # --------------------------------------------------------
        if context_type in {"chat", "identity"}:
            self._last_human_answer = final_output.get("final_answer")

        return {
            "success": True,
            "context_type": context_type,
            "identity_reasoning": identity_reasoning,
            "classification": classification,
            "result": result,
            "final_output": final_output,
        }

    # ============================================================
    # HANDLERS
    # ============================================================
    def _handle_identity(
        self,
        user_input: str,
        reasoning: Dict[str, Any],
    ) -> Dict[str, Any]:

        lower = user_input.lower()

        if any(
            q in lower
            for q in [
                "ko si",
                "ko si ti",
                "šta si ti",
                "ko je adnan.ai",
                "tvoj identitet",
            ]
        ):
            text = "Ja sam Adnan.AI — digitalni CEO i orkestrator sistema Evolia."
        else:
            text = "Razumijem."

        return {
            "type": "identity",
            "response": text,
            "reasoning": reasoning,
        }

    def _handle_chat(self, user_input: str) -> Dict[str, Any]:
        lower = user_input.lower().strip()

        FOLLOW_UP_MARKERS = [
            "zašto", "zasto", "a zašto", "a zasto",
            "kako", "možeš", "mozes",
            "pojasni", "šta onda", "sta onda",
            "i dalje", "dalje", "a onda",
        ]

        is_follow_up = any(lower.startswith(m) or m in lower for m in FOLLOW_UP_MARKERS)

        if is_follow_up and self._last_human_answer:
            response = self._last_human_answer
        else:
            response = user_input

        return {
            "type": "chat",
            "response": response,
        }

    def _handle_memory(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "memory",
            "response": self.memory_engine.process(user_input),
        }

    def _handle_meta(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "meta",
            "response": {
                "status": "meta-command-received",
                "input": user_input,
            },
        }

    # ============================================================
    # SOP HANDLER — KANONSKI (FAZA 6)
    # ============================================================
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

    # ============================================================
    # GENERIC DELEGATION (NON-SOP)
    # ============================================================
    def _delegate_operation(
        self,
        user_input: str,
        context_type: str,
    ) -> Dict[str, Any]:

        decision = self.decision_engine.process_ceo_instruction(user_input)

        return {
            "type": "delegation",
            "context": context_type,
            "delegation": {
                "command": decision.get("command"),
                "payload": decision.get("payload"),
            },
        }

from typing import Dict, Any
import hashlib

from .identity_reasoning import IdentityReasoningEngine
from .context_classifier import ContextClassifier
from .final_response_engine import FinalResponseEngine
from .playbook_engine import PlaybookEngine

from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.memory_service import MemoryService
from services.sop_knowledge_registry import SOPKnowledgeRegistry
from services.conversation_state_service import ConversationStateService

CONFIRMATION_KEYWORDS = {
    "da", "yes", "potvrdi", "potvrđujem", "ok", "u redu", "izvrši", "izvrsi"
}


class ContextOrchestrator:
    """
    CEO-level orchestrator.

    FAZA SOP-KI: SOP Knowledge Intelligence (READ-ONLY)
    FAZA CSI: Conversation State Intelligence
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

        self.reasoner = IdentityReasoningEngine(identity, mode, state)
        self.classifier = ContextClassifier()
        self.response_engine = FinalResponseEngine(identity)
        self.playbook_engine = PlaybookEngine()

        self.decision_engine = AdnanAIDecisionService()
        self.memory_engine = MemoryService()

        self.sop_registry = SOPKnowledgeRegistry()
        self.conversation_state = ConversationStateService()

    # ============================================================
    # MAIN ENTRY
    # ============================================================
    async def run(self, user_input: str) -> Dict[str, Any]:
        normalized = (user_input or "").lower().strip()
        state = self.conversation_state.get()

        # ============================================================
        # SOP LIST
        # ============================================================
        if normalized in {"sop", "pokaži sop", "pokazi sop", "lista sop"}:
            sops = self.sop_registry.list_sops()
            self.conversation_state.set_sop_list(sops)

            items = [
                f"{i+1}. {sop['name']} (v{sop.get('version', '1.0')})"
                for i, sop in enumerate(sops)
            ]

            return self._final_read_only({
                "type": "sop_list",
                "response": {
                    "topic": "SOP_LIST",
                    "items": items,
                },
            })

        # ============================================================
        # SOP NUMERIC SELECTION
        # ============================================================
        if state["state"] == "SOP_LIST" and state["expected_input"] == "sop_selection":
            if normalized.isdigit():
                index = int(normalized) - 1
                sops = state.get("sop_list", [])

                if 0 <= index < len(sops):
                    sop_meta = sops[index]
                    sop_id = sop_meta["id"]

                    self.conversation_state.set_active_sop(sop_id)

                    sop = self.sop_registry.get_sop(sop_id, mode="full")
                    content = sop["content"]

                    items = [
                        f"Naziv: {content.get('name')}",
                        f"Verzija: {content.get('version')}",
                        f"Opis: {content.get('description', '')}",
                        "",
                        "Koraci:",
                        *[
                            f"{step.get('step')}. {step.get('title')}"
                            for step in content.get("steps", [])
                        ],
                        "",
                        "Ako želiš izvršenje, napiši: izvrši ovaj sop",
                    ]

                    return self._final_read_only({
                        "type": "sop_detail",
                        "response": {
                            "topic": "SOP",
                            "items": items,
                        },
                    })

            self.conversation_state.set_idle()

        # ============================================================
        # SOP EXECUTION REQUEST
        # ============================================================
        if state["state"] == "SOP_ACTIVE" and "izvrši" in normalized:
            fingerprint = hashlib.sha256(normalized.encode()).hexdigest()

            self.conversation_state.set_pending_decision(
                text=f"execute sop:{state['active_sop_id']}",
                fingerprint=fingerprint,
            )

            return self._final_read_only({
                "type": "decision_candidate",
                "response": "Želiš li potvrditi izvršenje ovog SOP-a? (da / ok)",
            })

        # ============================================================
        # CONFIRMATION  ✅ KLJUČNA POPRAVKA
        # ============================================================
        state = self.conversation_state.get()  # 🔥 OBAVEZNO REFRESH

        if (
            state["state"] == "DECISION_PENDING"
            and state["expected_input"] == "confirmation"
            and normalized in CONFIRMATION_KEYWORDS
        ):
            pending = state.get("pending_decision") or {}

            execution = self.decision_engine.process_ceo_instruction(
                pending.get("text", "")
            )

            self.conversation_state.set_executing()
            self.memory_engine.set_active_decision(execution)
            self.conversation_state.set_idle()

            return {
                "success": True,
                "context_type": "execution",
                "decision_intent": "confirmed",
                "result": {
                    "type": "delegation",
                    "delegation": execution,
                },
                "final_output": {
                    "final_answer": execution.get(
                        "system_response",
                        "SOP je potvrđen i delegiran."
                    )
                },
            }

        # ============================================================
        # FALLBACK
        # ============================================================
        return self._final_read_only({
            "type": "chat",
            "response": "Razumio sam. Nastavi.",
        })

    # ============================================================
    # READ-ONLY WRAPPER
    # ============================================================
    def _final_read_only(self, result: Dict[str, Any]) -> Dict[str, Any]:
        final = self.response_engine.format_response(
            identity_reasoning=None,
            classification={"context_type": "knowledge"},
            result=result,
        )
        return {
            "success": True,
            "context_type": "knowledge",
            "decision_intent": "read_only",
            "result": result,
            "final_output": final,
        }

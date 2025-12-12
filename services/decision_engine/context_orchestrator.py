from typing import Dict, Any, Optional, List
import hashlib

from .identity_reasoning import IdentityReasoningEngine
from .context_classifier import ContextClassifier
from .final_response_engine import FinalResponseEngine
from .playbook_engine import PlaybookEngine

from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.memory_service import MemoryService
from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.sop_knowledge_registry import SOPKnowledgeRegistry
from services.conversation_state_service import ConversationStateService

CONFIRMATION_KEYWORDS = {
    "da", "yes", "potvrdi", "potvrđujem", "ok", "u redu", "izvrši", "izvrsi"
}


class ContextOrchestrator:
    """
    CEO-level orchestrator.

    FAZA 1–8: postojeće ponašanje
    FAZA 17: Intent hardening + confirmation binding
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

        # SOP KNOWLEDGE
        self.sop_registry = SOPKnowledgeRegistry()

        # CONVERSATION STATE INTELLIGENCE (CANONICAL)
        self.conversation_state = ConversationStateService()

        # Pending decision (execution)
        self._pending_decision: Optional[str] = None
        self._pending_fingerprint: Optional[str] = None

    async def run(self, user_input: str) -> Dict[str, Any]:
        normalized = (user_input or "").lower().strip()
        state = self.conversation_state.get()

        # ============================================================
        # SOP LIST REQUEST
        # ============================================================
        if normalized in {"sop", "pokaži sop", "pokazi sop", "lista sop"}:
            sops = self.sop_registry.list_sops()
            self.conversation_state.set_sop_list(sops)

            numbered = [
                f"{i+1}. {sop['name']} (v{sop.get('version', '1.0')})"
                for i, sop in enumerate(sops)
            ]

            return self._final_read_only({
                "type": "sop_list",
                "response": {
                    "message": "Ovo su SOP-ovi u sistemu. Reci broj (1, 2, 3…) ili ime SOP-a.",
                    "items": numbered,
                }
            })

        # ============================================================
        # SOP NUMERIC SELECTION (CSI)
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
                    playbook = self.playbook_engine.evaluate(
                        user_input=sop_meta["name"],
                        identity_reasoning={},
                        context={"context_type": "sop"},
                    )

                    return self._final_read_only({
                        "type": "sop_detail",
                        "response": {
                            "sop": sop["content"],
                            "playbook": playbook,
                            "hint": "Ako želiš izvršenje, napiši: izvrši ovaj sop",
                        },
                    })

            # invalid input → reset SOP flow
            self.conversation_state.set_idle()

        # ============================================================
        # SOP NAME SELECTION (CSI)
        # ============================================================
        if state["state"] == "SOP_LIST":
            for sop_meta in state.get("sop_list", []):
                if sop_meta["name"].lower() in normalized:
                    sop_id = sop_meta["id"]
                    self.conversation_state.set_active_sop(sop_id)

                    sop = self.sop_registry.get_sop(sop_id, mode="full")
                    playbook = self.playbook_engine.evaluate(
                        user_input=sop_meta["name"],
                        identity_reasoning={},
                        context={"context_type": "sop"},
                    )

                    return self._final_read_only({
                        "type": "sop_detail",
                        "response": {
                            "sop": sop["content"],
                            "playbook": playbook,
                            "hint": "Ako želiš izvršenje, napiši: izvrši ovaj sop",
                        },
                    })

        # ============================================================
        # SOP EXECUTION REQUEST (PENDING)
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
        # CONFIRMATION
        # ============================================================
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
        # FALLBACK (READ-ONLY CHAT)
        # ============================================================
        return self._final_read_only({
            "type": "chat",
            "response": "Razumio sam. Nastavi.",
        })

    # ============================================================
    # HELPERS
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

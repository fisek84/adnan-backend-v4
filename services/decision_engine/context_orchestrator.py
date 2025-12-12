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
    "da", "yes", "ok", "potvrdi", "potvrđujem"
}


class ContextOrchestrator:
    """
    SOP + CSI orchestrator (KANONSKI)
    """

    def __init__(self, identity: Dict[str, Any], mode: Dict[str, Any], state: Dict[str, Any]):
        self.identity = identity
        self.mode = mode
        self.state = state

        self.response_engine = FinalResponseEngine(identity)
        self.playbook_engine = PlaybookEngine()
        self.decision_engine = AdnanAIDecisionService()
        self.memory_engine = MemoryService()
        self.sop_registry = SOPKnowledgeRegistry()
        self.conversation_state = ConversationStateService()

    async def run(self, user_input: str) -> Dict[str, Any]:
        normalized = (user_input or "").strip().lower()
        state = self.conversation_state.get()

        # -------------------------------------------------
        # SOP LIST
        # -------------------------------------------------
        if normalized in {"sop", "pokaži sop", "pokazi sop", "lista sop"}:
            sops = self.sop_registry.list_sops()
            self.conversation_state.set_sop_list(sops)

            return self._final({
                "type": "sop_list",
                "response": {
                    "topic": "SOP_LIST",
                    "items": [
                        f"{i+1}. {s['name']} (v{s.get('version','1.0')})"
                        for i, s in enumerate(sops)
                    ]
                }
            })

        # -------------------------------------------------
        # SOP SELECT
        # -------------------------------------------------
        if state["state"] == "SOP_LIST" and normalized.isdigit():
            idx = int(normalized) - 1
            sops = state.get("sop_list", [])

            if 0 <= idx < len(sops):
                sop_id = sops[idx]["id"]
                self.conversation_state.set_active_sop(sop_id)

                sop = self.sop_registry.get_sop(sop_id, mode="full")["content"]

                return self._final({
                    "type": "sop_detail",
                    "response": {
                        "topic": "SOP",
                        "items": [
                            f"Naziv: {sop['name']}",
                            f"Verzija: {sop['version']}",
                            f"Opis: {sop.get('description','')}",
                            "",
                            "Koraci:",
                            *[f"{s['step']}. {s['title']}" for s in sop.get("steps", [])],
                            "",
                            "Ako želiš izvršenje, napiši: izvrši ovaj sop"
                        ]
                    }
                })

        # -------------------------------------------------
        # EXECUTION REQUEST
        # -------------------------------------------------
        if state["state"] == "SOP_ACTIVE" and normalized == "izvrši ovaj sop":
            self.conversation_state.set_pending_decision(
                text=f"execute sop:{state['active_sop_id']}",
                fingerprint=hashlib.sha256(normalized.encode()).hexdigest(),
            )

            return self._final({
                "type": "decision_candidate",
                "response": "Želiš li potvrditi izvršenje ovog SOP-a? (da / ok)"
            })

        # -------------------------------------------------
        # CONFIRMATION ✅ OVDJE JE POPRAVKA
        # -------------------------------------------------
        if (
            state["state"] == "DECISION_PENDING"
            and state["expected_input"] == "confirmation"
            and normalized in CONFIRMATION_KEYWORDS
        ):
            pending = state["pending_decision"]
            execution = self.decision_engine.process_ceo_instruction(pending["text"])

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
                    "final_answer": "SOP je potvrđen za izvršenje."
                }
            }

        # -------------------------------------------------
        # FALLBACK
        # -------------------------------------------------
        return self._final({
            "type": "chat",
            "response": "Razumijem. Nastavi."
        })

    def _final(self, result: Dict[str, Any]) -> Dict[str, Any]:
        final = self.response_engine.format_response(
            identity_reasoning=None,
            classification={"context_type": "knowledge"},
            result=result,
        )
        return {
            "success": True,
            "context_type": "knowledge",
            "result": result,
            "final_output": final,
        }

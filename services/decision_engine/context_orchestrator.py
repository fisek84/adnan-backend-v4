from typing import Dict, Any, Optional, List
import hashlib

from services.decision_engine.identity_reasoning import IdentityReasoningEngine
from services.decision_engine.context_classifier import ContextClassifier
from services.decision_engine.final_response_engine import FinalResponseEngine
from services.decision_engine.playbook_engine import PlaybookEngine

from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.memory_service import MemoryService
from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.sop_knowledge_registry import SOPKnowledgeRegistry


CONFIRMATION_KEYWORDS = {
    "da", "yes", "potvrdi", "potvrđujem", "ok", "u redu", "izvrši", "izvrsi"
}


class ContextOrchestrator:
    """
    CEO-level orchestrator.

    FAZA 1–8: postojeće ponašanje
    FAZA 17: Intent hardening + confirmation binding
    FAZA SOP-KI: SOP Knowledge Intelligence (READ-ONLY)
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
        self._last_sop_list: Optional[List[Dict[str, Any]]] = None
        self._active_sop: Optional[str] = None

        # Pending decision
        self._pending_decision: Optional[str] = None
        self._pending_fingerprint: Optional[str] = None

    async def run(self, user_input: str) -> Dict[str, Any]:
        normalized = (user_input or "").lower().strip()

        # ============================================================
        # SOP LIST (READ-ONLY)
        # ============================================================
        if normalized in {"sop", "pokaži sop", "pokazi sop", "lista sop"}:
            sops = self.sop_registry.list_sops()
            self._last_sop_list = sops

            lines = ["Imamo sljedeće SOP-ove:"]
            for i, sop in enumerate(sops, start=1):
                lines.append(f"{i}. {sop['name']} (v{sop.get('version', '1.0')})")

            lines.append("Reci broj (1, 2, 3…) ili ime SOP-a.")

            return self._final_read_only({
                "type": "sop_list",
                "response": "\n".join(lines)
            })

        # ============================================================
        # SOP NUMERIC SELECTION
        # ============================================================
        if normalized.isdigit() and self._last_sop_list:
            idx = int(normalized) - 1
            if 0 <= idx < len(self._last_sop_list):
                sop_meta = self._last_sop_list[idx]
                self._active_sop = sop_meta["id"]

                sop = self.sop_registry.get_sop(self._active_sop, mode="full")
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
        # SOP NAME SELECTION
        # ============================================================
        if self._last_sop_list:
            for sop_meta in self._last_sop_list:
                if sop_meta["name"].lower() in normalized:
                    self._active_sop = sop_meta["id"]

                    sop = self.sop_registry.get_sop(self._active_sop, mode="full")
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
        if self._active_sop and "izvrši" in normalized:
            self._set_pending(f"execute sop:{self._active_sop}")
            return self._final_read_only({
                "type": "decision_candidate",
                "response": "Želiš li potvrditi izvršenje ovog SOP-a? (da / ok)",
            })

        # ============================================================
        # CONFIRMATION
        # ============================================================
        if self._pending_decision and self._is_confirmation(normalized):
            execution = self.decision_engine.process_ceo_instruction(
                self._pending_decision
            )
            self.memory_engine.set_active_decision(execution)
            self._clear_pending()

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
            "response": "Razumio sam. Nastavi."
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

    def _set_pending(self, text: str):
        self._pending_decision = text
        self._pending_fingerprint = hashlib.sha256(text.encode()).hexdigest()

    def _clear_pending(self):
        self._pending_decision = None
        self._pending_fingerprint = None

    def _is_confirmation(self, text: str) -> bool:
        return text in CONFIRMATION_KEYWORDS

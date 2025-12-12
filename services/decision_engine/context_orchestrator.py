from typing import Dict, Any, Optional
import hashlib

from services.decision_engine.identity_reasoning import IdentityReasoningEngine
from services.decision_engine.context_classifier import ContextClassifier
from services.decision_engine.final_response_engine import FinalResponseEngine
from services.decision_engine.playbook_engine import PlaybookEngine

from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.memory_service import MemoryService
from services.knowledge_snapshot_service import KnowledgeSnapshotService


CONFIRMATION_KEYWORDS = {
    "da", "yes", "potvrdi", "potvrđujem", "ok", "u redu", "izvrši", "izvrsi"
}


class ContextOrchestrator:
    """
    CEO-level orchestrator.

    FAZA 1–8: postojeće ponašanje
    FAZA 17: Intent hardening + confirmation binding
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

        # FAZA 17 — hardened pending decision
        self._pending_decision: Optional[str] = None
        self._pending_fingerprint: Optional[str] = None

    async def run(self, user_input: str) -> Dict[str, Any]:

        normalized = (user_input or "").lower().strip()

        # ============================================================
        # FAZA 8 — STATUS QUERY
        # ============================================================
        if normalized in {"status", "gdje smo", "šta radimo", "sta radimo"}:
            active = self.memory_engine.get_active_decision()
            result = {
                "type": "status",
                "response": active or "Nema aktivne odluke."
            }

            final_output = self.response_engine.format_response(
                identity_reasoning=None,
                classification={"context_type": "status"},
                result=result,
            )

            return {
                "success": True,
                "context_type": "status",
                "decision_intent": "read_only",
                "result": result,
                "final_output": final_output,
            }

        # ============================================================
        # FAZA 6 + FAZA 17 — CONFIRMATION GUARD (HARDENED)
        # ============================================================
        if self._pending_decision and not self._is_confirmation(normalized):
            # ako korisnik krene novu temu → poništi pending
            self._clear_pending()
            return {
                "success": True,
                "context_type": "confirmation_cancelled",
                "decision_intent": "cancelled",
                "result": {
                    "type": "decision_candidate",
                    "message": "Prethodna odluka je poništena. Možemo nastaviti dalje.",
                },
                "final_output": {
                    "final_answer": "Prethodna odluka je poništena."
                },
            }

        # ============================================================
        # FAZA 5/6 → FAZA 7 — CONFIRMATION ACCEPTED (BOUND)
        # ============================================================
        if self._pending_decision and self._is_confirmation(normalized):
            execution = self.decision_engine.process_ceo_instruction(
                self._pending_decision
            )

            # FAZA 8 — STORE ACTIVE DECISION
            self.memory_engine.set_active_decision(execution)

            self._clear_pending()

            return {
                "success": True,
                "context_type": "execution",
                "decision_intent": "confirmed",
                "result": {
                    "type": "delegation",
                    "agent": "ops_layer",
                    "delegation": execution,
                },
                "final_output": {
                    "final_answer": execution.get(
                        "system_response",
                        "Zadatak je potvrđen i delegiran."
                    )
                },
            }

        # ============================================================
        # NORMAL FLOW
        # ============================================================
        identity_reasoning = self.reasoner.generate_reasoning(user_input)
        classification = self.classifier.classify(user_input, identity_reasoning)
        context_type = classification.get("context_type")

        decision_intent = self._derive_decision_intent(context_type)

        if context_type == "identity":
            result = self._handle_identity()

        elif context_type == "chat":
            result = self._handle_chat(user_input)

        elif context_type == "memory":
            result = self._handle_memory(user_input)

        elif context_type == "knowledge":
            knowledge = self._handle_business_knowledge(user_input)
            result = knowledge if knowledge else self._knowledge_help_result()

        elif context_type == "sop":
            self._set_pending(user_input)
            result = {
                "type": "decision_candidate",
                "message": "Prepoznat SOP. Želiš li da pripremim i izvršim plan?",
            }

        elif context_type in {"business", "notion", "agent"}:
            self._set_pending(user_input)
            result = {
                "type": "decision_candidate",
                "message": "Prepoznata je potencijalna odluka. Da li potvrđuješ izvršenje?",
            }

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

        return {
            "success": True,
            "context_type": context_type,
            "decision_intent": decision_intent,
            "result": result,
            "final_output": final_output,
        }

    # ============================================================
    # FAZA 17 — PENDING MANAGEMENT
    # ============================================================
    def _set_pending(self, text: str):
        self._pending_decision = text
        self._pending_fingerprint = self._fingerprint(text)

    def _clear_pending(self):
        self._pending_decision = None
        self._pending_fingerprint = None

    def _fingerprint(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _is_confirmation(self, text: str) -> bool:
        return text in CONFIRMATION_KEYWORDS

    def _derive_decision_intent(self, context_type: str) -> str:
        if context_type in {"knowledge", "chat", "identity", "meta", "status"}:
            return "read_only"
        if context_type in {"business", "notion", "agent", "sop"}:
            return "decision_candidate"
        return "unknown"

    # ============================================================
    # READ-ONLY KNOWLEDGE
    # ============================================================
    def _handle_business_knowledge(self, user_input: str) -> Optional[Dict[str, Any]]:
        if not KnowledgeSnapshotService.is_ready():
            return None

        snapshot = KnowledgeSnapshotService.get_snapshot()
        databases = snapshot.get("databases")
        if not databases:
            return None

        lower = (user_input or "").lower().strip()

        for key, db in databases.items():
            label = (db.get("label") or "").lower()
            if key in lower or (label and label in lower):
                items = db.get("items", [])
                names = [
                    it.get("name") if isinstance(it, dict) else str(it)
                    for it in items if it
                ]
                return {
                    "type": "knowledge",
                    "response": {
                        "topic": key,
                        "count": len(names),
                        "items": names,
                    },
                }

        return None

    def _knowledge_help_result(self) -> Dict[str, Any]:
        snapshot = KnowledgeSnapshotService.get_snapshot()
        databases = snapshot.get("databases") or {}

        items = [f"{k} → {v.get('label') or k}" for k, v in databases.items()]

        return {
            "type": "knowledge",
            "response": {
                "topic": "help",
                "count": len(items),
                "items": items,
            },
        }

    # ============================================================
    # OTHER HANDLERS
    # ============================================================
    def _handle_identity(self) -> Dict[str, Any]:
        return {
            "type": "identity",
            "response": "Ja sam Adnan.AI — digitalni CEO sistema Evolia.",
        }

    def _handle_chat(self, user_input: str) -> Dict[str, Any]:
        return {"type": "chat", "response": user_input}

    def _handle_memory(self, user_input: str) -> Dict[str, Any]:
        return {"type": "memory", "response": self.memory_engine.process(user_input)}

    def _handle_meta(self, user_input: str) -> Dict[str, Any]:
        return {"type": "meta", "response": {"input": user_input}}

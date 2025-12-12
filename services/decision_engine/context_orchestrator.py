from typing import Dict, Any, Optional

from services.decision_engine.identity_reasoning import IdentityReasoningEngine
from services.decision_engine.context_classifier import ContextClassifier
from services.decision_engine.final_response_engine import FinalResponseEngine
from services.decision_engine.playbook_engine import PlaybookEngine

from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.memory_service import MemoryService

# READ-ONLY KNOWLEDGE
from services.notion_service import NotionService


class ContextOrchestrator:
    """
    CEO-level orchestrator.

    FAZA 1: READ-ONLY poslovna svijest (Notion knowledge)
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

        # READ-ONLY Notion knowledge (injectovan u startupu)
        self.notion_knowledge: Optional[NotionService] = None

        self._last_human_answer: Optional[str] = None

    # ============================================================
    # KNOWLEDGE INJECTION
    # ============================================================
    def attach_notion_knowledge(self, notion_service: NotionService):
        """
        READ-ONLY Notion knowledge.
        Nikad se ne koristi za execution.
        """
        self.notion_knowledge = notion_service

    # ============================================================
    # MAIN ORCHESTRATION
    # ============================================================
    async def run(self, user_input: str) -> Dict[str, Any]:

        identity_reasoning = self.reasoner.generate_reasoning(user_input)
        classification = self.classifier.classify(user_input, identity_reasoning)
        context_type = classification.get("context_type")

        if context_type == "identity":
            result = self._handle_identity()

        elif context_type == "chat":
            result = self._handle_chat(user_input)

        elif context_type == "memory":
            result = self._handle_memory(user_input)

        elif context_type == "knowledge":
            # ČIST READ-ONLY REPORTING
            knowledge = self._handle_business_knowledge(user_input)
            result = knowledge if knowledge else {
                "type": "knowledge",
                "response": "Nema dostupnih podataka za traženi upit.",
            }

        elif context_type == "sop":
            result = self._handle_sop(user_input, identity_reasoning, classification)

        elif context_type in {"business", "notion", "agent"}:
            # prvo pokušaj READ-ONLY znanje
            knowledge = self._handle_business_knowledge(user_input)
            result = knowledge if knowledge else self._delegate_operation(user_input)

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
            "result": result,
            "final_output": final_output,
        }

    # ============================================================
    # READ-ONLY KNOWLEDGE (GLOBAL + PER-DB)
    # ============================================================
    def _handle_business_knowledge(self, user_input: str) -> Optional[Dict[str, Any]]:
        if not self.notion_knowledge:
            return None

        snapshot = self.notion_knowledge.get_knowledge_snapshot()
        if not snapshot or not snapshot.get("databases"):
            return None

        lower = user_input.lower()

        # GLOBAL REPORT (CEO overview)
        if any(w in lower for w in [
            "report", "izvještaj", "izvjestaj",
            "pregled svega", "cijela firma", "stanje firme",
        ]):
            return {
                "type": "knowledge",
                "response": {
                    "topic": "full_report",
                    "databases": snapshot["databases"],
                },
            }

        # POJEDINAČNA BAZA
        for key, db in snapshot["databases"].items():
            label = (db.get("label") or "").lower()
            if key in lower or label in lower:
                return {
                    "type": "knowledge",
                    "response": {
                        "topic": key,
                        "count": len(db.get("items", [])),
                        "items": [item.get("name") for item in db.get("items", [])],
                    },
                }

        return None

    # ============================================================
    # DELEGATION (UNCHANGED)
    # ============================================================
    def _delegate_operation(self, user_input: str) -> Dict[str, Any]:
        decision = self.decision_engine.process_ceo_instruction(user_input)
        return {
            "type": "delegation",
            "context": "business",
            "delegation": decision,
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

from typing import Dict, Any

from .identity_reasoning import IdentityReasoningEngine
from .context_classifier import ContextClassifier
from services.decision_engine.final_response_engine import FinalResponseEngine
from services.decision_engine.playbook_engine import PlaybookEngine

# Postojeći servisi — samo ih importujemo, ne mijenjamo ih
from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.memory_service import MemoryService
from services.notion_service import NotionService
from services.agents_service import AgentsService


class ContextOrchestrator:
    """
    Centralni orkestrator — mozak Adnan.ai sistema.
    ------------------------------------------------
    Prima:
        user_input: str
        identity: dict
        mode: dict
        state: dict

    Radi:
        1. Identity Reasoning
        2. Context Classification
        3. Playbook Business Layer (za business tok)
        4. Odabir toka (identity, business, notion, sop, agent, memory, meta)
        5. Final Response Engine (Adnan-style output)
    """

    def __init__(self, identity: Dict[str, Any], mode: Dict[str, Any], state: Dict[str, Any]):
        self.identity = identity
        self.mode = mode
        self.state = state

        self.reasoner = IdentityReasoningEngine(identity, mode, state)
        self.classifier = ContextClassifier()
        self.response_engine = FinalResponseEngine(identity)
        self.playbook_engine = PlaybookEngine()

        self.decision_engine = AdnanAIDecisionService()
        self.memory_engine = MemoryService()
        self.notion_engine = NotionService()
        self.agents_engine = AgentsService()

    def run(self, user_input: str) -> Dict[str, Any]:
        # 1 — Identity Reasoning
        identity_reasoning = self.reasoner.generate_reasoning(user_input)

        # 2 — Context Classification
        classification = self.classifier.classify(user_input, identity_reasoning)
        context = classification["context_type"]

        # 3 — Routing prema kontekstu
        if context == "identity":
            result = self._handle_identity(user_input, identity_reasoning)

        elif context == "business":
            playbook = self.playbook_engine.evaluate(
                user_input=user_input,
                identity_reasoning=identity_reasoning,
                context=classification
            )
            result = self._handle_business_playbook(user_input, playbook)

        elif context == "notion":
            result = self._handle_notion(user_input)

        elif context == "sop":
            result = self._handle_sop(user_input)

        elif context == "agent":
            result = self._handle_agent_query(user_input)

        elif context == "memory":
            result = self._handle_memory(user_input)

        elif context == "meta":
            result = self._handle_meta(user_input)

        else:
            result = {
                "success": False,
                "system_response": "Nisam siguran u kontekst.",
                "context_type": context,
            }

        # 4 — Final Response Layer (Adnan-style output)
        final_output = self.response_engine.format_response(
            identity_reasoning=identity_reasoning,
            classification=classification,
            result=result
        )

        return {
            "success": True,
            "context_type": context,
            "identity_reasoning": identity_reasoning,
            "classification": classification,
            "result": result,
            "final_output": final_output,
        }

    # -----------------------------------------------------------
    # BUSINESS PLAYBOOK HANDLER
    # -----------------------------------------------------------

    def _handle_business_playbook(self, user_input: str, playbook: Dict[str, Any]) -> Dict[str, Any]:
        action = playbook.get("recommended_action")
        target_db = playbook.get("target_database")

        # FOLLOW SOP
        if action == "follow_sop":
            return {
                "type": "sop",
                "response": self.notion_engine.handle_sop(user_input)
            }

        # QUERY/UPDATE BUSINESS DATA
        if action == "query_or_update_notion":
            return {
                "type": "notion",
                "response": self.notion_engine.smart_process(user_input, target_db)
            }

        # NEXT STEP (CEO)
        if action == "next_step":
            return {
                "type": "business",
                "response": self.decision_engine.next_step(user_input)
            }

        # GENERAL BUSINESS ADVICE
        return {
            "type": "business",
            "response": self.decision_engine.process_business(user_input)
        }

    # -----------------------------------------------------------
    # HANDLERI TOKOVA (minimalni — ne diramo postojeću logiku)
    # -----------------------------------------------------------

    def _handle_identity(self, user_input: str, reasoning: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "identity",
            "response": self.decision_engine.process_identity(user_input, reasoning)
        }

    def _handle_business(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "business",
            "response": self.decision_engine.process_business(user_input)
        }

    def _handle_notion(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "notion",
            "response": self.notion_engine.process(user_input)
        }

    def _handle_sop(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "sop",
            "response": self.notion_engine.handle_sop(user_input)
        }

    def _handle_agent_query(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "agent",
            "response": self.agents_engine.query(user_input)
        }

    def _handle_memory(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "memory",
            "response": self.memory_engine.process(user_input)
        }

    def _handle_meta(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "meta",
            "response": {
                "status": "meta-command-received",
                "input": user_input
            }
        }

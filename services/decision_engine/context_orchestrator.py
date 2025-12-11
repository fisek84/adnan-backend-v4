from typing import Dict, Any
import os

from .identity_reasoning import IdentityReasoningEngine
from .context_classifier import ContextClassifier
from services.decision_engine.final_response_engine import FinalResponseEngine
from services.decision_engine.playbook_engine import PlaybookEngine

# Ostali servisi
from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.memory_service import MemoryService
from services.notion_service import NotionService
from services.agents_service import AgentsService


class ContextOrchestrator:
    """
    Centralni orkestrator — stabilna verzija bez async problema.
    Svi async Notion pozivi sada koriste SYNC adapter iz NotionService-a.
    """

    def __init__(self, identity: Dict[str, Any], mode: Dict[str, Any], state: Dict[str, Any]):
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

        # Notion (async internally, sync wrapper externally)
        self.notion_engine = NotionService(
            os.getenv("NOTION_API_KEY"),
            os.getenv("NOTION_GOALS_DB"),
            os.getenv("NOTION_TASKS_DB"),
            os.getenv("NOTION_PROJECTS_DB"),
        )

        # Agents (sync)
        self.agents_engine = AgentsService(
            os.getenv("NOTION_API_KEY"),
            os.getenv("NOTION_EXCHANGE_DB"),
            os.getenv("NOTION_PROJECTS_DB"),
        )

    # -----------------------------------------------------------
    # MAIN EXECUTOR
    # -----------------------------------------------------------

    def run(self, user_input: str) -> Dict[str, Any]:
        identity_reasoning = self.reasoner.generate_reasoning(user_input)
        classification = self.classifier.classify(user_input, identity_reasoning)

        context = classification["context_type"]

        # ROUTING
        if context == "identity":
            result = self._handle_identity(user_input, identity_reasoning)

        elif context == "business":
            playbook = self.playbook_engine.evaluate(
                user_input=user_input,
                identity_reasoning=identity_reasoning,
                context=classification,
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

        # FINAL RESPONSE
        final_output = self.response_engine.format_response(
            identity_reasoning=identity_reasoning,
            classification=classification,
            result=result,
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
    # HANDLERS
    # -----------------------------------------------------------

    def _handle_identity(self, user_input: str, reasoning: Dict[str, Any]) -> Dict[str, Any]:

        lower = user_input.lower()

        if any(q in lower for q in ["ko si", "ko si ti", "šta si ti", "ko je adnan.ai", "tvoj identitet"]):
            text = (
                "Ja sam Adnan.AI — digitalna rekonstrukcija tvog načina razmišljanja "
                "i donošenja odluka. Fokusiran, precizan, sistemski."
            )
        else:
            text = "Razumijem. Reci mi šta želiš dalje."

        return {
            "type": "identity",
            "response": text,
            "reasoning": reasoning
        }

    def _handle_business(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "business",
            "response": self.decision_engine.process_ceo_instruction(user_input),
        }

    def _handle_business_playbook(self, user_input: str, playbook: Dict[str, Any]) -> Dict[str, Any]:

        action = playbook.get("recommended_action")
        target_db = playbook.get("target_database")

        if action == "follow_sop":
            return {
                "type": "sop",
                "response": self.notion_engine.handle_sop_sync(user_input),
            }

        if action == "query_or_update_notion":
            return {
                "type": "notion",
                "response": self.notion_engine.smart_process_sync(user_input, target_db),
            }

        if action == "next_step":
            return {
                "type": "business",
                "response": self.decision_engine.process_ceo_instruction(user_input),
            }

        return {
            "type": "business",
            "response": self.decision_engine.process_ceo_instruction(user_input),
        }

    def _handle_notion(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "notion",
            "response": self.notion_engine.process_sync(user_input),
        }

    def _handle_sop(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "sop",
            "response": self.notion_engine.handle_sop_sync(user_input),
        }

    def _handle_agent_query(self, user_input: str) -> Dict[str, Any]:
        return {
            "type": "agent",
            "response": self.agents_engine.query(user_input),
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

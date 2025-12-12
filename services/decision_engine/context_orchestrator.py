from typing import Dict, Any, Optional, List, Tuple

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
            result = knowledge if knowledge else self._knowledge_help_result()

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
    # READ-ONLY KNOWLEDGE (GLOBAL + GROUPED + PER-DB)
    # ============================================================
    def _handle_business_knowledge(self, user_input: str) -> Optional[Dict[str, Any]]:
        if not self.notion_knowledge:
            return None

        snapshot = self.notion_knowledge.get_knowledge_snapshot()
        databases = snapshot.get("databases") if isinstance(snapshot, dict) else None
        if not databases:
            return None

        lower = (user_input or "").lower().strip()

        # ----------------------------
        # GLOBAL REPORT (CEO overview)
        # ----------------------------
        if any(w in lower for w in [
            "report", "izvještaj", "izvjestaj",
            "pregled svega", "cijela firma", "stanje firme",
        ]):
            return {
                "type": "knowledge",
                "response": {
                    "topic": "full_report",
                    "databases": databases,
                },
            }

        # ----------------------------
        # GROUPED TOPICS (SOP / AGENTS)
        # ----------------------------
        # "pokaži sop", "koje sop imamo", "outreach sop", itd.
        if "sop" in lower:
            grouped = self._aggregate_group(databases, include_if_key_contains=["sop"])
            if grouped:
                return {
                    "type": "knowledge",
                    "response": {
                        "topic": "sop",
                        "count": len(grouped),
                        "items": grouped,
                    },
                }
            return None

        # "koje agente imamo"
        if any(w in lower for w in ["agent", "agenti", "agents"]):
            grouped = self._aggregate_group(databases, include_if_key_contains=["agent"])
            if grouped:
                return {
                    "type": "knowledge",
                    "response": {
                        "topic": "agents",
                        "count": len(grouped),
                        "items": grouped,
                    },
                }
            return None

        # ----------------------------
        # PER-DB MATCH (key ili label)
        # ----------------------------
        for key, db in databases.items():
            label = (db.get("label") or "").lower()
            if key in lower or (label and label in lower):
                items = db.get("items", [])
                names = []
                for it in items:
                    if isinstance(it, dict):
                        names.append(it.get("name") or "")
                    else:
                        names.append(str(it))
                names = [n for n in names if n]

                return {
                    "type": "knowledge",
                    "response": {
                        "topic": key,
                        "count": len(names),
                        "items": names,
                    },
                }

        # ----------------------------
        # COMMON NATURAL LANGUAGE MAP
        # ----------------------------
        # "koji su mi ciljevi", "koji su mi zadaci", itd.
        if any(w in lower for w in ["cilj", "ciljevi", "goals"]):
            return self._best_effort_topic(databases, prefer_keys=["goals", "active_goals", "completed_goals", "blocked_goals"])

        if any(w in lower for w in ["zadaci", "taskovi", "tasks"]):
            return self._best_effort_topic(databases, prefer_keys=["tasks"])

        if any(w in lower for w in ["projekti", "projects", "project"]):
            return self._best_effort_topic(databases, prefer_keys=["projects", "agent_projects"])

        if any(w in lower for w in ["kpi", "metric", "metrics"]):
            return self._best_effort_topic(databases, prefer_keys=["kpi", "ai_weekly_summary"])

        if any(w in lower for w in ["lead", "leadovi", "leads"]):
            return self._best_effort_topic(databases, prefer_keys=["lead"])

        return None

    def _aggregate_group(
        self,
        databases: Dict[str, Any],
        include_if_key_contains: List[str],
    ) -> List[str]:
        out: List[str] = []
        for key, db in databases.items():
            k = (key or "").lower()
            if any(token in k for token in include_if_key_contains):
                label = db.get("label") or key
                count = len(db.get("items", []) or [])
                out.append(f"{label} ({count})")
        return out

    def _best_effort_topic(
        self,
        databases: Dict[str, Any],
        prefer_keys: List[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Ako snapshot koristi drugačije key-eve, pokušaj pogoditi najbolji match.
        """
        lower_keys = {k.lower(): k for k in databases.keys()}

        for pk in prefer_keys:
            for key_l, original_key in lower_keys.items():
                if pk in key_l:
                    db = databases.get(original_key, {})
                    items = db.get("items", []) or []
                    names: List[str] = []
                    for it in items:
                        if isinstance(it, dict):
                            names.append(it.get("name") or "")
                        else:
                            names.append(str(it))
                    names = [n for n in names if n]
                    return {
                        "type": "knowledge",
                        "response": {
                            "topic": original_key,
                            "count": len(names),
                            "items": names,
                        },
                    }
        return None

    def _knowledge_help_result(self) -> Dict[str, Any]:
        """
        READ-ONLY fallback: pokaži šta je trenutno dostupno u snapshotu.
        (Nikad string, da ne ruši formatter.)
        """
        if not self.notion_knowledge:
            return {
                "type": "knowledge",
                "response": {
                    "topic": "help",
                    "count": 0,
                    "items": ["Notion knowledge nije attachovan."],
                },
            }

        snapshot = self.notion_knowledge.get_knowledge_snapshot()
        databases = snapshot.get("databases") if isinstance(snapshot, dict) else None
        if not databases:
            return {
                "type": "knowledge",
                "response": {
                    "topic": "help",
                    "count": 0,
                    "items": ["Snapshot još nije spreman ili nema baza."],
                },
            }

        items = []
        for key, db in databases.items():
            label = db.get("label") or key
            items.append(f"{key} → {label}")

        return {
            "type": "knowledge",
            "response": {
                "topic": "help",
                "count": len(items),
                "items": items,
            },
        }

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

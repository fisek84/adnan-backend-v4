from typing import Dict, Any
import time

from services.intent_classifier import IntentClassifier
from services.intent_csi_binder import IntentCSIBinder

from .final_response_engine import FinalResponseEngine
from .playbook_engine import PlaybookEngine

from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.memory_service import MemoryService
from services.sop_knowledge_registry import SOPKnowledgeRegistry
from services.conversation_state_service import ConversationStateService

from services.agent_router.agent_router import AgentRouter

from services.autonomy.autonomy_hook import AutonomyHook
from services.autonomy.kill_switch import AutonomyKillSwitch
from services.autonomy.feature_flags import AutonomyFeatureFlags
from services.autonomy.safe_mode import AutonomySafeMode


class ContextOrchestrator:
    """
    CSI-CENTRIC SOP Orchestrator (KANONSKI)
    """

    def __init__(
        self,
        identity: Dict[str, Any],
        mode: Dict[str, Any],
        state: Dict[str, Any],
        conversation_state: ConversationStateService,
    ):
        self.identity = identity
        self.mode = mode
        self.state = state

        self.intent_classifier = IntentClassifier()
        self.intent_binder = IntentCSIBinder()

        self.response_engine = FinalResponseEngine(identity)
        self.playbook_engine = PlaybookEngine()
        self.decision_engine = AdnanAIDecisionService()
        self.memory_engine = MemoryService()

        self.sop_registry = SOPKnowledgeRegistry()
        self.conversation_state = conversation_state

        self.agent_router = AgentRouter()

        self.autonomy = AutonomyHook(
            conversation_state=conversation_state,
            kill_switch=AutonomyKillSwitch(),
            feature_flags=AutonomyFeatureFlags(),
            safe_mode=AutonomySafeMode(),
        )

    # =====================================================
    # MAIN LOOP
    # =====================================================
    async def run(self, user_input: str) -> Dict[str, Any]:
        text = (user_input or "").strip()

        csi_snapshot = self.conversation_state.get() or {}
        csi_state = csi_snapshot.get("state") or "IDLE"
        request_id = csi_snapshot.get("request_id")

        intent = self.intent_classifier.classify(text)
        bind = self.intent_binder.bind(intent, csi_state)

        # ---------------- RESET ----------------
        if bind.action == "reset":
            self.conversation_state.set_idle(request_id=request_id)
            return self._final({"type": "reset"})

        # ---------------- GOAL ----------------
        if bind.action == "create_goal":
            goal = {
                "text": bind.payload.get("text"),
                "status": "draft",
                "created_at": time.time(),
            }
            self.conversation_state.set_goal_draft(goal=goal, request_id=request_id)
            return self._final({"type": "goal_draft", "goal": goal})

        if bind.action == "confirm_goal":
            goal = self.conversation_state.get().get("goal_draft")
            if goal:
                self.memory_engine.store_goal(goal)
            self.conversation_state.set_idle(request_id=request_id)
            return self._final({"type": "goal_confirmed", "goal": goal})

        if bind.action == "cancel_goal":
            self.conversation_state.set_idle(request_id=request_id)
            return self._final({"type": "goal_cancelled"})

        # ---------------- PLAN ----------------
        if bind.action == "create_plan":
            goal = self.conversation_state.get().get("goal_draft")
            if not goal:
                return self._fallback()

            self.conversation_state.set_plan_create(request_id=request_id)
            plan = self.decision_engine.generate_plan_from_goal(goal)

            plan_obj = {
                "goal": goal,
                "plan": plan,
                "status": "draft",
                "created_at": time.time(),
            }

            self.conversation_state.set_plan_draft(plan=plan_obj, request_id=request_id)
            return self._final({"type": "plan_draft", "plan": plan_obj})

        if bind.action == "confirm_plan":
            plan = self.conversation_state.get().get("plan_draft")
            if plan:
                self.memory_engine.store_plan(plan)
            self.conversation_state.confirm_plan(request_id=request_id)
            self.conversation_state.set_idle(request_id=request_id)
            return self._final({"type": "plan_confirmed", "plan": plan})

        if bind.action == "cancel_plan":
            self.conversation_state.set_idle(request_id=request_id)
            return self._final({"type": "plan_cancelled"})

        # ---------------- TASK ----------------
        if bind.action == "create_task":
            task = {
                "text": bind.payload.get("text"),
                "status": "draft",
                "created_at": time.time(),
            }
            self.conversation_state.set_task_create(task=task, request_id=request_id)
            return self._final({"type": "task_create", "task": task})

        if bind.action == "confirm_task":
            task = self.conversation_state.get().get("task_draft")
            self.conversation_state.confirm_task(request_id=request_id)
            return self._final({"type": "task_confirmed", "task": task})

        if bind.action == "start_task":
            self.conversation_state.start_task(request_id=request_id)

            task = self.conversation_state.get().get("task_draft")
            if not task:
                self.conversation_state.fail_task(request_id=request_id)
                return self._final({"type": "task_failed", "reason": "no_task"})

            command = {
                "command": "create_database_entry",
                "payload": task,
            }

            result = await self.agent_router.execute(command)

            if result.get("success"):
                self.conversation_state.complete_task(request_id=request_id)
                self.conversation_state.set_idle(request_id=request_id)
                return self._final(
                    {
                        "type": "task_done",
                        "agent_result": result,
                    }
                )

            self.conversation_state.fail_task(request_id=request_id)
            self.conversation_state.set_idle(request_id=request_id)
            return self._final(
                {
                    "type": "task_failed",
                    "agent_result": result,
                }
            )

        return self._fallback()

    # ---------------- HELPERS ----------------
    def _fallback(self):
        return self._final({"type": "chat", "message": "Razumijem."})

    def _final(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        final = self.response_engine.format_response(
            identity_reasoning=None,
            classification={"context_type": "knowledge"},
            result=payload,
        )
        return {
            "success": True,
            "context_type": "knowledge",
            "result": payload,
            "final_output": final,
        }

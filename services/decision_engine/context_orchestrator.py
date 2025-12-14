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

# =====================================================
# FAZA 5 — READ-ONLY AUTONOMY (KANON)
# =====================================================
from services.autonomy.autonomy_hook import AutonomyHook
from services.autonomy.kill_switch import AutonomyKillSwitch
from services.autonomy.feature_flags import AutonomyFeatureFlags
from services.autonomy.safe_mode import AutonomySafeMode

# =====================================================
# BLOK 8 — OBSERVABILITY
# =====================================================
from services.observability.telemetry_emitter import TelemetryEmitter
from services.observability.telemetry_event import TelemetryEvent


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

        # -------------------------------------------------
        # CORE
        # -------------------------------------------------
        self.intent_classifier = IntentClassifier()
        self.intent_binder = IntentCSIBinder()

        self.response_engine = FinalResponseEngine(identity)
        self.playbook_engine = PlaybookEngine()
        self.decision_engine = AdnanAIDecisionService()
        self.memory_engine = MemoryService()

        self.sop_registry = SOPKnowledgeRegistry()
        self.conversation_state = conversation_state  # 🔒 CSI SINGLETON

        # -------------------------------------------------
        # FAZA 5 — AUTONOMY (PASSIVE / READ-ONLY)
        # -------------------------------------------------
        self.autonomy = AutonomyHook(
            conversation_state=conversation_state,
            kill_switch=AutonomyKillSwitch(),
            feature_flags=AutonomyFeatureFlags(),
            safe_mode=AutonomySafeMode(),
        )

        # -------------------------------------------------
        # TELEMETRY
        # -------------------------------------------------
        self.telemetry = TelemetryEmitter()

    # =====================================================
    # MAIN LOOP
    # =====================================================
    async def run(self, user_input: str) -> Dict[str, Any]:
        text = (user_input or "").strip()

        # ✅ KANONSKI CSI GUARD (OVO JE KLJUČNO)
        csi = self.conversation_state.get() or {}
        csi_state = csi.get("state") or "IDLE"
        request_id = csi.get("request_id")

        # -------------------------------------------------
        # FAZA 5 — AUTONOMY (READ-ONLY)
        # -------------------------------------------------
        autonomy_signal = self.autonomy.evaluate(
            iteration=1,
            expected_outcome=None,
            actual_result=None,
            retry_count=0,
            last_error=None,
        )

        self.telemetry.emit(
            TelemetryEvent.now(
                event_type="autonomy_evaluated",
                csi_state=csi_state,
                payload={"signal": bool(autonomy_signal)},
            )
        )

        # -------------------------------------------------
        # 1. INTENT
        # -------------------------------------------------
        intent = self.intent_classifier.classify(text)

        self.telemetry.emit(
            TelemetryEvent.now(
                event_type="intent_classified",
                csi_state=csi_state,
                intent=intent.type.value,
            )
        )

        # -------------------------------------------------
        # 2. CSI BINDING
        # -------------------------------------------------
        bind = self.intent_binder.bind(intent, csi_state)

        self.telemetry.emit(
            TelemetryEvent.now(
                event_type="csi_bound",
                csi_state=csi_state,
                intent=intent.type.value,
                action=bind.action,
            )
        )

        # -------------------------------------------------
        # RESET
        # -------------------------------------------------
        if bind.action == "reset":
            self.conversation_state.set_idle(request_id=request_id)
            return self._final({
                "type": "reset",
                "message": "Stanje je resetovano. Spreman sam.",
            })

        # -------------------------------------------------
        # GOAL — CREATE (FAZA 3)
        # -------------------------------------------------
        if bind.action == "create_goal":
            goal_object = {
                "text": bind.payload.get("text"),
                "status": "draft",
                "created_at": time.time(),
            }

            self.conversation_state.set_goal_draft(
                goal=goal_object,
                request_id=request_id,
            )

            return self._final({
                "type": "goal_draft",
                "goal": goal_object,
                "message": "Cilj je prepoznat. Potvrdi ili otkaži.",
            })

        # -------------------------------------------------
        # GOAL — CONFIRM / CANCEL
        # -------------------------------------------------
        if bind.action == "confirm_goal":
            goal = csi.get("goal_draft")
            if goal:
                self.memory_engine.store_goal(goal)

            self.conversation_state.set_idle(request_id=request_id)
            return self._final({"type": "goal_confirmed", "goal": goal})

        if bind.action == "cancel_goal":
            self.conversation_state.set_idle(request_id=request_id)
            return self._final({"type": "goal_cancelled"})

        # -------------------------------------------------
        # PLAN — CREATE (FAZA 4)
        # -------------------------------------------------
        if bind.action == "create_plan":
            goal = csi.get("goal_draft")
            if not goal:
                return self._fallback()

            plan = self.decision_engine.generate_plan_from_goal(goal)

            plan_object = {
                "goal": goal,
                "plan": plan,
                "status": "draft",
                "created_at": time.time(),
            }

            self.conversation_state.set_plan_draft(
                plan=plan_object,
                request_id=request_id,
            )

            return self._final({
                "type": "plan_draft",
                "plan": plan_object,
                "message": "Plan je generisan. Potvrdi ili otkaži.",
            })

        # -------------------------------------------------
        # PLAN — CONFIRM / CANCEL
        # -------------------------------------------------
        if bind.action == "confirm_plan":
            plan = csi.get("plan_draft")
            if plan:
                self.memory_engine.store_plan(plan)

            self.conversation_state.set_idle(request_id=request_id)
            return self._final({"type": "plan_confirmed", "plan": plan})

        if bind.action == "cancel_plan":
            self.conversation_state.set_idle(request_id=request_id)
            return self._final({"type": "plan_cancelled"})

        # -------------------------------------------------
        # TASKS FROM PLAN
        # -------------------------------------------------
        if bind.action == "generate_tasks_from_plan":
            plan = csi.get("plan_draft")
            if not plan:
                return self._fallback()

            tasks = self.decision_engine.generate_tasks_from_plan(plan)

            task_drafts = [{
                "text": t,
                "origin": "plan",
                "status": "draft",
                "created_at": time.time(),
            } for t in tasks]

            return self._final({
                "type": "task_drafts_from_plan",
                "tasks": task_drafts,
            })

        return self._fallback()

    # =====================================================
    # HELPERS
    # =====================================================
    def _fallback(self) -> Dict[str, Any]:
        return self._final({
            "type": "chat",
            "message": "Razumijem. Nastavi.",
        })

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

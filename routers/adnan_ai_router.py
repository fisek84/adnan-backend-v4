# C:\adnan-backend-v4\routers\adnan_ai_router.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging

from services.intent_classifier import IntentClassifier
from services.intent_csi_binder import IntentCSIBinder
from services.conversation_state_service import ConversationStateService, CSIState

from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.execution_orchestrator import ExecutionOrchestrator
from services.response_formatter import ResponseFormatter
from services.governance_service import GovernanceService
from services.metrics_service import MetricsService


# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(prefix="/adnan-ai", tags=["AdnanAI"])

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

intent_classifier = IntentClassifier()
intent_binder = IntentCSIBinder()
conversation_state = ConversationStateService()

decision_service = AdnanAIDecisionService()
execution_orchestrator = ExecutionOrchestrator()
response_formatter = ResponseFormatter()
governance_service = GovernanceService()


# ============================================================
# REQUEST MODEL
# ============================================================

class AdnanAIInput(BaseModel):
    text: str


# ============================================================
# NATURAL LANGUAGE ENTRYPOINT (FULL FLOW)
# ============================================================

@router.post("/input")
async def adnan_ai_input(payload: AdnanAIInput):
    """
    Canonical Adnan.AI natural language entrypoint.

    FLOW:
    Intent → CSI → Decision → Governance → EXEC → Response
    """

    try:
        user_text = payload.text.strip()
        if not user_text:
            raise HTTPException(status_code=400, detail="Empty input")

        # ==================================================
        # METRICS — INPUT
        # ==================================================
        MetricsService.incr("input.total")

        # --------------------------------------------------
        # 1. INTENT CLASSIFICATION
        # --------------------------------------------------
        intent = intent_classifier.classify(user_text)

        MetricsService.emit("input", {
            "intent": intent.type.value,
            "confidence": intent.confidence,
        })

        # --------------------------------------------------
        # 2. CURRENT CSI STATE
        # --------------------------------------------------
        csi_snapshot = conversation_state.get()
        current_state = csi_snapshot["state"]

        # --------------------------------------------------
        # 3. INTENT → CSI BINDING
        # --------------------------------------------------
        binder_result = intent_binder.bind(intent, current_state)

        logger.info(
            "Intent=%s | CSI=%s -> %s | action=%s",
            intent.type.value,
            current_state,
            binder_result.next_state,
            binder_result.action,
        )

        MetricsService.incr(f"csi.transition.{binder_result.next_state}")

        # --------------------------------------------------
        # 4. APPLY CSI TRANSITION (DATA ONLY)
        # --------------------------------------------------
        if binder_result.next_state != current_state:
            if binder_result.next_state == CSIState.IDLE.value:
                conversation_state.set_idle()

            elif binder_result.next_state == CSIState.SOP_LIST.value:
                conversation_state._state.state = CSIState.SOP_LIST.value
                conversation_state._save_state(conversation_state._state)

            elif binder_result.next_state == CSIState.SOP_ACTIVE.value:
                conversation_state._state.state = CSIState.SOP_ACTIVE.value
                conversation_state._save_state(conversation_state._state)

            elif binder_result.next_state == CSIState.DECISION_PENDING.value:
                conversation_state._state.state = CSIState.DECISION_PENDING.value
                conversation_state._save_state(conversation_state._state)

            elif binder_result.next_state == CSIState.EXECUTING.value:
                conversation_state.set_executing()

        # refresh snapshot after transition
        csi_snapshot = conversation_state.get()

        # --------------------------------------------------
        # 5. DECISION BUILDING (NO EXECUTION)
        # --------------------------------------------------
        decision = None
        if binder_result.action:
            decision = decision_service.build_decision(
                action=binder_result.action,
                intent=intent.type.value,
                confidence=intent.confidence,
                csi_state=csi_snapshot,
            )

        if decision:
            MetricsService.incr("decision.created")
            if decision.get("confirmed"):
                MetricsService.incr("decision.confirmed")

        # --------------------------------------------------
        # 6. GOVERNANCE + EXECUTION (ONLY IF CONFIRMED)
        # --------------------------------------------------
        execution_result = None
        if decision and decision.get("confirmed") and decision.get("decision_candidate"):

            policy = governance_service.evaluate(decision)

            if not policy["allowed"]:
                MetricsService.incr("governance.blocked")
                MetricsService.emit("governance.block", {
                    "reason": policy["reason"],
                })

                return {
                    "ok": False,
                    "response": {
                        "message": policy["reason"],
                        "status": "blocked",
                    },
                    "state": conversation_state.get()["state"],
                }

            execution_result = await execution_orchestrator.execute(decision)

            MetricsService.incr("execution.total")
            if execution_result.get("success"):
                MetricsService.incr("execution.success")
            else:
                MetricsService.incr("execution.failed")

            # after execution → CSI back to IDLE
            conversation_state.set_idle()
            csi_snapshot = conversation_state.get()

        # --------------------------------------------------
        # 7. RESPONSE FORMATTING (CEO-GRADE)
        # --------------------------------------------------
        response = response_formatter.format(
            intent=intent.type.value,
            confidence=intent.confidence,
            csi_state=csi_snapshot,
            decision=decision,
            execution_result=execution_result,
        )

        return {
            "ok": True,
            "response": response,
            "confidence": intent.confidence,
            "state": csi_snapshot["state"],
        }

    except Exception as e:
        logger.exception("AdnanAI input error")
        raise HTTPException(status_code=500, detail=str(e))

# C:\adnan-backend-v4\routers\adnan_ai_router.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging

from services.intent_classifier import IntentClassifier
from services.intent_csi_binder import IntentCSIBinder
from services.conversation_state_service import ConversationStateService, CSIState
from services.approval_state_service import ApprovalStateService

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
approval_service = ApprovalStateService()

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
    Intent → CSI → Decision → Governance → EXEC → CSI WRITE-BACK → Response
    """

    try:
        user_text = payload.text.strip()
        if not user_text:
            raise HTTPException(status_code=400, detail="Empty input")

        MetricsService.incr("input.total")

        # --------------------------------------------------
        # APPROVAL COMMAND (FAZA D6)
        # --------------------------------------------------
        if user_text.lower() == "approve":
            csi = conversation_state.get()
            approval_id = csi.get("pending_decision", {}).get("approval_id")

            if not approval_id:
                return {
                    "ok": False,
                    "response": {"message": "Nema aktivnog approval zahtjeva."},
                    "state": csi["state"],
                }

            updated = approval_service.approve_next_level(
                approval_id=approval_id,
                approved_by="ceo",
            )

            return {
                "ok": True,
                "response": {
                    "message": "Approval nivo odobren.",
                    "approval": updated,
                },
                "state": csi["state"],
            }

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
        # 4. APPLY CSI TRANSITION (SAFE)
        # --------------------------------------------------
        if binder_result.next_state != current_state:
            conversation_state.apply_execution_state(
                next_csi_state=binder_result.next_state,
                request_id=None,
                reason="intent_binding",
            )

        csi_snapshot = conversation_state.get()

        # --------------------------------------------------
        # 5. DECISION BUILDING
        # --------------------------------------------------
        decision = None
        if binder_result.action:
            decision = decision_service.build_decision(
                action=binder_result.action,
                intent=intent.type.value,
                confidence=intent.confidence,
                csi_state=csi_snapshot,
            )

        # --------------------------------------------------
        # 6. GOVERNANCE + EXECUTION
        # --------------------------------------------------
        execution_result = None
        if decision and decision.get("confirmed") and decision.get("decision_candidate"):

            policy = governance_service.evaluate(decision)

            if not policy["allowed"]:
                return {
                    "ok": False,
                    "response": {"message": policy["reason"]},
                    "state": conversation_state.get()["state"],
                }

            execution_result = await execution_orchestrator.execute(decision)

            conversation_state.apply_execution_state(
                next_csi_state=execution_result.get("csi_next_state"),
                request_id=execution_result.get("execution_id"),
                reason="execution_result",
            )

            csi_snapshot = conversation_state.get()

        # --------------------------------------------------
        # 7. RESPONSE
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

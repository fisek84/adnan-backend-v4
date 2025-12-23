# routers/adnan_ai_action_router.py

from fastapi import APIRouter
from pydantic import BaseModel

from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.action_safety_service import ActionSafetyService
from services.action_execution_service import ActionExecutionService
from services.action_workflow_service import ActionWorkflowService


router = APIRouter(prefix="/adnan-ai/actions", tags=["AdnanAI Actions"])


# -------------------------------
# MODELS
# -------------------------------
class ActionRequest(BaseModel):
    text: str


# -------------------------------
# MAIN ENDPOINT
# -------------------------------
@router.post("/")
async def ai_action_endpoint(request: ActionRequest):
    """
    Action Engine Endpoint (Korak 8.6)
    Prima AI text → decision engine → action/workflow izvršenje.
    """

    decision_service = AdnanAIDecisionService()
    safety_service = ActionSafetyService()
    executor = ActionExecutionService()
    workflow_executor = ActionWorkflowService()

    # ---------------------------------------
    # 1. Decision Engine → interpretacija teksta
    # ---------------------------------------
    decision = decision_service.process(request.text)
    directives = decision.get("directives", [])

    # Ako nema direktiva → nema akcija
    if not directives:
        return {
            "ok": True,
            "action_executed": False,
            "reason": "no_action_detected",
            "decision": decision,
        }

    # ---------------------------------------
    # 2. Ako AI generiše workflow umjesto jedne akcije
    # ---------------------------------------
    # Convention: decision["workflow"] može postojati
    if "workflow" in decision:
        workflow = decision["workflow"]

        # SAFETY PROVJERA
        safety = safety_service.validate_workflow(workflow)
        if not safety["allowed"]:
            return {
                "ok": False,
                "workflow_executed": False,
                "reason": safety["reason"],
                "decision": decision,
            }

        # EXECUTE WORKFLOW
        result = workflow_executor.execute_workflow(workflow)

        return {
            "ok": True,
            "workflow_executed": True,
            "result": result,
            "decision": decision,
        }

    # ---------------------------------------
    # 3. Jednostruka akcija
    # ---------------------------------------
    directive = directives[0]  # uzimamo primarni directive

    params = {
        "input": decision.get("input"),
        "state": decision.get("state"),
        "mode": decision.get("mode"),
        "priority_context": decision.get("priority_context"),
    }

    # SAFETY PROVJERA ZA AKCIJU
    safety = safety_service.validate_action(directive, params)
    if not safety["allowed"]:
        return {
            "ok": False,
            "action_executed": False,
            "reason": safety["reason"],
            "decision": decision,
        }

    # ---------------------------------------
    # 4. Izvršenje akcije (safe execution)
    # ---------------------------------------
    exec_result = executor.execute(directive, params)

    return {
        "ok": True,
        "action_executed": exec_result.get("executed", False),
        "directive": directive,
        "result": exec_result,
        "decision": decision,
    }

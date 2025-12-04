# routers/adnan_ai_router.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging

from services.prompt_builder import PromptBuilder
from services.ai_command_service import AICommandService

from services.identity_loader import load_adnan_identity
from services.adnan_state_service import get_adnan_state
from services.adnan_kernel_service import get_adnan_kernel
from services.adnan_mode_service import get_adnan_mode
from services.adnan_decision_service import get_decision_engine_signature
from services.adnan_eval_service import evaluate_text
from services.adnan_analyze_service import analyze_text

router = APIRouter(prefix="/adnan-ai", tags=["Adnan.AI"])

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ============================================================
# MODELS
# ============================================================
class QueryModel(BaseModel):
    text: str


# ============================================================
# GLOBAL SERVICES
# ============================================================
prompt_builder = PromptBuilder()
ai_service = AICommandService()


# ============================================================
# MAIN AI QUERY ENDPOINT
# ============================================================
@router.post("/")
async def query_adnan_ai(request: QueryModel):
    logger.info(f"[ADNAN.AI] Request received: {request.text}")

    try:
        prompt = prompt_builder.build_prompt(request.text)
        logger.info(f"[ADNAN.AI] Prompt built: {prompt}")
    except Exception as e:
        logger.error(f"[ADNAN.AI] Prompt build error: {str(e)}")
        raise HTTPException(500, f"Prompt build error: {str(e)}")

    try:
        # Keeping sync call for now, but safe for async expansion
        response = ai_service.execute(prompt, {})
        logger.info(f"[ADNAN.AI] Response: {response}")
    except Exception as e:
        logger.error(f"[ADNAN.AI] AI execution error: {str(e)}")
        raise HTTPException(500, f"AI Execution error: {str(e)}")

    return {"ok": True, "response": response}


# ============================================================
# IDENTITY ENDPOINT
# ============================================================
@router.get("/identity")
def get_identity():
    try:
        data = load_adnan_identity()
        logger.info("[ADNAN.AI] Identity loaded")
        return data
    except Exception as e:
        logger.error(f"[ADNAN.AI] Identity load error: {str(e)}")
        raise HTTPException(500, f"Identity load error: {str(e)}")


# ============================================================
# STATE — FULL SNAPSHOT
# ============================================================
@router.get("/state")
def adnan_state():
    logger.info("[ADNAN.AI] Loading system state...")
    return get_adnan_state()


# ============================================================
# KERNEL
# ============================================================
@router.get("/kernel")
def adnan_kernel():
    logger.info("[ADNAN.AI] Loading kernel...")
    return get_adnan_kernel()


# ============================================================
# MODE (Evolia Mode)
# ============================================================
@router.get("/mode")
def adnan_mode():
    logger.info("[ADNAN.AI] Loading mode...")
    return get_adnan_mode()


# ============================================================
# DECISION ENGINE SIGNATURE
# ============================================================
@router.get("/decision-engine")
def decision_engine():
    logger.info("[ADNAN.AI] Loading decision engine signature...")
    return get_decision_engine_signature()


# ============================================================
# EVAL — SAFE EVALUATION
# ============================================================
@router.post("/eval")
def adnan_eval(request: QueryModel):
    try:
        logger.info(f"[ADNAN.AI] Evaluating: {request.text}")
        result = evaluate_text(request.text)
        return {"ok": True, "evaluation": result}
    except Exception as e:
        logger.error(f"[ADNAN.AI] Evaluation error: {str(e)}")
        raise HTTPException(500, f"Evaluation error: {str(e)}")


# ============================================================
# ANALYZE — INTERPRET WITHOUT EXECUTION
# ============================================================
@router.post("/analyze")
def adnan_analyze(request: QueryModel):
    try:
        logger.info(f"[ADNAN.AI] Analyzing: {request.text}")
        result = analyze_text(request.text)
        return {"ok": True, "analysis": result}
    except Exception as e:
        logger.error(f"[ADNAN.AI] Analysis error: {str(e)}")
        raise HTTPException(500, f"Analysis error: {str(e)}")

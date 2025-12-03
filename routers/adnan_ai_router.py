from services.adnan_state_service import get_adnan_state
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging  # Dodajemo logovanje
from services.prompt_builder import PromptBuilder
from services.ai_command_service import AICommandService
from services.identity_loader import load_adnan_identity   # ✅ FIXED IMPORT
from services.adnan_kernel_service import get_adnan_kernel
from services.adnan_mode_service import get_adnan_mode
from services.adnan_decision_service import get_decision_engine_signature
from services.adnan_eval_service import evaluate_text
from services.adnan_analyze_service import analyze_text

router = APIRouter(prefix="/adnan-ai", tags=["Adnan.AI"])

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class QueryModel(BaseModel):
    text: str

prompt_builder = PromptBuilder()
ai_service = AICommandService()

# ==========================================================
# Main AI Query Endpoint
# ==========================================================
@router.post("/")
def query_adnan_ai(request: QueryModel):
    logger.info(f"🟦 REQUEST RECEIVED: {request.text}")

    prompt = prompt_builder.build_prompt(request.text)
    logger.info(f"🟪 GENERATED PROMPT: {prompt}")

    try:
        response = ai_service.execute(prompt, {})
        logger.info(f"🟥 RAW RESPONSE: {response}")
    except Exception as e:
        logger.error(f"Error during AI execution: {str(e)}")
        raise HTTPException(500, f"AI Execution error: {str(e)}")

    return {"response": response}


# ==========================================================
# Identity Endpoint — Safe and Functional
# ==========================================================
@router.get("/identity")
def get_identity():
    try:
        identity = load_adnan_identity()
        logger.info("🟩 IDENTITY LOADED")
        return identity
    except Exception as e:
        logger.error(f"Error loading identity: {str(e)}")
        return {"error": str(e)}


# ==========================================================
# State Endpoint — Returns full safe system snapshot
# ==========================================================
@router.get("/state")
def adnan_state():
    logger.info("🟩 Fetching Adnan state snapshot")
    state = get_adnan_state()
    logger.info("🟩 Adnan state fetched successfully")
    return state


# ==========================================================
# Kernel Endpoint — Returns core identity data
# ==========================================================
@router.get("/kernel")
def adnan_kernel():
    logger.info("🟩 Fetching Adnan kernel data")
    kernel = get_adnan_kernel()
    logger.info("🟩 Adnan kernel fetched successfully")
    return kernel


# ==========================================================
# Mode Endpoint — Returns current Evolia Mode
# ==========================================================
@router.get("/mode")
def adnan_mode():
    logger.info("🟩 Fetching current Evolia mode")
    mode = get_adnan_mode()
    logger.info("🟩 Evolia mode fetched successfully")
    return mode


# ==========================================================
# Decision Engine Endpoint — Returns engine structure
# ==========================================================
@router.get("/decision-engine")
def decision_engine():
    logger.info("🟩 Fetching decision engine signature")
    engine_signature = get_decision_engine_signature()
    logger.info("🟩 Decision engine signature fetched successfully")
    return engine_signature


# ==========================================================
# Eval Endpoint — Safe text evaluation
# ==========================================================
@router.post("/eval")
def adnan_eval(request: QueryModel):
    logger.info(f"🟩 Evaluating text: {request.text}")
    result = evaluate_text(request.text)
    logger.info(f"🟩 Text evaluation result: {result}")
    return result


# ==========================================================
# Analyze Endpoint — AI interpretation without actions
# ==========================================================
@router.post("/analyze")
def adnan_analyze(request: QueryModel):
    logger.info(f"🟩 Analyzing text: {request.text}")
    result = analyze_text(request.text)
    logger.info(f"🟩 Text analysis result: {result}")
    return result

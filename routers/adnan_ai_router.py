from services.adnan_state_service import get_adnan_state
from fastapi import APIRouter
from pydantic import BaseModel
from services.prompt_builder import PromptBuilder
from services.ai_command_service import AICommandService
from services.identity_loader import load_adnan_identity   # ✅ FIXED IMPORT
from services.adnan_kernel_service import get_adnan_kernel
from services.adnan_mode_service import get_adnan_mode
from services.adnan_decision_service import get_decision_engine_signature
from services.adnan_eval_service import evaluate_text
from services.adnan_analyze_service import analyze_text


router = APIRouter(prefix="/adnan-ai", tags=["Adnan.AI"])

class QueryModel(BaseModel):
    text: str

prompt_builder = PromptBuilder()
ai_service = AICommandService()

@router.post("/")
def query_adnan_ai(request: QueryModel):
    print("🟦 REQUEST RECEIVED:", request.text)

    prompt = prompt_builder.build_prompt(request.text)
    print("🟪 GENERATED PROMPT:", prompt)

    response = ai_service.execute(prompt, {})
    print("🟥 RAW RESPONSE:", response)

    return {"response": response}


# ----------------------------------------------------
# ✅ IDENTITY ENDPOINT — SAFE AND FUNCTIONAL
# ----------------------------------------------------
@router.get("/identity")
def get_identity():
    try:
        identity = load_adnan_identity()
        return identity
    except Exception as e:
        return {"error": str(e)}


# ----------------------------------------------------
# ✅ STATE ENDPOINT — returns full safe system snapshot
# ----------------------------------------------------
@router.get("/state")
def adnan_state():
    return get_adnan_state()


# ----------------------------------------------------
# ✅ KERNEL ENDPOINT — returns core identity data
# ----------------------------------------------------
@router.get("/kernel")
def adnan_kernel():
    return get_adnan_kernel()


# ----------------------------------------------------
# ✅ MODE ENDPOINT — returns current Evolia Mode
# ----------------------------------------------------
@router.get("/mode")
def adnan_mode():
    return get_adnan_mode()


# ----------------------------------------------------
# ✅ DECISION ENGINE ENDPOINT — returns engine structure
# ----------------------------------------------------
@router.get("/decision-engine")
def decision_engine():
    return get_decision_engine_signature()
    # ----------------------------------------------------
# ✅ EVAL ENDPOINT — safe text evaluation
# ----------------------------------------------------
@router.post("/eval")
def adnan_eval(request: QueryModel):
    return evaluate_text(request.text)
    # ----------------------------------------------------
# ✅ ANALYZE ENDPOINT — AI interpretation without actions
# ----------------------------------------------------
@router.post("/analyze")
def adnan_analyze(request: QueryModel):
    return analyze_text(request.text)



from fastapi import APIRouter, HTTPException
import logging

from services.ai_command_service import AICommandService
from services.adnan_ai_decision_service import AdnanAIDecisionService  # ← (7.2)

router = APIRouter(prefix="/adnan-ai", tags=["AdnanAI"])

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Jedna instanca AICommandService (učitava identity.json već interno)
ai_service = AICommandService()


@router.post("/")
def adnan_ai_query(payload: dict):
    """
    Glavni endpoint za komunikaciju AI klona sa backendom.
    Podržava:
    - prirodni jezik ("pokaži mi ciljeve")
    - strukturirane komande ("GET /goals/all")
    """
    try:
        text = payload.get("text")
        if not text:
            raise HTTPException(status_code=400, detail="Missing 'text' field")

        logger.info(f"[ADNAN.AI] Received query: {text}")

        # -----------------------------
        # Decision Layer (7.2 + 7.5)
        # -----------------------------
        decision_service = AdnanAIDecisionService()
        decision_context = decision_service.align(text)
        decision_process = decision_service.process(text)
        # -----------------------------

        # -----------------------------
        # 8.1 — Action Detection Layer (PRIPREMA)
        # -----------------------------
        action_detected = None

        # Ako decision engine proslijedi directives koje liče na akcije
        if decision_process.get("directives"):
            action_detected = decision_process["directives"]

        # Ne izvršavamo još ništa — samo detekcija
        # -----------------------------

        result = ai_service.execute(text, payload={})

        return {
            "ok": True,
            "response": result,
            "decision_context": decision_context,
            "decision_process": decision_process,
            "action_detected": action_detected  # ← DODANO (8.1)
        }

    except Exception as e:
        logger.error(f"[ADNAN.AI] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

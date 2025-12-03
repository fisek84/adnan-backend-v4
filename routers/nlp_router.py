from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging  # Dodajemo logovanje

# Injected iz main.py
ai_service_global = None

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/nlp", tags=["NLP"])

class NLPRequest(BaseModel):
    query: str


@router.post("/")
async def run_nlp(req: NLPRequest):
    # Logovanje kada je upit primljen
    logger.info(f"Received NLP request: {req.query}")

    if not ai_service_global:
        logger.error("AICommandService not initialized")
        raise HTTPException(500, "AICommandService not initialized")

    try:
        # Pozivanje AI servisa
        result = ai_service_global.execute(req.query, {})
        logger.info(f"NLP execution result: {result}")
    except Exception as e:
        logger.error(f"NLP Execution error: {str(e)}")
        raise HTTPException(500, f"NLP Execution error: {str(e)}")

    return {"result": result}

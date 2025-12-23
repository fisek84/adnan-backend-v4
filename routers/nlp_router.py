# routers/nlp_router.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
from typing import Optional

# Global AI service instance (injected at startup)
_ai_service_global: Optional[object] = None


# Setter for main.py
def set_ai_service(service):
    global _ai_service_global
    _ai_service_global = service


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/nlp", tags=["NLP"])


# ============================================================
# REQUEST MODEL
# ============================================================
class NLPRequest(BaseModel):
    query: str


# ============================================================
# NLP EXECUTION ENDPOINT
# ============================================================
@router.post("/")
async def run_nlp(req: NLPRequest):
    logger.info(f"[NLP] Incoming query: {req.query}")

    # Validate AI service
    if _ai_service_global is None:
        logger.error("[NLP] AICommandService not initialized")
        raise HTTPException(500, "AICommandService not initialized")

    # Validate input
    if not req.query.strip():
        logger.error("[NLP] Empty query received")
        raise HTTPException(400, "Query cannot be empty")

    try:
        # If execute() is async → await it
        if hasattr(_ai_service_global.execute, "__call__"):
            result = _ai_service_global.execute(req.query, {})
            if hasattr(result, "__await__"):
                result = await result
        else:
            raise RuntimeError("AICommandService.execute() not callable")

        logger.info(f"[NLP] Execution result: {result}")

        return {"result": result}

    except Exception as e:
        logger.error(f"[NLP] Execution error: {type(e).__name__}: {str(e)}")
        raise HTTPException(500, f"NLP Execution error: {str(e)}")

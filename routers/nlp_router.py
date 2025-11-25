from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Injected iz main.py
ai_service_global = None

router = APIRouter(prefix="/nlp", tags=["NLP"])


class NLPRequest(BaseModel):
    query: str


@router.post("/")
async def run_nlp(req: NLPRequest):
    if not ai_service_global:
        raise HTTPException(500, "AICommandService not initialized")

    try:
        # Natural human language input
        result = ai_service_global.execute(req.query, {})
    except Exception as e:
        raise HTTPException(500, f"NLP Execution error: {str(e)}")

    return {"result": result}
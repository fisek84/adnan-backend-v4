from fastapi import APIRouter, Depends, HTTPException, status
from services.ai_command_service import AICommandService

router = APIRouter(prefix="/ai", tags=["AI Engine"])

# Global DI reference – injektuje se iz main.py
ai_service_global: AICommandService | None = None


# ============================================================
# INTERNAL VALIDATION (Centralized)
# ============================================================
def _require_ai_service() -> AICommandService:
    """
    Ensures that AICommandService is initialized before routing.
    Prevents silent errors and gives clean 500 responses.
    """
    if ai_service_global is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AICommandService is not initialized"
        )
    return ai_service_global


# ============================================================
# STATUS
# ============================================================
@router.get(
    "/",
    summary="Check AI engine availability",
    status_code=200
)
def ai_status():
    return {"status": "ok", "message": "AI engine endpoint active"}


# ============================================================
# EXECUTE AI COMMAND
# ============================================================
@router.post(
    "/command",
    summary="Execute a low-level AI command",
    status_code=200
)
def ai_command(payload: dict, service: AICommandService = Depends(_require_ai_service)):
    """
    Accepts unstructured AI commands (payload dict) and
    delegates processing to AICommandService.
    """
    result = service.process(payload)
    return {
        "status": "success",
        "operation": "command",
        "input": payload,
        "output": result
    }


# ============================================================
# RUN HIGH-LEVEL AI OPERATION
# ============================================================
@router.post(
    "/run",
    summary="Execute a high-level AI action",
    status_code=200
)
def run_command(payload: dict, service: AICommandService = Depends(_require_ai_service)):
    """
    High-level wrapper for AI command execution.
    Semantically identical to /command, but used by systems
    that distinguish between 'raw commands' and 'operations'.
    """
    result = service.process(payload)
    return {
        "status": "success",
        "operation": "run",
        "input": payload,
        "output": result
    }
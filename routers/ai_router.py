from fastapi import APIRouter, Depends
from services.ai_command_service import AICommandService

router = APIRouter(prefix="/ai")

# Globalni DI placeholder – popunjava se u main.py
ai_service_global: AICommandService = None

def get_ai_service() -> AICommandService:
    return ai_service_global


@router.post("/command")
def ai_command(payload: dict, service: AICommandService = Depends(get_ai_service)):
    return service.process(payload)


@router.post("/run")
def run_command(payload: dict, service: AICommandService = Depends(get_ai_service)):
    return service.process(payload)
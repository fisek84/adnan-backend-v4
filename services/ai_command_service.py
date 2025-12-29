# services/ai_command_service.py

from typing import Dict, Any
import logging

from models.ai_command import AICommand
from services.action_dictionary import is_valid_command
from services.action_safety_service import ActionSafetyService
from services.execution_orchestrator import ExecutionOrchestrator
from services.failure_handler import FailureHandler

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class AICommandService:
    """
    AI COMMAND SERVICE — CANONICAL

    Pravila:
    - Validira i provjerava sigurnost
    - NE upravlja execution lifecycle
    - NE registruje execution
    - SAMO delegira Orchestratoru
    """

    def __init__(self):
        self.safety = ActionSafetyService()
        self.orchestrator = ExecutionOrchestrator()
        self.failure_handler = FailureHandler()

    async def execute(self, command: AICommand) -> Dict[str, Any]:
        if not isinstance(command, AICommand):
            raise RuntimeError("Invalid AICommand object.")

        if not command.validated:
            raise RuntimeError("AICommand is not validated by COOTranslationService.")

        try:
            # ==================================================
            # READ PATH (NO APPROVAL REQUIRED)
            # ==================================================
            if command.read_only:
                if not is_valid_command(command.command):
                    raise ValueError(f"Invalid system command: {command.command}")

                self.safety.check(command)
                return await self.orchestrator.execute(command)

            # ==================================================
            # WRITE PATH (APPROVAL REQUIRED)
            # ==================================================
            if not command.intent:
                raise RuntimeError("WRITE command must define intent.")

            # 🔒 KANONSKI GUARD: nema execution-a bez approval-a
            if not command.approval_id:
                raise RuntimeError("WRITE command requires approval_id.")

            # 🔑 KANONSKA GARANCIJA: input MORA postojati
            if command.input is None:
                command.input = {}

            self.safety.check(command)
            return await self.orchestrator.execute(command)

        except Exception as e:
            return self.failure_handler.classify(
                source="execution",
                reason=str(e),
                execution_id=command.execution_id,
            )

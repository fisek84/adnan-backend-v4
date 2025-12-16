from typing import Dict, Any

from models.ai_command import AICommand
from services.action_dictionary import is_valid_command
from services.action_safety_service import ActionSafetyService
from services.execution_orchestrator import ExecutionOrchestrator


class AICommandService:
    """
    AI COMMAND SERVICE — KANONSKI

    Pravila:
    - READ: command-based
    - WRITE: intent-based
    - nema execution logike
    """

    def __init__(self):
        self.safety = ActionSafetyService()
        self.orchestrator = ExecutionOrchestrator()

    async def execute(self, command: AICommand) -> Dict[str, Any]:
        if not command or not isinstance(command, AICommand):
            raise RuntimeError("Invalid AICommand object.")

        if not command.validated:
            raise RuntimeError(
                "AICommand is not validated by COOTranslationService."
            )

        # ==================================================
        # READ PATH — COMMAND BASED
        # ==================================================
        if command.read_only:
            if not is_valid_command(command.command):
                raise ValueError(
                    f"Invalid system command: {command.command}"
                )

            # SAFETY PRE-CHECK (NO EXECUTION)
            self.safety.check(command)

            result = await self.orchestrator.execute(command)

        # ==================================================
        # WRITE PATH — INTENT BASED (KANONSKI)
        # ==================================================
        else:
            if not command.intent:
                raise RuntimeError("WRITE command must define intent.")

            # SAFETY PRE-CHECK (NO EXECUTION)
            self.safety.check(command)

            result = await self.orchestrator.execute(command)

        # ==================================================
        # POST-EXECUTION SYNC
        # ==================================================
        execution_state = result.get("execution_state")
        if execution_state:
            command.execution_state = execution_state

        AICommand.log(command)
        return result

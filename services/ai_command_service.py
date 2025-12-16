# services/ai_command_service.py
from typing import Dict, Any

from models.ai_command import AICommand
from services.action_dictionary import is_valid_command, get_action_definition
from services.action_safety_service import ActionSafetyService
from services.execution_orchestrator import ExecutionOrchestrator


class AICommandService:
    """
    AI COMMAND SERVICE — CANONICAL DISPATCHER

    Uloga:
    - validira AICommand
    - delegira execution orchestratoru
    - NE određuje execution ishod
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

        if not is_valid_command(command.command):
            raise ValueError(f"Invalid system command: {command.command}")

        definition = get_action_definition(command.command)
        if not definition:
            raise ValueError(
                f"Missing action definition for '{command.command}'"
            )

        allowed_owners = definition.get("allowed_owners", [])
        if allowed_owners and command.owner not in allowed_owners:
            raise PermissionError(
                f"Owner '{command.owner}' is not allowed for command '{command.command}'"
            )

        # SAFETY PRE-CHECK (NON-EXECUTING)
        self.safety.check(command)

        # --------------------------------------------------
        # DELEGATE EXECUTION (SOURCE OF TRUTH)
        # --------------------------------------------------
        result = await self.orchestrator.execute(command)

        # --------------------------------------------------
        # SYNC EXECUTION STATE FROM RESULT (IF PRESENT)
        # --------------------------------------------------
        execution_state = result.get("execution_state")
        if execution_state:
            command.execution_state = execution_state

        AICommand.log(command)

        return result

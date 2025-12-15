# services/ai_command_service.py

from typing import Dict, Any

from models.ai_command import AICommand
from services.action_dictionary import (
    is_valid_command,
    get_action_definition,
)
from services.action_safety_service import ActionSafetyService
from services.execution_orchestrator import ExecutionOrchestrator


class AICommandService:
    """
    EXECUTION DISPATCHER (CANONICAL)

    - prima ISKLJUČIVO AICommand
    - NE izvršava akcije direktno
    - ASYNC dispatcher prema ExecutionOrchestrator-u
    """

    def __init__(self):
        self.safety = ActionSafetyService()
        self.orchestrator = ExecutionOrchestrator()

    # ---------------------------------------------------------
    # MAIN ENTRYPOINT
    # ---------------------------------------------------------

    async def execute(self, command: AICommand) -> Dict[str, Any]:
        """
        Dispatch a validated AICommand to ExecutionOrchestrator.
        """

        # -------------------------------------------------
        # HARD VALIDATION
        # -------------------------------------------------

        if not command.validated:
            raise RuntimeError("AICommand is not validated by COO Translator.")

        if not is_valid_command(command.command):
            raise ValueError(f"Invalid system command: {command.command}")

        definition = get_action_definition(command.command)

        # -------------------------------------------------
        # OWNER VALIDATION (CANONICAL)
        # -------------------------------------------------

        allowed_owners = definition.get("allowed_owners", [])
        if command.owner not in allowed_owners:
            raise PermissionError(
                f"Owner '{command.owner}' is not allowed for command '{command.command}'"
            )

        # -------------------------------------------------
        # SAFETY CHECK (FINAL GUARD)
        # -------------------------------------------------

        self.safety.check(command)

        # -------------------------------------------------
        # DISPATCH TO ORCHESTRATOR (CANONICAL)
        # -------------------------------------------------

        result = await self.orchestrator.execute(command)

        # -------------------------------------------------
        # STATE UPDATE
        # -------------------------------------------------

        command.execution_state = "DISPATCHED"
        AICommand.log_command(command)

        return result

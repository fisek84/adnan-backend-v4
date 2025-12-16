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
    AI COMMAND SERVICE — CANONICAL DISPATCHER

    Uloga:
    - prima ISKLJUČIVO validiran AICommand
    - vrši HARD VALIDACIJE (command + owner + safety)
    - delegira ExecutionOrchestrator-u
    - NE izvršava akcije
    - NE shape-a response
    """

    def __init__(self):
        self.safety = ActionSafetyService()
        self.orchestrator = ExecutionOrchestrator()

    # =========================================================
    # MAIN ENTRYPOINT
    # =========================================================
    async def execute(self, command: AICommand) -> Dict[str, Any]:
        """
        Dispatch validated AICommand to ExecutionOrchestrator.
        """

        # -------------------------------------------------
        # HARD VALIDATION (NON-NEGOTIABLE)
        # -------------------------------------------------
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
            raise ValueError(f"Missing action definition for '{command.command}'")

        # -------------------------------------------------
        # OWNER VALIDATION (CANONICAL)
        # -------------------------------------------------
        allowed_owners = definition.get("allowed_owners", [])
        if allowed_owners and command.owner not in allowed_owners:
            raise PermissionError(
                f"Owner '{command.owner}' is not allowed for command '{command.command}'"
            )

        # -------------------------------------------------
        # SAFETY CHECK (FINAL PRE-GOVERNANCE GUARD)
        # -------------------------------------------------
        self.safety.check(command)

        # -------------------------------------------------
        # DISPATCH (NO SIDE EFFECTS HERE)
        # -------------------------------------------------
        result = await self.orchestrator.execute(command)

        # -------------------------------------------------
        # STATE TRACE (NON-BINDING)
        # -------------------------------------------------
        command.execution_state = "DISPATCHED"
        AICommand.log(command)

        return result

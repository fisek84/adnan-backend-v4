# services/autonomy/autonomy_decision_service.py

"""
AUTONOMY DECISION SERVICE (FAKE / DEV)

Uloga:
- prima META komandu: request_execution
- donosi odluku (OVDJE: uvijek odobrava)
- emituje REAL AICommand za execution

NAPOMENA:
- Ovo je DEV implementacija
- Kasnije se zamjenjuje pravim policy engine-om
"""

from typing import Dict, Any

from models.ai_command import AICommand


class AutonomyDecisionService:
    """
    Fake autonomy brain.
    ALWAYS approves execution requests.
    """

    async def decide(self, command: AICommand) -> AICommand:
        """
        Convert request_execution → real system command.
        """

        requested_command = command.input.get("requested_command")
        if not requested_command:
            raise RuntimeError("Missing requested_command in request_execution")

        # Emit REAL command as SYSTEM
        return AICommand(
            command=requested_command,
            intent=command.intent,
            source="system",                 # 🔐 KLJUČNO
            input={},
            params={},
            metadata={
                "executor": "system",        # 🔐 KLJUČNO
                "approved_by": "autonomy",
            },
            validated=True,
        )

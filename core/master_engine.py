import time
from typing import Any, Dict

from services.state_service import StateService
from services.progress_service import ProgressService
from services.ai_command_service import AICommandService
from models.ai_response import AIResponse
from models.ai_command import AICommand


class MasterEngine:
    """
    Evolia Master Engine — central orchestrator that connects:
    - system state
    - AI command processing
    - progress evaluation
    - future agent routing (extension-ready)
    """

    def __init__(self):
        self.state = StateService()
        self.progress = ProgressService()
        self.ai = AICommandService()

    # ---------------------------------------------------------
    # BASIC SYSTEM STATUS
    # ---------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        return {
            "engine": "master_running",
            "components": {
                "state": True,
                "progress": True,
                "ai_engine": True
            }
        }

    def check_state(self) -> Dict[str, Any]:
        return {"state": self.state.status()}

    def check_progress(self) -> Dict[str, Any]:
        return {"progress": self.progress.compute()}

    # ---------------------------------------------------------
    # CENTRAL AI COMMAND DISPATCH
    # ---------------------------------------------------------
    def run_ai_command(self, payload: Dict[str, Any]) -> AIResponse:
        """
        Main entrypoint for all AI commands in Evolia System.
        Accepts raw dict → validates → executes → wraps output
        into a standardized AIResponse.
        """

        start = time.time()

        # Validate input into AICommand model
        try:
            command = AICommand(**payload)
        except Exception as e:
            return AIResponse(
                success=False,
                result=None,
                message="Invalid AI command payload",
                metadata={"duration_ms": int((time.time() - start) * 1000)},
                error=str(e)
            )

        # Execute via AICommandService
        try:
            result = self.ai.process(command)
            return AIResponse(
                success=True,
                result=result,
                message="AI command executed successfully",
                metadata={
                    "duration_ms": int((time.time() - start) * 1000),
                    "command": command.command,
                },
                error=None
            )

        except Exception as e:
            return AIResponse(
                success=False,
                result=None,
                message="AI engine internal failure",
                metadata={
                    "duration_ms": int((time.time() - start) * 1000),
                    "command": payload.get("command")
                },
                error=str(e)
            )
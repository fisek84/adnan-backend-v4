from typing import Dict, Any
from datetime import datetime
from uuid import uuid4
import logging

from models.ai_command import AICommand
from services.execution_governance_service import ExecutionGovernanceService
from services.autonomy.autonomy_decision_service import AutonomyDecisionService
from services.system_read_executor import SystemReadExecutor
from services.action_execution_service import ActionExecutionService
from services.failure_handler import FailureHandler

logger = logging.getLogger(__name__)


class ExecutionOrchestrator:
    """
    EXECUTION ORCHESTRATOR — KANONSKI (FAZA 3.7)

    Pravila:
    - READ: read_only=True, NO intent
    - WRITE: intent-based
    - nikad ne miješati
    """

    STATE_COMPLETED = "COMPLETED"
    STATE_FAILED = "FAILED"
    STATE_BLOCKED = "BLOCKED"

    CONTRACT_VERSION = "3.3"

    def __init__(self):
        self._governance = ExecutionGovernanceService()
        self._autonomy = AutonomyDecisionService()

        self._read_executor = SystemReadExecutor()
        self._write_executor = ActionExecutionService()
        self._failure_handler = FailureHandler()

    # =========================================================
    # MAIN ENTRYPOINT
    # =========================================================
    async def execute(self, command: AICommand) -> Dict[str, Any]:

        # -----------------------------------------------------
        # AUTONOMY WRAPPER (NO EXECUTION)
        # -----------------------------------------------------
        if command.command == "request_execution":
            approved_command = await self._autonomy.decide(command)
            if not approved_command:
                return self._failure_handler.classify(
                    source="autonomy",
                    reason="Autonomy decision rejected.",
                    execution_id="N/A",
                    metadata={"command": command.command},
                )
            return await self.execute(approved_command)

        if not command.validated:
            raise RuntimeError("Execution attempted on non-validated AICommand.")

        execution_id = str(uuid4())
        started_at = datetime.utcnow().isoformat()

        # -----------------------------------------------------
        # GOVERNANCE
        # -----------------------------------------------------
        governance = self._governance.evaluate(
            role=command.owner,
            context_type=command.metadata.get("context_type", "system"),
            directive=command.command,
            params=command.input or {},
            approval_id=command.approval_id,
        )

        # -----------------------------------------------------
        # APPROVAL BLOCK
        # -----------------------------------------------------
        if not governance.get("allowed"):
            if (
                governance.get("source") == "governance"
                and governance.get("next_csi_state") == "DECISION_PENDING"
            ):
                return {
                    "execution_id": execution_id,
                    "execution_state": self.STATE_BLOCKED,
                    "reason": governance.get("reason"),
                    "command": command.command,
                    "approval_required": True,
                    "read_only": False,
                    "timestamp": started_at,
                }

            return self._failure_handler.classify(
                source=governance.get("source"),
                reason=governance.get("reason"),
                execution_id=execution_id,
                metadata={
                    "governance": governance,
                    "command": command.command,
                },
            )

        # =====================================================
        # READ PATH — SANITIZED (NO INTENT)
        # =====================================================
        if command.read_only:
            try:
                # 🔒 KLJUČNO: READ nikad ne nosi intent
                command.intent = None

                return await self._read_executor.execute(
                    command=command,
                    execution_contract={
                        "execution_id": execution_id,
                        "command": command.command,
                        "contract_version": self.CONTRACT_VERSION,
                        "started_at": started_at,
                    },
                )
            except Exception as e:
                return self._failure_handler.classify(
                    source="system",
                    reason=str(e),
                    execution_id=execution_id,
                    metadata={"command": command.command},
                )

        # =====================================================
        # WRITE PATH — INTENT BASED
        # =====================================================
        if not command.intent:
            raise RuntimeError("WRITE execution requires intent.")

        try:
            result = await self._write_executor.execute(
                intent=command.intent,
                payload=command.input or {},
            )

            return {
                "execution_id": execution_id,
                "execution_state": self.STATE_COMPLETED,
                "intent": command.intent,
                "result": result,
                "contract_version": self.CONTRACT_VERSION,
                "timestamp": datetime.utcnow().isoformat(),
                "read_only": False,
            }

        except Exception as e:
            return self._failure_handler.classify(
                source="execution",
                reason=str(e),
                execution_id=execution_id,
                metadata={"intent": command.intent},
            )

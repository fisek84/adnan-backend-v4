from typing import Dict, Any
import logging
from datetime import datetime
from uuid import uuid4

from services.sop_execution_manager import SOPExecutionManager
from services.notion_ops.ops_engine import NotionOpsEngine
from services.execution_governance_service import ExecutionGovernanceService

logger = logging.getLogger(__name__)


class ExecutionOrchestrator:
    """
    ExecutionOrchestrator — V1.2 EXECUTION → CSI ENFORCED

    RULES:
    - Governance decision is MANDATORY
    - CSI transition is enforced BEFORE execution
    - No execution without explicit EXECUTING state
    """

    STATE_COMPLETED = "COMPLETED"
    STATE_FAILED = "FAILED"

    CSI_COMPLETED = "COMPLETED"
    CSI_FAILED = "FAILED"

    CONTRACT_VERSION = "1.2"

    def __init__(self):
        self._sop_executor = SOPExecutionManager()
        self._notion_executor = NotionOpsEngine()
        self._governance = ExecutionGovernanceService()

    async def execute(
        self,
        decision: Dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> Dict[str, Any]:

        execution_id = str(uuid4())
        started_at = datetime.utcnow().isoformat()

        executor = decision.get("executor")
        command = decision.get("command")
        payload = decision.get("payload", {})

        # --------------------------------------------------
        # VALIDATION
        # --------------------------------------------------
        if not executor or not command:
            return self._fail(
                execution_id=execution_id,
                executor=executor,
                summary="Nema izvršne akcije.",
                started_at=started_at,
            )

        # --------------------------------------------------
        # GOVERNANCE (FAZA D3)
        # --------------------------------------------------
        governance = self._governance.evaluate(
            role=decision.get("role", "system"),
            context_type=decision.get("context_type", "sop"),
            directive=command,
            params=payload,
            approval_id=decision.get("approval_id"),
        )

        next_csi = governance.get("next_csi_state")

        if not governance.get("allowed") or next_csi != "EXECUTING":
            return {
                "execution_id": execution_id,
                "success": False,
                "execution_state": "BLOCKED",
                "csi_next_state": next_csi,
                "executor": executor,
                "summary": governance.get("reason"),
                "started_at": started_at,
                "finished_at": datetime.utcnow().isoformat(),
                "details": {"governance": governance},
                "audit": {
                    "contract_version": self.CONTRACT_VERSION,
                    "executor": executor,
                    "success": False,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            }

        # --------------------------------------------------
        # DRY RUN
        # --------------------------------------------------
        if dry_run:
            return self._success(
                execution_id=execution_id,
                executor=executor,
                summary="Simulacija izvršenja (bez ikakve akcije).",
                started_at=started_at,
                details={
                    "command": command,
                    "payload": payload,
                    "dry_run": True,
                },
            )

        try:
            # --------------------------------------------------
            # ROUTING (EXECUTING ONLY)
            # --------------------------------------------------
            if executor == "sop_execution_manager":
                execution_plan = payload.get("execution_plan")
                sop_id = payload.get("sop_id")

                if not execution_plan:
                    return self._fail(
                        execution_id=execution_id,
                        executor=executor,
                        summary="Nedostaje SOP execution plan.",
                        started_at=started_at,
                    )

                raw = await self._sop_executor.execute_plan(
                    execution_plan=execution_plan,
                    current_sop=sop_id,
                )

            elif executor == "notion_ops":
                raw = await self._notion_executor.execute(
                    command=command,
                    payload=payload,
                )

            else:
                return self._fail(
                    execution_id=execution_id,
                    executor=executor,
                    summary=f"Nepoznat executor: {executor}",
                    started_at=started_at,
                )

            if not isinstance(raw, dict):
                return self._fail(
                    execution_id=execution_id,
                    executor=executor,
                    summary="Nevalidan execution rezultat.",
                    started_at=started_at,
                )

            success = bool(raw.get("success"))

            return self._success(
                execution_id=execution_id,
                executor=executor,
                summary=raw.get("summary", ""),
                started_at=started_at,
                details=raw,
                success=success,
            )

        except Exception as e:
            logger.exception("EXECUTION ERROR")
            return self._fail(
                execution_id=execution_id,
                executor=executor,
                summary=str(e),
                started_at=started_at,
            )

    # ============================================================
    # CONTRACT HELPERS
    # ============================================================
    def _success(
        self,
        *,
        execution_id: str,
        executor: str,
        summary: str,
        started_at: str,
        details: Dict[str, Any],
        success: bool = True,
    ) -> Dict[str, Any]:

        return {
            "execution_id": execution_id,
            "success": success,
            "execution_state": (
                self.STATE_COMPLETED if success else self.STATE_FAILED
            ),
            "csi_next_state": (
                self.CSI_COMPLETED if success else self.CSI_FAILED
            ),
            "executor": executor,
            "summary": summary,
            "started_at": started_at,
            "finished_at": datetime.utcnow().isoformat(),
            "details": details,
            "audit": {
                "contract_version": self.CONTRACT_VERSION,
                "executor": executor,
                "success": success,
                "timestamp": datetime.utcnow().isoformat(),
            },
        }

    def _fail(
        self,
        *,
        execution_id: str,
        executor: str,
        summary: str,
        started_at: str,
    ) -> Dict[str, Any]:

        return {
            "execution_id": execution_id,
            "success": False,
            "execution_state": self.STATE_FAILED,
            "csi_next_state": self.CSI_FAILED,
            "executor": executor,
            "summary": summary,
            "started_at": started_at,
            "finished_at": datetime.utcnow().isoformat(),
            "details": {},
            "audit": {
                "contract_version": self.CONTRACT_VERSION,
                "executor": executor,
                "success": False,
                "timestamp": datetime.utcnow().isoformat(),
            },
        }

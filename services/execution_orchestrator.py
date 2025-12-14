# FILE: services/execution_orchestrator.py

from typing import Dict, Any
import logging
from datetime import datetime
from uuid import uuid4

from services.sop_execution_manager import SOPExecutionManager
from services.notion_ops.ops_engine import NotionOpsEngine
from services.execution_governance_service import ExecutionGovernanceService
from services.memory_service import MemoryService

from services.identity_loader import load_agents_identity
from services.agent_health_registry import AgentHealthRegistry
from services.agent_assignment_service import AgentAssignmentService
from services.agent_load_balancer import AgentLoadBalancer
from services.agent_isolation_service import AgentIsolationService
from services.agent_lifecycle_service import AgentLifecycleService

logger = logging.getLogger(__name__)


class ExecutionOrchestrator:
    """
    ExecutionOrchestrator — EXECUTION GOVERNANCE CORE

    FAZA 6:
    - execution contract
    - partial failure normalization
    - KPI + audit canonicalization

    FAZA 7:
    - agent identity
    - health
    - assignment
    - load balancing
    - isolation
    - lifecycle

    FAZA 12:
    - memory write-path (execution outcomes)
    """

    STATE_COMPLETED = "COMPLETED"
    STATE_FAILED = "FAILED"
    STATE_BLOCKED = "BLOCKED"

    CSI_COMPLETED = "COMPLETED"
    CSI_FAILED = "FAILED"

    CONTRACT_VERSION = "1.3"

    EXECUTION_POLICY = {
        "retry": {"enabled": False, "max_attempts": 1},
        "timeout": {"enabled": False, "max_duration_sec": None},
        "compensation": {"enabled": False},
    }

    def __init__(self):
        # Executors
        self._sop_executor = SOPExecutionManager()
        self._notion_executor = NotionOpsEngine()
        self._governance = ExecutionGovernanceService()

        # Memory (FAZA 12)
        self._memory = MemoryService()

        # Agent OS (FAZA 7)
        self._agents_identity = load_agents_identity()
        self._agent_health = AgentHealthRegistry()
        self._agent_lifecycle = AgentLifecycleService()
        self._agent_isolation = AgentIsolationService()
        self._load_balancer = AgentLoadBalancer()

        self._agent_assignment = AgentAssignmentService(
            agents_identity=self._agents_identity,
            agent_health_registry=self._agent_health,
        )

        for agent_id in self._agents_identity.keys():
            self._agent_health.register_agent(agent_id)

    # ============================================================
    # MAIN EXECUTION
    # ============================================================
    async def execute(self, decision: Dict[str, Any], *, dry_run: bool = False) -> Dict[str, Any]:
        execution_id = str(uuid4())
        started_at = datetime.utcnow()
        started_at_iso = started_at.isoformat()

        executor = decision.get("executor")
        command = decision.get("command")
        payload = decision.get("payload", {})

        execution_contract = {
            "execution_id": execution_id,
            "executor": executor,
            "command": command,
            "policy": self.EXECUTION_POLICY,
            "contract_version": self.CONTRACT_VERSION,
            "started_at": started_at_iso,
        }

        if not executor or not command:
            return self._fail(
                execution_contract=execution_contract,
                summary="Nema izvršne akcije.",
                started_at=started_at_iso,
            )

        # --------------------------------------------------------
        # GOVERNANCE
        # --------------------------------------------------------
        governance = self._governance.evaluate(
            role=decision.get("role", "system"),
            context_type=decision.get("context_type", "sop"),
            directive=command,
            params=payload,
            approval_id=decision.get("approval_id"),
        )

        if not governance.get("allowed"):
            self._memory.store_decision_outcome(
                decision_type="execution",
                context_type=decision.get("context_type", "sop"),
                target=command,
                success=False,
                metadata={"reason": governance.get("reason"), "state": "blocked"},
            )

            return self._blocked(
                execution_contract=execution_contract,
                governance=governance,
                started_at=started_at_iso,
            )

        # --------------------------------------------------------
        # AGENT SELECTION
        # --------------------------------------------------------
        agent_id = self._agent_assignment.assign_agent(command)

        if not agent_id:
            return self._fail_with_memory(
                execution_contract,
                command,
                decision,
                "Nijedan agent nije dostupan.",
                started_at_iso,
            )

        if not self._agent_lifecycle.is_active(agent_id):
            return self._fail_with_memory(
                execution_contract,
                command,
                decision,
                f"Agent '{agent_id}' je deaktiviran.",
                started_at_iso,
            )

        if self._agent_isolation.is_isolated(agent_id):
            return self._fail_with_memory(
                execution_contract,
                command,
                decision,
                f"Agent '{agent_id}' je izolovan.",
                started_at_iso,
            )

        if not self._load_balancer.can_accept(agent_id):
            return self._fail_with_memory(
                execution_contract,
                command,
                decision,
                f"Agent '{agent_id}' je preopterećen.",
                started_at_iso,
            )

        if dry_run:
            return self._success(
                execution_contract=execution_contract,
                summary="Simulacija izvršenja.",
                started_at=started_at_iso,
                finished_at=datetime.utcnow(),
                details={"dry_run": True, "agent": agent_id},
            )

        # --------------------------------------------------------
        # EXECUTION
        # --------------------------------------------------------
        self._load_balancer.reserve(agent_id)
        self._agent_health.mark_alive(agent_id)

        try:
            raw = await self._execute_once(executor, command, payload)
            finished_at = datetime.utcnow()

            success = bool(raw.get("success"))
            partial = self._detect_partial_failure(raw)

            self._memory.store_decision_outcome(
                decision_type="execution",
                context_type=decision.get("context_type", "sop"),
                target=command,
                success=success,
                metadata={
                    "executor": executor,
                    "agent": agent_id,
                    "partial_failure": partial,
                },
            )

            if not success:
                self._agent_health.record_error(agent_id)

            return self._success(
                execution_contract=execution_contract,
                summary=raw.get("summary", ""),
                started_at=started_at_iso,
                finished_at=finished_at,
                details={**raw, "agent": agent_id},
                success=success,
                has_partial_failure=partial,
            )

        except Exception as e:
            self._agent_health.record_error(agent_id)

            self._memory.store_decision_outcome(
                decision_type="execution",
                context_type=decision.get("context_type", "sop"),
                target=command,
                success=False,
                metadata={"error": str(e), "agent": agent_id},
            )

            raise

        finally:
            self._load_balancer.release(agent_id)

    # ============================================================
    # INTERNAL EXECUTION
    # ============================================================
    async def _execute_once(self, executor: str, command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if executor == "sop_execution_manager":
            return await self._sop_executor.execute_plan(
                execution_plan=payload.get("execution_plan"),
                current_sop=payload.get("sop_id"),
            )

        if executor == "notion_ops":
            return await self._notion_executor.execute(command=command, payload=payload)

        raise RuntimeError(f"Nepoznat executor: {executor}")

    # ============================================================
    # HELPERS
    # ============================================================
    def _detect_partial_failure(self, raw: Dict[str, Any]) -> bool:
        return not raw.get("success") and "results" in raw

    def _blocked(self, *, execution_contract, governance, started_at):
        finished_at = datetime.utcnow()
        return {
            "execution_id": execution_contract["execution_id"],
            "success": False,
            "execution_state": self.STATE_BLOCKED,
            "csi_next_state": governance.get("next_csi_state"),
            "executor": execution_contract["executor"],
            "summary": governance.get("reason"),
            "started_at": started_at,
            "finished_at": finished_at.isoformat(),
            "details": {"governance": governance},
        }

    def _fail_with_memory(self, contract, command, decision, reason, started_at):
        self._memory.store_decision_outcome(
            decision_type="execution",
            context_type=decision.get("context_type", "sop"),
            target=command,
            success=False,
            metadata={"reason": reason},
        )
        return self._fail(contract, reason, started_at)

    def _success(self, *, execution_contract, summary, started_at,
                 finished_at, details, success=True, has_partial_failure=False):
        return {
            "execution_id": execution_contract["execution_id"],
            "success": success,
            "execution_state": self.STATE_COMPLETED if success else self.STATE_FAILED,
            "csi_next_state": self.CSI_COMPLETED if success else self.CSI_FAILED,
            "executor": execution_contract["executor"],
            "summary": summary,
            "started_at": started_at,
            "finished_at": finished_at.isoformat(),
            "details": details,
        }

    def _fail(self, execution_contract, summary, started_at):
        finished_at = datetime.utcnow()
        return {
            "execution_id": execution_contract["execution_id"],
            "success": False,
            "execution_state": self.STATE_FAILED,
            "csi_next_state": self.CSI_FAILED,
            "executor": execution_contract["executor"],
            "summary": summary,
            "started_at": started_at,
            "finished_at": finished_at.isoformat(),
        }

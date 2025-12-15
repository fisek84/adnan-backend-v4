from typing import Dict, Any
import logging
from datetime import datetime
from uuid import uuid4

from models.ai_command import AICommand
from services.sop_execution_manager import SOPExecutionManager
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
    Canonical AICommand-based executor.
    """

    STATE_COMPLETED = "COMPLETED"
    STATE_FAILED = "FAILED"
    STATE_BLOCKED = "BLOCKED"

    CSI_COMPLETED = "COMPLETED"
    CSI_FAILED = "FAILED"

    CONTRACT_VERSION = "2.0"

    EXECUTION_POLICY = {
        "retry": {"enabled": False, "max_attempts": 1},
        "timeout": {"enabled": False, "max_duration_sec": None},
        "compensation": {"enabled": False},
    }

    def __init__(self):
        self._sop_executor = SOPExecutionManager()
        self._governance = ExecutionGovernanceService()
        self._memory = MemoryService()

        # -------------------------------
        # AGENT OS (FAZA 7)
        # -------------------------------
        self._agents_identity = load_agents_identity()
        self._agent_health = AgentHealthRegistry()
        self._agent_lifecycle = AgentLifecycleService()
        self._agent_isolation = AgentIsolationService()
        self._load_balancer = AgentLoadBalancer()

        self._agent_assignment = AgentAssignmentService(
            agents_identity=self._agents_identity,
            agent_health_registry=self._agent_health,
        )

        # Agenti su ALIVE na bootu ako su enabled
        for agent_id, agent in self._agents_identity.items():
            self._agent_health.register_agent(agent_id)
            if agent.get("enabled", False):
                self._agent_health.mark_alive(agent_id)

    # ============================================================
    # MAIN EXECUTION
    # ============================================================
    async def execute(self, command: AICommand, *, dry_run: bool = False) -> Dict[str, Any]:

        if not command.validated:
            raise RuntimeError("Execution attempted on non-validated AICommand.")

        executor = command.metadata.get("executor")
        if not executor:
            raise RuntimeError("Missing executor in AICommand metadata.")

        execution_id = str(uuid4())
        started_at = datetime.utcnow().isoformat()

        execution_contract = {
            "execution_id": execution_id,
            "command": command.command,
            "policy": self.EXECUTION_POLICY,
            "contract_version": self.CONTRACT_VERSION,
            "started_at": started_at,
        }

        # --------------------------------------------------------
        # GOVERNANCE
        # --------------------------------------------------------
        governance = self._governance.evaluate(
            role=command.source,
            context_type=command.metadata.get("context_type", "system"),
            directive=command.command,
            params=command.input or {},
            approval_id=command.metadata.get("approval_id"),
        )

        if not governance.get("allowed"):
            return self._blocked(
                execution_contract=execution_contract,
                governance=governance,
                started_at=started_at,
            )

        # --------------------------------------------------------
        # AGENT SELECTION
        # --------------------------------------------------------
        agent_id = self._agent_assignment.assign_agent(executor)

        if not agent_id:
            return self._fail(
                execution_contract,
                "Nijedan agent nije dostupan.",
                started_at,
            )

        if not self._agent_lifecycle.is_active(agent_id):
            return self._fail(
                execution_contract,
                f"Agent '{agent_id}' je deaktiviran.",
                started_at,
            )

        if self._agent_isolation.is_isolated(agent_id):
            return self._fail(
                execution_contract,
                f"Agent '{agent_id}' je izolovan.",
                started_at,
            )

        if not self._load_balancer.can_accept(agent_id):
            return self._fail(
                execution_contract,
                f"Agent '{agent_id}' je preopterećen.",
                started_at,
            )

        # --------------------------------------------------------
        # DRY RUN
        # --------------------------------------------------------
        if dry_run:
            return self._success(
                execution_contract=execution_contract,
                summary="Simulacija delegiranog izvršenja.",
                started_at=started_at,
                finished_at=datetime.utcnow(),
                details={"dry_run": True, "agent": agent_id},
            )

        # --------------------------------------------------------
        # EXECUTION (DELEGATED)
        # --------------------------------------------------------
        self._load_balancer.reserve(agent_id)

        try:
            finished_at = datetime.utcnow()
            return self._success(
                execution_contract=execution_contract,
                summary="Zadatak delegiran agentu na izvršenje.",
                started_at=started_at,
                finished_at=finished_at,
                details={
                    "agent": agent_id,
                    "executor": executor,
                    "command": command.command,
                    "delegated": True,
                },
                success=True,
            )
        finally:
            self._load_balancer.release(agent_id)

    # ============================================================
    # HELPERS
    # ============================================================
    def _blocked(self, *, execution_contract, governance, started_at):
        finished_at = datetime.utcnow()
        return {
            "execution_id": execution_contract["execution_id"],
            "success": False,
            "execution_state": self.STATE_BLOCKED,
            "csi_next_state": governance.get("next_csi_state"),
            "summary": governance.get("reason"),
            "started_at": started_at,
            "finished_at": finished_at.isoformat(),
        }

    def _success(self, *, execution_contract, summary, started_at,
                 finished_at, details, success=True):
        return {
            "execution_id": execution_contract["execution_id"],
            "success": success,
            "execution_state": self.STATE_COMPLETED if success else self.STATE_FAILED,
            "csi_next_state": self.CSI_COMPLETED if success else self.CSI_FAILED,
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
            "summary": summary,
            "started_at": started_at,
            "finished_at": finished_at.isoformat(),
        }

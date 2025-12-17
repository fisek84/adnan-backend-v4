from typing import Dict, Any, Union
import logging

from models.ai_command import AICommand
from services.execution_governance_service import ExecutionGovernanceService
from services.execution_registry import ExecutionRegistry
from services.notion_ops_agent import NotionOpsAgent
from services.notion_service import get_notion_service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ExecutionOrchestrator:
    """
    CANONICAL EXECUTION ORCHESTRATOR

    - orchestrira lifecycle
    - NE odlučuje policy
    - NE izvršava write
    - radi ISKLJUČIVO nad AICommand, uz ulaznu normalizaciju
    """

    def __init__(self):
        self.governance = ExecutionGovernanceService()
        self.registry = ExecutionRegistry()
        self.notion_agent = NotionOpsAgent(get_notion_service())

    async def execute(self, command: Union[AICommand, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Ulaz može biti AICommand ili dict (npr. direktno iz API sloja).
        CANON: ovdje se payload kanonizuje u AICommand, bez interpretacije intent-a.
        """
        cmd = self._normalize_command(command)
        execution_id = cmd.execution_id

        # 1) REGISTER (idempotent)
        self.registry.register(cmd)

        # 2) GOVERNANCE (FIRST-PASS ONLY)
        decision = self.governance.evaluate(
            initiator=cmd.initiator,
            context_type=cmd.command,
            directive=cmd.command,
            params=cmd.params or {},
            execution_id=execution_id,
            approval_id=cmd.approval_id,
        )

        # 3) APPROVAL GATE
        if not decision.get("allowed"):
            cmd.execution_state = "BLOCKED"
            self.registry.block(execution_id, decision)

            return {
                "execution_id": execution_id,
                "execution_state": "BLOCKED",
                "reason": decision.get("reason"),
                "approval_id": decision.get("approval_id"),
            }

        return await self._execute_after_approval(cmd)

    async def resume(self, execution_id: str) -> Dict[str, Any]:
        """
        Resume nakon eksplicitnog odobrenja:
        - ne radi novi governance pass
        - koristi već registrirani AICommand
        """
        command = self.registry.get(execution_id)
        if not command:
            raise RuntimeError("Execution not found")

        # Defanzivno: ako je historijski ostao dict, kanonizuj i osvježi registry
        cmd = self._normalize_command(command)
        if cmd is not command:
            self.registry.register(cmd)

        logger.info("Resuming approved execution %s", execution_id)

        return await self._execute_after_approval(cmd)

    async def _execute_after_approval(self, command: AICommand) -> Dict[str, Any]:
        execution_id = command.execution_id

        # 4) EXECUTE (AGENT)
        command.execution_state = "EXECUTING"
        result = await self.notion_agent.execute(command)

        # 5) COMPLETE
        command.execution_state = "COMPLETED"
        self.registry.complete(execution_id, result)

        return {
            "execution_id": execution_id,
            "execution_state": "COMPLETED",
            "result": result,
        }

    @staticmethod
    def _normalize_command(raw: Union[AICommand, Dict[str, Any]]) -> AICommand:
        """
        Jedini dozvoljeni kanonski tip unutar Orchestratora je AICommand.
        Ako dođe dict, radimo istu normalizaciju kao Registry:
        - rasklapamo ugniježđeni "command" dict
        - propagiramo intent
        - odbacujemo polja koja AICommand ne poznaje
        """
        if isinstance(raw, AICommand):
            return raw

        if isinstance(raw, dict):
            data = dict(raw)

            inner_cmd = data.get("command")
            if isinstance(inner_cmd, dict):
                if "command" in inner_cmd:
                    data["command"] = inner_cmd["command"]
                if "params" in inner_cmd and "params" not in data:
                    data["params"] = inner_cmd["params"]
                if "context_type" in inner_cmd and "context_type" not in data:
                    data["context_type"] = inner_cmd["context_type"]
                if "intent" in inner_cmd and "intent" not in data:
                    data["intent"] = inner_cmd["intent"]

            allowed_fields = set(AICommand.model_fields.keys())
            filtered = {k: v for k, v in data.items() if k in allowed_fields}

            return AICommand(**filtered)

        raise TypeError("ExecutionOrchestrator requires AICommand or dict payload")

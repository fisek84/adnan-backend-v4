from typing import Dict, Any, Union
from threading import Lock

from models.ai_command import AICommand


class ExecutionRegistry:
    """
    CANONICAL EXECUTION REGISTRY

    - SINGLE SOURCE OF TRUTH za execution lifecycle
    - čuva NAJNOVIJI AICommand po execution_id
    - deterministički resume
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._executions: Dict[str, AICommand] = {}
            return cls._instance

    # ============================================================
    # REGISTRATION
    # ============================================================
    def register(self, command: Union[AICommand, Dict[str, Any]]) -> None:
        """
        Registration stores the latest AICommand snapshot.
        Idempotent.

        Ulaz može biti AICommand ili dict (npr. iz gateway_server.py).
        Interno uvijek čuvamo AICommand.
        """
        cmd = self._normalize_command(command)
        self._executions[cmd.execution_id] = cmd

    # ============================================================
    # STATE TRANSITIONS (COMMAND-BASED)
    # ============================================================
    def block(self, execution_id: str, decision: Dict[str, Any]) -> None:
        command = self._require(execution_id)
        command.execution_state = "BLOCKED"
        command.decision = decision

    def complete(self, execution_id: str, result: Dict[str, Any]) -> None:
        command = self._require(execution_id)
        command.execution_state = "COMPLETED"
        command.result = result

    # ============================================================
    # ACCESS
    # ============================================================
    def get(self, execution_id: str) -> AICommand | None:
        return self._executions.get(execution_id)

    def _require(self, execution_id: str) -> AICommand:
        if execution_id not in self._executions:
            raise RuntimeError(f"Execution {execution_id} not registered")
        return self._executions[execution_id]

    # ============================================================
    # NORMALIZATION
    # ============================================================
    @staticmethod
    def _normalize_command(command: Union[AICommand, Dict[str, Any]]) -> AICommand:
        """
        Jedini kanonski tip unutar Registry-ja je AICommand.
        Ako dođe dict, plitko ga normalizujemo bez mijenjanja intent-a:
        - rasklapamo ugniježđeni "command" dict
        - propagiramo intent
        - odbacujemo polja koja AICommand ne poznaje (npr. "status")
        """
        if isinstance(command, AICommand):
            return command

        if isinstance(command, dict):
            raw = dict(command)  # plitka kopija

            # Ako je raw["command"] ugniježđeni dict (goal_write, intent, params, context_type...)
            inner_cmd = raw.get("command")
            if isinstance(inner_cmd, dict):
                # Bez interpretacije intent-a: samo prenosimo polja 1:1
                if "command" in inner_cmd:
                    raw["command"] = inner_cmd["command"]
                if "params" in inner_cmd and "params" not in raw:
                    raw["params"] = inner_cmd["params"]
                if "context_type" in inner_cmd and "context_type" not in raw:
                    raw["context_type"] = inner_cmd["context_type"]
                if "intent" in inner_cmd and "intent" not in raw:
                    raw["intent"] = inner_cmd["intent"]

            # Filtriraj samo polja koja AICommand poznaje (Pydantic v2)
            allowed_fields = set(AICommand.model_fields.keys())
            filtered = {k: v for k, v in raw.items() if k in allowed_fields}

            return AICommand(**filtered)

        raise TypeError("ExecutionRegistry.register requires AICommand or dict payload")

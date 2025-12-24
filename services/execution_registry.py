from __future__ import annotations

from threading import Lock
from typing import Any, Dict, Optional, Union

from models.ai_command import AICommand


class ExecutionRegistry:
    """
    CANONICAL EXECUTION REGISTRY

    - SINGLE SOURCE OF TRUTH za execution lifecycle
    - čuva NAJNOVIJI AICommand po execution_id
    - deterministički resume
    """

    _instance: Optional["ExecutionRegistry"] = None
    _lock: Lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._executions = {}
                cls._instance._exec_lock = Lock()
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

        execution_id = getattr(cmd, "execution_id", None)
        if not isinstance(execution_id, str) or not execution_id:
            raise ValueError(
                "ExecutionRegistry.register requires command with execution_id"
            )

        with self._exec_lock:
            self._executions[execution_id] = cmd

    # ============================================================
    # STATE TRANSITIONS (COMMAND-BASED)
    # ============================================================
    def block(self, execution_id: str, decision: Dict[str, Any]) -> None:
        with self._exec_lock:
            command = self._require(execution_id)
            command.execution_state = "BLOCKED"
            command.decision = decision

    def complete(self, execution_id: str, result: Dict[str, Any]) -> None:
        with self._exec_lock:
            command = self._require(execution_id)
            command.execution_state = "COMPLETED"
            command.result = result

    # ============================================================
    # ACCESS
    # ============================================================
    def get(self, execution_id: str) -> Optional[AICommand]:
        with self._exec_lock:
            return self._executions.get(execution_id)

    def _require(self, execution_id: str) -> AICommand:
        if execution_id not in self._executions:
            raise RuntimeError(f"Execution {execution_id} not registered")
        return self._executions[execution_id]

    # ============================================================
    # NORMALIZATION
    # ============================================================
    @staticmethod
    def _allowed_fields() -> set[str]:
        # Pydantic v2: model_fields, Pydantic v1: __fields__
        model_fields = getattr(AICommand, "model_fields", None)
        if isinstance(model_fields, dict):
            return set(model_fields.keys())

        v1_fields = getattr(AICommand, "__fields__", None)
        if isinstance(v1_fields, dict):
            return set(v1_fields.keys())

        return set()

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
            raw: Dict[str, Any] = dict(command)  # plitka kopija

            inner_cmd = raw.get("command")
            if isinstance(inner_cmd, dict):
                # Bez interpretacije intent-a: samo prenosimo polja 1:1
                inner_command = inner_cmd.get("command")
                if isinstance(inner_command, str):
                    raw["command"] = inner_command

                if "params" in inner_cmd and "params" not in raw:
                    raw["params"] = inner_cmd.get("params")

                if "context_type" in inner_cmd and "context_type" not in raw:
                    raw["context_type"] = inner_cmd.get("context_type")

                if "intent" in inner_cmd and "intent" not in raw:
                    raw["intent"] = inner_cmd.get("intent")

            allowed_fields = ExecutionRegistry._allowed_fields()
            if allowed_fields:
                filtered = {k: v for k, v in raw.items() if k in allowed_fields}
            else:
                filtered = raw

            return AICommand(**filtered)

        raise TypeError("ExecutionRegistry.register requires AICommand or dict payload")

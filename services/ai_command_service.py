from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable


class AICommandService:
    """
    Evolia AI Command Engine v3.0 (PRO)
    -------------------------------------------------------
    Napredni komandni pipeline:
    ✔ komande registrirane po imenu
    ✔ validacija payload-a
    ✔ automatski logovi
    ✔ hvatanje grešaka (bez pucanja)
    ✔ standardizovan izlaz
    ✔ proširiv sistem za AI agente
    """

    def __init__(self):
        # command_name → callable
        self.commands: Dict[str, Callable] = {}

        # event log
        self.logs = []

        self.register_default_commands()

    # ============================================================
    # INTERNAL HELPERS
    # ============================================================
    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def _log(self, status: str, command: str, payload: Any, message: str = None):
        self.logs.append({
            "timestamp": self._now(),
            "status": status,
            "command": command,
            "payload": payload,
            "message": message,
        })

    # ============================================================
    # COMMAND REGISTRATION
    # ============================================================
    def register(self, name: str, fn: Callable):
        """
        Register a new AI command.
        Example:
            ai.register("sync_goals", lambda p: sync_service.sync_goals_up())
        """
        self.commands[name] = fn

    def register_default_commands(self):
        """
        Default built-in commands for Evolia system.
        """

        # simple ping
        self.register("ping", lambda payload: {"pong": True})

        # echo (for debugging)
        self.register("echo", lambda payload: payload)

        # time fetch
        self.register("time", lambda payload: {"time": self._now()})

    # ============================================================
    # PROCESS COMMAND
    # ============================================================
    def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a command from payload:
        {
            "command": "something",
            "args": { ... }
        }
        """

        # -----------------------------
        # validate structure
        # -----------------------------
        if "command" not in payload:
            self._log("error", "unknown", payload, "Missing 'command'")
            return {
                "status": "error",
                "error": "Missing 'command' field"
            }

        command_name = payload["command"]
        args = payload.get("args", {})

        # -----------------------------
        # unknown command
        # -----------------------------
        if command_name not in self.commands:
            self._log("error", command_name, args, "Unknown command")
            return {
                "status": "error",
                "error": f"Unknown command '{command_name}'",
                "available_commands": list(self.commands.keys())
            }

        fn = self.commands[command_name]

        # -----------------------------
        # execute safely
        # -----------------------------
        try:
            result = fn(args)
            self._log("success", command_name, args)
            return {
                "status": "success",
                "command": command_name,
                "output": result
            }

        except Exception as e:
            self._log("error", command_name, args, str(e))
            return {
                "status": "error",
                "command": command_name,
                "error": str(e)
            }

    # ============================================================
    # STATUS / INSPECTION
    # ============================================================
    def status(self):
        return {
            "commands_registered": list(self.commands.keys()),
            "logs_count": len(self.logs),
            "recent_logs": self.logs[-15:],
        }
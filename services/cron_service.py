# services/cron_service.py

from datetime import datetime, timezone
from typing import Callable, Dict, List, Any
import threading


class CronJobError(Exception):
    """Raised when a cron job fails."""

    pass


class CronService:
    """
    Evolia CronService v2.1 — CANONICAL (FAZA 13 / SCALING)

    Uloga:
    - determinističko izvršavanje cron jobova
    - BACKPRESSURE: nema paralelnog run-a
    - FAILURE CONTAINMENT: jedan job ne ruši ostale
    - READ / WRITE eksplicitno kontrolisano

    ZABRANE:
    - NEMA paralelizma
    - NEMA retry heuristika
    - NEMA autonomnog schedulinga
    """

    def __init__(self):
        self.jobs: Dict[str, Callable] = {}
        self.last_run: Dict[str, str] = {}
        self.logs: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._running = False

    # ---------------------------------------------------------
    # UTILITIES
    # ---------------------------------------------------------
    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ---------------------------------------------------------
    # JOB REGISTRATION (DETERMINISTIC)
    # ---------------------------------------------------------
    def register(self, name: str, fn: Callable):
        if not callable(fn):
            raise ValueError("Cron job must be callable")

        self.jobs[name] = fn

    # ---------------------------------------------------------
    # INTERNAL: LOG RECORD
    # ---------------------------------------------------------
    def _log(self, name: str, status: str, message: str = None):
        self.logs.append(
            {
                "timestamp": self._now(),
                "job": name,
                "status": status,
                "message": message,
            }
        )

    # ---------------------------------------------------------
    # RUN ALL CRON JOBS (BACKPRESSURE GUARDED)
    # ---------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        with self._lock:
            if self._running:
                return {
                    "cron_status": "rejected",
                    "reason": "cron_already_running",
                    "timestamp": self._now(),
                }
            self._running = True

        results = {}

        try:
            for name, fn in self.jobs.items():
                try:
                    output = fn()  # sync only, by design
                    self.last_run[name] = self._now()

                    results[name] = {
                        "status": "success",
                        "output": output,
                    }
                    self._log(name, "success")

                except Exception as e:
                    self._log(name, "error", str(e))
                    results[name] = {
                        "status": "error",
                        "error": str(e),
                    }

            return {
                "cron_status": "executed",
                "timestamp": self._now(),
                "results": results,
            }

        finally:
            with self._lock:
                self._running = False

    # ---------------------------------------------------------
    # HEALTH / STATUS (READ ONLY)
    # ---------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "jobs_registered": list(self.jobs.keys()),
            "last_run": dict(self.last_run),
            "log_count": len(self.logs),
            "recent_logs": self.logs[-10:],
            "read_only": True,
        }

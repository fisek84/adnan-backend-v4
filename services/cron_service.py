from datetime import datetime, timezone
from typing import Callable, Dict, List, Any


class CronJobError(Exception):
    """Raised when a cron job fails."""
    pass


class CronService:
    """
    Evolia CronService v2.0 (PRO)
    --------------------------------------------------------
    - Registracija cron jobova
    - Praćenje zadnjeg izvršenja
    - Logovanje uspjeha i grešaka
    - Izvršavanje svih cron jobova po pozivu
    - Sigurnosni error handling
    """

    def __init__(self):
        self.jobs: Dict[str, Callable] = {}
        self.last_run: Dict[str, str] = {}
        self.logs: List[Dict[str, Any]] = []

    # ---------------------------------------------------------
    # UTILITIES
    # ---------------------------------------------------------
    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    # ---------------------------------------------------------
    # JOB REGISTRATION
    # ---------------------------------------------------------
    def register(self, name: str, fn: Callable):
        """
        Register a cron job function.
        Example:
            cron.register("sync_goals", lambda: sync_service.sync_goals_up())
        """
        self.jobs[name] = fn

    # ---------------------------------------------------------
    # INTERNAL: record log
    # ---------------------------------------------------------
    def _log(self, name: str, status: str, message: str = None):
        entry = {
            "timestamp": self._now(),
            "job": name,
            "status": status,
            "message": message,
        }
        self.logs.append(entry)

    # ---------------------------------------------------------
    # RUN ALL CRON JOBS
    # ---------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        results = {}

        for name, fn in self.jobs.items():
            try:
                output = fn()  # support sync functions
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

    # ---------------------------------------------------------
    # HEALTH CHECK
    # ---------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        return {
            "jobs_registered": list(self.jobs.keys()),
            "last_run": self.last_run,
            "log_count": len(self.logs),
            "recent_logs": self.logs[-10:]
        }
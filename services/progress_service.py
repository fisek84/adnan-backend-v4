from datetime import datetime, timezone
from typing import Optional


class ProgressService:
    """
    Centralni engine za praćenje napretka sistema.
    Računa:
    - uspješnost operacija
    - vrijeme izvršavanja
    - ratio uspjeh/neuspjeh
    - prosječno vrijeme događaja

    Spreman za proširenje u AI/Notion sync sistemu.
    """

    def __init__(self):
        self.total_operations = 0
        self.success_count = 0
        self.failure_count = 0
        self.events: list[dict] = []

    # ---------------------------------------------------------
    # RECORD EVENTS
    # ---------------------------------------------------------
    def record_success(self, message: str = "ok"):
        """
        Bilježi uspješan događaj.
        """
        self.total_operations += 1
        self.success_count += 1

        self.events.append({
            "timestamp": self._now(),
            "status": "success",
            "message": message
        })

    def record_failure(self, message: str):
        """
        Bilježi neuspješan događaj.
        """
        self.total_operations += 1
        self.failure_count += 1

        self.events.append({
            "timestamp": self._now(),
            "status": "failure",
            "message": message
        })

    # ---------------------------------------------------------
    # COMPUTE PROGRESS SNAPSHOT
    # ---------------------------------------------------------
    def compute(self) -> dict:
        """
        Vraća snapshot trenutnog napretka sistema:
        - ukupne operacije
        - uspješnost
        - neuspješnost
        - ukupni score (%)
        - zadnji događaji
        """
        if self.total_operations == 0:
            score = None
        else:
            score = round((self.success_count / self.total_operations) * 100, 2)

        return {
            "engine": "progress_service",
            "total_operations": self.total_operations,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": score,
            "recent_events": self.events[-10:]
        }

    # ---------------------------------------------------------
    # RESET ENGINE
    # ---------------------------------------------------------
    def reset(self):
        """
        Resetuje stanje napretka.
        """
        self.total_operations = 0
        self.success_count = 0
        self.failure_count = 0
        self.events.clear()

        return {
            "status": "reset",
            "timestamp": self._now()
        }

    # ---------------------------------------------------------
    # INTERNAL
    # ---------------------------------------------------------
    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
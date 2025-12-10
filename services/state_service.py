from datetime import datetime, timezone


class StateService:
    """
    Centralno mjesto za praćenje internog stanja sistema.
    Može se povezati sa:
    - MasterEngine
    - AI subsystemima
    - Sync servisima
    """

    def __init__(self):
        self.boot_time = datetime.now(timezone.utc)
        self.state_flags = {}
        self.events = []

    # ---------------------------------------------------------
    # BASIC STATUS
    # ---------------------------------------------------------
    def status(self) -> dict:
        """
        Vraća trenutno stanje servisa sa metapodacima.
        """
        return {
            "service": "state_service",
            "status": "active",
            "boot_time": self.boot_time.isoformat(),
            "uptime_seconds": self._uptime(),
            "flags": self.state_flags,
            "events_count": len(self.events),
        }

    # ---------------------------------------------------------
    # STATE FLAGS
    # ---------------------------------------------------------
    def set_flag(self, key: str, value: bool):
        """
        Postavlja interne state flagove (npr. 'sync_running': True).
        """
        self.state_flags[key] = value

    def get_flag(self, key: str) -> bool:
        return self.state_flags.get(key, False)

    # ---------------------------------------------------------
    # EVENT LOGGING
    # ---------------------------------------------------------
    def record_event(self, message: str):
        """
        Bilježi sistemske događaje (debug, info, problemi…).
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": message,
        }
        self.events.append(entry)

    def get_events(self, last: int = 20):
        """
        Vraća zadnjih X događaja (default: 20).
        """
        return self.events[-last:]

    # ---------------------------------------------------------
    # INTERNAL
    # ---------------------------------------------------------
    def _uptime(self) -> float:
        """
        Koliko sekundi je servis aktivan.
        """
        delta = datetime.now(timezone.utc) - self.boot_time
        return round(delta.total_seconds(), 2)
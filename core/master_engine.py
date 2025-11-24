class MasterEngine:
    """
    Evolia MasterEngine v4.1
    - Minimal core engine
    - Used for system-level checks, diagnostics, internal state
    """

    def __init__(self):
        self._state = "idle"
        self._progress = 0
        self._info = {}

    # ============================================================
    # INTERNAL STATE MGMT
    # ============================================================
    def set_state(self, state: str):
        self._state = state

    def set_progress(self, progress: int):
        self._progress = max(0, min(100, progress))

    def update_info(self, key: str, value):
        self._info[key] = value

    # ============================================================
    # GETTERS (USED BY ROUTES)
    # ============================================================
    def status(self):
        return {"state": self._state}

    def check_state(self):
        return {
            "state": self._state,
            "progress": self._progress,
            "info": self._info
        }

    def check_progress(self):
        return {"progress": self._progress}
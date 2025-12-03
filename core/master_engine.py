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

        # Inicijalizujemo logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    # ============================================================
    # INTERNAL STATE MGMT
    # ============================================================
    def set_state(self, state: str):
        self.logger.info(f"Setting state to: {state}")
        self._state = state

    def set_progress(self, progress: int):
        progress = max(0, min(100, progress))
        self.logger.info(f"Setting progress to: {progress}%")
        self._progress = progress

    def update_info(self, key: str, value):
        self.logger.info(f"Updating info: {key} = {value}")
        self._info[key] = value

    # ============================================================
    # GETTERS (USED BY ROUTES)
    # ============================================================
    def status(self):
        self.logger.debug(f"Checking state: {self._state}")
        return {"state": self._state}

    def check_state(self):
        self.logger.debug(f"Checking internal state: {self._state}, progress: {self._progress}, info: {self._info}")
        return {
            "state": self._state,
            "progress": self._progress,
            "info": self._info
        }

    def check_progress(self):
        self.logger.debug(f"Checking progress: {self._progress}")
        return {"progress": self._progress}

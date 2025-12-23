import logging


class MasterEngine:
    """
    Evolia MasterEngine v4.1
    - Minimal core engine
    - Used for system-level checks, diagnostics, internal state
    """

    def __init__(self) -> None:
        self._state: str = "idle"
        self._progress: int = 0
        self._info: dict[str, object] = {}

        # Inicijalizujemo logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    # ============================================================
    # INTERNAL STATE MGMT
    # ============================================================
    def set_state(self, state: str) -> None:
        self.logger.info(f"Setting state to: {state}")
        self._state = state

    def set_progress(self, progress: int) -> None:
        clamped = max(0, min(100, progress))
        self.logger.info(f"Setting progress to: {clamped}%")
        self._progress = clamped

    def update_info(self, key: str, value: object) -> None:
        self.logger.info(f"Updating info: {key} = {value}")
        self._info[key] = value

    # ============================================================
    # GETTERS (USED BY ROUTES)
    # ============================================================
    def status(self) -> dict[str, str]:
        self.logger.debug(f"Checking state: {self._state}")
        return {"state": self._state}

    def check_state(self) -> dict[str, object]:
        self.logger.debug(
            "Checking internal state: %s, progress: %s, info: %s",
            self._state,
            self._progress,
            self._info,
        )
        return {"state": self._state, "progress": self._progress, "info": self._info}

    def check_progress(self) -> dict[str, int]:
        self.logger.debug(f"Checking progress: {self._progress}")
        return {"progress": self._progress}

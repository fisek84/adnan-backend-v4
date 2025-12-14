# services/autonomy/safe_mode.py

class AutonomySafeMode:
    """
    Read-only / safe mode.

    RULES:
    - Autonomy can evaluate
    - Autonomy cannot suggest actions
    """

    def __init__(self, enabled: bool = False):
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False
    
# services/autonomy/kill_switch.py

class AutonomyKillSwitch:
    """
    Global kill-switch for autonomy.

    RULES:
    - Hard override
    - Checked before policy, coordinator, recovery
    """

    def __init__(self, enabled: bool = True):
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def disable(self):
        self._enabled = False

    def enable(self):
        self._enabled = True

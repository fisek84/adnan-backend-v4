# services/autonomy/kill_switch.py

from datetime import datetime
from typing import Optional


class AutonomyKillSwitch:
    """
    Global kill-switch for autonomy.

    FAZA 8 / #24 — KILL-SWITCH ENFORCEMENT

    RULES:
    - Hard override (no bypass)
    - Checked before ANY autonomy logic
    - Audit-friendly (timestamped)
    - No execution, no side-effects beyond state
    """

    def __init__(self, enabled: bool = True):
        self._enabled: bool = enabled
        self._last_changed_at: Optional[str] = datetime.utcnow().isoformat()

    # -------------------------------------------------
    # READ
    # -------------------------------------------------
    def is_enabled(self) -> bool:
        return self._enabled

    def status(self) -> dict:
        return {
            "enabled": self._enabled,
            "last_changed_at": self._last_changed_at,
        }

    # -------------------------------------------------
    # HARD CONTROL
    # -------------------------------------------------
    def disable(self, *, reason: Optional[str] = None):
        self._enabled = False
        self._last_changed_at = datetime.utcnow().isoformat()
        # reason intentionally not persisted here (no storage side-effects)

    def enable(self):
        self._enabled = True
        self._last_changed_at = datetime.utcnow().isoformat()

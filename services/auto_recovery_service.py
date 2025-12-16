from typing import Dict, Any
import logging
from datetime import datetime

from services.alerting_service import AlertingService
from services.adnan_mode_service import load_mode, save_mode


logger = logging.getLogger(__name__)


class AutoRecoveryService:
    """
    AutoRecoveryService — FAZA 10 / Agent Specialization

    RULES:
    - READ alerting status
    - READ current mode
    - WRITE mode.json only when safe
    - NO execution
    - NO decisions
    """

    RECOVERABLE_MODES = {"safe", "restricted"}
    TARGET_MODE = "operational"

    def __init__(self):
        self.alerting = AlertingService()

    # --------------------------------------------------
    # PUBLIC ENTRYPOINT
    # --------------------------------------------------
    def evaluate_and_recover(self) -> Dict[str, Any]:
        alert_status = self.alerting.evaluate()

        if alert_status.get("ok") is not True:
            return {
                "recovered": False,
                "reason": "System still unhealthy",
                "violations": alert_status.get("violations") or [],
            }

        current_mode = load_mode()
        current_mode_name = current_mode.get("current_mode")

        if current_mode_name not in self.RECOVERABLE_MODES:
            return {
                "recovered": False,
                "reason": "Current mode not recoverable",
                "current_mode": current_mode_name,
            }

        # --------------------------------------------------
        # APPLY RECOVERY (EXPLICIT, GOVERNED)
        # --------------------------------------------------
        new_mode = {
            "current_mode": self.TARGET_MODE,
            "changed_at": datetime.utcnow().isoformat(),
            "reason": "Auto-recovery: system healthy",
            "previous_mode": current_mode_name,
        }

        save_mode(new_mode)

        logger.info(
            "AUTO-RECOVERY: %s → %s",
            current_mode_name,
            self.TARGET_MODE,
        )

        return {
            "recovered": True,
            "from": current_mode_name,
            "to": self.TARGET_MODE,
        }

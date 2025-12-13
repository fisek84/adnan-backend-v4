from typing import Dict, Any
import logging
from datetime import datetime

from services.alerting_service import AlertingService
from services.adnan_mode_service import load_mode, save_mode


logger = logging.getLogger(__name__)


class AutoDegradationService:
    """
    Auto-degradation Service

    RULES:
    - READ alerting status
    - WRITE mode.json only
    - NO execution
    - NO decisions
    """

    def __init__(self):
        self.alerting = AlertingService()

    # --------------------------------------------------
    # PUBLIC ENTRYPOINT
    # --------------------------------------------------
    def evaluate_and_apply(self) -> Dict[str, Any]:
        alert_status = self.alerting.evaluate()

        if alert_status["ok"]:
            return {
                "changed": False,
                "reason": "System healthy",
            }

        violations = alert_status.get("violations", [])
        if not violations:
            return {
                "changed": False,
                "reason": "No actionable violations",
            }

        current_mode = load_mode()
        current_mode_name = current_mode.get("current_mode")

        target_mode = self._resolve_target_mode(violations)

        if not target_mode or target_mode == current_mode_name:
            return {
                "changed": False,
                "reason": "No mode change required",
                "current_mode": current_mode_name,
            }

        # --------------------------------------------------
        # APPLY MODE CHANGE
        # --------------------------------------------------
        new_mode = {
            "current_mode": target_mode,
            "changed_at": datetime.utcnow().isoformat(),
            "reason": violations,
        }

        save_mode(new_mode)

        logger.warning(
            "AUTO-DEGRADATION: %s → %s",
            current_mode_name,
            target_mode,
        )

        return {
            "changed": True,
            "from": current_mode_name,
            "to": target_mode,
            "violations": violations,
        }

    # --------------------------------------------------
    # MODE RESOLUTION
    # --------------------------------------------------
    def _resolve_target_mode(self, violations) -> str:
        for v in violations:
            if v["type"] == "governance_block_rate":
                return "restricted"

            if v["type"] in {
                "decision_success_rate",
                "execution_failure_rate",
            }:
                return "safe"

        return ""

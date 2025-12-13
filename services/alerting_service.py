from typing import Dict, Any, List
import logging

from services.metrics_service import MetricsService

logger = logging.getLogger(__name__)


class AlertingService:
    """
    SLA / SLO Alerting Service

    RULES:
    - READ-ONLY
    - Evaluates metrics snapshot
    - Returns violations
    - NO execution
    - NO side effects
    """

    # --------------------------------------------------
    # SLO THRESHOLDS (KANONSKI)
    # --------------------------------------------------
    DECISION_SUCCESS_MIN = 0.90
    EXECUTION_FAILURE_MAX = 0.10
    GOVERNANCE_BLOCK_MAX = 0.30

    # --------------------------------------------------
    # PUBLIC ENTRYPOINT
    # --------------------------------------------------
    def evaluate(self) -> Dict[str, Any]:
        snapshot = MetricsService.snapshot()
        counters = snapshot.get("counters", {})

        violations: List[Dict[str, Any]] = []

        # ----------------------------------------------
        # DECISION SUCCESS RATE
        # ----------------------------------------------
        decision_created = counters.get("decision.created", 0)
        decision_confirmed = counters.get("decision.confirmed", 0)

        if decision_created > 0:
            success_rate = decision_confirmed / decision_created
            if success_rate < self.DECISION_SUCCESS_MIN:
                violations.append({
                    "type": "decision_success_rate",
                    "value": round(success_rate, 2),
                    "threshold": self.DECISION_SUCCESS_MIN,
                })

        # ----------------------------------------------
        # EXECUTION FAILURE RATE
        # ----------------------------------------------
        execution_total = counters.get("execution.total", 0)
        execution_failed = counters.get("execution.failed", 0)

        if execution_total > 0:
            failure_rate = execution_failed / execution_total
            if failure_rate > self.EXECUTION_FAILURE_MAX:
                violations.append({
                    "type": "execution_failure_rate",
                    "value": round(failure_rate, 2),
                    "threshold": self.EXECUTION_FAILURE_MAX,
                })

        # ----------------------------------------------
        # GOVERNANCE BLOCK RATE
        # ----------------------------------------------
        governance_checks = counters.get("governance.checked", 0)
        governance_blocked = counters.get("governance.blocked", 0)

        if governance_checks > 0:
            block_rate = governance_blocked / governance_checks
            if block_rate > self.GOVERNANCE_BLOCK_MAX:
                violations.append({
                    "type": "governance_block_rate",
                    "value": round(block_rate, 2),
                    "threshold": self.GOVERNANCE_BLOCK_MAX,
                })

        return {
            "ok": len(violations) == 0,
            "violations": violations,
            "snapshot": {
                "decision_created": decision_created,
                "execution_total": execution_total,
                "governance_checks": governance_checks,
            },
        }

from typing import Optional, Dict, Any
from dataclasses import dataclass

from services.autonomy.activation_contract import AutonomyProposal


@dataclass
class AutonomyCycleResult:
    """
    Aggregated result of a single autonomy evaluation cycle.
    Data-only, no side effects.
    """

    loop: Optional[str]
    self_check: Optional[str]
    recovery: Optional[str]
    reevaluation: Optional[Dict[str, Any]] = None
    proposal: Optional[AutonomyProposal] = None


class AutonomyCoordinator:
    """
    Coordinates a single autonomy evaluation cycle.

    FAZA 8 / #22:
    - explicit goal/plan re-evaluation signal
    - no decisions
    - no execution
    """

    def run_cycle(
        self,
        *,
        iteration: int,
        csi_state: str,
        expected_outcome: Optional[Dict[str, Any]] = None,
        actual_result: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
        last_error: Optional[str] = None,
    ) -> AutonomyCycleResult:
        """
        Aggregates autonomy evaluation signals.
        """

        # -------------------------------------------------
        # RE-EVALUATION SIGNAL (DATA ONLY)
        # -------------------------------------------------
        reevaluation = {
            "iteration": iteration,
            "expected_outcome": expected_outcome,
            "actual_result": actual_result,
            "retry_count": retry_count,
            "last_error": last_error,
            "needs_review": bool(last_error) or retry_count > 0,
        }

        # Coordinator does NOT generate proposals.
        proposal = None

        return AutonomyCycleResult(
            loop="evaluated",
            self_check="evaluated",
            recovery="evaluated",
            reevaluation=reevaluation,
            proposal=proposal,
        )

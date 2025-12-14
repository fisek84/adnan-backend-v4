# services/autonomy/autonomy_coordinator.py

from typing import Optional
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
    proposal: Optional[AutonomyProposal] = None


class AutonomyCoordinator:
    """
    Coordinates a single autonomy evaluation cycle.

    RULES:
    - No decision making
    - No heuristics
    - No execution semantics
    - Aggregation only
    """

    def run_cycle(
        self,
        *,
        iteration: int,
        csi_state: str,
        expected_outcome=None,
        actual_result=None,
        retry_count: int = 0,
        last_error: Optional[str] = None,
    ) -> AutonomyCycleResult:
        """
        Aggregates autonomy evaluation signals.
        """

        # Coordinator does NOT generate proposals.
        # Proposals are produced by dedicated evaluators (e.g. RecoveryStrategy).
        proposal = None

        return AutonomyCycleResult(
            loop="evaluated",
            self_check="evaluated",
            recovery="evaluated",
            proposal=proposal,
        )

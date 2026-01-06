# services/execution_governance_service.py

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from services.approval_state_service import get_approval_state
from services.policy_service import PolicyService


class ExecutionGovernanceService:
    """
    EXECUTION GOVERNANCE SERVICE — CANONICAL

    Pravilo:
    - Policy gleda KO TRAŽI (initiator), ne ko POSJEDUJE sistem
    - Governance NE ponavlja safety
    - Governance NE SMIJE praviti dupli approval ako je approval lifecycle već kreiran upstream (npr. /api/execute).
      Njegova uloga je: validate + policy gate + approval verification.
    """

    # Minimalni read-only direktivi koji NE TRAŽE approval.
    # (Usklađeno sa COOTranslationService._KNOWN_COMMANDS i sistemskim pitanjima.)
    _READ_ONLY_DIRECTIVES = {"system_query", "list_goals"}

    def __init__(self) -> None:
        self.policy = PolicyService()
        self.approvals = get_approval_state()

        self._governance_limits: Dict[str, Any] = {
            "max_execution_time_seconds": 30,
            "retry_policy": {"enabled": False, "max_retries": 0},
        }

    def evaluate(
        self,
        *,
        initiator: str,
        context_type: str,
        directive: str,
        params: Dict[str, Any],  # primamo parametre, ali governance ih ne mijenja
        execution_id: str,
        approval_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        ts = datetime.utcnow().isoformat()

        initiator_norm = str(initiator or "").strip()
        context_type_norm = str(context_type or "").strip()
        directive_norm = str(directive or "").strip()
        execution_id_norm = str(execution_id or "").strip()

        approval_id_norm: Optional[str]
        if approval_id is None:
            approval_id_norm = None
        else:
            a = str(approval_id).strip()
            approval_id_norm = a if a else None

        # --------------------------------------------------------
        # BASIC VALIDATION
        # --------------------------------------------------------
        if not execution_id_norm:
            return self._block(
                reason="missing_execution_id",
                ts=ts,
                execution_id=execution_id_norm,
                context_type=context_type_norm,
                directive=directive_norm,
                approval_id=approval_id_norm,
            )

        if not initiator_norm:
            return self._block(
                reason="missing_initiator",
                ts=ts,
                execution_id=execution_id_norm,
                context_type=context_type_norm,
                directive=directive_norm,
                approval_id=approval_id_norm,
            )

        if not directive_norm:
            return self._block(
                reason="missing_directive",
                ts=ts,
                execution_id=execution_id_norm,
                context_type=context_type_norm,
                directive=directive_norm,
                approval_id=approval_id_norm,
            )

        if not context_type_norm:
            return self._block(
                reason="missing_context_type",
                ts=ts,
                execution_id=execution_id_norm,
                context_type=context_type_norm,
                directive=directive_norm,
                approval_id=approval_id_norm,
            )

        # --------------------------------------------------------
        # POLICY (INITIATOR-AWARE)
        # --------------------------------------------------------
        if not self.policy.can_request(initiator_norm):
            return self._block(
                reason="initiator_not_allowed",
                ts=ts,
                execution_id=execution_id_norm,
                context_type=context_type_norm,
                directive=directive_norm,
                approval_id=approval_id_norm,
            )

        if not self.policy.is_action_allowed_for_role(initiator_norm, directive_norm):
            return self._block(
                reason="action_not_allowed",
                ts=ts,
                execution_id=execution_id_norm,
                context_type=context_type_norm,
                directive=directive_norm,
                approval_id=approval_id_norm,
            )

        # --------------------------------------------------------
        # READ-ONLY FAST PATH (NO APPROVAL)
        # --------------------------------------------------------
        if directive_norm in self._READ_ONLY_DIRECTIVES:
            return {
                "allowed": True,
                "execution_id": execution_id_norm,
                "approval_id": approval_id_norm,
                "context_type": context_type_norm,
                "directive": directive_norm,
                "read_only": True,
                "governance": self._governance_limits,
                "timestamp": ts,
                "policy": {"initiator": initiator_norm},
            }

        # --------------------------------------------------------
        # APPROVAL VERIFICATION (NO DUPLICATE CREATE)
        # --------------------------------------------------------
        if not approval_id_norm:
            # Kanonski: approval se kreira upstream (/api/execute ili drugi entrypoint).
            # Governance ovdje samo kaže da je approval potreban.
            return self._block(
                reason="approval_required",
                ts=ts,
                execution_id=execution_id_norm,
                context_type=context_type_norm,
                directive=directive_norm,
                approval_id=None,
            )

        if self.approvals.is_fully_approved(approval_id_norm) is not True:
            return self._block(
                reason="approval_not_granted",
                ts=ts,
                execution_id=execution_id_norm,
                context_type=context_type_norm,
                directive=directive_norm,
                approval_id=approval_id_norm,
            )

        # --------------------------------------------------------
        # ALLOWED
        # --------------------------------------------------------
        return {
            "allowed": True,
            "execution_id": execution_id_norm,
            "approval_id": approval_id_norm,
            "context_type": context_type_norm,
            "directive": directive_norm,
            "read_only": False,
            "governance": self._governance_limits,
            "timestamp": ts,
            "policy": {
                "initiator": initiator_norm,
            },
        }

    def _block(
        self,
        *,
        reason: str,
        ts: str,
        execution_id: str,
        context_type: str,
        directive: str,
        approval_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Determinističan response shape (uvijek isti ključevi)
        return {
            "allowed": False,
            "reason": reason,
            "execution_id": execution_id,
            "approval_id": approval_id,  # može biti None; namjerno
            "context_type": context_type,
            "directive": directive,
            "timestamp": ts,
            "governance": self._governance_limits,
        }

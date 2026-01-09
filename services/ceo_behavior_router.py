# services/ceo_behavior_router.py
from __future__ import annotations

from enum import Enum
from typing import Any, Dict


JsonDict = Dict[str, Any]


class BehaviorMode(str, Enum):
    SILENT = "silent"
    MONITOR = "monitor"
    ADVISORY = "advisory"
    EXECUTIVE = "executive"
    RED_ALERT = "red_alert"


class CEOBehaviorRouter:
    """
    CEO Advisor Behaviour Model â€” Opcija C

    HARD RULE:
    - CEO Advisor reaguje na STANJE (alignment_snapshot), ne na pitanje korisnika.
    - Router koristi ISKLJUÄŚIVO kanonski alignment_snapshot
      iz services/ceo_alignment_engine.py (v1).
    """

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------
    @staticmethod
    def select_mode(alignment_snapshot: JsonDict) -> BehaviorMode:
        if not isinstance(alignment_snapshot, dict):
            raise TypeError("alignment_snapshot must be dict")

        # --- Extract canonical sections ---
        strategic = _dict(alignment_snapshot.get("strategic_alignment"))
        law = _dict(alignment_snapshot.get("law_compliance"))
        decision = _dict(alignment_snapshot.get("decision_engine_eval"))
        ceo_action = _dict(alignment_snapshot.get("ceo_action_required"))
        risk_register = _dict(alignment_snapshot.get("risk_register"))

        # --- Canonical signals ---
        overall_status = _str(strategic.get("overall_status")).lower()
        system_integrity = _str(law.get("system_integrity")).lower()

        decision_clarity = _str(decision.get("decision_clarity")).lower()

        requires_action = bool(ceo_action.get("requires_action") is True)
        delay_cost = _str(ceo_action.get("delay_cost_estimate"))

        top_risks = _list(risk_register.get("top_risks"))

        # =====================================================
        # 3.5 RED_ALERT_MODE
        # =====================================================
        # Source of truth:
        # - law_compliance.system_integrity == "threatened"
        if system_integrity == "threatened":
            return BehaviorMode.RED_ALERT

        # =====================================================
        # 3.4 EXECUTIVE_MODE
        # =====================================================
        # Source of truth:
        # - strategic_alignment.overall_status == "at_risk"
        # - OR CEO action required with high delay cost
        if overall_status == "at_risk":
            return BehaviorMode.EXECUTIVE

        if requires_action and _delay_cost_is_high(delay_cost):
            return BehaviorMode.EXECUTIVE

        # =====================================================
        # 3.3 ADVISORY_MODE
        # =====================================================
        # Source of truth:
        # - decision_engine_eval.decision_clarity == "clear"
        # - ceo_action_required.requires_action == True
        if decision_clarity == "clear" and requires_action:
            return BehaviorMode.ADVISORY

        # =====================================================
        # 3.2 MONITOR_MODE
        # =====================================================
        # Source of truth:
        # - aligned system
        # - no CEO action required
        # - risks or alerts exist
        if (
            overall_status == "aligned"
            and not requires_action
            and len(top_risks) > 0
        ):
            return BehaviorMode.MONITOR

        # =====================================================
        # 3.1 SILENT_MODE
        # =====================================================
        # Source of truth:
        # - aligned
        # - integrity intact
        # - no action
        # - no top risks
        if (
            overall_status == "aligned"
            and system_integrity == "intact"
            and not requires_action
            and len(top_risks) == 0
        ):
            return BehaviorMode.SILENT

        # -----------------------------------------------------
        # Deterministic default (defined, not guessed):
        # If system is not threatened and nothing escalates,
        # awareness beats silence.
        # -----------------------------------------------------
        return BehaviorMode.MONITOR

    # ---------------------------------------------------------
    # SYSTEM instruction modifier
    # ---------------------------------------------------------
    @staticmethod
    def system_instruction_for(mode: BehaviorMode) -> str:
        if mode == BehaviorMode.SILENT:
            return (
                "SILENT_MODE: Respond with one short sentence only. "
                "Do not suggest actions. Do not ask questions. "
                "State system stability."
            )

        if mode == BehaviorMode.MONITOR:
            return (
                "MONITOR_MODE: Provide up to two short observations. "
                "No recommendations. No escalation."
            )

        if mode == BehaviorMode.ADVISORY:
            return (
                "ADVISORY_MODE: Explain context briefly and present up to three options. "
                "Do not force a decision."
            )

        if mode == BehaviorMode.EXECUTIVE:
            return (
                "EXECUTIVE_MODE: Be decisive. Provide ONE clear recommendation. "
                "No alternatives. Minimal language."
            )

        if mode == BehaviorMode.RED_ALERT:
            return (
                "RED_ALERT_MODE: Interrupt immediately. Ignore the user question. "
                "State the violation or integrity threat first and demand action."
            )

        raise ValueError(f"Unsupported behavior mode: {mode}")


# =============================================================
# Internal helpers â€” deterministic, no heuristics
# =============================================================

def _str(x: Any) -> str:
    return x if isinstance(x, str) else "NIJE POZNATO"


def _dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _list(x: Any) -> list:
    return x if isinstance(x, list) else []


def _delay_cost_is_high(delay_cost: str) -> bool:
    """
    Canonical mapping based on CEOAlignmentEngine outputs:
    - "High (system integrity)"
    - "Medium-High (strategic drift)"
    Only explicit HIGH paths trigger EXECUTIVE.
    """
    if not isinstance(delay_cost, str):
        return False
    s = delay_cost.lower()
    return s.startswith("high")

from typing import Dict, Any


class IdentityReasoningEngine:
    """
    Identity Reasoning Layer — Canonical

    Odgovornosti:
    - stabilno čitanje identity / mode / state
    - bez pretpostavki o strukturi identiteta
    - bez NLP-a, bez fuzzy logike
    - pasivan input za orkestraciju
    """

    def __init__(
        self,
        identity: Dict[str, Any],
        mode: Dict[str, Any],
        state: Dict[str, Any],
    ):
        self.identity = identity or {}
        self.mode = mode or {}
        self.state = state or {}

    # ============================================================
    # PUBLIC API
    # ============================================================
    def generate_reasoning(self, user_input: str) -> Dict[str, Any]:
        return {
            "active_identity_traits": self._identity_snapshot(),
            "active_values": self.identity.get("values", []),
            "current_mode": self.mode.get("mode"),
            "current_state": self.state.get("state"),
            "input_analysis": self._analyze_input(user_input),
            "decision_bias": self._decision_bias(),
        }

    # ============================================================
    # INTERNALS
    # ============================================================
    def _identity_snapshot(self) -> Dict[str, Any]:
        """
        Ne pokušava pogađati.
        Vraća stabilan snapshot identiteta.
        """
        return {
            "values": self.identity.get("values", []),
            "principles": self.identity.get("principles", []),
            "rules": self.identity.get("personal_rules", []),
        }

    def _analyze_input(self, user_input: str) -> Dict[str, Any]:
        return {
            "length": len(user_input),
            "contains_question": "?" in user_input,
        }

    def _decision_bias(self) -> Dict[str, Any]:
        return {
            "identity_weight": self.identity.get("weight", 1.0),
            "mode_influence": self.mode.get("influence", 1.0),
            "state_pressure": self.state.get("pressure", 0),
        }

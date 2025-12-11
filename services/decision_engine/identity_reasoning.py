from typing import Dict, Any


class IdentityReasoningEngine:
    """
    Identity Reasoning Layer
    -------------------------
    Ovo je prvi sloj koji se izvršava prije classification i orchestration.
    Vraća strukturisan reasoning baziran na Adnanovoj ličnosti, modu, state-u i pravilima.
    """

    def __init__(self, identity: Dict[str, Any], mode: Dict[str, Any], state: Dict[str, Any]):
        self.identity = identity or {}
        self.mode = mode or {}
        self.state = state or {}

    def generate_reasoning(self, user_input: str) -> Dict[str, Any]:
        """
        Glavna metoda:
        - Čita identity.json
        - Čita mode.json
        - Čita state.json
        - Kreira reasoning blok koji orchestration mora koristiti
        """

        return {
            "active_identity_traits": self._extract_identity_traits(user_input),
            "active_values": self.identity.get("values", []),
            "current_mode": self.mode.get("mode", None),
            "current_state": self.state.get("state", None),
            "input_analysis": self._analyze_input(user_input),
            "decision_bias": self._determine_decision_bias(),
        }

    def _extract_identity_traits(self, user_input: str) -> Dict[str, Any]:
        """
        Spoji relevantne dijelove identiteta bazirane na sadržaju pitanja.
        Ovo će kasnije biti prošireno fuzzy-em i NLP-om.
        """
        traits = self.identity.get("traits", {})
        relevant = {}

        for key, value in traits.items():
            if key.lower() in user_input.lower():
                relevant[key] = value

        return relevant

    def _analyze_input(self, user_input: str) -> Dict[str, Any]:
        """
        Minimalna analiza teksta — bez NLP-a.
        Kasnije će Context Classifier ovdje proširiti logiku.
        """
        return {
            "length": len(user_input),
            "contains_question": "?" in user_input,
            "keywords": user_input.lower().split(),
        }

    def _determine_decision_bias(self) -> Dict[str, Any]:
        """
        Kombinuje identity + mode + state u jasne smjernice.
        Ovo je najvažniji dio za orkestraciju.
        """
        return {
            "identity_weight": self.identity.get("weight", 1.0),
            "mode_influence": self.mode.get("influence", 1.0),
            "state_pressure": self.state.get("pressure", 0),
        }

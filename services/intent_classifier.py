# services/intent_classifier.py

import re
from typing import Optional
from services.intent_contract import Intent, IntentType


# ============================================================
# INTENT CLASSIFIER
# ============================================================

class IntentClassifier:
    """
    Deterministic intent classifier.
    Maps raw user text to IntentType.

    RULES:
    - No execution
    - No state changes
    - No ML / heuristics
    """

    def classify(self, text: Optional[str]) -> Intent:
        if not text:
            return Intent(type=IntentType.NONE, confidence=1.0)

        t = text.strip().lower()

        # ----------------------------------------------------
        # RESET
        # ----------------------------------------------------
        if self._match(t, r"\b(reset|kreni ispočetka|počni ponovo)\b"):
            return Intent(IntentType.RESET, 0.95)

        # ----------------------------------------------------
        # LIST SOPs (ROBUST)
        # ----------------------------------------------------
        if self._match(t, r"\b(sop|procedure|procedura)\b"):
            return Intent(IntentType.LIST_SOPS, 0.9)

        # ----------------------------------------------------
        # VIEW / SELECT SOP
        # ----------------------------------------------------
        if self._match(t, r"\b(onaj|ovaj|taj|drugi|treći|prvi)\b"):
            return Intent(IntentType.VIEW_SOP, 0.7)

        # ----------------------------------------------------
        # REQUEST EXECUTION (SOP)
        # ----------------------------------------------------
        if self._match(t, r"\b(pokreni|izvrši|uradi|startaj)\b"):
            return Intent(IntentType.REQUEST_EXECUTION, 0.9)

        # ----------------------------------------------------
        # WRITE — CREATE (FAZA F5.1)
        # ----------------------------------------------------
        if self._match(t, r"\b(kreiraj|napravi|dodaj|create|add)\b"):
            return Intent(IntentType.CREATE, 0.9)

        # ----------------------------------------------------
        # CONFIRM
        # ----------------------------------------------------
        if self._match(t, r"\b(da|može|ok|okej|ajde|potvrdi)\b"):
            return Intent(IntentType.CONFIRM, 0.95)

        # ----------------------------------------------------
        # CANCEL
        # ----------------------------------------------------
        if self._match(t, r"\b(ne|nemoj|odustani|prekini|stop)\b"):
            return Intent(IntentType.CANCEL, 0.95)

        # ----------------------------------------------------
        # CLARIFICATION
        # ----------------------------------------------------
        if self._match(t, r"\b(šta je|šta radi|objasni|pojasni)\b"):
            return Intent(IntentType.ASK_CLARIFICATION, 0.8)

        # ----------------------------------------------------
        # FALLBACK
        # ----------------------------------------------------
        return Intent(type=IntentType.NONE, confidence=0.4)

    # --------------------------------------------------------
    # INTERNAL
    # --------------------------------------------------------
    def _match(self, text: str, pattern: str) -> bool:
        return re.search(pattern, text) is not None

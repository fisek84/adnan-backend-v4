import re
from services.intent_contract import Intent, IntentType


class IntentClassifier:
    """
    Deterministic intent classifier.
    NO execution.
    NO side effects.
    """

    DEFAULT_CONFIDENCE_THRESHOLD = 0.75

    # ==================================================
    # REGEX RULES (ORDER MATTERS)
    # ==================================================

    SYSTEM_QUERY_PATTERNS = [
        r"\b(pregledaj|provjeri|prikaži|daj)\b.*\b(stanje sistema|sistem)\b",
        r"\b(stanje sistema)\b",
        r"\b(status sistema)\b",
        r"\b(system status|system state)\b",
    ]

    GOALS_LIST_PATTERNS = [
        r"\b(listaj|prikaži|daj)\b.*\b(ciljeve|goals)\b",
        r"\b(goals list|list goals)\b",
    ]

    GOAL_CREATE_PATTERNS = [
        r"\b(create|add|new)\b.*\b(goal)\b",
        r"\bkreiraj\b.*\b(cilj)\b",
        r"\bnapravi\b.*\b(cilj)\b",
        r"\bnovi\b.*\b(cilj)\b",
        r"\b(business goal)\b",
    ]

    SOP_LIST_PATTERNS = [
        r"\b(listaj|prikaži|daj)\b.*\b(sop|sopove|procedure|procedures)\b",
        r"\b(list sops|list sop)\b",
    ]

    SOP_VIEW_PATTERNS = [
        r"\b(prikaži|otvori|pogledaj)\b.*\b(sop)\b",
        r"\b(view sop)\b",
    ]

    IDENTITY_PATTERNS = [
        r"\bko si\b",
        r"\bko si ti\b",
        r"\bšta si\b",
        r"\bsta si\b",
        r"\bšta radiš\b",
        r"\bsta radis\b",
    ]

    CONFIRM_PATTERNS = [
        r"^da$",
        r"^može$",
        r"^moze$",
        r"^ok$",
        r"^yes$",
        r"^confirm$",
        r"^approve$",
    ]

    CANCEL_PATTERNS = [
        r"^ne$",
        r"^odustani$",
        r"^cancel$",
        r"^no$",
        r"^reject$",
        r"^stop$",
    ]

    # ==================================================
    # MAIN CLASSIFIER
    # ==================================================

    def classify(self, text: str, *, source: str) -> Intent:
        lowered = (text or "").lower().strip()

        # --------------------------------------------------
        # CONFIRM
        # --------------------------------------------------
        for pattern in self.CONFIRM_PATTERNS:
            if re.fullmatch(pattern, lowered):
                return Intent(
                    type=IntentType.CONFIRM,
                    confidence=0.99,
                    payload={},
                    source=source,
                )

        # --------------------------------------------------
        # CANCEL
        # --------------------------------------------------
        for pattern in self.CANCEL_PATTERNS:
            if re.fullmatch(pattern, lowered):
                return Intent(
                    type=IntentType.CANCEL,
                    confidence=0.99,
                    payload={},
                    source=source,
                )

        # --------------------------------------------------
        # SYSTEM QUERY (READ-ONLY)
        # --------------------------------------------------
        for pattern in self.SYSTEM_QUERY_PATTERNS:
            if re.search(pattern, lowered):
                return Intent(
                    type=IntentType.SYSTEM_QUERY,
                    confidence=0.95,
                    payload={},
                    source=source,
                )

        # --------------------------------------------------
        # GOALS LIST (READ)
        # --------------------------------------------------
        for pattern in self.GOALS_LIST_PATTERNS:
            if re.search(pattern, lowered):
                return Intent(
                    type=IntentType.GOALS_LIST,
                    confidence=0.92,
                    payload={},
                    source=source,
                )

        # --------------------------------------------------
        # SOP LIST (READ)
        # --------------------------------------------------
        for pattern in self.SOP_LIST_PATTERNS:
            if re.search(pattern, lowered):
                return Intent(
                    type=IntentType.LIST_SOPS,
                    confidence=0.92,
                    payload={},
                    source=source,
                )

        # --------------------------------------------------
        # SOP VIEW (READ)
        # --------------------------------------------------
        for pattern in self.SOP_VIEW_PATTERNS:
            if re.search(pattern, lowered):
                return Intent(
                    type=IntentType.VIEW_SOP,
                    confidence=0.93,
                    payload={},
                    source=source,
                )

        # --------------------------------------------------
        # GOAL CREATE (WRITE / APPROVAL REQUIRED)
        # --------------------------------------------------
        for pattern in self.GOAL_CREATE_PATTERNS:
            if re.search(pattern, lowered):
                return Intent(
                    type=IntentType.GOAL_CREATE,
                    confidence=0.90,
                    payload={},
                    source=source,
                )

        # --------------------------------------------------
        # IDENTITY / CHAT
        # --------------------------------------------------
        for pattern in self.IDENTITY_PATTERNS:
            if re.search(pattern, lowered):
                return Intent(
                    type=IntentType.CHAT,
                    confidence=0.9,
                    payload={},
                    source=source,
                )

        # --------------------------------------------------
        # FALLBACK
        # --------------------------------------------------
        return Intent(
            type=IntentType.CHAT,
            confidence=0.4,
            payload={},
            source=source,
        )

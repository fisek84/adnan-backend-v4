import re
from typing import Optional
from services.intent_contract import Intent, IntentType


class IntentClassifier:
    """
    Deterministic intent classifier.

    RULES:
    - Text parsing ONLY here
    - Order MATTERS
    - No CSI access
    - NEVER throws
    """

    def classify(self, text: Optional[str]) -> Intent:
        try:
            if not text or not text.strip():
                return self._fallback()

            t = text.strip().lower()

            # ----------------------------------------------------
            # NUMERIC INPUT — SOP SELECTION
            # ----------------------------------------------------
            if t.isdigit():
                return Intent(
                    type=IntentType.VIEW_SOP,
                    confidence=1.0,
                    payload={"index": int(t) - 1},
                )

            # ----------------------------------------------------
            # RESET
            # ----------------------------------------------------
            if self._match(t, r"\b(reset|kreni ispočetka|počni ponovo)\b"):
                return Intent(IntentType.RESET, 0.95)

            # ----------------------------------------------------
            # REQUEST EXECUTION (SAMO EKSPLICITNO)
            # ----------------------------------------------------
            if self._match(t, r"\b(pokreni|izvrši|izvrsi|startaj)\b"):
                return Intent(IntentType.REQUEST_EXECUTION, 0.95)

            # ----------------------------------------------------
            # TASK GENERATION FROM PLAN — FAZA 4
            # ----------------------------------------------------
            if self._match(
                t,
                r"\b(razloži plan|razlozi plan|napravi taskove iz plana|generiši taskove|taskovi iz plana)\b",
            ):
                return Intent(IntentType.TASK_GENERATE_FROM_PLAN, 0.95)

            # ----------------------------------------------------
            # PLAN CREATE — FAZA 4
            # ----------------------------------------------------
            if self._match(t, r"\b(plan|planiraj|napravi plan|razradi plan)\b"):
                return Intent(
                    type=IntentType.PLAN_CREATE,
                    confidence=0.9,
                    payload={"text": text},
                )

            # ----------------------------------------------------
            # TASK CREATE — FAZA 3
            # ----------------------------------------------------
            if self._match(t, r"\b(moram|treba da|uraditi|zadatak|task|to do)\b"):
                return Intent(
                    type=IntentType.TASK_CREATE,
                    confidence=0.9,
                    payload={"text": text},
                )

            # ----------------------------------------------------
            # GOAL CREATE — FAZA 3
            # ----------------------------------------------------
            if self._match(t, r"\b(želim|zelim|cilj|goal|postati|da budem|da postanem)\b"):
                return Intent(
                    type=IntentType.GOAL_CREATE,
                    confidence=0.9,
                    payload={"text": text},
                )

            # ----------------------------------------------------
            # PLAN CONFIRM / CANCEL
            # ----------------------------------------------------
            if self._match(t, r"\b(da|može|moze|ok|okej|potvrdi)\b") and self._match(t, r"\b(plan)\b"):
                return Intent(IntentType.PLAN_CONFIRM, 0.95)

            if self._match(t, r"\b(ne|nemoj|odustani|prekini|stop)\b") and self._match(t, r"\b(plan)\b"):
                return Intent(IntentType.PLAN_CANCEL, 0.95)

            # ----------------------------------------------------
            # GOAL CONFIRM / CANCEL
            # ----------------------------------------------------
            if self._match(t, r"\b(da|može|moze|ok|okej|potvrdi)\b") and self._match(t, r"\b(goal|cilj)\b"):
                return Intent(IntentType.GOAL_CONFIRM, 0.95)

            if self._match(t, r"\b(ne|nemoj|odustani|prekini|stop)\b") and self._match(t, r"\b(goal|cilj)\b"):
                return Intent(IntentType.GOAL_CANCEL, 0.95)

            # ----------------------------------------------------
            # TASK CONFIRM / CANCEL
            # ----------------------------------------------------
            if self._match(t, r"\b(da|može|moze|ok|okej|potvrdi)\b") and self._match(t, r"\b(task|zadatak)\b"):
                return Intent(IntentType.TASK_CONFIRM, 0.95)

            if self._match(t, r"\b(ne|nemoj|odustani|prekini|stop)\b") and self._match(t, r"\b(task|zadatak)\b"):
                return Intent(IntentType.TASK_CANCEL, 0.95)

            # ----------------------------------------------------
            # LIST SOPs
            # ----------------------------------------------------
            if self._match(t, r"\b(sop|procedure|procedura)\b"):
                return Intent(IntentType.LIST_SOPS, 0.9)

            # ----------------------------------------------------
            # CREATE (GENERIC)
            # ----------------------------------------------------
            if self._match(t, r"\b(kreiraj|napravi|dodaj|create|add)\b"):
                return Intent(IntentType.CREATE, 0.9)

            # ----------------------------------------------------
            # FALLBACK — KANONSKI
            # ----------------------------------------------------
            return self._fallback()

        except Exception:
            # ❗ KANON: classifier NIKAD ne smije rušiti sistem
            return self._fallback()

    def _fallback(self) -> Intent:
        # Ne prepoznato = CHAT (nikad NONE)
        return Intent(type=IntentType.CHAT, confidence=1.0)

    def _match(self, text: str, pattern: str) -> bool:
        return re.search(pattern, text) is not None

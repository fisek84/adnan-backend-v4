# services/intent_classifier.py

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

    DEFAULT_CONFIDENCE_THRESHOLD = 0.85

    def classify(self, text: Optional[str], *, source: str = "user") -> Intent:
        try:
            if not text or not text.strip():
                return self._chat(text, source)

            t = text.strip().lower()

            # ---------------------------------
            # RESET
            # ---------------------------------
            if re.search(r"\b(reset|kreni ispočetka|počni ponovo)\b", t):
                return Intent(IntentType.RESET, 1.0, {"raw_text": text}, source)

            # ---------------------------------
            # SYSTEM QUERY / ANALYZE (READ-ONLY)
            # ---------------------------------
            if re.search(
                r"\b("
                r"pregledaj.*stanje.*sistema|"
                r"pregled sistema|"
                r"stanje sistema|"
                r"analiziraj.*sistem|"
                r"analiza sistema|"
                r"system status|"
                r"system analyze|"
                r"system analysis"
                r")\b",
                t
            ):
                return Intent(
                    IntentType.SYSTEM_QUERY,
                    0.95,
                    {"raw_text": text},
                    source,
                )

            # ---------------------------------
            # TASK EXECUTION — FAZA 5 (RANO)
            # ---------------------------------
            if re.search(r"\b(pokreni zadatak|start task|započni zadatak)\b", t):
                return Intent(IntentType.TASK_START, 1.0, {"raw_text": text}, source)

            if re.search(r"\b(zadatak je gotov|završio sam zadatak|task done)\b", t):
                return Intent(IntentType.TASK_COMPLETE, 1.0, {"raw_text": text}, source)

            if re.search(r"\b(zadatak nije uspio|task failed|neuspješan zadatak)\b", t):
                return Intent(IntentType.TASK_FAIL, 1.0, {"raw_text": text}, source)

            # ---------------------------------
            # GOAL CONFIRM / CANCEL
            # ---------------------------------
            if re.search(r"\b(potvrdi cilj|potvrđujem cilj|da cilj)\b", t):
                return Intent(IntentType.GOAL_CONFIRM, 1.0, {"raw_text": text}, source)

            if re.search(r"\b(odustani od cilja|otkaži cilj|cancel goal)\b", t):
                return Intent(IntentType.GOAL_CANCEL, 1.0, {"raw_text": text}, source)

            # ---------------------------------
            # PLAN CONFIRM / CANCEL
            # ---------------------------------
            if re.search(r"\b(potvrdi plan|da plan)\b", t):
                return Intent(IntentType.PLAN_CONFIRM, 1.0, {"raw_text": text}, source)

            if re.search(r"\b(otkaži plan|odustani od plana)\b", t):
                return Intent(IntentType.PLAN_CANCEL, 1.0, {"raw_text": text}, source)

            # ---------------------------------
            # TASK CONFIRM / CANCEL
            # ---------------------------------
            if re.search(r"\b(potvrdi zadatak|da zadatak)\b", t):
                return Intent(IntentType.TASK_CONFIRM, 1.0, {"raw_text": text}, source)

            if re.search(r"\b(otkaži zadatak|odustani od zadatka)\b", t):
                return Intent(IntentType.TASK_CANCEL, 1.0, {"raw_text": text}, source)

            # ---------------------------------
            # GENERIC CONFIRM / CANCEL
            # ---------------------------------
            if re.fullmatch(r"(da|može|moze|ok|okej|yes)", t):
                return Intent(IntentType.CONFIRM, 1.0, {"raw_text": text}, source)

            if re.fullmatch(r"(ne|nemoj|odustani|prekini|stop|no)", t):
                return Intent(IntentType.CANCEL, 1.0, {"raw_text": text}, source)

            # ---------------------------------
            # TASKS FROM PLAN
            # ---------------------------------
            if re.search(r"\b(generiši taskove|taskovi iz plana|razloži plan)\b", t):
                return Intent(IntentType.TASK_GENERATE_FROM_PLAN, 0.9, {"raw_text": text}, source)

            # ---------------------------------
            # GOALS LIST / QUERY (READ-ONLY)
            # ---------------------------------
            if re.search(
                r"\b(daj|prikaži|pokazi|listaj|show)\b.*\b(cilj|ciljevi|ciljeva|ciljevima)\b",
                t
            ):
                return Intent(IntentType.GOALS_LIST, 1.0, {"raw_text": text}, source)

            # ---------------------------------
            # PLAN CREATE
            # ---------------------------------
            if re.search(r"\b(napravi plan|razradi plan|planiraj)\b", t):
                return Intent(IntentType.PLAN_CREATE, 0.9, {"raw_text": text}, source)

            # ---------------------------------
            # GOAL CREATE
            # ---------------------------------
            if re.search(r"\b(želim|zelim|cilj|goal|postati)\b", t):
                return Intent(IntentType.GOAL_CREATE, 0.9, {"raw_text": text}, source)

            # ---------------------------------
            # TASK CREATE
            # ---------------------------------
            if re.search(r"\b(task|zadatak|uraditi|to do)\b", t):
                return Intent(IntentType.TASK_CREATE, 0.9, {"raw_text": text}, source)

            return self._chat(text, source)

        except Exception:
            return self._chat(text, source)

    # --------------------------------------------------
    # INTERNAL
    # --------------------------------------------------
    def _chat(self, text: Optional[str], source: str) -> Intent:
        return Intent(IntentType.CHAT, 1.0, {"raw_text": text}, source)

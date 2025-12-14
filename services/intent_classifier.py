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
                return Intent(IntentType.CHAT, 1.0)

            t = text.strip().lower()

            # ---------------------------------
            # RESET (HIGHEST PRIORITY)
            # ---------------------------------
            if re.search(r"\b(reset|kreni ispočetka|počni ponovo|pocni ponovo)\b", t):
                return Intent(IntentType.RESET, 1.0)

            # ---------------------------------
            # GOAL CONFIRM — FAZA 3 (FINAL FIX)
            # ---------------------------------
            if re.search(r"\b(potvrdi cilj|potvrđujem cilj|confirm goal)\b", t):
                return Intent(IntentType.GOAL_CONFIRM, 0.95)

            # ---------------------------------
            # GOAL CANCEL — FAZA 3
            # ---------------------------------
            if re.search(r"\b(otkaži cilj|otkazi cilj|cancel goal)\b", t):
                return Intent(IntentType.GOAL_CANCEL, 0.95)

            # ---------------------------------
            # CONFIRM / CANCEL (GENERIC)
            # ---------------------------------
            if re.fullmatch(r"(da|može|moze|ok|okej|yes)", t):
                return Intent(IntentType.CONFIRM, 1.0)

            if re.fullmatch(r"(ne|nemoj|odustani|prekini|stop|no)", t):
                return Intent(IntentType.CANCEL, 1.0)

            # ---------------------------------
            # EXECUTION
            # ---------------------------------
            if re.search(r"\b(pokreni|izvrši|izvrsi|startaj)\b", t):
                return Intent(IntentType.REQUEST_EXECUTION, 0.95)

            # ---------------------------------
            # TASKS FROM PLAN
            # ---------------------------------
            if re.search(r"\b(generiši taskove|generisi taskove|taskovi iz plana|razloži plan|razlozi plan)\b", t):
                return Intent(IntentType.TASK_GENERATE_FROM_PLAN, 0.9)

            # ---------------------------------
            # PLAN CREATE
            # ---------------------------------
            if re.search(r"\b(napravi plan|razradi plan|planiraj|plan)\b", t):
                return Intent(IntentType.PLAN_CREATE, 0.9, payload={"text": text})

            # ---------------------------------
            # GOAL CREATE
            # ---------------------------------
            if re.search(r"\b(želim|zelim|cilj|goal|postati)\b", t):
                return Intent(IntentType.GOAL_CREATE, 0.9, payload={"text": text})

            # ---------------------------------
            # TASK CREATE
            # ---------------------------------
            if re.search(r"\b(task|zadatak|uraditi|to do)\b", t):
                return Intent(IntentType.TASK_CREATE, 0.9, payload={"text": text})

            # ---------------------------------
            # FALLBACK CHAT
            # ---------------------------------
            return Intent(IntentType.CHAT, 1.0)

        except Exception:
            return Intent(IntentType.CHAT, 1.0)

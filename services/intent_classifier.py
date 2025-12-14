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
            # RESET
            # ---------------------------------
            if re.search(r"\b(reset|kreni ispočetka|počni ponovo)\b", t):
                return Intent(IntentType.RESET, 1.0)

            # ---------------------------------
            # TASK EXECUTION — FAZA 5 (MORA BITI RANO)
            # ---------------------------------
            if re.search(r"\b(pokreni zadatak|start task|započni zadatak)\b", t):
                return Intent(IntentType.TASK_START, 1.0)

            if re.search(r"\b(zadatak je gotov|završio sam zadatak|task done)\b", t):
                return Intent(IntentType.TASK_COMPLETE, 1.0)

            if re.search(r"\b(zadatak nije uspio|task failed|neuspješan zadatak)\b", t):
                return Intent(IntentType.TASK_FAIL, 1.0)

            # ---------------------------------
            # GOAL CONFIRM / CANCEL
            # ---------------------------------
            if re.search(r"\b(potvrdi cilj|potvrđujem cilj|da cilj)\b", t):
                return Intent(IntentType.GOAL_CONFIRM, 1.0)

            if re.search(r"\b(odustani od cilja|otkaži cilj|cancel goal)\b", t):
                return Intent(IntentType.GOAL_CANCEL, 1.0)

            # ---------------------------------
            # PLAN CONFIRM / CANCEL
            # ---------------------------------
            if re.search(r"\b(potvrdi plan|da plan)\b", t):
                return Intent(IntentType.PLAN_CONFIRM, 1.0)

            if re.search(r"\b(otkaži plan|odustani od plana)\b", t):
                return Intent(IntentType.PLAN_CANCEL, 1.0)

            # ---------------------------------
            # TASK CONFIRM / CANCEL
            # ---------------------------------
            if re.search(r"\b(potvrdi zadatak|da zadatak)\b", t):
                return Intent(IntentType.TASK_CONFIRM, 1.0)

            if re.search(r"\b(otkaži zadatak|odustani od zadatka)\b", t):
                return Intent(IntentType.TASK_CANCEL, 1.0)

            # ---------------------------------
            # GENERIC CONFIRM / CANCEL
            # ---------------------------------
            if re.fullmatch(r"(da|može|moze|ok|okej|yes)", t):
                return Intent(IntentType.CONFIRM, 1.0)

            if re.fullmatch(r"(ne|nemoj|odustani|prekini|stop|no)", t):
                return Intent(IntentType.CANCEL, 1.0)

            # ---------------------------------
            # TASKS FROM PLAN
            # ---------------------------------
            if re.search(r"\b(generiši taskove|taskovi iz plana|razloži plan)\b", t):
                return Intent(IntentType.TASK_GENERATE_FROM_PLAN, 0.9)

            # ---------------------------------
            # PLAN CREATE
            # ---------------------------------
            if re.search(r"\b(napravi plan|razradi plan|planiraj)\b", t):
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

            return Intent(IntentType.CHAT, 1.0)

        except Exception:
            return Intent(IntentType.CHAT, 1.0)

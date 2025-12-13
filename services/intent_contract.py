# services/intent_contract.py

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any


# ============================================================
# INTENT ENUM (KANONSKI SET)
# ============================================================

class IntentType(Enum):
    NONE = "none"                            # small talk / irrelevant
    LIST_SOPS = "list_sops"                  # "pokaži sop-ove"
    VIEW_SOP = "view_sop"                    # "onaj drugi"
    REQUEST_EXECUTION = "request_execution"  # "pokreni ovo"
    CREATE = "create"                        # "kreiraj", "napravi", "dodaj"
    CONFIRM = "confirm"                      # "može", "ok", "da"
    CANCEL = "cancel"                        # "ne", "odustani"
    ASK_CLARIFICATION = "ask_clarification"  # "šta je ovo?"
    RESET = "reset"                          # "kreni ispočetka"


# ============================================================
# INTENT PAYLOAD
# ============================================================

@dataclass
class Intent:
    """
    Intent is a SIGNAL, not a decision.
    """

    type: IntentType
    confidence: float                      # 0.0 – 1.0
    payload: Optional[Dict[str, Any]] = None

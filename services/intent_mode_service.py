import re
from typing import Dict, Any

WRITE_MARKERS = [
    "postavi", "dodaj", "kreiraj", "napravi", "azuriraj", "ažuriraj", "promijeni", "obriši", "obrisi",
    "set", "add", "create", "update", "change", "delete", "remove"
]

QUESTION_MARKERS = ["?", "sta", "što", "kako", "zasto", "zašto", "objasni", "explain", "why", "how", "what"]

def decide_read_write(message: str) -> Dict[str, Any]:
    msg = (message or "").strip()
    low = msg.lower()

    # 1) pitanje → read
    if any(q in low for q in QUESTION_MARKERS) or "?" in msg:
        return {"read_only": True, "reason": "question_like"}

    # 2) imperativ / write marker → write
    if any(w in low for w in WRITE_MARKERS):
        return {"read_only": False, "require_approval": True, "reason": "imperative_like"}

    # 3) default safe
    return {"read_only": True, "reason": "default_safe"}

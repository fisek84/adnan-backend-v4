import re
from typing import List, Dict, Any, Optional


class SOPMapper:
    """
    SOP Mapper — FAZA 4–6 (STABLE)

    Pravila:
    - resolve_sop vraća LOGIČKI SOP KEY
    - build_execution_plan je DEPRECATED (ne koristi se)
    - nema izvršenja
    """

    def __init__(self):
        self.sop_map = {
            "customer_onboarding_sop": [
                r"onboarding",
                r"onboard",
                r"uvođenje",
                r"novog klijenta",
            ],
            "qualification_sop": [r"kvalifik", r"qualification", r"qualify"],
            "outreach_sop": [r"outreach", r"prvi kontakt"],
            "follow_up_sop": [r"follow", r"follow[- ]?up", r"prati dalje"],
        }

        # FAZA 5/6 — canonical aliasing (NON-BREAKING)
        self.sop_aliases = {
            "customer onboarding sop": "customer_onboarding_sop",
            "customer_onboarding_sop": "customer_onboarding_sop",
        }

    # ------------------------------------------------------------
    # RESOLVE SOP (KANONSKI)
    # ------------------------------------------------------------
    def resolve_sop(self, text: str) -> Optional[str]:
        for sop_name, patterns in self.sop_map.items():
            for p in patterns:
                if re.search(p, text, re.IGNORECASE):
                    return self._normalize_sop_key(sop_name)
        return None

    def _normalize_sop_key(self, sop_name: str) -> str:
        """
        Garantuje stabilan SOP key kroz sistem.
        """
        return self.sop_aliases.get(sop_name, sop_name)

    # ------------------------------------------------------------
    # BUILD EXECUTION PLAN (DEPRECATED — NE KORISTITI)
    # ------------------------------------------------------------
    def build_execution_plan(self, sop_name: str) -> List[Dict[str, Any]]:
        """
        DEPRECATED.
        Ostavljen isključivo radi backward compatibility.
        Ne koristi se u runtime flow-u.
        """
        return []

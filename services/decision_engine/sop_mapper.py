import re

class SOPMapper:

    def __init__(self):
        # ključne riječi za svaku SOP bazu
        self.sop_map = {
            "qualification sop": [
                r"kvalifik", r"qualification", r"qualify", r"qlf", r"qual proc"
            ],
            "outreach sop": [
                r"outreach", r"pristup", r"prvi kontakt"
            ],
            "follow up sop": [
                r"follow", r"followup", r"prati dalje", r"follow-up"
            ],
            "fsc sop": [
                r"fsc", r"sales cycle", r"funnel step", r"prodajni ciklus"
            ],
            "flp ops sop": [
                r"flp ops", r"ops flp", r"lead pipeline ops"
            ],
            "lss sop": [
                r"lss", r"lead scoring", r"scoring system"
            ],
            "partner activation sop": [
                r"partner activation", r"aktivacija partnera", r"activate partner"
            ],
            "partner performance sop": [
                r"partner performance", r"performanse partnera"
            ],
            "partner leadership sop": [
                r"partner leadership", r"vodjenje partnera"
            ],
            "customer onboarding sop": [
                r"onboard", r"onboarding", r"uvod klijenta", r"klijentsko onboard"
            ],
            "customer retention sop": [
                r"retention", r"zadržavanje klijenata", r"retencija"
            ],
            "customer performance sop": [
                r"customer performance", r"performanse klijenta"
            ],
            "partner potential sop": [
                r"potential partner", r"potencijal partnera"
            ],
            "sales closing sop": [
                r"closing", r"zatvaranje prodaje", r"sales close"
            ]
        }

    ###################################################################
    # MAIN SOP RESOLUTION
    ###################################################################
    def resolve_sop(self, text: str) -> str | None:
        """
        Detektuje SOP iz CEO teksta i vraća canonical SOP naziv.
        """
        for sop_name, patterns in self.sop_map.items():
            for p in patterns:
                if re.search(p, text, re.IGNORECASE):
                    return sop_name
        return None

import re
from difflib import SequenceMatcher


class NaturalLanguageExpansionEngine:
    """
    A3 – Natural Language Command Expansion
    Proširuje kratke CEO instrukcije u kompleksnije strukture.
    """

    def __init__(self):
        pass

    def _similarity(self, a, b):
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def _extract_keywords(self, text):
        return re.findall(r"[A-Za-z0-9]+", text.lower())

    def expand(self, instruction: str):
        """
        Ulaz: kratka CEO rečenica
        Izlaz: proširena struktura (taskovi, subtasks, preporuke)
        """

        if not instruction or len(instruction.strip()) == 0:
            return {"expanded": [], "metadata": {}}

        text = instruction.lower()
        expanded = []
        meta = {}

        # --------------------------------------------------
        # Onboarding scenario
        # --------------------------------------------------
        if "onboard" in text or "onboarding" in text:
            expanded.append({
                "type": "task",
                "title": "Prepare onboarding checklist",
                "description": "Create all required onboarding steps."
            })
            expanded.append({
                "type": "task",
                "title": "Schedule onboarding meeting",
                "description": "Coordinate with HR and team lead."
            })
            meta["category"] = "onboarding"

        # --------------------------------------------------
        # Hiring scenario
        # --------------------------------------------------
        if "hire" in text or "recruit" in text:
            expanded.append({
                "type": "task",
                "title": "Initiate hiring pipeline",
                "description": "Create job description and publish role."
            })
            meta["category"] = "hiring"

        # --------------------------------------------------
        # Sales / outreach scenario
        # --------------------------------------------------
        if "lead" in text or "outreach" in text or "contact" in text:
            expanded.append({
                "type": "task",
                "title": "Prepare outreach sequence",
                "description": "Draft email templates and plan outreach schedule."
            })
            meta["category"] = "outreach"

        # --------------------------------------------------
        # Finance / reporting scenario
        # --------------------------------------------------
        if "report" in text or "kpi" in text or "metrics" in text:
            expanded.append({
                "type": "task",
                "title": "Prepare KPI report",
                "description": "Collect company metrics and format report."
            })
            meta["category"] = "reporting"

        # --------------------------------------------------
        # If nothing matched → return defaults
        # --------------------------------------------------
        if len(expanded) == 0:
            expanded.append({
                "type": "task",
                "title": instruction.strip(),
                "description": ""
            })

        return {
            "expanded": expanded,
            "metadata": meta
        }

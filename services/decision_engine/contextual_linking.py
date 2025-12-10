# services/decision_engine/contextual_linking.py

import re
from difflib import SequenceMatcher

class ContextualLinkingEngine:
    def __init__(self, database_map):
        self.database_map = database_map
        self.goals = database_map.get("goals", [])
        self.projects = database_map.get("projects", [])

    def _similarity(self, a, b):
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def _extract_keywords(self, text):
        tokens = re.findall(r"[A-Za-z0-9]+", text.lower())
        return list(set(tokens))

    def find_related_entities(self, task_text):
        keywords = self._extract_keywords(task_text)
        related = {
            "goals": [],
            "projects": []
        }

        for kw in keywords:
            for goal in self.goals:
                if self._similarity(kw, goal["name"]) > 0.75:
                    related["goals"].append(goal["id"])

            for proj in self.projects:
                if self._similarity(kw, proj["name"]) > 0.75:
                    related["projects"].append(proj["id"])

        return related

    def apply(self, task_payload):
        task_text = task_payload.get("task_text", "")
        return self.find_related_entities(task_text)

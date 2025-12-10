# services/decision_engine/cross_database_reasoning.py

import re
from difflib import SequenceMatcher

class CrossDatabaseReasoningEngine:
    def __init__(self, database_map):
        self.database_map = database_map
        self.goals = database_map.get("goals", [])
        self.projects = database_map.get("projects", [])

    def _similarity(self, a, b):
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def _extract_keywords(self, text):
        tokens = re.findall(r"[A-Za-z0-9]+", text.lower())
        return list(set(tokens))

    def infer_goal_relationship(self, task_text):
        keywords = self._extract_keywords(task_text)
        detected_goals = []

        for kw in keywords:
            for goal in self.goals:
                if self._similarity(kw, goal["name"]) > 0.8:
                    detected_goals.append(goal["id"])

        return detected_goals

    def infer_project_context(self, task_text):
        keywords = self._extract_keywords(task_text)
        detected_projects = []

        for kw in keywords:
            for proj in self.projects:
                if self._similarity(kw, proj["name"]) > 0.8:
                    detected_projects.append(proj["id"])

        return detected_projects

    def apply(self, task_payload):
        text = task_payload.get("task_text", "")

        related_goals = self.infer_goal_relationship(text)
        related_projects = self.infer_project_context(text)

        return {
            "cross_related_goals": related_goals,
            "cross_related_projects": related_projects
        }

import difflib

class StaticMemoryEngine:

    def __init__(self, memory: dict):
        self.memory = memory
        self.rules = memory.get("rules", [])

    def apply(self, text: str) -> dict:
        return self.evaluate(text)

    def _fuzzy_match(self, text: str, keyword: str) -> bool:
        """
        Fuzzy logic:
        1. Direct substring match (fast path)
        2. Token-based partial match (handles ‘ključni Q1 cilj’)
        3. Similarity ratio >= 0.75 (Levenshtein / difflib)
        """

        t = text.lower()
        kw = keyword.lower()

        # 1. Direct substring match
        if kw in t:
            return True

        # 2. Token-based match (e.g. "ključni cilj" -> "ključni Q1 cilj")
        kw_tokens = kw.split()
        if all(token in t for token in kw_tokens):
            return True

        # 3. Fuzzy ratio match (difflib)
        ratio = difflib.SequenceMatcher(None, kw, t).ratio()
        if ratio >= 0.75:
            return True

        return False

    def evaluate(self, text: str) -> dict:
        text_lower = text.lower()

        triggered = []
        total_impact = {
            "alignment_bonus": 0,
            "trust_bonus": 0,
            "priority_bonus": 0
        }

        for rule in self.rules:
            rule_id = rule.get("id")
            keywords = rule.get("keywords", [])
            impact = rule.get("impact", {})

            for kw in keywords:
                if self._fuzzy_match(text_lower, kw):

                    triggered.append(rule_id)

                    total_impact["alignment_bonus"] += impact.get("alignment_bonus", 0)
                    total_impact["trust_bonus"] += impact.get("trust_bonus", 0)
                    total_impact["priority_bonus"] += impact.get("priority_bonus", 0)

                    break  # one rule triggered once

        return {
            "rules_triggered": triggered,
            "impact": total_impact
        }

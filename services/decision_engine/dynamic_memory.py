# dynamic_memory_engine.py

import unicodedata


class DynamicMemoryEngine:
    def __init__(self, session_memory: dict):
        """
        session_memory dolazi iz AdnanAIDecisionService.
        Ovdje punimo local cache iz persistentnog memory-ja.
        """
        self.memory = session_memory.get("dynamic_memory", {})
        self.memory.setdefault("tasks", [])

    # ---------------------------------------------
    # Normalizacija teksta
    # ---------------------------------------------
    def normalize(self, text: str) -> str:
        if not text:
            return ""
        t = text.lower().strip()

        # uklanjanje dijakritike
        t = unicodedata.normalize("NFD", t)
        t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")

        return t

    # ---------------------------------------------
    # Fuzzy similarity (Levenshtein ratio)
    # ---------------------------------------------
    def levenshtein_ratio(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0

        a = self.normalize(a)
        b = self.normalize(b)

        len_a = len(a)
        len_b = len(b)

        dp = [[0] * (len_b + 1) for _ in range(len_a + 1)]

        for i in range(len_a + 1):
            dp[i][0] = i
        for j in range(len_b + 1):
            dp[0][j] = j

        for i in range(1, len_a + 1):
            for j in range(1, len_b + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                dp[i][j] = min(
                    dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost
                )

        dist = dp[len_a][len_b]
        max_len = max(len_a, len_b)
        return 1 - (dist / max_len)

    # ---------------------------------------------
    # Fuzzy duplicate check
    # ---------------------------------------------
    def check_duplicates(self, title: str):
        normalized_new = self.normalize(title)

        duplicates = []
        for t in self.memory["tasks"]:
            ratio = self.levenshtein_ratio(normalized_new, self.normalize(t))
            if ratio >= 0.75:  # fuzzy match threshold
                duplicates.append({"task": t, "similarity": ratio})

        return duplicates

    # ---------------------------------------------
    # Evaluate D1
    # ---------------------------------------------
    def evaluate(self, text: str, command: dict) -> dict:
        title = command["payload"]["entry"]["Name"]

        duplicates = self.check_duplicates(title)

        return {"duplicates_found": duplicates, "duplicate_exists": len(duplicates) > 0}

    # ---------------------------------------------
    # Dodavanje novog taska u memoriju (persistencija)
    # ---------------------------------------------
    def add_task(self, title: str):
        if title and title not in self.memory["tasks"]:
            self.memory["tasks"].append(title)

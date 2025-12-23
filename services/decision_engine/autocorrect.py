class AutocorrectEngine:
    def __init__(self):
        # canonical mapping of all valid database names
        self.known_databases = {
            "tasks": "tasks",
            "task": "tasks",
            "goals": "goals",
            "goal": "goals",
            "projects": "projects",
            "project": "projects",
            "agent": "agent",
            "agents": "agent",
            "qualification sop": "qualification sop",
            "sales sop": "sales sop",
            "onboarding sop": "onboarding sop",
            "execution sop": "execution sop",
            "reporting sop": "reporting sop",
        }

    def levenshtein(self, s1, s2):
        if len(s1) < len(s2):
            return self.levenshtein(s2, s1)

        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def autocorrect(self, text):
        raw = text.strip().lower()

        # if exact match → no correction needed
        if raw in self.known_databases:
            return {
                "corrected": self.known_databases[raw],
                "autocorrected": False,
                "distance": 0,
                "raw": raw,
            }

        # fuzzy match candidates
        candidates = list(self.known_databases.keys())
        best_match = None
        best_score = 999

        for c in candidates:
            dist = self.levenshtein(raw, c)
            if dist < best_score:
                best_score = dist
                best_match = c

        # threshold, distance > 4 is noise
        if best_score <= 4:
            return {
                "corrected": self.known_databases[best_match],
                "autocorrected": True,
                "distance": best_score,
                "raw": raw,
            }

        # no correction
        return {
            "corrected": raw,
            "autocorrected": False,
            "distance": best_score,
            "raw": raw,
        }

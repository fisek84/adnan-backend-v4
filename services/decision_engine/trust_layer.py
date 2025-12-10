import re

class TrustLayer:

    def __init__(self):
        # fuzzy patterns for detecting ambiguity
        self.vague_phrases = [
            r"\buradi ovo\b",
            r"\buradi to\b",
            r"\bnešto\b",
            r"\bpar stvari\b",
            r"\bsve stvari\b",
            r"\bnekako\b",
            r"\bpo mogućnosti\b",
            r"\bmožda\b",
            r"\bako stigneš\b"
        ]

        self.missing_action_patterns = [
            r"\bdodaj\b(?!.*bazi)",
            r"\bukloni\b(?!.*task|goal|projekt)",
        ]

    ###################################################################
    # MAIN TRUST EVALUATION
    ###################################################################
    def evaluate(self, text: str) -> dict:
        flags = []

        # 1 — vague language detection
        for pattern in self.vague_phrases:
            if re.search(pattern, text, re.IGNORECASE):
                flags.append("vague_language")
                break

        # 2 — missing target
        if re.search(r"\bdodaj\b", text, re.IGNORECASE) and not re.search(r"bazi", text, re.IGNORECASE):
            flags.append("missing_target")

        # 3 — missing actionable components
        if not re.search(r"Status:", text, re.IGNORECASE):
            flags.append("missing_status")

        if not re.search(r"Priority:", text, re.IGNORECASE):
            flags.append("missing_priority")

        # SCORE (simple heuristic)
        base_score = 1.0
        deduction = len(flags) * 0.15
        trust_score = max(0.0, round(base_score - deduction, 2))

        return {
            "score": trust_score,
            "flags": flags
        }

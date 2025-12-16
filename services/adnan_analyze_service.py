# services/adnan_analyze_service.py

from typing import Dict, Any


def analyze_text(text: str) -> Dict[str, Any]:
    """
    AdnanAnalyzeService — FAZA 11 / Reasoning Layer

    PURPOSE:
    - READ-ONLY analiza ulaznog teksta
    - kontekstualna i dijagnostička evaluacija
    - SAVJETODAVNI sloj (bez akcije)

    CONSTRAINTS:
    - NEMA AICommandService
    - NEMA execution-a
    - NEMA state mutation
    - NEMA implicitnih odluka
    """

    clean_text = text or ""
    length = len(clean_text)
    words = clean_text.split()

    return {
        "input": {
            "text": clean_text,
        },
        "analysis": {
            "length": length,
            "word_count": len(words),
            "is_question": clean_text.strip().endswith("?"),
            "contains_numbers": any(ch.isdigit() for ch in clean_text),
            "uppercase_ratio": (
                sum(ch.isupper() for ch in clean_text) / max(1, length)
            ),
        },
        "meta": {
            "read_only": True,
            "layer": "reasoning",
            "diagnostic": "Text analyzed safely without execution.",
        },
    }

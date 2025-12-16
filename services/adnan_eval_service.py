# services/adnan_eval_service.py

from typing import Dict, Any


def evaluate_text(input_text: str) -> Dict[str, Any]:
    """
    AdnanEvalService — FAZA 11 / Reasoning Layer

    PURPOSE:
    - READ-ONLY evaluacija teksta
    - verifikacija ulaza i osnovna semantička signalizacija
    - pomoćni sloj za reasoning pipeline

    CONSTRAINTS:
    - NEMA AI poziva
    - NEMA execution-a
    - NEMA state mutation
    - NEMA donošenja odluka
    """

    text = input_text or ""
    length = len(text)

    return {
        "input": {
            "text": text,
        },
        "evaluation": {
            "length": length,
            "is_question": text.strip().endswith("?"),
            "contains_numbers": any(char.isdigit() for char in text),
        },
        "meta": {
            "read_only": True,
            "layer": "reasoning",
            "diagnostic": "Safe evaluation completed without execution.",
        },
    }

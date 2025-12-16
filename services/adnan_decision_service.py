# services/adnan_decision_service.py

from typing import Dict, Any


def get_decision_engine_signature() -> Dict[str, Any]:
    """
    AdnanDecisionService — FAZA 11 / Reasoning Layer

    PURPOSE:
    - STATIČKA, READ-ONLY definicija Decision Engine-a
    - edukativni i savjetodavni prikaz pipeline-a
    - služi UX-u i Reasoning sloju za objašnjenje ponašanja sistema

    CONSTRAINTS:
    - NEMA izvršavanja
    - NEMA odluka
    - NEMA state mutation
    - NEMA implicitne logike
    """

    return {
        "engine": {
            "name": "Adnan.AI Decision Engine",
            "version": "1.0",
            "type": "static-signature",
        },
        "pipeline": [
            {
                "step": 1,
                "name": "Perception",
                "description": "Sistem prima ulaz bez interpretacije ili akcije.",
            },
            {
                "step": 2,
                "name": "Interpretation",
                "description": "Kontekst se čita i strukturira (READ-only).",
            },
            {
                "step": 3,
                "name": "Evaluation",
                "description": "Analiza namjere i značenja bez donošenja odluka.",
            },
            {
                "step": 4,
                "name": "Decision",
                "description": "Odluka postoji kao koncept, ne kao akcija.",
            },
            {
                "step": 5,
                "name": "Response",
                "description": "UX izlaz bez execution-a.",
            },
        ],
        "meta": {
            "read_only": True,
            "layer": "reasoning",
            "status": "static-definition",
        },
    }

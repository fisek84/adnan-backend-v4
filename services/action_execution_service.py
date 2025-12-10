# services/action_execution_service.py

from typing import Dict, Any
from services.action_dictionary import ACTION_MAP


class ActionExecutionService:
    """
    Execution Engine (Korak 8.3)

    Ovaj servis:
    - prima directive + params
    - nalazi odgovarajuću funkciju u ACTION_MAP
    - izvršava je na siguran način
    - vraća standardizovani rezultat
    """

    def execute(self, directive: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Glavna funkcija izvršavanja.
        """

        # -------------------------------
        # 1. Validacija direktive
        # -------------------------------
        if not directive:
            return {
                "executed": False,
                "error": "missing_directive"
            }

        func = ACTION_MAP.get(directive)

        if not func:
            return {
                "executed": False,
                "error": "unsupported_action",
                "directive": directive
            }

        # -------------------------------
        # 2. Validacija parametara
        # -------------------------------
        if params is None:
            params = {}

        if not isinstance(params, dict):
            return {
                "executed": False,
                "error": "invalid_params_format",
                "expected": "dict",
                "got": type(params).__name__,
            }

        # -------------------------------
        # 3. Izvršenje akcije (sigurno)
        # -------------------------------
        try:
            result = func(params)
        except Exception as e:
            return {
                "executed": False,
                "error": "action_failed",
                "message": str(e)
            }

        # -------------------------------
        # 4. Standardizovani format odgovora
        # -------------------------------
        return {
            "executed": True,
            "directive": directive,
            "params": params,
            "result": result
        }

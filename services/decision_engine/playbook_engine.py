from typing import Dict, Any, List

from services.decision_engine.sop_mapper import SOPMapper


class PlaybookEngine:
    """
    BUSINESS PLAYBOOK ENGINE — FAZA 4–7 (CEO level)

    Pravila:
    - prepoznaje SOP intent
    - mapira SOP (LOGIČKI, ne DB)
    - vraća EXECUTION PLAN + VARIJANTE
    - NEMA izvršenja
    - NEMA memorije
    - NEMA odlučivanja
    """

    def __init__(self):
        self.sop_mapper = SOPMapper()

    # ============================================================
    # PUBLIC API
    # ============================================================
    def evaluate(
        self,
        user_input: str,
        identity_reasoning: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:

        context_type = context.get("context_type")
        text = user_input.lower()

        if context_type == "sop":
            sop_name = self.sop_mapper.resolve_sop(text)

            if not sop_name:
                return {
                    "type": "sop_execution",
                    "success": False,
                    "reason": "SOP intent detected but SOP not resolved",
                }

            base_plan = self._build_sop_execution_plan(sop_name)

            return {
                "type": "sop_execution",
                "sop": sop_name,
                "execution_plan": base_plan,   # backward-compatible
                "variants": self._build_variants(sop_name, base_plan),
            }

        return {
            "type": "noop",
            "reason": "No SOP playbook matched",
        }

    # ============================================================
    # SOP → EXECUTION PLAN (BASELINE)
    # ============================================================
    def _build_sop_execution_plan(self, sop_name: str) -> List[Dict[str, Any]]:
        """
        Baseline plan (SAFE DEFAULT).
        """

        if sop_name == "customer onboarding sop":
            return [
                {
                    "step": "create_project",
                    "agent": "notion_ops",
                    "command": "create_database_entry",
                    "critical": True,
                    "payload": {
                        "database_key": "projects",
                        "properties": {
                            "Name": {
                                "title": [
                                    {"text": {"content": "New Client Onboarding"}}
                                ]
                            }
                        },
                    },
                },
                {
                    "step": "create_kickoff_task",
                    "agent": "notion_ops",
                    "command": "create_database_entry",
                    "critical": False,
                    "payload": {
                        "database_key": "tasks",
                        "properties": {
                            "Name": {
                                "title": [
                                    {"text": {"content": "Kickoff call"}}
                                ]
                            }
                        },
                    },
                },
            ]

        return [
            {
                "step": "list_tasks",
                "agent": "notion_ops",
                "command": "query_database",
                "critical": False,
                "payload": {
                    "database_key": "tasks",
                },
            }
        ]

    # ============================================================
    # FAZA 7.2 — VARIANTS (DESCRIPTIVE ONLY)
    # ============================================================
    def _build_variants(
        self,
        sop_name: str,
        base_plan: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        VARIJANTE SU OPISNE.
        NEMA logike.
        NEMA odluke.
        """

        variants: Dict[str, List[Dict[str, Any]]] = {
            "default": base_plan,
        }

        if sop_name == "customer onboarding sop":
            # FAST: minimalni koraci
            variants["fast"] = [
                step for step in base_plan
                if step.get("step") == "create_project"
            ]

            # FULL: eksplicitno svi koraci (isti kao default, ali imenovano)
            variants["full"] = list(base_plan)

        return variants

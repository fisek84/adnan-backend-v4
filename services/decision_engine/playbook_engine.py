from typing import Dict, Any, List, Optional

from services.decision_engine.sop_mapper import SOPMapper
from services.memory_service import MemoryService


class PlaybookEngine:
    """
    BUSINESS PLAYBOOK ENGINE — FAZA 4–7 + FAZA 9.1 + FAZA 9.2 + FAZA 9.3 (CEO level)

    Pravila:
    - prepoznaje SOP intent
    - mapira SOP (LOGIČKI, ne DB)
    - vraća EXECUTION PLAN + VARIJANTE
    - READ-ONLY (NEMA izvršenja)
    """

    def __init__(self):
        self.sop_mapper = SOPMapper()
        self.memory = MemoryService()  # READ-ONLY

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

            sop_bias = self.memory.get_cross_sop_bias(sop_name)
            sop_success_rate = self.memory.sop_success_rate(sop_name)

            recommendation = self._build_sop_recommendation(
                current_sop=sop_name,
                bias=sop_bias,
            )

            return {
                "type": "sop_execution",
                "sop": sop_name,
                "execution_plan": base_plan,
                "execution_plan_preview": self.preview_execution_plan(
                    {"steps": base_plan}
                ),
                "variants": self._build_variants(sop_name, base_plan),
                "sop_bias": sop_bias,
                "sop_success_rate": sop_success_rate,
                "recommendation": recommendation,
            }

        return {
            "type": "noop",
            "reason": "No SOP playbook matched",
        }

    # ============================================================
    # SOP → EXECUTION PLAN (BASELINE)
    # ============================================================
    def _build_sop_execution_plan(self, sop_name: str) -> List[Dict[str, Any]]:
        if sop_name == "customer onboarding sop":
            return [
                {
                    "step": "create_project",
                    "agent": "agent",
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
                    "agent": "agent",
                    "command": "create_database_entry",
                    "critical": False,
                    "payload": {
                        "database_key": "tasks",
                        "properties": {
                            "Name": {"title": [{"text": {"content": "Kickoff call"}}]}
                        },
                    },
                },
            ]

        return [
            {
                "step": "list_tasks",
                "agent": "agent",
                "command": "query_database",
                "critical": False,
                "payload": {
                    "database_key": "tasks",
                },
            }
        ]

    # ============================================================
    # SOP EXECUTION PLAN PREVIEW (READ-ONLY)
    # ============================================================
    def preview_execution_plan(self, sop_content: Dict[str, Any]) -> Dict[str, Any]:
        steps = sop_content.get("steps", [])
        preview: List[Dict[str, Any]] = []

        for index, step in enumerate(steps):
            preview.append(
                {
                    "order": index + 1,
                    "step": step.get("step"),
                    "agent": step.get("agent"),
                    "command": step.get("command"),
                    "critical": step.get("critical", False),
                }
            )

        return {
            "type": "execution_plan_preview",
            "count": len(preview),
            "steps": preview,
            "read_only": True,
        }

    # ============================================================
    # VARIANTS (DESCRIPTIVE ONLY)
    # ============================================================
    def _build_variants(
        self,
        sop_name: str,
        base_plan: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        variants: Dict[str, List[Dict[str, Any]]] = {
            "default": base_plan,
        }

        if sop_name == "customer onboarding sop":
            variants["fast"] = [
                step for step in base_plan if step.get("step") == "create_project"
            ]
            variants["full"] = list(base_plan)

        return variants

    # ============================================================
    # SOP CHAINING RECOMMENDATION (READ-ONLY)
    # ============================================================
    def _build_sop_recommendation(
        self,
        current_sop: str,
        bias: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not bias:
            return None

        best = bias[0]

        return {
            "message": (
                f"Nakon SOP-a '{current_sop}', "
                f"historijski je najbolje slijedio SOP '{best['to']}' "
                f"(success rate: {best['success_rate']})."
            ),
            "suggested_next_sop": best["to"],
            "confidence": best["success_rate"],
            "source": "historical_execution_data",
            "read_only": True,
        }

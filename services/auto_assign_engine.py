# services/auto_assign_engine.py

from typing import Any, Dict, Optional, List


class AutoAssignEngine:
    """
    AutoAssignEngine — FAZA 10 / Agent Specialization

    PURPOSE:
    - Deterministička relacijska rezolucija (READ-ONLY)
    - Task → Goal (direktno)
    - Task → Project
    - Project → Primary Goal (fallback)
    - Project → Tasks (reverse lookup)

    CONSTRAINTS:
    - READ ONLY
    - NEMA execution-a
    - NEMA side-effecta
    - NEMA autonomne logike
    """

    # -----------------------------------------------------------
    # TASK → GOAL (DIRECT)
    # -----------------------------------------------------------
    @staticmethod
    def get_goal_id_from_task(page: Dict[str, Any]) -> Optional[str]:
        props = page.get("properties", {})
        goal = props.get("Goal")

        if goal and goal.get("type") == "relation" and goal.get("relation"):
            raw = goal["relation"][0]["id"]
            return raw.replace("-", "")

        return None

    # -----------------------------------------------------------
    # PROJECT → PRIMARY GOAL
    # -----------------------------------------------------------
    @staticmethod
    def get_primary_goal_from_project(project_page: Dict[str, Any]) -> Optional[str]:
        props = project_page.get("properties", {})
        pg = props.get("Primary Goal")

        if pg and pg.get("relation"):
            raw = pg["relation"][0]["id"]
            return raw.replace("-", "")

        return None

    # -----------------------------------------------------------
    # TASK → GOAL preko PROJECTA (fallback)
    # -----------------------------------------------------------
    @staticmethod
    def get_goal_from_project_fallback(
        task_page: Dict[str, Any],
        project_page: Dict[str, Any],
    ) -> Optional[str]:
        return AutoAssignEngine.get_primary_goal_from_project(project_page)

    # -----------------------------------------------------------
    # TASK → PROJECT (DIRECT)
    # -----------------------------------------------------------
    @staticmethod
    def get_project_from_task(page: Dict[str, Any]) -> Optional[str]:
        props = page.get("properties", {})
        proj = props.get("Project")

        if proj and proj.get("relation"):
            raw = proj["relation"][0]["id"]
            return raw.replace("-", "")

        return None

    # -----------------------------------------------------------
    # PROJECT → TASKS DB (reverse lookup)
    # -----------------------------------------------------------
    @staticmethod
    def get_task_ids_from_project(project_page: Dict[str, Any]) -> List[str]:
        props = project_page.get("properties", {})
        tasks_field = props.get("Tasks DB")

        if not tasks_field or not tasks_field.get("relation"):
            return []

        return [t["id"].replace("-", "") for t in tasks_field["relation"]]

    # -----------------------------------------------------------
    # EFFECTIVE GOAL LOGIC
    # -----------------------------------------------------------
    @staticmethod
    def resolve_effective_goal(
        task_page: Dict[str, Any],
        project_page: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Priority:
        1. Direct Goal on Task
        2. Primary Goal on Project
        """
        direct = AutoAssignEngine.get_goal_id_from_task(task_page)
        if direct:
            return direct

        if project_page:
            return AutoAssignEngine.get_primary_goal_from_project(project_page)

        return None

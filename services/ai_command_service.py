class AICommandService:
    """
    Evolia Natural Language Command Engine v1.0
    """

    def __init__(self):
        # REGISTER COMMANDS
        self._commands = {
            # SYSTEM
            "echo": self._echo,

            # TASKS
            "GET /tasks/all": self._get_tasks_all,

            # GOALS
            "GET /goals/all": self._get_goals_all,
            "GET /goals/full": self._get_goals_full,
            "GET /goals/subgoals": self._get_subgoals,

            # COMBINED
            "GET /goals+tasks": self._get_goals_and_tasks,
        }

    # -------------------------
    # MAIN EXECUTOR
    # -------------------------
    def execute(self, command: str, payload: dict):
        """
        Accepts BOTH:
        - structured commands (GET /tasks/all)
        - natural language ('pokaži mi ciljeve')
        """
        command = command.strip()

        # Natural language → translate to structured command
        if not command.startswith("GET") and not command.startswith("POST"):
            command, payload = self._interpret_natural(command)

        # Validate
        if command not in self._commands:
            raise ValueError(f"Unknown command: {command}")

        return self._commands[command](payload)

    # -------------------------
    # NATURAL LANGUAGE PARSER
    # -------------------------
    def _interpret_natural(self, text: str):
        t = text.lower().strip()

        # GOALS — LIST
        if "ciljev" in t and ("lista" in t or "prikaži" in t or "pokaži" in t):
            return ("GET /goals/all", {})

        # GOAL FULL DETAIL
        if "informacije o ciljevima" in t or "detalji ciljeva" in t:
            return ("GET /goals/full", {})

        # SUBGOALS
        if "podciljev" in t:
            return ("GET /goals/subgoals", {})

        # TASKS — LIST
        if "task" in t and ("lista" in t or "pokaži" in t or "prikaži" in t):
            return ("GET /tasks/all", {})

        # GOALS + TASKS
        if ("ciljev" in t) and ("task" in t):
            return ("GET /goals+tasks", {})

        raise ValueError("Natural language command not recognized.")

    # -------------------------
    # HANDLERS
    # -------------------------

    def _echo(self, payload: dict):
        return payload

    def _get_tasks_all(self, payload: dict):
        from services.tasks import get_all_tasks
        return get_all_tasks()

    def _get_goals_all(self, payload: dict):
        from services.goals_notion import get_all_goals
        return get_all_goals()

    def _get_goals_full(self, payload: dict):
        from services.goals_notion import get_full_goals
        return get_full_goals()

    def _get_subgoals(self, payload: dict):
        from services.goals_notion import get_subgoals
        return get_subgoals()

    def _get_goals_and_tasks(self, payload: dict):
        from services.goals_notion import get_all_goals
        from services.tasks import get_all_tasks
        return {
            "goals": get_all_goals(),
            "tasks": get_all_tasks()
        }
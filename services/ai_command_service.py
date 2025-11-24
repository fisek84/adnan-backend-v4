class AICommandService:
    """
    Evolia AICommandService v4.1
    - Jednostavan command executor
    - Služi kao most prema lokalnim AI komandama
    """

    def __init__(self):
        self._commands = {
            "echo": self._echo,
            "sum": self._sum,
            "multiply": self._multiply,
        }

    # ============================================================
    # AVAILABLE COMMANDS
    # ============================================================
    def available_commands(self):
        return list(self._commands.keys())

    # ============================================================
    # EXECUTE COMMAND
    # ============================================================
    def execute(self, command: str, payload: dict):
        if command not in self._commands:
            raise ValueError(f"Unknown command: {command}")

        return self._commands[command](payload)

    # ============================================================
    # BUILT-IN COMMANDS
    # ============================================================
    def _echo(self, payload: dict):
        return payload

    def _sum(self, payload: dict):
        numbers = payload.get("numbers", [])
        return sum(numbers)

    def _multiply(self, payload: dict):
        a = payload.get("a", 1)
        b = payload.get("b", 1)
        return a * b
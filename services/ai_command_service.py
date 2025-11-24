class AICommandService:
    """
    Evolia AICommandService v4.1
    Jednostavan command executor
    """

    def __init__(self):
        self._commands = {
            "echo": self._echo,
            "sum": self._sum,
            "multiply": self._multiply,
        }

    def available_commands(self):
        return list(self._commands.keys())

    def execute(self, command: str, payload: dict):
        if command not in self._commands:
            raise ValueError(f"Unknown command: {command}")
        return self._commands[command](payload)

    def _echo(self, payload: dict):
        return payload

    def _sum(self, payload: dict):
        return sum(payload.get("numbers", []))

    def _multiply(self, payload: dict):
        return payload.get("a", 1) * payload.get("b", 1)
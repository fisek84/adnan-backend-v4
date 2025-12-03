import json
import openai
import os
from services.identity_loader import load_adnan_identity


class AICommandService:
    def __init__(self):
        # Load OpenAI key from environment
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing in environment variables.")

        openai.api_key = api_key

        # Official v2 client
        self.client = openai.OpenAI()
        self.model = "gpt-4.1-mini"

        # Load full Adnan.AI identity (JSON)
        self.identity = load_adnan_identity()     # ✅ PRAVILNA FUNKCIJA

        # Map structured commands
        self._commands = {
            "GET /goals/all": self._get_goals_list,
            "GET /goals/full": self._get_goals_full,
            "GET /goals/subgoals": self._get_goals_subgoals,
            "GET /tasks/all": self._get_tasks_list,
            "GET /goals+tasks": self._get_goals_and_tasks,
        }

    # ---------------------------------------------------------
    # MAIN ENTRYPOINT
    # ---------------------------------------------------------

    def execute(self, command: str, payload: dict):
        """
        Accepts BOTH:
        - structured commands (GET /tasks/all)
        - natural language ('pokaži mi ciljeve')
        """
        command = command.strip()

        # Translate natural → structured OR natural fallback
        if not command.startswith("GET") and not command.startswith("POST"):
            command, payload = self._interpret_natural(command)

        # If it's natural fallback → call GPT
        if command == "natural":
            return self._natural_fallback(payload["text"])

        # Structured command handler
        if command not in self._commands:
            raise ValueError(f"Unknown command: {command}")

        return self._commands[command](payload)

    # ---------------------------------------------------------
    # NATURAL LANGUAGE PARSING
    # ---------------------------------------------------------

    def _interpret_natural(self, text: str):
        t = text.lower().strip()

        # Normalizacija dijakritike
        t = (
            t.replace("ć", "c")
            .replace("č", "c")
            .replace("š", "s")
            .replace("ž", "z")
            .replace("đ", "dj")
        )

        # Goals list
        if any(x in t for x in ["ciljev", "ciljeve", "ciljevi"]):
            if any(x in t for x in ["lista", "pokazi", "prikazi"]):
                return ("GET /goals/all", {})

        # Full details
        if "informacije o ciljevima" in t or "detalji ciljeva" in t:
            return ("GET /goals/full", {})

        # Subgoals
        if "podciljev" in t or "podciljeve" in t:
            return ("GET /goals/subgoals", {})

        # Tasks list
        if any(x in t for x in ["task", "taskovi", "taskove"]):
            if any(x in t for x in ["lista", "pokazi", "prikazi"]):
                return ("GET /tasks/all", {})

        # Combined
        goals_terms = ["ciljev", "ciljeve", "ciljevi"]
        task_terms = ["task", "taskovi", "taskove"]

        if any(g in t for g in goals_terms) and any(s in t for s in task_terms):
            return ("GET /goals+tasks", {})

        # Unknown natural → fall back to GPT
        return ("natural", {"text": text})

    # ---------------------------------------------------------
    # GPT NATURAL FALLBACK
    # ---------------------------------------------------------

    def _natural_fallback(self, text: str):
        """
        Backend koristi kompletan Adnan.AI identitet kao system prompt.
        """
        system_prompt = (
            "Ti si Adnan.AI — digitalni klon korisnika. "
            "Radiš striktno u skladu sa identitetom, kernelom, principima, "
            "ponašanjem i logikom iz JSON fajla.\n\n"
            "JSON IDENTITET:\n"
            + json.dumps(self.identity, ensure_ascii=False, indent=2)
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        )

        return {
            "type": "natural",
            "input": text,
            "output": response.choices[0].message.content,   # ✅ FIXED
        }

    # ---------------------------------------------------------
    # STRUCTURED COMMAND ENDPOINTS
    # ---------------------------------------------------------

    def _get_goals_list(self, payload):
        return {"ok": True, "data": "goal-list"}

    def _get_goals_full(self, payload):
        return {"ok": True, "data": "goal-full"}

    def _get_goals_subgoals(self, payload):
        return {"ok": True, "data": "goal-subgoals"}

    def _get_tasks_list(self, payload):
        return {"ok": True, "data": "task-list"}

    def _get_goals_and_tasks(self, payload):
        return {"ok": True, "data": "goals+tasks"}
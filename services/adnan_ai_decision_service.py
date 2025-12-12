import json
from pathlib import Path
from typing import Dict, Any

from rapidfuzz import fuzz, process

from services.decision_engine.autocorrect import AutocorrectEngine
from services.decision_engine.trust_layer import TrustLayer
from services.decision_engine.sop_mapper import SOPMapper
from services.decision_engine.static_memory_engine import StaticMemoryEngine
from services.decision_engine.dynamic_memory import DynamicMemoryEngine
from services.decision_engine.personality_engine import PersonalityEngine


# ================================================================
# PATHS — CANONICAL
# ================================================================
BASE_PATH = Path(__file__).resolve().parent.parent / "identity"


# ================================================================
# DATABASE MAP (LOGICAL KEYS ONLY)
# ================================================================
DATABASE_MAP = {
    "task": "tasks",
    "tasks": "tasks",
    "goal": "goals",
    "goals": "goals",
    "cilj": "goals",
    "ciljevi": "goals",
    "project": "projects",
    "projects": "projects",
    "weekly": "ai_weekly_summary",
}


# ================================================================
# ACTION VERBS
# ================================================================
ACTION_PATTERNS = {
    "create": ["kreiraj", "napravi", "create", "add", "dodaj", "novi", "new"],
    "update": ["update", "izmijeni", "uredi", "promijeni"],
    "delete": ["obriši", "obrisi", "delete", "remove"],
    "query": ["prikaži", "listaj", "show", "get", "query", "pokaži"],
}


# ================================================================
# HELPERS
# ================================================================
def fuzzy_match(value, choices, threshold=75):
    if not value:
        return None
    result = process.extractOne(value, choices, scorer=fuzz.partial_ratio)
    if not result:
        return None
    match, score, _ = result
    return match if score >= threshold else None


def extract_title_from_text(text: str) -> str:
    if ":" in text:
        return text.split(":", 1)[1].strip()
    tokens = text.split()
    return tokens[-1] if tokens else "Untitled"


def natural_response(command: str) -> str:
    return {
        "create_database_entry": "Mogu kreirati novi zapis u Notionu.",
        "update_database_entry": "Mogu ažurirati zapis u Notionu.",
        "delete_page": "Mogu obrisati zapis iz Notiona.",
        "query_database": "Mogu prikupiti podatke iz Notiona.",
    }.get(command, "Mogu izvršiti zahtjev.")


# ================================================================
# CEO DECISION SERVICE — FAZA 7.3 (DELEGATION CONTRACT)
# ================================================================
class AdnanAIDecisionService:
    """
    CEO Brain — prirodni jezik → DELEGACIJSKI UGOVOR.
    - NEMA direktnog izvršenja
    - Eksplicitni executor: notion_ops
    """

    def __init__(self):
        self.identity = self._load("identity.json")
        self.kernel = self._load("kernel.json")
        self.mode = self._load("mode.json")
        self.state = self._load("state.json")
        self.static_memory = self._load("static_memory.json")

        self.autocorrect = AutocorrectEngine()
        self.trust_layer = TrustLayer()
        self.sop_mapper = SOPMapper()
        self.static_memory_engine = StaticMemoryEngine(self.static_memory)
        self.dynamic_memory_engine = DynamicMemoryEngine({})

        self.personality_engine = PersonalityEngine()

    # ============================================================
    # LOADERS
    # ============================================================
    def _load(self, filename: str) -> Dict[str, Any]:
        path = BASE_PATH / filename
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)

    # ============================================================
    # INTENT DETECTION
    # ============================================================
    def _detect_intent(self, text: str) -> Dict[str, Any]:
        t = text.lower()

        action = None
        for act, patterns in ACTION_PATTERNS.items():
            if fuzzy_match(t, patterns, 70):
                action = act
                break

        db_key_raw = fuzzy_match(t, DATABASE_MAP.keys(), 70)
        db_key = DATABASE_MAP.get(db_key_raw)

        return {
            "action": action,
            "database_key": db_key,
            "raw_text": text,
        }

    # ============================================================
    # COMMAND BUILDER (DELEGATION-ONLY)
    # ============================================================
    def _build_command(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        action = intent.get("action")
        db_key = intent.get("database_key")
        raw_text = intent.get("raw_text", "")

        if not action or not db_key:
            return {"command": None, "payload": {}}

        if action == "query":
            return {
                "command": "query_database",
                "payload": {"database_key": db_key},
            }

        if action == "create":
            title = extract_title_from_text(raw_text)
            return {
                "command": "create_database_entry",
                "payload": {
                    "database_key": db_key,
                    "properties": {
                        "Name": {
                            "title": [
                                {"text": {"content": title}}
                            ]
                        }
                    },
                },
            }

        if action == "update":
            return {
                "command": "update_database_entry",
                "payload": {"database_key": db_key},
            }

        if action == "delete":
            return {
                "command": "delete_page",
                "payload": {},
            }

        return {"command": None, "payload": {}}

    # ============================================================
    # ENTRYPOINT — FAZA 7.3
    # ============================================================
    def process_ceo_instruction(self, text: str) -> Dict[str, Any]:
        lower = text.lower()

        # MEMORY (LOCAL ONLY)
        if "zapamti" in lower:
            self.personality_engine.learn_from_text(text)
            return {
                "decision_candidate": False,
                "executor": None,
                "command": None,
                "payload": {},
                "system_response": "Zabilježeno.",
            }

        intent = self._detect_intent(text)
        command_block = self._build_command(intent)

        if not command_block["command"]:
            return {
                "decision_candidate": False,
                "executor": None,
                "command": None,
                "payload": {},
                "system_response": "Razumijem.",
            }

        # --------------------------------------------------------
        # FAZA 7.3 — FORMAL DELEGATION CONTRACT
        # --------------------------------------------------------
        return {
            "decision_candidate": True,
            "executor": "notion_ops",
            "command": command_block["command"],
            "payload": command_block["payload"],
            "origin": "adnan.ai",
            "confirmed": False,
            "system_response": natural_response(command_block["command"]),
        }

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

# SOP KNOWLEDGE
from services.sop_knowledge_registry import SOPKnowledgeRegistry


# ================================================================
# PATHS — CANONICAL
# ================================================================
BASE_PATH = Path(__file__).resolve().parent.parent / "identity"


# ================================================================
# DATABASE MAP
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
        "create_database_entry": "Kreiram novi zapis.",
        "update_database_entry": "Ažuriram postojeći zapis.",
        "delete_page": "Brišem zapis.",
        "query_database": "Prikupljam podatke.",
        "execute_sop": "SOP je potvrđen i ide u izvršenje.",
    }.get(command, "Izvršavam zahtjev.")


# ================================================================
# CEO DECISION SERVICE — KANONSKI
# ================================================================
class AdnanAIDecisionService:
    """
    CEO Brain — prirodni jezik → DELEGATION CONTRACT
    NEMA izvršenja.
    """

    WRITE_COMMANDS = {
        "create_database_entry",
        "update_database_entry",
        "delete_page",
    }

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

        self.sop_registry = SOPKnowledgeRegistry()

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
    # ENTRYPOINT — LEGACY (RAW TEXT)
    # ============================================================
    def process_ceo_instruction(self, text: str) -> Dict[str, Any]:
        lower = text.lower().strip()

        # ========================================================
        # 🟢 SOP EXECUTION — LEGACY PATH
        # ========================================================
        if lower.startswith("execute sop:"):
            sop_id = lower.replace("execute sop:", "").strip()

            sop = self.sop_registry.get_sop(sop_id, mode="summary")
            if not sop:
                return {
                    "decision_candidate": False,
                    "executor": None,
                    "command": None,
                    "payload": {},
                    "system_response": "Nepoznat SOP.",
                }

            return {
                "decision_candidate": False,
                "executor": "sop_execution_manager",
                "command": "execute_sop",
                "payload": {
                    "sop_id": sop_id,
                    "sop_name": sop["name"],
                },
                "origin": "adnan.ai",
                "confirmed": True,
                "system_response": f"SOP '{sop['name']}' je potvrđen za izvršenje.",
            }

        # ========================================================
        # MEMORY
        # ========================================================
        if "zapamti" in lower:
            self.personality_engine.learn_from_text(text)
            return {
                "decision_candidate": False,
                "executor": None,
                "command": None,
                "payload": {},
                "system_response": "Zabilježeno.",
            }

        # ========================================================
        # NOTION INTENTS — LEGACY
        # ========================================================
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

        decision = {
            "decision_candidate": True,
            "executor": "notion_ops",
            "command": command_block["command"],
            "payload": command_block["payload"],
            "origin": "adnan.ai",
            "confirmed": False,
            "system_response": natural_response(command_block["command"]),
        }

        # ========================================================
        # FAZA F3 — WRITE INTENT PROPAGATION
        # ========================================================
        if command_block["command"] in self.WRITE_COMMANDS:
            decision["write_intent"] = True

        return decision

    # ============================================================
    # INTENT DETECTION — LEGACY
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
    # COMMAND BUILDER — LEGACY
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
                            "title": [{"text": {"content": title}}]
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
    # CSI / INTENT ADAPTER — KANONSKI
    # ============================================================
    def build_decision(
        self,
        action: str,
        intent: str,
        confidence: float,
        csi_state: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not action:
            return {
                "decision_candidate": False,
                "executor": None,
                "command": None,
                "payload": {},
                "system_response": "Razumijem.",
            }

        if action == "request_execution":
            sop_id = csi_state.get("active_sop_id")
            if not sop_id:
                return {
                    "decision_candidate": False,
                    "executor": None,
                    "command": None,
                    "payload": {},
                    "system_response": "Nema aktivnog SOP-a.",
                }

            sop = self.sop_registry.get_sop(sop_id, mode="summary")
            if not sop:
                return {
                    "decision_candidate": False,
                    "executor": None,
                    "command": None,
                    "payload": {},
                    "system_response": "Nepoznat SOP.",
                }

            return {
                "decision_candidate": True,
                "executor": "sop_execution_manager",
                "command": "execute_sop",
                "payload": {
                    "sop_id": sop_id,
                    "sop_name": sop["name"],
                },
                "origin": "adnan.ai",
                "confirmed": True,
                "confidence": confidence,
                "system_response": f"SOP '{sop['name']}' je spreman za izvršenje.",
            }

        return {
            "decision_candidate": False,
            "executor": None,
            "command": None,
            "payload": {},
            "system_response": "Razumijem.",
        }

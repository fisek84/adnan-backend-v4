import json
from pathlib import Path
import re
import copy

from rapidfuzz import fuzz, process

# AUTOCORRECT A2
from services.decision_engine.autocorrect import AutocorrectEngine

# TRUST LAYER T1
from services.decision_engine.trust_layer import TrustLayer

# SOP INTELLIGENCE S2
from services.decision_engine.sop_mapper import SOPMapper

# STATIC MEMORY M1
from services.decision_engine.static_memory_engine import StaticMemoryEngine

# DYNAMIC MEMORY D1
from services.decision_engine.dynamic_memory import DynamicMemoryEngine

# PERSONALITY ENGINE P1
from services.decision_engine.personality_engine import PersonalityEngine


BASE_PATH = Path(__file__).resolve().parent.parent / "identity"
MEMORY_FILE = BASE_PATH / "memory.json"


###################################################################
# EXTENDED DATABASE MAP
###################################################################
DATABASE_MAP = {
    "task": "2ad5873bd84a80e8b4dac703018212fe",
    "tasks": "2ad5873bd84a80e8b4dac703018212fe",

    "goal": "2ac5873bd84a801f956fc30327b8ef94",
    "goals": "2ac5873bd84a801f956fc30327b8ef94",

    "cilj": "2ac5873bd84a801f956fc30327b8ef94",
    "ciljevi": "2ac5873bd84a801f956fc30327b8ef94",

    "project": "2ac5873bd84a8004aac0ea9c53025bfc",
    "projects": "2ac5873bd84a8004aac0ea9c53025bfc",

    "note": "2b75873bd84a80619330eb45348dd90e",
    "notes": "2b75873bd84a80619330eb45348dd90e",

    "weekly summary": "2b75873bd84a80619330eb45348dd90e",

    "kpi": "2bd5873bd84a80b68889df5485567703",
}


###################################################################
# ACTION VERBS
###################################################################
ACTION_PATTERNS = {
    "create": ["kreiraj", "napravi", "create", "add", "dodaj", "postavi", "new"],
    "update": ["update", "izmijeni", "uredi", "promijeni", "change", "postavi status"],
    "delete": ["obriši", "obrisi", "delete", "remove", "ukloni"],
    "query": ["prikaži", "listaj", "show", "get", "query", "pokaži"],
    "link": ["poveži", "povezi", "link", "relate", "connect", "dodijeli", "dodjeli", "assign"]
}


###################################################################
# FUZZY HELPERS
###################################################################
def fuzzy_match(value, choices, threshold=75):
    if not value:
        return None
    result = process.extractOne(value, choices, scorer=fuzz.partial_ratio)
    if not result:
        return None
    match, score, _ = result
    return match if score >= threshold else None


def fuzzy_extract_name(text):
    low = text.lower()
    cleaned = (
        low.replace("kreiraj", "")
        .replace("napravi", "")
        .replace("dodaj", "")
        .replace("obrisi", "")
        .replace("obriši", "")
        .replace("task", "")
        .replace("goal", "")
        .strip()
    )
    return cleaned if cleaned else ""


###################################################################
# NATURAL LANGUAGE RESPONSE
###################################################################
def natural_response(cmd):
    if cmd.get("blocked"):
        return cmd.get("system_response", "Potrebna je potvrda.")

    return {
        "create_database_entry": "Kreiram novi zapis.",
        "update_database_entry": "Ažuriram zapis.",
        "delete_page": "Brišem zapis.",
        "query_database": "Prikupljam podatke.",
        "query_all": "Prikupljam sve podatke.",
        "link_records": "Povezujem relacije."
    }.get(cmd.get("command"), "Izvršavam tvoj zahtjev.")


###################################################################
# HYBRID BRAIN DECISION ENGINE (FINAL VERSION)
###################################################################
class AdnanAIDecisionService:

    def __init__(self):
        # Load engine configs
        self.identity = self._load("identity.json")
        self.kernel = self._load("kernel.json")
        self.mode = self._load("mode.json")
        self.state = self._load("state.json")
        self.decision_engine = self._load("decision_engine.json")
        self.static_memory = self._load("static_memory.json")

        # sub-engines
        self.autocorrect_engine = AutocorrectEngine()
        self.trust_layer = TrustLayer()
        self.sop_mapper = SOPMapper()
        self.static_memory_engine = StaticMemoryEngine(self.static_memory)

        # memory engines
        self.session_memory = self._init_session_memory()
        self.dynamic_memory_engine = DynamicMemoryEngine(self.session_memory)

        # identity / personality brain
        self.personality_engine = PersonalityEngine()

    ###################################################################
    # HYBRID ROUTER HELPERS
    ###################################################################
    def is_business_message(self, text: str) -> bool:
        t = text.lower()
        keywords = [
            "task", "goal", "project", "kpi",
            "cilj", "projekat", "zad", "zadatak",
            "outreach", "sales", "follow up", "proces", "sop",
            "rast", "skaliranje", "performance"
        ]
        return any(k in t for k in keywords)

    def chat_response(self, text: str) -> dict:
        return {
            "command": None,
            "payload": {},
            "local_only": True,
            "system_response": self._chat_logic(text)
        }

    def _chat_logic(self, text: str) -> str:
        t = text.lower()
        if "ko si" in t:
            return "Ja sam Adnan.AI — tvoj digitalni klon, dizajniran da razmišlja i djeluje kao ti."
        if "ko sam ja" in t:
            return "Ti si Adnan Fisek — kreator Evolia ekosistema."
        return "Razumijem. Reci mi šta želiš dalje."

    ###################################################################
    # MEMORY
    ###################################################################
    def _init_session_memory(self):
        if MEMORY_FILE.exists():
            return json.load(open(MEMORY_FILE, "r", encoding="utf-8-sig"))

        base = {
            "dynamic_memory": {"tasks": []},
            "last_mode": None,
            "last_state": None,
            "trace": [],
            "notes": []
        }
        json.dump(base, open(MEMORY_FILE, "w", encoding="utf-8"), indent=2)
        return base

    def _load(self, filename: str):
        return json.load(open(BASE_PATH / filename, "r", encoding="utf-8-sig"))

    def _save_memory(self):
        json.dump(self.session_memory, open(MEMORY_FILE, "w", encoding="utf-8"), indent=2)

    ###################################################################
    # INTENT + COMMAND BUILDERS
    ###################################################################
    def detect_intent(self, text):
        t = text.lower()

        action = None
        for act, patterns in ACTION_PATTERNS.items():
            if fuzzy_match(t, patterns, 70):
                action = act
                break

        db_guess = fuzzy_match(t, list(DATABASE_MAP.keys()), 70)

        name = ""
        patterns = [
            r"(ime|title|naziv)\s*[-:]\s*(.+)",
            r"(task|goal|project|note)\s*[-:]\s*(.+)",
            r"(task|goal|project|note)\s+([A-Za-z0-9_\-\s]+)$"
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                name = m.group(len(m.groups()))
                break

        if not name:
            name = fuzzy_extract_name(text)

        status_match = re.search(r"status\s*[-:]\s*([\w ]+)", text, re.IGNORECASE)
        status = status_match.group(1).strip() if status_match else ""

        priority_match = re.search(r"(priority|prioritet)\s*[-:]\s*([\w ]+)", text, re.IGNORECASE)
        priority = priority_match.group(2).strip() if priority_match else ""

        parent = None
        child = None
        link_match = re.search(
            r"(task|goal|project|subgoal)\s+(.+?)\s+.*?(na|u|pod|to)\s+(goal|cilj|project|task)\s+(.+)",
            text,
            re.IGNORECASE
        )
        if link_match:
            child_raw = link_match.group(2).strip()
            parent_raw = link_match.group(5).strip()
            child = fuzzy_match(child_raw, [child_raw, name], 60)
            parent = fuzzy_match(parent_raw, list(DATABASE_MAP.keys()), 60)

        return {
            "action": action,
            "database": db_guess,
            "name": name,
            "status": status,
            "priority": priority,
            "parent": parent,
            "child": child,
            "raw_text": text
        }

    def build_command(self, intent):
        if intent["action"] == "link":
            return {"command": "link_records", "payload": {
                "parent_name": intent["parent"],
                "child_name": intent["child"]
            }}

        if intent["action"] == "delete":
            return {"command": "delete_page", "payload": {"name": intent.get("name")}}

        if intent["action"] == "query" and "all" in intent["raw_text"].lower():
            return {"command": "query_all", "payload": {}}

        if intent["action"] == "query":
            db_id = DATABASE_MAP.get(intent["database"])
            return {"command": "query_database", "payload": {"database_id": db_id}}

        db_id = DATABASE_MAP.get(intent["database"])
        entry = {
            "Name": intent.get("name", ""),
            "Status": intent.get("status", ""),
            "Priority": intent.get("priority", "")
        }

        if intent["action"] == "create":
            return {"command": "create_database_entry", "payload": {"database_id": db_id, "entry": entry}}

        if intent["action"] == "update":
            return {"command": "update_database_entry",
                    "payload": {"page_id": None, "entry": entry}}

        return {"command": None, "payload": {}}

    ###################################################################
    # ERROR ENGINE
    ###################################################################
    def apply_error_engine(self, command):

        if command["command"] == "delete_page":
            command["error_engine"] = (
                {"errors": []}
                if command["payload"].get("name")
                else {"errors": ["Missing name for delete_page"]}
            )
            return command

        if command["command"] in ["query_all", "link_records"]:
            command["error_engine"] = {"errors": []}
            return command

        entry = command["payload"].get("entry", {})
        db = command["payload"].get("database_id")

        errors = []
        warnings = []
        auto = {}

        if db is None:
            command["error_engine"] = {"errors": ["Unknown database."]}
            return command

        if entry.get("Name", "").strip() == "":
            entry["Name"] = "Untitled"
            auto["Name"] = "Untitled"
            warnings.append("Auto-filled Name")

        if entry.get("Status", "").strip() == "":
            entry["Status"] = "To Do"
            auto["Status"] = "To Do"

        if entry.get("Priority", "").strip() == "":
            entry["Priority"] = "Medium"
            auto["Priority"] = "Medium"

        command["payload"]["entry"] = entry
        command["error_engine"] = {"errors": errors, "warnings": warnings, "auto": auto}
        return command

    ###################################################################
    # MASTER ENTRYPOINT — HYBRID ROUTER
    ###################################################################
    def process_ceo_instruction(self, text: str):

        lower = text.lower().strip()

        # 1) PERSONALITY MODE
        if (
            "nauči ovo o meni" in lower or
            "nauci ovo o meni" in lower or
            "zapamti ovo o meni" in lower
        ):
            learn = self.personality_engine.learn_from_text(text)
            system_response = "Zabilježio sam novu informaciju o tebi." if learn.get("stored") else "Već imam ovu informaciju."
            return {
                "command": None,
                "payload": {},
                "personality_update": learn,
                "error_engine": {"errors": []},
                "system_response": system_response,
                "local_only": True
            }

        # 2) BUSINESS MODE
        if self.is_business_message(lower):
            return self._process_business_instruction(text)

        # 3) CHAT MODE (default)
        return self.chat_response(text)

    ###################################################################
    # BUSINESS PIPELINE WRAPPER
    ###################################################################
    def _process_business_instruction(self, text: str):

        intent = self.detect_intent(text)
        command = self.build_command(intent)

        # add layers
        command["trust"] = self.trust_layer.evaluate(text)
        command["static_memory"] = self.static_memory_engine.apply(text)

        if command.get("payload") and "entry" in command["payload"]:
            command["dynamic_memory"] = self.dynamic_memory_engine.evaluate(text, command)
        else:
            command["dynamic_memory"] = None

        # errors
        command = self.apply_error_engine(command)
        if command["error_engine"]["errors"]:
            command["system_response"] = "Nisam mogao izvršiti zbog greške."
            return command

        # memory save
        if "entry" in command.get("payload", {}):
            title = command["payload"]["entry"]["Name"]
            if title:
                self.dynamic_memory_engine.add_task(title)
                self.session_memory["dynamic_memory"] = copy.deepcopy(self.dynamic_memory_engine.memory)
                self._save_memory()

        command["system_response"] = natural_response(command)
        return command

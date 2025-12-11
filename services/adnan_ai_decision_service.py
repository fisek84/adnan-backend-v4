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


BASE_PATH = Path(__file__).resolve().parent.parent / "adnan_ai"
MEMORY_FILE = BASE_PATH / "memory.json"


###################################################################
# EXTENDED DATABASE + RELATION MAP
###################################################################
DATABASE_MAP = {
    "task": "2ad5873bd84a80e8b4dac703018212fe",
    "tasks": "2ad5873bd84a80e8b4dac703018212fe",

    "goal": "2ac5873bd84a801f956fc30327b8ef94",
    "goals": "2ac5873bd84a801f956fc30327b8ef94",
    "cilj": "2ac5873bd84a801f956fc30327b8ef94",
    "ciljevi": "2ac5873bd84a801f956fc30327b8ef94",
    "objective": "2ac5873bd84a801f956fc30327b8ef94",

    "subgoal": "2ac5873bd84a801f956fc30327b8ef94",
    "podcilj": "2ac5873bd84a801f956fc30327b8ef94",
    "podciljevi": "2ac5873bd84a801f956fc30327b8ef94",

    "project": "2ac5873bd84a8004aac0ea9c53025bfc",
    "projects": "2ac5873bd84a8004aac0ea9c53025bfc",

    "note": "2b75873bd84a80619330eb45348dd90e",
    "notes": "2b75873bd84a80619330eb45348dd90e",

    "weekly summary": "2b75873bd84a80619330eb45348dd90e",

    "kpi": "2bd5873bd84a80b68889df5485567703",

    # SOP DATABASES
    "outreach sop": "2c35873bd84a809ab4bcd6a0e0908f0b",
    "qualification sop": "2c35873bd84a80db8d37f71470424185",
    "follow up sop": "2c35873bd84a80908941d4d1eb29ae17",
    "fsc sop": "2c35873bd84a80c7a5c0c21dcb765c1b",
    "flp ops sop": "2c35873bd84a8047b63bea50e5f78090",
    "lss sop": "2c35873bd84a80c3ba85c66344fc98d4",
    "partner activation sop": "2c35873bd84a808793edf056ad0c1a1f",
    "partner performance sop": "2c35873bd84a80b4a27ad85c42560287",
    "partner leadership sop": "2c35873bd84a80c6bbafcc6d3a5a5d3a",
    "customer onboarding sop": "2c35873bd84a80f088abdc26d47fe551",
    "customer retention sop": "2c35873bd84a80109336c02496f100b3",
    "customer performance sop": "2c35873bd84a80708e8fcd3bf1d0132a",
    "partner potential sop": "2c35873bd84a80cbb885c2d22d4a0ee0",
    "sales closing sop": "2c35873bd84a80a8beb8eb61fb730dcc",
}


###################################################################
# ACTION PATTERNS
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
    result, score, _ = process.extractOne(value, choices, scorer=fuzz.partial_ratio)
    return result if score >= threshold else None


def fuzzy_extract_name(text):
    text_low = text.lower()
    cleaned = (
        text_low.replace("kreiraj", "")
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
# RESPONSE LAYER
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
# MAIN CLASS
###################################################################
class AdnanAIDecisionService:

    def __init__(self):
        self.identity = self._load("identity.json")
        self.kernel = self._load("kernel.json")
        self.mode = self._load("mode.json")
        self.state = self._load("state.json")
        self.decision_engine = self._load("decision_engine.json")
        self.static_memory = self._load("static_memory.json")

        self.autocorrect_engine = AutocorrectEngine()
        self.trust_layer = TrustLayer()
        self.sop_mapper = SOPMapper()
        self.static_memory_engine = StaticMemoryEngine(self.static_memory)
        self.session_memory = self._init_session_memory()
        self.dynamic_memory_engine = DynamicMemoryEngine(self.session_memory)

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
    # INTENT DETECTION
    ###################################################################
    def detect_intent(self, text: str):

        t = text.lower()

        #############################
        # ACTION (FUZZY)
        #############################
        action = None
        for act, patterns in ACTION_PATTERNS.items():
            if fuzzy_match(t, patterns, 70):
                action = act
                break

        #############################
        # DATABASE (FUZZY)
        #############################
        db_guess = fuzzy_match(t, list(DATABASE_MAP.keys()), 70)

        #############################
        # NAME EXTRACTION (FUZZY)
        #############################
        name = ""

        patterns = [
            r"(ime|title|naziv)\s*[-:]\s*(.+)",
            r"(task|goal|project|note|subgoal)\s*[-:]\s*(.+)",
            r"(task|goal|project|note|subgoal)\s+([A-Za-z0-9_\-\s]+)$"
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                name = m.group(len(m.groups()))
                break

        if not name:
            name = fuzzy_extract_name(text)

        #############################
        # STATUS
        #############################
        status = ""
        m = re.search(r"status\s*[-:]\s*([\w ]+)", text, re.IGNORECASE)
        if m:
            status = m.group(1).strip()

        #############################
        # PRIORITY
        #############################
        priority = ""
        m = re.search(r"(priority|prioritet)\s*[-:]\s*([\w ]+)", text, re.IGNORECASE)
        if m:
            priority = m.group(2).strip()

        #############################
        # LINK RELATIONS (FUZZY)
        #############################
        parent = None
        child = None

        link_match = re.search(
            r"(task|goal|project|subgoal|podcilj)\s+(.+?)\s+.*?(na|u|pod|to)\s+(goal|cilj|project|task|subgoal)\s+(.+)",
            text, re.IGNORECASE
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

    ###################################################################
    # COMMAND BUILDER
    ###################################################################
    def build_command(self, intent):

        # LINK
        if intent["action"] == "link":
            return {
                "command": "link_records",
                "payload": {
                    "parent_name": intent["parent"],
                    "child_name": intent["child"]
                }
            }

        # DELETE
        if intent["action"] == "delete":
            return {
                "command": "delete_page",
                "payload": {"name": intent.get("name")}
            }

        # QUERY ALL
        if intent["action"] == "query" and "all" in intent["raw_text"].lower():
            return {
                "command": "query_all",
                "payload": {}
            }

        # QUERY DB
        if intent["action"] == "query":
            db_id = DATABASE_MAP.get(intent["database"])
            return {
                "command": "query_database",
                "payload": {"database_id": db_id}
            }

        db_id = DATABASE_MAP.get(intent["database"])
        entry = {
            "Name": intent.get("name", ""),
            "Status": intent.get("status", ""),
            "Priority": intent.get("priority", "")
        }

        # CREATE
        if intent["action"] == "create":
            return {
                "command": "create_database_entry",
                "payload": {"database_id": db_id, "entry": entry}
            }

        # UPDATE
        if intent["action"] == "update":
            return {
                "command": "update_database_entry",
                "payload": {"page_id": None, "entry": entry}
            }

        return {"command": None, "payload": {}}

    ###################################################################
    # ERROR ENGINE
    ###################################################################
    def apply_error_engine(self, command):

        if command["command"] == "delete_page":
            if not command["payload"].get("name"):
                command["error_engine"] = {"errors": ["Missing name for delete"]}

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
            errors.append("Unknown database.")
            command["error_engine"] = {"errors": errors}
            return command

        if entry.get("Name", "").strip() == "":
            entry["Name"] = "Untitled"
            auto["Name"] = "Untitled"
            warnings.append("Name auto-set to Untitled")

        if entry.get("Status", "").strip() == "":
            entry["Status"] = "To Do"
            auto["Status"] = "To Do"

        if entry.get("Priority", "").strip() == "":
            entry["Priority"] = "Medium"
            auto["Priority"] = "Medium"

        command["payload"]["entry"] = entry
        command["error_engine"] = {
            "errors": errors,
            "warnings": warnings,
            "auto": auto
        }
        return command

    ###################################################################
    # ENTRYPOINT
    ###################################################################
    def process_ceo_instruction(self, text: str):

        intent = self.detect_intent(text)

        command = self.build_command(intent)

        # Add trust + memory layers
        command["trust"] = self.trust_layer.evaluate(text)
        command["static_memory"] = self.static_memory_engine.apply(text)
        # Skip dynamic memory for commands without entry (delete, link, query)
        if command.get("payload") and "entry" in command["payload"]:
            command["dynamic_memory"] = self.dynamic_memory_engine.evaluate(text, command)
        else:
            command["dynamic_memory"] = None


        # Validate
        command = self.apply_error_engine(command)
        if command["error_engine"]["errors"]:
            command["system_response"] = "Nisam mogao izvršiti zbog greške."
            return command

        # Save memory for created tasks
        if "entry" in command["payload"]:
            title = command["payload"]["entry"].get("Name")
            if title:
                self.dynamic_memory_engine.add_task(title)
                self.session_memory["dynamic_memory"] = copy.deepcopy(self.dynamic_memory_engine.memory)
                self._save_memory()

        command["system_response"] = natural_response(command)
        return command

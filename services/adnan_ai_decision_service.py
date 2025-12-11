import json
from pathlib import Path
import re
import copy

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

    "kpi": "2bd5873bd84a80b68889df5485567703"
}


RELATION_FIELDS = {
    "goal→subgoal": "Subgoals",
    "subgoal→goal": "Parent Goal",
    "goal→task": "Tasks",
    "task→goal": "Goal",
    "project→task": "Tasks",
    "task→project": "Project",
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
# NATURAL SYSTEM RESPONSE
###################################################################
def natural_response(cmd):
    if cmd.get("blocked"):
        return cmd.get("system_response", "Potrebna je potvrda.")
    return {
        "create_database_entry": "Kreiram novi zapis.",
        "update_database_entry": "Ažuriram zapis.",
        "delete_page": "Brišem zapis.",
        "query_database": "Prikupljam podatke.",
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
    # INTENT ENGINE (Advanced NL Interpreter)
    ###################################################################
    def detect_intent(self, text: str):
        t = text.lower()

        # Detect action
        action = None
        for act, patterns in ACTION_PATTERNS.items():
            if any(re.search(p, t) for p in patterns):
                action = act
                break

        # Detect database
        db_guess = None
        for db in DATABASE_MAP.keys():
            if db in t:
                db_guess = db
                break

        # Extract name (robust)
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
            first_line = text.strip().split("\n")[0]
            name = (
                first_line.replace("kreiraj", "")
                          .replace("napravi", "")
                          .replace("dodaj", "")
                          .replace("task", "")
                          .strip()
            )

        # Status
        status = ""
        m = re.search(r"status\s*[-:]\s*([\w ]+)", text, re.IGNORECASE)
        if m:
            status = m.group(1).strip()

        # Priority
        priority = ""
        m = re.search(r"(priority|prioritet)\s*[-:]\s*([\w ]+)", text, re.IGNORECASE)
        if m:
            priority = m.group(2).strip()

        # For linking: detect sentence patterns like:
        # "povezi task Majmun na cilj Prodaja"
        parent = None
        child = None
        link_match = re.search(
            r"(task|goal|project|podcilj|subgoal)\s+(.+?)\s+.*?(na|u|pod|to)\s+(goal|cilj|project|task)\s+(.+)",
            text, re.IGNORECASE
        )
        if link_match:
            child = link_match.group(2).strip()
            parent = link_match.group(5).strip()

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

        # LINKING MODE
        if intent["action"] == "link":
            return {
                "command": "link_records",
                "payload": {
                    "parent_name": intent["parent"],
                    "child_name": intent["child"]
                }
            }

        db_id = DATABASE_MAP.get(intent["database"])

        entry = {
            "Name": intent.get("name", ""),
            "Status": intent.get("status", ""),
            "Priority": intent.get("priority", "")
        }

        if intent["action"] == "create":
            return {
                "command": "create_database_entry",
                "payload": {"database_id": db_id, "entry": entry}
            }

        if intent["action"] == "update":
            return {
                "command": "update_database_entry",
                "payload": {"page_id": None, "entry": entry}
            }

        if intent["action"] == "delete":
            return {
                "command": "delete_page",
                "payload": {"name": intent.get("name")}
            }

        if intent["action"] == "query":
            return {
                "command": "query_database",
                "payload": {"database_id": db_id}
            }

        return {"command": None, "payload": {}}


    ###################################################################
    # ERROR ENGINE (auto defaults)
    ###################################################################
    def apply_error_engine(self, command):

        if command["command"] == "link_records":
            return command

        entry = command["payload"].get("entry", {})
        db = command["payload"].get("database_id")

        errors = []
        warnings = []
        auto = {}

        if command["command"] == "delete_page":
            if not command["payload"].get("name"):
                errors.append({"type": "c", "msg": "Name missing"})
            command["error_engine"] = {"errors": errors}
            return command

        if db is None:
            errors.append({"type": "critical_error", "msg": "Unknown database"})
            command["error_engine"] = {"errors": errors}
            return command

        if entry.get("Name", "").strip() == "":
            entry["Name"] = "Untitled"
            warnings.append({"msg": "Name auto-set"})
            auto["Name"] = "Untitled"

        if entry.get("Status", "").strip() == "":
            entry["Status"] = "To Do"
            warnings.append({"msg": "Status auto-set"})
            auto["Status"] = "To Do"

        if entry.get("Priority", "").strip() == "":
            entry["Priority"] = "Medium"
            warnings.append({"msg": "Priority auto-set"})
            auto["Priority"] = "Medium"

        command["payload"]["entry"] = entry
        command["error_engine"] = {"errors": errors, "warnings": warnings, "auto": auto}
        return command


    ###################################################################
    # ENTRYPOINT
    ###################################################################
    def process_ceo_instruction(self, text: str):

        intent = self.detect_intent(text)

        # Build command
        command = self.build_command(intent)

        # Add Trust + Memory
        command["trust"] = self.trust_layer.evaluate(text)
        command["static_memory"] = self.static_memory_engine.apply(text)
        command["dynamic_memory"] = self.dynamic_memory_engine.evaluate(text, command)

        # Error engine
        command = self.apply_error_engine(command)
        if command["error_engine"]["errors"]:
            command["system_response"] = "Nisam mogao izvršiti zbog greške."
            return command

        # Save dynamic memory
        if "entry" in command["payload"]:
            title = command["payload"]["entry"].get("Name")
            if title:
                self.dynamic_memory_engine.add_task(title)
                self.session_memory["dynamic_memory"] = copy.deepcopy(self.dynamic_memory_engine.memory)
                self._save_memory()

        # Response
        command["system_response"] = natural_response(command)
        return command

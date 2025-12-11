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
# EXTENDED DATABASE MAP (full workspace)
###################################################################
DATABASE_MAP = {
    "task": "2ad5873bd84a80e8b4dac703018212fe",
    "tasks": "2ad5873bd84a80e8b4dac703018212fe",

    "goal": "2ac5873bd84a801f956fc30327b8ef94",
    "goals": "2ac5873bd84a801f956fc30327b8ef94",

    "project": "2ac5873bd84a8004aac0ea9c53025bfc",
    "projects": "2ac5873bd84a8004aac0ea9c53025bfc",

    "note": "2b75873bd84a80619330eb45348dd90e",
    "notes": "2b75873bd84a80619330eb45348dd90e",
    "weekly summary": "2b75873bd84a80619330eb45348dd90e",

    "kpi": "2bd5873bd84a80b68889df5485567703"
}


###################################################################
# NATURAL LANGUAGE → INTENT
###################################################################
ACTION_PATTERNS = {
    "create": [r"kreiraj", r"napravi", r"create", r"add", r"dodaj", r"postavi"],
    "update": [r"update", r"izmijeni", r"promijeni", r"uredi", r"postavi status"],
    "query":  [r"prikaži", r"listaj", r"show", r"get", r"query", r"pokaži"]
}


###################################################################
# RESPONSE LAYER — prirodni jezik
###################################################################
def natural_response(command):
    if command.get("blocked"):
        if command["reason"] == "confirmation_required":
            return f"Treba mi potvrda: {command['question']}"
        return "Nisam mogao izvršiti zadatak zbog kritične greške."

    cmd = command.get("command")

    if cmd == "create_database_entry":
        return "Kreiram novi zapis u Notion bazi."

    if cmd == "update_database_entry":
        return "Ažuriram postojeći zapis u Notionu."

    if cmd == "query_database":
        return "Dohvaćam podatke iz Notion baze."

    return "Izvršavam tvoj zahtjev."


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
    # MEMORY LOADERS
    ###################################################################
    def _init_session_memory(self):
        if MEMORY_FILE.exists():
            return json.load(open(MEMORY_FILE, "r", encoding="utf-8-sig"))

        base = {
            "last_mode": None,
            "last_state": None,
            "trace": [],
            "notes": [],
            "dynamic_memory": {"tasks": []},
            "agent_memory": []
        }
        json.dump(base, open(MEMORY_FILE, "w", encoding="utf-8"), indent=2)
        return base


    def _load(self, filename: str):
        return json.load(open(BASE_PATH / filename, "r", encoding="utf-8-sig"))


    def _save_memory(self):
        json.dump(self.session_memory, open(MEMORY_FILE, "w", encoding="utf-8"), indent=2)


    ###################################################################
    # DOMAIN-AWARE INTENT DETECTION (Bosnian + English)
    ###################################################################
    def detect_intent(self, text: str):

        text_low = text.lower()

        # 1) Detect action
        action = None
        for act, patterns in ACTION_PATTERNS.items():
            for p in patterns:
                if re.search(p, text_low):
                    action = act
                    break

        # 2) Detect database (domain-aware)
        db_guess = None
        for db in DATABASE_MAP.keys():
            if db in text_low:
                db_guess = db
                break

        # 2b) Fallback domain rules
        if not db_guess:
            if "kpi" in text_low:
                db_guess = "kpi"
            elif "rezime" in text_low or "summary" in text_low:
                db_guess = "weekly summary"
            elif "zabilježi" in text_low or "note" in text_low:
                db_guess = "notes"

        # 3) Extract structured fields
        name = ""
        status = ""
        priority = ""

        name_match = re.search(r"(ime|title|naziv)\s*[-:]\s*(.+)", text, re.IGNORECASE)
        if name_match:
            name = name_match.group(2).strip()

        status_match = re.search(r"(status)\s*[-:]\s*([\w ]+)", text, re.IGNORECASE)
        if status_match:
            status = status_match.group(2).strip()

        prio_match = re.search(r"(priority|prioritet)\s*[-:]\s*([\w ]+)", text, re.IGNORECASE)
        if prio_match:
            priority = prio_match.group(2).strip()

        # 4) HARD CONFIRM MODE
        if action == "create" and not db_guess:
            return {
                "needs_confirmation": True,
                "question": "U koju Notion bazu želiš da kreiram ovaj zapis?",
                "missing": "database"
            }

        if not action:
            return {
                "needs_confirmation": True,
                "question": "Da li želiš da kreiram, ažuriram ili prikažem podatke?",
                "missing": "action"
            }

        return {
            "action": action,
            "database": db_guess,
            "name": name,
            "status": status,
            "priority": priority,
            "needs_confirmation": False
        }


    ###################################################################
    # COMMAND BUILDER
    ###################################################################
    def build_command(self, intent):
        db_id = DATABASE_MAP.get(intent.get("database"))

        entry = {
            "Name": intent.get("name", ""),
            "Status": intent.get("status", ""),
            "Priority": intent.get("priority", "")
        }

        if intent["action"] == "create":
            return {
                "command": "create_database_entry",
                "payload": {
                    "database_id": db_id,
                    "entry": entry
                }
            }

        if intent["action"] == "update":
            return {
                "command": "update_database_entry",
                "payload": {
                    "page_id": None,
                    "entry": entry
                }
            }

        if intent["action"] == "query":
            return {
                "command": "query_database",
                "payload": {
                    "database_id": db_id
                }
            }

        return {"command": None, "payload": {}}


    ###################################################################
    # ERROR ENGINE (auto-fixing)
    ###################################################################
    def apply_error_engine(self, command):
        entry = command["payload"].get("entry", {})
        db = command["payload"].get("database_id")

        errors = []
        warnings = []
        auto = {}

        if db is None:
            errors.append({
                "type": "critical_error",
                "field": "database",
                "message": "Unknown database name provided."
            })
            command["error_engine"] = {"errors": errors, "warnings": warnings}
            return command

        if entry.get("Name", "").strip() == "":
            entry["Name"] = "Untitled"
            auto["Name"] = "Untitled"
            warnings.append({"field": "Name", "message": "Missing → auto 'Untitled'"})

        if entry.get("Status", "").strip() == "":
            entry["Status"] = "To Do"
            auto["Status"] = "To Do"
            warnings.append({"field": "Status", "message": "Missing → auto 'To Do'"})

        if entry.get("Priority", "").strip() == "":
            entry["Priority"] = "Medium"
            auto["Priority"] = "Medium"
            warnings.append({"field": "Priority", "message": "Missing → auto 'Medium'"})

        command["payload"]["entry"] = entry
        command["error_engine"] = {"errors": errors, "warnings": warnings, "auto": auto}

        return command


    ###################################################################
    # ENTRYPOINT
    ###################################################################
    def process_ceo_instruction(self, text: str):

        intent = self.detect_intent(text)

        # 1) Hard Confirm Mode
        if intent.get("needs_confirmation"):
            return {
                "success": False,
                "blocked": True,
                "reason": "confirmation_required",
                "question": intent["question"],
                "system_response": intent["question"]
            }

        # 2) Build command
        command = self.build_command(intent)

        # 3) Trust + Memory layers
        command["trust"] = self.trust_layer.evaluate(text)
        command["static_memory"] = self.static_memory_engine.apply(text)
        command["dynamic_memory"] = self.dynamic_memory_engine.evaluate(text, command)

        # 4) Error Engine
        command = self.apply_error_engine(command)
        if command["error_engine"]["errors"]:
            command["system_response"] = "Nisam mogao izvršiti zbog kritične greške."
            return command

        # 5) Add to dynamic memory
        if "entry" in command["payload"]:
            title = command["payload"]["entry"].get("Name")
            if title:
                self.dynamic_memory_engine.add_task(title)
                self.session_memory["dynamic_memory"] = copy.deepcopy(self.dynamic_memory_engine.memory)
                self._save_memory()

        # 6) Natural language response
        command["system_response"] = natural_response(command)

        return command

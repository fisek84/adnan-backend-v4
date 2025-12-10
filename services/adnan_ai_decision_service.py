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

# DYNAMIC MEMORY D1 (correct)
from services.decision_engine.dynamic_memory import DynamicMemoryEngine


BASE_PATH = Path(__file__).resolve().parent.parent / "adnan_ai"
MEMORY_FILE = BASE_PATH / "memory.json"


###################################################################
# FULL DATABASE MAP
###################################################################
DATABASE_MAP = {
    "tasks": "2ad5873bd84a80e8b4dac703018212fe",
    "goals": "2ac5873bd84a801f956fc30327b8ef94",
    "projects": "2ac5873bd84a8004aac0ea9c53025bfc",
    "agent exchange": "2b45873bd84a80169f7fceffd8405fef",
    "active goals": "2b75873bd84a807081c9d5b9a068f9d6",
    "completed goals": "2b75873bd84a806ba853cbde32e0f849",
    "blocked goals": "2b75873bd84a80ab85a9ec90ca34fb02",
    "kpi": "2bd5873bd84a80b68889df5485567703",
    "flp": "2bd5873bd84a80d3b9c9dceeaba651e8",
    "lead": "2bb5873bd84a8095aac1f68b5d60ccf9",
    "weekly summary": "2b75873bd84a80619330eb45348dd90e",
    "agent projects": "2b45873bd84a80b3b06dd578c8c5d664",
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
    "sales closing sop": "2c35873bd84a80a8beb8eb61fb730dcc"
}


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

        # INIT MODULES
        self.autocorrect_engine = AutocorrectEngine()
        self.trust_layer = TrustLayer()
        self.sop_mapper = SOPMapper()
        self.static_memory_engine = StaticMemoryEngine(self.static_memory)

        # SESSION MEMORY INIT
        self.session_memory = self._init_session_memory()

        # D1 ENGINE
        self.dynamic_memory_engine = DynamicMemoryEngine(self.session_memory)


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
    # CEO PARSER
    ###################################################################
    def from_ceo_to_command(self, text: str) -> dict:

        db_match = re.search(r"u (.*?) bazi", text, re.IGNORECASE)
        title_match = re.search(r"bazi: (.*?)(?:\. Status:|\. Prioritet:|\.)", text, re.IGNORECASE)
        status_match = re.search(r"Status: ([\w ]]+)", text, re.IGNORECASE)
        priority_match = re.search(r"Priority: ([\w ]]+)", text, re.IGNORECASE)

        db_name = db_match.group(1).strip().lower() if db_match else None

        # SOP INTELLIGENCE
        sop_db = self.sop_mapper.resolve_sop(text)
        if sop_db:
            db_name = sop_db

        # AUTOCORRECT
        autocorrect_info = None
        if db_name:
            autocorrect_info = self.autocorrect_engine.autocorrect(db_name)
            db_name = autocorrect_info["corrected"]

        title = title_match.group(1).strip() if title_match else ""
        status = status_match.group(1).strip() if status_match else ""
        priority = priority_match.group(1).strip() if priority_match else ""

        return {
            "command": "create_database_entry",
            "payload": {
                "database_id": DATABASE_MAP.get(db_name),
                "entry": {
                    "Name": title,
                    "Status": status,
                    "Priority": priority
                }
            },
            "autocorrect": autocorrect_info,
            "sop_detected": sop_db
        }


    ###################################################################
    # TRUST LAYER
    ###################################################################
    def apply_trust_layer(self, text: str) -> dict:
        return self.trust_layer.evaluate(text)


    ###################################################################
    # STATIC MEMORY (M1)
    ###################################################################
    def apply_static_memory(self, text: str) -> dict:
        return self.static_memory_engine.apply(text)


    ###################################################################
    # ERROR ENGINE
    ###################################################################
    def apply_error_engine(self, command: dict) -> dict:

        entry = command["payload"]["entry"]
        db = command["payload"]["database_id"]

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
            command["autocorrected"] = False
            return command

        if entry["Name"].strip() == "":
            warnings.append({
                "type": "validation_error",
                "field": "Name",
                "message": "Title missing → auto-set to 'Untitled'."
            })
            entry["Name"] = "Untitled"
            auto["Name"] = "Untitled"

        if entry["Status"].strip() == "":
            warnings.append({
                "type": "validation_error",
                "field": "Status",
                "message": "Missing status → auto-default = 'To Do'."
            })
            entry["Status"] = "To Do"
            auto["Status"] = "To Do"

        if entry["Priority"].strip() == "":
            warnings.append({
                "type": "validation_error",
                "field": "Priority",
                "message": "Missing priority → auto-default = 'Medium'."
            })
            entry["Priority"] = "Medium"
            auto["Priority"] = "Medium"

        command["payload"]["entry"] = entry
        command["autocorrected"] = True
        command["error_engine"] = {
            "errors": errors,
            "warnings": warnings,
            "auto_corrected_fields": auto
        }
        return command


    ###################################################################
    # SCORING
    ###################################################################
    def evaluate_alignment(self, title: str) -> float:
        rules = self.decision_engine["decision_engine"]["scoring"]["alignment_rules"]
        score = 0
        for kw in rules["strategic_keywords"]:
            if kw in title.lower():
                score += 0.2
        return min(score, 1.0)


    def map_priority(self, p):
        return self.decision_engine["decision_engine"]["scoring"]["priority_map"].get(p, 0.5)


    def map_urgency(self, s):
        return self.decision_engine["decision_engine"]["scoring"]["urgency_rules"].get(s, 0.5)


    def calculate_score(self, entry: dict) -> float:
        w = self.decision_engine["decision_engine"]["scoring"]["weights"]
        score = (
            self.evaluate_alignment(entry["Name"]) * w["goals_alignment"] +
            self.map_urgency(entry["Status"]) * w["urgency"] +
            self.map_priority(entry["Priority"]) * w["priority_field"]
        )
        return round(min(max(score, 0), 1), 2)


    ###################################################################
    # BEHAVIORAL FILTERS
    ###################################################################
    def apply_behavioral_filters(self, command: dict) -> dict:
        entry = command["payload"]["entry"]
        rep = {"clarity": True, "simplicity": True, "mission_alignment": True, "issues": []}

        if len(entry["Name"]) < 3:
            rep["clarity"] = False
            rep["issues"].append("Title too short")

        if " and " in entry["Name"].lower():
            rep["simplicity"] = False
            rep["issues"].append("Multiple actions in one task")

        if command["score"] < 0.4:
            rep["mission_alignment"] = False
            rep["issues"].append("Low mission score")

        command["behavioral_filters"] = rep
        return command


    ###################################################################
    # AUDIT
    ###################################################################
    def audit_decision(self, command: dict) -> dict:
        audit = {"structural_ok": True, "strategic_ok": True, "issues": []}

        entry = command["payload"]["entry"]

        if entry["Name"] == "" or entry["Status"] == "" or entry["Priority"] == "":
            audit["structural_ok"] = False
            audit["issues"].append("Missing required fields")

        if command.get("score", 0) < 0.3:
            audit["strategic_ok"] = False
            audit["issues"].append("Score < 0.3")

        command["audit"] = audit
        return command


    ###################################################################
    # MAIN PIPELINE
    ###################################################################
    def decide_action(self, context: dict) -> dict:

        text = context["input"]

        # 1 – PARSE
        cmd = self.from_ceo_to_command(text)

        # 2 – TRUST LAYER
        cmd["trust"] = self.apply_trust_layer(text)

        # 3 – STATIC MEMORY
        cmd["static_memory_influence"] = self.apply_static_memory(text)

        # 4 – DYNAMIC MEMORY (duplicate check)
        d1 = self.dynamic_memory_engine.evaluate(text, cmd)
        cmd["dynamic_memory"] = d1

        if d1["duplicate_exists"]:
            cmd.setdefault("error_engine", {"errors": [], "warnings": []})
            cmd["error_engine"]["errors"].append({
                "type": "duplicate_error",
                "message": "Task već postoji — kreiranje blokirano."
            })
            return cmd

        # 5 – ERROR ENGINE
        cmd = self.apply_error_engine(cmd)
        if cmd["error_engine"]["errors"]:
            return cmd

        # 6 – SCORING
        cmd["score"] = self.calculate_score(cmd["payload"]["entry"])

        # 7 – BEHAVIORAL FILTERS
        cmd = self.apply_behavioral_filters(cmd)

        return cmd


    ###################################################################
    # ENTRYPOINT
    ###################################################################
    def process_ceo_instruction(self, text: str):

        context = {
            "input": text,
            "static_memory": self.static_memory,
            "dynamic_memory": self.session_memory.get("dynamic_memory", {}),
            "agent_memory": self.session_memory.get("agent_memory", [])
        }

        decision = self.decide_action(context)
        decision = self.audit_decision(decision)

        # Add to dynamic memory only if NO critical errors
        if "error_engine" in decision and not decision["error_engine"]["errors"]:
            title = decision["payload"]["entry"]["Name"]
            self.dynamic_memory_engine.add_task(title)

        # persist
        self.session_memory["dynamic_memory"] = copy.deepcopy(self.dynamic_memory_engine.memory)
        self._save_memory()

        return decision

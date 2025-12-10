import json
from pathlib import Path

# Correct absolute path inside Render Docker image
BASE_PATH = Path(__file__).resolve().parent / "adnan_ai"
MEMORY_FILE = BASE_PATH / "memory.json"


class AdnanAIDecisionService:
    def __init__(self):
        self.identity = self._load("identity.json")
        self.kernel = self._load("kernel.json")
        self.mode = self._load("mode.json")
        self.state = self._load("state.json")
        self.decision_engine = self._load("decision_engine.json")

        # ---------------------------
        # LOAD PERSISTENT MEMORY
        # ---------------------------
        if MEMORY_FILE.exists():
            with open(MEMORY_FILE, "r", encoding="utf-8-sig") as f:
                self.session_memory = json.load(f)
        else:
            self.session_memory = {
                "last_mode": None,
                "last_state": None,
                "trace": [],
                "notes": []
            }
            self._save_memory()

    def _save_memory(self):
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.session_memory, f, ensure_ascii=False, indent=2)

    def _load(self, filename: str):
        path = BASE_PATH / filename
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)

    def align(self, user_input: str) -> dict:
        return {
            "mode": self.mode.get("current_mode"),
            "state": self.state.get("current_state"),
            "directives": self.decision_engine.get("directives", []),
            "input": user_input,
        }

    def process(self, user_input: str) -> dict:
        directives = []
        mode_switch = None

        memory_flag = False
        memory_keywords = ["zapamti", "zapisi", "remember", "save note"]
        if any(k.lower() in user_input.lower() for k in memory_keywords):
            memory_flag = True

        engine_rules = self.decision_engine.get("rules", [])

        for rule in engine_rules:
            keywords = rule.get("keywords", [])
            if any(kw.lower() in user_input.lower() for kw in keywords):
                directives.append(rule.get("action"))
                if "set_mode" in rule:
                    mode_switch = rule["set_mode"]

        new_mode = self.mode.get("current_mode")
        if mode_switch:
            new_mode = mode_switch
            self.mode["current_mode"] = new_mode

        snapshot = {
            "input": user_input,
            "mode": new_mode,
            "state": self.state.get("current_state"),
            "directives": directives,
            "kernel": self.kernel.get("core_directives", []),
            "memory_flag": memory_flag
        }

        snapshot = self.auto_transition(snapshot)
        self.update_memory(snapshot)
        snapshot["priority_context"] = self.prioritize(snapshot)

        memory_context = self.get_memory_context()
        snapshot["fusion_context"] = self.fuse(snapshot, memory_context)

        return snapshot

    def enforce(self, gpt_output: str, snapshot: dict) -> str:
        mode = snapshot.get("mode")
        directives = snapshot.get("directives", [])
        kernel_directives = snapshot.get("kernel", [])

        corrections = []

        if mode == "operational" and len(gpt_output) > 400:
            corrections.append("Odgovor treba biti kraći i operativan.")

        if mode == "strategic" and "vizija" not in gpt_output.lower():
            corrections.append("Dodaj strateški ugao i viziju.")

        if mode == "diagnostic" and "uzrok" not in gpt_output.lower():
            corrections.append("Dodaj uzrok i dijagnostički ugao.")

        if mode == "deep_clarity" and "jasno" not in gpt_output.lower():
            corrections.append("Dodaj maksimalnu jasnoću i dubinu objašnjenja.")

        for d in directives:
            if d and d.lower() not in gpt_output.lower():
                corrections.append(f"Nedostaje direktiva: {d}")

        for kd in kernel_directives:
            if kd and kd.lower() not in gpt_output.lower():
                corrections.append(f"Uskladi se sa kernel direktivom: {kd}")

        if not corrections:
            return gpt_output

        correction_note = "\n\n[Alignment Note]: " + " | ".join(corrections)
        return gpt_output + correction_note

    def refine(self, output: str, snapshot: dict) -> str:
        mode = snapshot.get("mode")

        if mode == "operational":
            lines = [l.strip() for l in output.split("\n") if l.strip()]
            if not lines:
                return output
            return "Operational Actions:\n- " + "\n- ".join(lines[:6])

        if mode == "strategic" and "Executive Summary" not in output:
            return (
                "Executive Summary:\n"
                "- Ključne strateške tačke navedene su u nastavku.\n\n"
                f"{output}"
            )

        if mode == "diagnostic":
            return (
                "Problem Analysis:\n"
                f"{output}\n\n"
                "Recommendation:\n"
                "- Identifikovati glavni uzrok i primijeniti korekcijske mjere."
            )

        if mode == "deep_clarity":
            return (
                "Deep Clarity Breakdown:\n"
                "1. Insight:\n"
                f"{output}\n\n"
                "2. Reasoning:\n"
                "- Razlozi i logika su eksplicitno izloženi u gornjem odgovoru.\n\n"
                "3. Conclusion:\n"
                "- Jasna odluka ili stav izvedeni iz analize."
            )

        return output

    def auto_transition(self, snapshot: dict) -> dict:
        current_mode = snapshot.get("mode")
        current_state = snapshot.get("state")
        directives = snapshot.get("directives", [])

        engine_rules = self.decision_engine.get("rules", [])

        for rule in engine_rules:
            action = rule.get("action")
            if action in directives:
                if "set_state" in rule:
                    new_state = rule["set_state"]
                    self.state["current_state"] = new_state
                    current_state = new_state

                if "set_mode" in rule:
                    new_mode = rule["set_mode"]
                    self.mode["current_mode"] = new_mode
                    current_mode = new_mode

        snapshot["mode"] = current_mode
        snapshot["state"] = current_state
        return snapshot

    def update_memory(self, snapshot: dict):
        self.session_memory["last_mode"] = snapshot.get("mode")
        self.session_memory["last_state"] = snapshot.get("state")

        trace_entry = {
            "input": snapshot.get("input"),
            "mode": snapshot.get("mode"),
            "state": snapshot.get("state"),
            "directives": snapshot.get("directives"),
        }

        self.session_memory["trace"].append(trace_entry)

        if snapshot.get("memory_flag"):
            self.session_memory["notes"].append(snapshot.get("input"))

        if len(self.session_memory["trace"]) > 20:
            self.session_memory["trace"].pop(0)

        # Save memory
        self._save_memory()

    def get_memory_context(self) -> dict:
        return {
            "last_mode": self.session_memory.get("last_mode"),
            "last_state": self.session_memory.get("last_state"),
            "trace": self.session_memory.get("trace", []),
            "notes": list(self.session_memory.get("notes", []))
        }

    def prioritize(self, snapshot: dict) -> dict:
        directives = snapshot.get("directives", [])
        kernel = snapshot.get("kernel", [])
        trace = self.session_memory.get("trace", [])

        priority_order = []
        high_impact = []
        high_risk = []

        for k in kernel:
            priority_order.append(k)
            high_impact.append(k)

        for d in directives:
            if d not in priority_order:
                priority_order.append(d)

        for t in trace:
            for td in (t.get("directives") or []):
                if td and td not in priority_order:
                    priority_order.append(td)

        return {
            "priority_order": priority_order,
            "high_impact_items": high_impact,
            "high_risk_items": high_risk,
        }

    def compress(self, output: str) -> str:
        lines = [l.strip() for l in output.split("\n") if l.strip()]

        seen = set()
        unique_lines = []
        for line in lines:
            if line not in seen:
                unique_lines.append(line)
                seen.add(line)

        if len(unique_lines) <= 5:
            return "\n".join(unique_lines)

        compressed = unique_lines[:5]
        return "\n".join(compressed)

    def executive_consistency(self, output: str, snapshot: dict) -> str:
        weak_phrases = [
            "možda", "pokušaću", "ukoliko je moguće",
            "pretpostavljam", "vjerovatno", "čini se da",
            "moglo bi biti", "eventualno"
        ]

        for phrase in weak_phrases:
            output = output.replace(phrase, "")

        if "Conclusion" not in output and "Zaključak" not in output:
            output += "\n\nConclusion:\n- Odluka je donesena na osnovu prioriteta, mode-a i state-a."

        return output

    def fuse(self, snapshot: dict, memory_context: dict) -> dict:
        mode = snapshot.get("mode")
        state = snapshot.get("state")
        directives = snapshot.get("directives", [])
        priority = snapshot.get("priority_context", {})

        last_mode = memory_context.get("last_mode")
        last_state = memory_context.get("last_state")
        trace = memory_context.get("trace", [])
        notes = memory_context.get("notes", [])

        recent_trace = trace[-3:] if len(trace) > 3 else trace

        fusion_score = {
            "mode_stability": 1.0 if mode == last_mode else 0.7,
            "state_stability": 1.0 if state == last_state else 0.6,
            "directive_intensity": min(len(directives) / 5, 1.0),
            "history_depth": min(len(recent_trace) / 3, 1.0),
        }

        return {
            "current_mode": mode,
            "current_state": state,
            "last_mode": last_mode,
            "last_state": last_state,
            "active_directives": directives,
            "recent_trace": recent_trace,
            "notes": notes,
            "priority_order": priority.get("priority_order", []),
            "fusion_score": fusion_score,
        }

    def fusion_guided(self, output: str, fusion_context: dict) -> str:
        score = fusion_context.get("fusion_score", {})

        mode_stab = score.get("mode_stability", 1)
        depth = score.get("history_depth", 1)
        intensity = score.get("directive_intensity", 1)

        if mode_stab < 0.8:
            lines = output.split("\n")
            output = "\n".join(lines[:5])

        if intensity > 0.7:
            output += "\n\n[Focus]: Prioritet je jasan. Egzekucija bez kašnjenja."

        if depth > 0.6:
            output += "\n[Continuity]: Usklađeno sa prethodnim odlukama."

        return output

    def assemble_output(self, gpt_output: str, snapshot: dict) -> str:
        step1 = self.enforce(gpt_output, snapshot)
        step2 = self.refine(step1, snapshot)
        step3 = self.compress(step2)
        step4 = self.executive_consistency(step3, snapshot)

        fusion_context = snapshot.get("fusion_context", {})
        step5 = self.fusion_guided(step4, fusion_context)

        notes = fusion_context.get("notes", [])
        if notes:
            step5 += "\n\nSession Memory Notes:\n- " + "\n- ".join(notes)
        else:
            step5 += "\n\nSession Memory Notes:\n- Nema zapisanih bilješki u ovoj sesiji."

        return step5

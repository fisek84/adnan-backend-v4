# services/memory_service.py

"""
Memory Service (Korak 9.1)

Ovaj servis upravlja STM → MTM → LTM memorijskim slojevima:
- STM: kratkoročna memorija (već postoji u decision_service, ali ovdje je konsolidujemo)
- MTM: srednjoročna memorija (2–7 dana)
- LTM: dugoročna memorija (trajna)

Svi podaci se čuvaju u:
    /adnan_ai/memory/mid_term.json
    /adnan_ai/memory/long_term.json
"""

import json
from pathlib import Path
from typing import Dict, Any, List


BASE_PATH = Path(__file__).resolve().parent.parent / "adnan_ai" / "memory"


class MemoryService:

    def __init__(self):
        # Kreiramo folder ako ne postoji
        BASE_PATH.mkdir(parents=True, exist_ok=True)

        self.mtm_file = BASE_PATH / "mid_term.json"
        self.ltm_file = BASE_PATH / "long_term.json"

        self.mid_term = self._load_json(self.mtm_file)
        self.long_term = self._load_json(self.ltm_file)

    # -------------------------------
    # Helper: Load JSON
    # -------------------------------
    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                return json.loads(content) if content else {}
        except:
            return {}

    # -------------------------------
    # Helper: Save JSON
    # -------------------------------
    def _save_json(self, path: Path, data: Dict[str, Any]):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    # --------------------------------------------------------
    # STM UPDATE — prima snapshot iz decision engine-a
    # --------------------------------------------------------
    def update_stm(self, snapshot: Dict[str, Any]):
        """
        Snapshot ima oblik:
        {
            input: "...",
            mode: "...",
            state: "...",
            directives: [...],
            priority_context: {...}
        }

        STM spremamo u MTM buffer.
        """

        entry = {
            "input": snapshot.get("input"),
            "mode": snapshot.get("mode"),
            "state": snapshot.get("state"),
            "directives": snapshot.get("directives"),
            "priority": snapshot.get("priority_context"),
        }

        # Dodaj u MTM buffer
        buffer: List[Dict[str, Any]] = self.mid_term.get("buffer", [])
        buffer.append(entry)

        # Ograniči buffer na max 50 stavki
        if len(buffer) > 50:
            buffer.pop(0)

        self.mid_term["buffer"] = buffer
        self._save_json(self.mtm_file, self.mid_term)

    # --------------------------------------------------------
    # MTM CONSOLIDATION — periodično sjedinjenje buffer → MTM
    # --------------------------------------------------------
    def consolidate_mtm(self):
        """
        Srednjoročna memorija se formira na osnovu STM buffera:
        - izvlače se najčešće direktive
        - izvlače se promjene stanja i moda
        - čuvaju se CEO preference (implicitne)
        """

        buffer: List[Dict[str, Any]] = self.mid_term.get("buffer", [])
        if not buffer:
            return

        directives_count = {}
        mode_count = {}
        state_count = {}

        for entry in buffer:
            # Count directives
            for d in entry.get("directives", []) or []:
                directives_count[d] = directives_count.get(d, 0) + 1

            # Mode frequency
            mode = entry.get("mode")
            if mode:
                mode_count[mode] = mode_count.get(mode, 0) + 1

            # State frequency
            state = entry.get("state")
            if state:
                state_count[state] = state_count.get(state, 0) + 1

        # Konsolidovana MTM memorija
        self.mid_term["directives_summary"] = directives_count
        self.mid_term["mode_summary"] = mode_count
        self.mid_term["state_summary"] = state_count

        self._save_json(self.mtm_file, self.mid_term)

    # --------------------------------------------------------
    # LTM LEARNING — dugoročna konsolidacija
    # --------------------------------------------------------
    def consolidate_ltm(self):
        """
        Long-Term Memory uči dugoročne obrasce:
        - dominantni mod
        - dominantni directives
        - najčešća AI ponašanja
        - trending projekti i teme (po input text-u)
        """

        mtm = self.mid_term

        # 1. Prebaci srednjoročne uvide u LTM
        self.long_term.setdefault("directives_history", [])
        self.long_term.setdefault("mode_history", [])
        self.long_term.setdefault("state_history", [])

        # Save summaries
        if "directives_summary" in mtm:
            self.long_term["directives_history"].append(mtm["directives_summary"])

        if "mode_summary" in mtm:
            self.long_term["mode_history"].append(mtm["mode_summary"])

        if "state_summary" in mtm:
            self.long_term["state_history"].append(mtm["state_summary"])

        # 2. Cleanup — držimo max 20 zapisa
        for key in ["directives_history", "mode_history", "state_history"]:
            if len(self.long_term[key]) > 20:
                self.long_term[key].pop(0)

        # 3. Save LTM
        self._save_json(self.ltm_file, self.long_term)


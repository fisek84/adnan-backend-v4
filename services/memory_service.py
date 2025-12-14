# services/memory_service.py

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional


BASE_PATH = Path(__file__).resolve().parent.parent / "adnan_ai" / "memory"


class MemoryService:
    """
    MemoryService — FAZA 12 (COMPLIANCE FREEZE)

    Pravila:
    - Jedan memory.json (kanonski)
    - Schema versioning (LOCKED)
    - Backward compatible load
    - Append-only za audit podatke
    - Execution piše, audit čita
    """

    # ============================================================
    # SCHEMA LOCK
    # ============================================================
    SCHEMA_VERSION = "1.0.0"  # 🔒 FAZA 12 LOCK — ne mijenja se bez migracije

    DECAY_HALF_LIFE_SECONDS = 60 * 60 * 24 * 30  # ~30 dana
    MIN_WEIGHT = 0.2

    def __init__(self):
        BASE_PATH.mkdir(parents=True, exist_ok=True)

        self.memory_file = BASE_PATH / "memory.json"
        self.memory = self._load()

        # --------------------------------------------------------
        # SCHEMA ENFORCEMENT (BACKWARD SAFE)
        # --------------------------------------------------------
        self.memory.setdefault("schema_version", self.SCHEMA_VERSION)

        self.memory.setdefault("entries", [])
        self.memory.setdefault("decision_outcomes", [])
        self.memory.setdefault("execution_stats", {})
        self.memory.setdefault("cross_sop_relations", {})

        # FAZA 3 / 4
        self.memory.setdefault("goals", [])
        self.memory.setdefault("plans", [])

        # FAZA 8
        self.memory.setdefault("active_decision", None)

        self._save()

    # ============================================================
    # INTERNALS
    # ============================================================
    def _load(self) -> Dict[str, Any]:
        if not self.memory_file.exists():
            return {}

        try:
            with open(self.memory_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                # backward compatibility
                if "schema_version" not in data:
                    data["schema_version"] = self.SCHEMA_VERSION
                return data
        except Exception:
            return {}

    def _save(self):
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(self.memory, f, indent=2, ensure_ascii=False)

    def _now(self) -> float:
        return time.time()

    def _decay_weight(self, timestamp: float) -> float:
        age = max(0.0, self._now() - timestamp)
        weight = 0.5 ** (age / self.DECAY_HALF_LIFE_SECONDS)
        return max(self.MIN_WEIGHT, round(weight, 4))

    # ============================================================
    # STM
    # ============================================================
    def process(self, user_input: str) -> Dict[str, Any]:
        self.memory["entries"].append({
            "text": user_input,
            "ts": self._now(),
        })

        if len(self.memory["entries"]) > 100:
            self.memory["entries"].pop(0)

        self._save()
        return {"stored": True, "count": len(self.memory["entries"])}

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.memory["entries"][-limit:]

    # ============================================================
    # FAZA 3 — GOALS
    # ============================================================
    def store_goal(self, goal: Dict[str, Any]):
        if not goal:
            return

        self.memory["goals"].append({
            **goal,
            "confirmed_at": self._now(),
        })

        self._save()

    # ============================================================
    # FAZA 4 — PLANS
    # ============================================================
    def store_plan(self, plan: Dict[str, Any]):
        if not plan:
            return

        self.memory["plans"].append({
            **plan,
            "confirmed_at": self._now(),
        })

        self._save()

    # ============================================================
    # FAZA 8 — ACTIVE DECISION
    # ============================================================
    def set_active_decision(self, decision: Dict[str, Any]):
        self.memory["active_decision"] = {
            "decision": decision,
            "ts": self._now(),
        }
        self._save()

    def clear_active_decision(self):
        self.memory["active_decision"] = None
        self._save()

    def get_active_decision(self) -> Optional[Dict[str, Any]]:
        return self.memory.get("active_decision")

    # ============================================================
    # FAZA 5 — DECISION OUTCOMES (APPEND-ONLY)
    # ============================================================
    def store_decision_outcome(
        self,
        decision_type: str,
        context_type: str,
        target: Optional[str],
        success: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        record = {
            "schema_version": self.SCHEMA_VERSION,
            "decision_type": decision_type,
            "context_type": context_type,
            "target": target,
            "success": success,
            "metadata": metadata or {},
            "ts": self._now(),
        }

        self.memory["decision_outcomes"].append(record)

        if len(self.memory["decision_outcomes"]) > 100:
            self.memory["decision_outcomes"].pop(0)

        # SOP cross-relations
        if decision_type == "sop":
            prev_sop = (metadata or {}).get("previous_sop")
            current_sop = target

            if prev_sop and current_sop:
                key = f"{prev_sop}->{current_sop}"
                rel = self.memory["cross_sop_relations"].setdefault(
                    key,
                    {"total": 0, "success": 0, "history": []},
                )

                rel["total"] += 1
                if success:
                    rel["success"] += 1

                rel["history"].append({
                    "success": success,
                    "ts": record["ts"],
                })

                if len(rel["history"]) > 200:
                    rel["history"] = rel["history"][-200:]

        self._save()

    # ============================================================
    # FAZA 6–12 — READ-ONLY ANALYTICS
    # ============================================================
    def sop_success_rate(self, sop_key: str) -> float:
        outcomes = [
            o for o in self.memory.get("decision_outcomes", [])
            if o.get("decision_type") == "sop"
            and o.get("target") == sop_key
        ]

        if not outcomes:
            return 0.0

        weighted_success = 0.0
        total_weight = 0.0

        for o in outcomes:
            w = self._decay_weight(o.get("ts", self._now()))
            total_weight += w
            if o.get("success"):
                weighted_success += w

        return round(weighted_success / total_weight, 2) if total_weight else 0.0

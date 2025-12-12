# services/memory_service.py

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional


BASE_PATH = Path(__file__).resolve().parent.parent / "adnan_ai" / "memory"


class MemoryService:
    """
    MemoryService — FAZA 1–9 (STABLE, CONSOLIDATED)

    Pravila:
    - Jedan memory.json (bez dupliranja fajlova)
    - STM + Decision + Execution + Cross-SOP Memory u istom storage-u
    - NEMA implicitnih side-effecta
    - CEO / Playbook samo čitaju
    - Execution (SOP / Agent) jedini pišu
    """

    DECAY_HALF_LIFE_SECONDS = 60 * 60 * 24 * 30  # ~30 dana
    MIN_WEIGHT = 0.2

    def __init__(self):
        BASE_PATH.mkdir(parents=True, exist_ok=True)

        self.memory_file = BASE_PATH / "memory.json"
        self.memory = self._load()

        self.memory.setdefault("entries", [])
        self.memory.setdefault("decision_outcomes", [])
        self.memory.setdefault("execution_stats", {})
        self.memory.setdefault("cross_sop_relations", {})

    # ============================================================
    # INTERNALS
    # ============================================================
    def _load(self) -> Dict[str, Any]:
        if not self.memory_file.exists():
            return {}

        try:
            with open(self.memory_file, "r", encoding="utf-8") as f:
                return json.load(f)
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
    # FAZA 5 — SOP OUTCOMES
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

        # --------------------------------------------------------
        # FAZA 9.1 — CROSS-SOP RELATIONS
        # --------------------------------------------------------
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

    # ============================================================
    # FAZA 6–7 — EXECUTION STATS
    # ============================================================
    def record_execution(self, decision_type: str, key: str, success: bool):
        entry = self.memory["execution_stats"].setdefault(
            f"{decision_type}:{key}",
            {"total": 0, "success": 0, "history": []},
        )

        entry["total"] += 1
        if success:
            entry["success"] += 1

        entry["history"].append({"success": success, "ts": self._now()})
        if len(entry["history"]) > 200:
            entry["history"] = entry["history"][-200:]

        self._save()

    def get_execution_stats(
        self, decision_type: str, key: str
    ) -> Optional[Dict[str, Any]]:
        entry = self.memory.get("execution_stats", {}).get(
            f"{decision_type}:{key}"
        )

        if not entry or not entry.get("history"):
            return None

        weighted_success = 0.0
        total_weight = 0.0

        for h in entry["history"]:
            w = self._decay_weight(h.get("ts", self._now()))
            total_weight += w
            if h.get("success"):
                weighted_success += w

        if not total_weight:
            return None

        return {
            "total": entry.get("total", 0),
            "success": entry.get("success", 0),
            "success_rate": round(weighted_success / total_weight, 2),
        }

    # ============================================================
    # FAZA 9.2 — CROSS-SOP READ-ONLY API
    # ============================================================
    def get_cross_sop_stats(
        self, from_sop: str, to_sop: str
    ) -> Optional[Dict[str, Any]]:
        key = f"{from_sop}->{to_sop}"
        rel = self.memory.get("cross_sop_relations", {}).get(key)

        if not rel or not rel.get("history"):
            return None

        weighted_success = 0.0
        total_weight = 0.0

        for h in rel["history"]:
            w = self._decay_weight(h.get("ts", self._now()))
            total_weight += w
            if h.get("success"):
                weighted_success += w

        if not total_weight:
            return None

        return {
            "from": from_sop,
            "to": to_sop,
            "total": rel.get("total", 0),
            "success": rel.get("success", 0),
            "success_rate": round(weighted_success / total_weight, 2),
        }

    def get_cross_sop_bias(self, current_sop: str) -> List[Dict[str, Any]]:
        """
        Vraća SOP-ove koji imaju dobar success rate NAKON current_sop.
        READ-ONLY signal za CEO / Playbook.
        """
        results: List[Dict[str, Any]] = []

        for key, rel in self.memory.get("cross_sop_relations", {}).items():
            if not key.startswith(f"{current_sop}->"):
                continue

            _, next_sop = key.split("->", 1)
            stats = self.get_cross_sop_stats(current_sop, next_sop)
            if stats:
                results.append(stats)

        results.sort(key=lambda r: r["success_rate"], reverse=True)
        return results

# services/memory_service.py

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal


BASE_PATH = Path(__file__).resolve().parent.parent / "adnan_ai" / "memory"

ScopeType = Literal["user", "session", "task", "execution"]


class MemoryService:
    """
    CANON (Phase 6): State/Memory SSOT API (scope-based) + backward compatible legacy API.

    - Level 1 backend: in-memory dict (persisted to disk for current repo compatibility).
    - Scopes: user/session/task/execution
    - Canonical ops: get/set/delete (+ internal TTL)
    """

    SCHEMA_VERSION = "1.0.0"  # 🔒 LOCKED
    DECAY_HALF_LIFE_SECONDS = 60 * 60 * 24 * 30
    MIN_WEIGHT = 0.2
    MAX_ENTRIES = 100
    MAX_DECISION_OUTCOMES = 100
    MAX_REL_HISTORY = 200
    MAX_WRITE_AUDIT_EVENTS = 500

    def __init__(self):
        BASE_PATH.mkdir(parents=True, exist_ok=True)

        self.memory_file = BASE_PATH / "memory.json"
        self.tmp_file = BASE_PATH / "memory.json.tmp"
        self._lock = threading.Lock()

        self.memory = self._load()

        # ---- root keys ----
        self.memory.setdefault("schema_version", self.SCHEMA_VERSION)

        # Legacy keys (kept)
        self.memory.setdefault("entries", [])
        self.memory.setdefault("decision_outcomes", [])
        self.memory.setdefault("execution_stats", {})
        self.memory.setdefault("cross_sop_relations", {})
        self.memory.setdefault("goals", [])
        self.memory.setdefault("plans", [])
        self.memory.setdefault("active_decision", None)

        # Phase 5/6 keys
        self.memory.setdefault("write_audit_events", [])

        # Phase 6 canonical scoped state
        self.memory.setdefault("scopes", {})
        scopes = self.memory["scopes"]
        if not isinstance(scopes, dict):
            scopes = {}
            self.memory["scopes"] = scopes

        for st in ("user", "session", "task", "execution"):
            scopes.setdefault(st, {})
            if not isinstance(scopes[st], dict):
                scopes[st] = {}

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
                if not isinstance(data, dict):
                    return {}
                if "schema_version" not in data:
                    data["schema_version"] = self.SCHEMA_VERSION
                return data
        except Exception:
            return {}

    def _save(self):
        with self._lock:
            data = json.dumps(self.memory, indent=2, ensure_ascii=False)
            with open(self.tmp_file, "w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(self.tmp_file, self.memory_file)

    def _now(self) -> float:
        return time.time()

    def _decay_weight(self, timestamp: float) -> float:
        age = max(0.0, self._now() - timestamp)
        weight = 0.5 ** (age / self.DECAY_HALF_LIFE_SECONDS)
        return max(self.MIN_WEIGHT, round(weight, 4))

    def _validate_scope(self, scope_type: str, scope_id: str) -> Optional[tuple[ScopeType, str]]:
        if scope_type not in ("user", "session", "task", "execution"):
            return None
        if not isinstance(scope_id, str) or not scope_id.strip():
            return None
        return scope_type, scope_id.strip()

    def _purge_expired_locked(self, scope_type: ScopeType, scope_id: str) -> None:
        scopes = self.memory.get("scopes", {})
        bucket = scopes.get(scope_type, {})
        state = bucket.get(scope_id)
        if not isinstance(state, dict):
            return

        now = self._now()
        expired_keys: List[str] = []
        for k, v in state.items():
            if not isinstance(v, dict):
                continue
            exp = v.get("exp")
            if isinstance(exp, (int, float)) and exp <= now:
                expired_keys.append(k)

        for k in expired_keys:
            state.pop(k, None)

        if expired_keys:
            self._save()

    # ============================================================
    # CANONICAL SCOPE API (Phase 6)
    # ============================================================
    def get(
        self,
        *,
        scope_type: str,
        scope_id: str,
        key: str,
        default: Any = None,
    ) -> Any:
        norm = self._validate_scope(scope_type, scope_id)
        if norm is None:
            return default
        st, sid = norm

        if not isinstance(key, str) or not key:
            return default

        with self._lock:
            self._purge_expired_locked(st, sid)
            scopes = self.memory["scopes"]
            bucket = scopes[st]
            state = bucket.get(sid)
            if not isinstance(state, dict):
                return default
            rec = state.get(key)
            if not isinstance(rec, dict):
                return default
            return rec.get("value", default)

    def set(
        self,
        *,
        scope_type: str,
        scope_id: str,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        norm = self._validate_scope(scope_type, scope_id)
        if norm is None:
            return False
        st, sid = norm

        if not isinstance(key, str) or not key:
            return False

        exp: Optional[float] = None
        if isinstance(ttl_seconds, int) and ttl_seconds > 0:
            exp = self._now() + float(ttl_seconds)

        rec = {
            "value": value,
            "ts": self._now(),
            "exp": exp,
            "meta": metadata or {},
        }

        with self._lock:
            scopes = self.memory["scopes"]
            bucket = scopes[st]
            state = bucket.get(sid)
            if not isinstance(state, dict):
                state = {}
                bucket[sid] = state
            state[key] = rec
            self._save()
        return True

    def delete(self, *, scope_type: str, scope_id: str, key: str) -> bool:
        norm = self._validate_scope(scope_type, scope_id)
        if norm is None:
            return False
        st, sid = norm

        if not isinstance(key, str) or not key:
            return False

        with self._lock:
            scopes = self.memory["scopes"]
            bucket = scopes[st]
            state = bucket.get(sid)
            if not isinstance(state, dict):
                return False
            existed = key in state
            state.pop(key, None)
            if existed:
                self._save()
            return existed

    def clear_scope(self, *, scope_type: str, scope_id: str) -> bool:
        norm = self._validate_scope(scope_type, scope_id)
        if norm is None:
            return False
        st, sid = norm

        with self._lock:
            scopes = self.memory["scopes"]
            bucket = scopes[st]
            existed = sid in bucket
            bucket.pop(sid, None)
            if existed:
                self._save()
            return existed

    # ============================================================
    # STM (legacy)
    # ============================================================
    def process(self, user_input: str) -> Dict[str, Any]:
        if not isinstance(user_input, str) or not user_input.strip():
            return {"stored": False, "count": len(self.memory["entries"])}

        self.memory["entries"].append({
            "text": user_input,
            "ts": self._now(),
        })

        if len(self.memory["entries"]) > self.MAX_ENTRIES:
            self.memory["entries"] = self.memory["entries"][-self.MAX_ENTRIES:]

        self._save()
        return {"stored": True, "count": len(self.memory["entries"])}

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        return self.memory["entries"][-limit:]

    # ============================================================
    # GOALS (legacy)
    # ============================================================
    def store_goal(self, goal: Dict[str, Any]):
        if not isinstance(goal, dict):
            return

        self.memory["goals"].append({
            **goal,
            "confirmed_at": self._now(),
        })
        self._save()

    # ============================================================
    # PLANS (legacy)
    # ============================================================
    def store_plan(self, plan: Dict[str, Any]):
        if not isinstance(plan, dict):
            return

        self.memory["plans"].append({
            **plan,
            "confirmed_at": self._now(),
        })
        self._save()

    # ============================================================
    # ACTIVE DECISION (legacy)
    # ============================================================
    def set_active_decision(self, decision: Dict[str, Any]):
        if not isinstance(decision, dict):
            return

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
    # DECISION OUTCOMES (legacy)
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
            "success": bool(success),
            "metadata": metadata or {},
            "ts": self._now(),
        }

        self.memory["decision_outcomes"].append(record)
        if len(self.memory["decision_outcomes"]) > self.MAX_DECISION_OUTCOMES:
            self.memory["decision_outcomes"] = self.memory["decision_outcomes"][-self.MAX_DECISION_OUTCOMES:]

        if decision_type == "sop" and target:
            prev_sop = record["metadata"].get("previous_sop")
            current_sop = target

            if prev_sop:
                key = f"{prev_sop}->{current_sop}"
                rel = self.memory["cross_sop_relations"].setdefault(
                    key, {"total": 0, "success": 0, "history": []}
                )

                rel["total"] += 1
                if success:
                    rel["success"] += 1

                rel["history"].append({
                    "success": success,
                    "ts": record["ts"],
                })

                if len(rel["history"]) > self.MAX_REL_HISTORY:
                    rel["history"] = rel["history"][-self.MAX_REL_HISTORY:]

        self._save()

    # ============================================================
    # WRITE AUDIT (Phase 5+)
    # ============================================================
    def append_write_audit_event(self, event: Dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return

        self.memory.setdefault("write_audit_events", [])
        self.memory["write_audit_events"].append({**event, "ts": self._now()})

        if len(self.memory["write_audit_events"]) > self.MAX_WRITE_AUDIT_EVENTS:
            self.memory["write_audit_events"] = self.memory["write_audit_events"][-self.MAX_WRITE_AUDIT_EVENTS:]

        self._save()

    # ============================================================
    # READ-ONLY ANALYTICS (legacy)
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
            ts = o.get("ts")
            if not isinstance(ts, (int, float)):
                continue
            w = self._decay_weight(ts)
            total_weight += w
            if o.get("success"):
                weighted_success += w

        return round(weighted_success / total_weight, 2) if total_weight else 0.0

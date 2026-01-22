# services/memory_service.py

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal


_DEFAULT_BASE_PATH = Path(__file__).resolve().parent.parent / "adnan_ai" / "memory"

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
        # NOTE (Windows deadlock root-cause): several codepaths call _save() while already
        # holding the lock (e.g., upsert_memory_write_v1 -> _save, _purge_expired_locked -> _save).
        # A non-reentrant Lock would deadlock; use RLock.
        self._lock = threading.RLock()

        base_path = (os.getenv("MEMORY_PATH") or "").strip()
        base = Path(base_path) if base_path else _DEFAULT_BASE_PATH
        base.mkdir(parents=True, exist_ok=True)

        self.memory_file = base / "memory.json"
        self.tmp_file = base / "memory.json.tmp"

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

        # Phase 7 (enterprise): canonical memory_write.v1 sink
        self.memory.setdefault("memory_items", [])
        self.memory.setdefault("last_memory_write", None)

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

    def _utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _missing_keys_report(keys: List[str]) -> Dict[str, Any]:
        missing = [k for k in keys if isinstance(k, str) and k.strip()]
        return {
            "ok": False,
            "stored_id": None,
            "memory_count": None,
            "last_write": None,
            "errors": [f"missing:{k}" for k in missing],
            "diagnostics": {
                "missing_keys": missing,
                "recommended_action": "fix_memory_write_payload",
            },
        }

    def upsert_memory_write_v1(
        self,
        payload: Dict[str, Any],
        *,
        approval_id: str,
        execution_id: Optional[str],
        identity_id: str,
    ) -> Dict[str, Any]:
        """Canonical, deterministic SSOT sink for memory_write.v1.

        - Validates schema and required fields
        - Enforces idempotency via idempotency_key
        - Writes to memory["memory_items"] only
        """

        if not isinstance(payload, dict):
            return {
                "ok": False,
                "stored_id": None,
                "memory_count": None,
                "last_write": None,
                "errors": ["invalid_payload:not_object"],
                "diagnostics": {
                    "missing_keys": ["schema_version", "item"],
                    "recommended_action": "send_memory_write_v1_object",
                },
            }

        sv = payload.get("schema_version")
        if not isinstance(sv, str) or sv.strip() != "memory_write.v1":
            return {
                "ok": False,
                "stored_id": None,
                "memory_count": None,
                "last_write": None,
                "errors": ["invalid_schema_version"],
                "diagnostics": {
                    "missing_keys": ["schema_version"],
                    "recommended_action": "use_schema_version_memory_write_v1",
                },
            }

        item = payload.get("item")
        if not isinstance(item, dict):
            return self._missing_keys_report(
                ["item.type", "item.text", "item.tags", "item.source"]
            )  # type: ignore[return-value]

        item_type = item.get("type")
        item_text = item.get("text")
        tags = item.get("tags")
        source = item.get("source")
        grounded_on = payload.get("grounded_on")
        idem = payload.get("idempotency_key")

        missing: List[str] = []
        if not isinstance(item_type, str) or not item_type.strip():
            missing.append("item.type")
        if not isinstance(item_text, str) or not item_text.strip():
            missing.append("item.text")
        if not isinstance(tags, list) or not all(
            isinstance(x, str) and x.strip() for x in tags
        ):
            missing.append("item.tags")
        if not isinstance(source, str) or not source.strip():
            missing.append("item.source")
        grounded_on_list: List[str] = []
        if isinstance(grounded_on, list):
            grounded_on_list = [
                str(x).strip()
                for x in grounded_on
                if isinstance(x, str) and str(x).strip()
            ]
        has_kb = any(x.startswith("KB:") for x in grounded_on_list)
        has_identity = any("identity_pack." in x for x in grounded_on_list)
        if (
            (not grounded_on_list)
            or len(grounded_on_list) < 2
            or (not has_kb)
            or (not has_identity)
        ):
            missing.append("grounded_on")
        if not isinstance(idem, str) or not idem.strip():
            missing.append("idempotency_key")

        if missing:
            return self._missing_keys_report(missing)  # type: ignore[return-value]

        with self._lock:
            self.memory.setdefault("memory_items", [])
            items = self.memory.get("memory_items")
            if not isinstance(items, list):
                items = []
                self.memory["memory_items"] = items

            # Idempotency: if same idempotency_key already exists, return existing.
            for it in items:
                if not isinstance(it, dict):
                    continue
                if it.get("idempotency_key") == idem:
                    stored_id0 = it.get("stored_id")
                    last_write0 = self.memory.get("last_memory_write")
                    return {
                        "ok": True,
                        "stored_id": stored_id0,
                        "memory_count": int(
                            len([x for x in items if isinstance(x, dict)])
                        ),
                        "last_write": last_write0,
                        "errors": [],
                    }

            stored_id = f"mem_{idem[:16]}"
            now_iso = self._utc_now_iso()
            rec = {
                "stored_id": stored_id,
                "schema_version": "memory_write.v1",
                "idempotency_key": idem,
                "item": {
                    "type": str(item_type).strip().lower(),
                    "text": str(item_text).strip(),
                    "tags": [
                        str(x).strip()
                        for x in (tags or [])
                        if isinstance(x, str) and x.strip()
                    ],
                    "source": str(source).strip().lower(),
                },
                "grounded_on": list(grounded_on_list),
                "approval_id": approval_id,
                "execution_id": execution_id,
                "identity_id": identity_id,
                "created_at": now_iso,
            }
            items.append(rec)
            self.memory["last_memory_write"] = now_iso
            self._save()

            return {
                "ok": True,
                "stored_id": stored_id,
                "memory_count": int(len([x for x in items if isinstance(x, dict)])),
                "last_write": now_iso,
                "errors": [],
            }

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

    def _validate_scope(
        self, scope_type: str, scope_id: str
    ) -> Optional[tuple[ScopeType, str]]:
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

        self.memory["entries"].append(
            {
                "text": user_input,
                "ts": self._now(),
            }
        )

        if len(self.memory["entries"]) > self.MAX_ENTRIES:
            self.memory["entries"] = self.memory["entries"][-self.MAX_ENTRIES :]

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

        self.memory["goals"].append(
            {
                **goal,
                "confirmed_at": self._now(),
            }
        )
        self._save()

    # ============================================================
    # PLANS (legacy)
    # ============================================================
    def store_plan(self, plan: Dict[str, Any]):
        if not isinstance(plan, dict):
            return

        self.memory["plans"].append(
            {
                **plan,
                "confirmed_at": self._now(),
            }
        )
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
            self.memory["decision_outcomes"] = self.memory["decision_outcomes"][
                -self.MAX_DECISION_OUTCOMES :
            ]

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

                rel["history"].append(
                    {
                        "success": success,
                        "ts": record["ts"],
                    }
                )

                if len(rel["history"]) > self.MAX_REL_HISTORY:
                    rel["history"] = rel["history"][-self.MAX_REL_HISTORY :]

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
            self.memory["write_audit_events"] = self.memory["write_audit_events"][
                -self.MAX_WRITE_AUDIT_EVENTS :
            ]

        self._save()

    # ============================================================
    # READ-ONLY ANALYTICS (legacy)
    # ============================================================
    def sop_success_rate(self, sop_key: str) -> float:
        outcomes = [
            o
            for o in self.memory.get("decision_outcomes", [])
            if o.get("decision_type") == "sop" and o.get("target") == sop_key
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

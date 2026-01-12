from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from services.decision_history_writer import insert_decision_history
from services.identity_resolver import resolve_identity_id

logger = logging.getLogger(__name__)

# Keep consistent with other persistence patterns (ExecutionRegistry uses a base path).
_BASE_PATH = Path(".data")
_REGISTRY_FILE = _BASE_PATH / "decision_outcomes.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    tmp.replace(path)


def _ensure_dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _ensure_str(x: Any) -> str:
    return x.strip() if isinstance(x, str) else ""


def _short_summary_from_payload(payload: Dict[str, Any], max_len: int = 280) -> str:
    """
    Deterministic: prefer command/intent + top-level params keys; do not dump huge payload.
    """
    cmd = _ensure_str(payload.get("command"))
    intent = _ensure_str(payload.get("intent"))
    params = payload.get("params")
    params_keys: List[str] = []
    if isinstance(params, dict):
        params_keys = sorted([str(k) for k in params.keys()])
    s = f"command={cmd or '(empty)'} intent={intent or '(empty)'} params_keys={params_keys}"
    return s[:max_len]


@dataclass(frozen=True)
class DecisionOutcomeRecord:
    decision_id: str
    execution_id: str
    approval_id: str
    timestamp: str

    alignment_snapshot_hash: Optional[str]
    behaviour_mode: Optional[str]

    recommendation_type: str
    recommendation_summary: str

    accepted: bool
    executed: bool
    execution_result: str  # success/fail/partial/unknown/not_executed

    owner: str

    # Optional debugging payloads (kept small)
    approval_status: Optional[str] = None


class DecisionOutcomeRegistry:
    """
    Central log of AI recommendations vs actual outcomes.
    Persistent JSON on disk, thread-safe, idempotent on (approval_id).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: Dict[str, Dict[str, Any]] = {}  # decision_id -> record dict
        self._by_approval_id: Dict[str, str] = {}  # approval_id -> decision_id
        self._by_execution_id: Dict[str, str] = {}  # execution_id -> decision_id
        self._load_from_disk_locked()

    # ----------------------------
    # CREATE (from approve/reject)
    # ----------------------------
    def create_or_get_for_approval(
        self,
        *,
        approval: Dict[str, Any],
        cmd_snapshot: Dict[str, Any],
        behaviour_mode: Optional[str],
        alignment_snapshot_hash: Optional[str],
        owner: str,
        accepted: bool,
    ) -> Dict[str, Any]:
        """
        Called exactly when approval decision is made (approve/reject).
        Idempotent: if approval_id already has a decision record, return it.
        """
        a = _ensure_dict(approval)
        approval_id = _ensure_str(a.get("approval_id"))
        execution_id = _ensure_str(a.get("execution_id"))
        status = _ensure_str(a.get("status"))

        if not approval_id:
            raise ValueError("DecisionOutcomeRegistry requires approval.approval_id")
        if not execution_id:
            raise ValueError("DecisionOutcomeRegistry requires approval.execution_id")

        # Decide timestamp deterministically.
        ts = (
            _ensure_str(a.get("decided_at"))
            or _ensure_str(a.get("created_at"))
            or _utc_now_iso()
        )

        # Recommendation typing (deterministic):
        # prefer cmd_snapshot intent, then command, then approval.command
        cs = _ensure_dict(cmd_snapshot)
        rec_type = (
            _ensure_str(cs.get("intent"))
            or _ensure_str(cs.get("command"))
            or _ensure_str(a.get("command"))
            or "unknown"
        )

        # Summary: prefer approval payload_summary if present, else cmd_snapshot
        payload_summary = a.get("payload_summary")
        if isinstance(payload_summary, dict) and payload_summary:
            rec_summary = _short_summary_from_payload(payload_summary)
        else:
            rec_summary = _short_summary_from_payload(cs)

        record_owner = _ensure_str(owner) or "unknown"

        with self._lock:
            existing_id = self._by_approval_id.get(approval_id)
            if existing_id:
                existing = self._store.get(existing_id)
                return dict(existing) if isinstance(existing, dict) else {}

            decision_id = str(uuid4())

            try:
                identity_id = resolve_identity_id(record_owner)
                insert_decision_history(decision_id=decision_id, identity_id=identity_id, origin='adnan.ai', executor=None, command=rec_type, payload=cs, confidence=None, confirmed=bool(accepted))
            except Exception:
                pass

            # Enterprise canon: approved ≠ executed
            executed = False
            execution_result = "unknown" if accepted else "not_executed"

            rec = DecisionOutcomeRecord(
                decision_id=decision_id,
                execution_id=execution_id,
                approval_id=approval_id,
                timestamp=ts,
                alignment_snapshot_hash=_ensure_str(alignment_snapshot_hash) or None,
                behaviour_mode=_ensure_str(behaviour_mode) or None,
                recommendation_type=rec_type,
                recommendation_summary=rec_summary,
                accepted=bool(accepted),
                executed=executed,
                execution_result=execution_result,
                owner=record_owner,
                approval_status=status or None,
            )

            rec_dict = rec.__dict__.copy()
            self._store[decision_id] = rec_dict
            self._by_approval_id[approval_id] = decision_id
            self._by_execution_id[execution_id] = decision_id

            self._persist_to_disk_locked()
            return dict(rec_dict)

    # ----------------------------
    # UPDATE (from orchestrator)
    # ----------------------------
    def set_execution_outcome(
        self, *, execution_id: str, outcome: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Called when execution finishes (COMPLETED/FAILED/etc).
        If record does not exist yet, returns None (caller can ignore).
        """
        eid = _ensure_str(execution_id)
        if not eid:
            raise ValueError("execution_id is required")

        out = _ensure_dict(outcome)
        state = _ensure_str(out.get("execution_state"))

        # Normalize outcome -> execution_result deterministically, no guessing.
        if state == "FAILED":
            normalized = "fail"
        elif state == "COMPLETED":
            normalized = "success"
        elif state:
            normalized = "unknown"
        else:
            normalized = "unknown"

        with self._lock:
            did = self._by_execution_id.get(eid)
            if not did:
                return None
            rec = self._store.get(did)
            if not isinstance(rec, dict):
                return None

            rec["executed"] = True
            rec["execution_result"] = normalized

            # Keep a small debug surface
            rec["execution_state"] = state or None
            if isinstance(out.get("failure"), dict):
                rec["failure"] = out.get("failure")
            elif isinstance(out.get("result"), dict):
                rr = out.get("result")
                rec["result_keys"] = sorted(list(rr.keys()))

            self._store[did] = rec
            self._persist_to_disk_locked()
            return dict(rec)

    # ----------------------------
    # LEGACY/TEST COMPAT (required by current tests)
    # ----------------------------
    def evaluate_and_update_decision(
        self, decision_id: str, execution_result: str, feedback: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Minimalna, deterministička update funkcija (test/legacy kompatibilnost).

        - decision_id mora postojati
        - executed se postavlja True
        - execution_result se snima kao string (testovi šalju "success"/"fail")
        - feedback je opcionalan (mali debug surface)
        """
        did = _ensure_str(decision_id)
        if not did:
            raise ValueError("decision_id is required")

        exec_res = _ensure_str(execution_result) or "unknown"

        with self._lock:
            rec = self._store.get(did)
            if not isinstance(rec, dict):
                return None

            rec["executed"] = True
            rec["execution_result"] = exec_res

            if isinstance(feedback, str) and feedback.strip():
                rec["feedback"] = feedback.strip()

            self._store[did] = rec
            self._persist_to_disk_locked()
            return dict(rec)

    def update_memory_periodically(self) -> Dict[str, Any]:
        """
        Test hook / placeholder. Nema runtime schedulera.
        Cron/job sistem eksterno poziva evaluatore (npr. OFL job).
        """
        return {"ok": True, "ts": _utc_now_iso()}

    # ----------------------------
    # READ (debug)
    # ----------------------------
    def get_by_execution_id(self, execution_id: str) -> Optional[Dict[str, Any]]:
        eid = _ensure_str(execution_id)
        if not eid:
            return None
        with self._lock:
            did = self._by_execution_id.get(eid)
            if not did:
                return None
            rec = self._store.get(did)
            return dict(rec) if isinstance(rec, dict) else None

    def list_recent(self, n: int = 50) -> List[Dict[str, Any]]:
        nn = int(n or 0)
        if nn <= 0:
            nn = 50
        with self._lock:
            items = list(self._store.values())
            items.sort(
                key=lambda x: str(_ensure_dict(x).get("timestamp")), reverse=True
            )
            return [dict(_ensure_dict(x)) for x in items[:nn]]

    # ----------------------------
    # DISK
    # ----------------------------
    def _load_from_disk_locked(self) -> None:
        with self._lock:
            try:
                if not _REGISTRY_FILE.exists():
                    return
                with open(_REGISTRY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    return

                store = data.get("store")
                by_approval = data.get("by_approval_id")
                by_exec = data.get("by_execution_id")

                if isinstance(store, dict):
                    self._store.update(
                        {str(k): _ensure_dict(v) for k, v in store.items()}
                    )
                if isinstance(by_approval, dict):
                    self._by_approval_id.update(
                        {str(k): str(v) for k, v in by_approval.items()}
                    )
                if isinstance(by_exec, dict):
                    self._by_execution_id.update(
                        {str(k): str(v) for k, v in by_exec.items()}
                    )

            except Exception as e:
                logger.warning("DecisionOutcomeRegistry load failed: %s", str(e))

    def _persist_to_disk_locked(self) -> None:
        try:
            payload = {
                "store": self._store,
                "by_approval_id": self._by_approval_id,
                "by_execution_id": self._by_execution_id,
                "updated_at": _utc_now_iso(),
            }
            _atomic_write_json(_REGISTRY_FILE, payload)
        except Exception as e:
            logger.warning("DecisionOutcomeRegistry persist failed: %s", str(e))


_DECISION_OUTCOME_REGISTRY_SINGLETON: Optional[DecisionOutcomeRegistry] = None
_DECISION_OUTCOME_REGISTRY_LOCK = threading.Lock()


def get_decision_outcome_registry() -> DecisionOutcomeRegistry:
    global _DECISION_OUTCOME_REGISTRY_SINGLETON

    with _DECISION_OUTCOME_REGISTRY_LOCK:
        if _DECISION_OUTCOME_REGISTRY_SINGLETON is None:
            _DECISION_OUTCOME_REGISTRY_SINGLETON = DecisionOutcomeRegistry()

        return _DECISION_OUTCOME_REGISTRY_SINGLETON

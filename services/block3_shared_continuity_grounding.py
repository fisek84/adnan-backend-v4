from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Tuple

from services.grounding_policy import classify_prompt


QuestionClass = Literal["META_SYSTEM", "FACT_SENSITIVE", "ADVISORY"]
GateDecision = Literal["ALLOW", "BOUNDED", "CLARIFY", "FAIL_CLOSED"]
ProviderStatus = Literal["OK", "EMPTY", "UNAVAILABLE"]


@dataclass(frozen=True)
class ContinuityKey:
    tenant_id: str
    principal_id: str
    conversation_id: str


ContinuityReadResult = Dict[str, Any]
ContinuityWriteResult = Dict[str, Any]
GroundingGateResult = Dict[str, Any]


class InMemoryContinuityStore:
    """Deterministic versioned continuity store for tests.

    Semantics:
    - `read` returns OK/NOT_FOUND.
    - `write(expected_version=None)` creates a new record if absent.
    - `write(expected_version=int)` performs CAS update and increments version.
    - On conflict, state MUST NOT be overwritten.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._db: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    def read(self, key: ContinuityKey) -> ContinuityReadResult:
        k = (key.tenant_id, key.principal_id, key.conversation_id)
        with self._lock:
            rec = self._db.get(k)
            if not isinstance(rec, dict):
                return {
                    "status": "NOT_FOUND",
                    "reason_code": "CONTINUITY_NOT_FOUND",
                    "state_version": None,
                    "state_payload": None,
                }
            return {
                "status": "OK",
                "reason_code": "CONTINUITY_OK",
                "state_version": int(rec.get("state_version") or 0),
                "state_payload": rec.get("state_payload"),
            }

    def write(
        self,
        key: ContinuityKey,
        *,
        expected_version: Optional[int],
        state_payload: Dict[str, Any],
    ) -> ContinuityWriteResult:
        k = (key.tenant_id, key.principal_id, key.conversation_id)
        with self._lock:
            rec = self._db.get(k)

            if expected_version is None:
                if isinstance(rec, dict):
                    return {
                        "status": "CONFLICT",
                        "reason_code": "CONTINUITY_CONFLICT",
                        "state_version": int(rec.get("state_version") or 0),
                    }
                self._db[k] = {"state_version": 1, "state_payload": dict(state_payload)}
                return {
                    "status": "OK",
                    "reason_code": "CONTINUITY_OK",
                    "state_version": 1,
                }

            if not isinstance(rec, dict):
                return {
                    "status": "NOT_FOUND",
                    "reason_code": "CONTINUITY_NOT_FOUND",
                    "state_version": None,
                }

            cur_ver = int(rec.get("state_version") or 0)
            if cur_ver != int(expected_version):
                return {
                    "status": "CONFLICT",
                    "reason_code": "CONTINUITY_CONFLICT",
                    "state_version": cur_ver,
                }

            new_ver = cur_ver + 1
            rec2 = {"state_version": new_ver, "state_payload": dict(state_payload)}
            self._db[k] = rec2
            return {
                "status": "OK",
                "reason_code": "CONTINUITY_OK",
                "state_version": new_ver,
            }


def classify_question_class(
    *, prompt: str, turn_gate_intent_category: str
) -> QuestionClass:
    if (turn_gate_intent_category or "").strip().upper() == "META_ASSISTANT":
        return "META_SYSTEM"

    pol = classify_prompt(prompt or "")
    if bool(getattr(pol, "needs_notion", False)) or bool(
        getattr(pol, "needs_memory_snapshot", False)
    ):
        return "FACT_SENSITIVE"

    return "ADVISORY"


def _normalize_evidence_summary(evidence_summary: Dict[str, Any]) -> Dict[str, Any]:
    es = evidence_summary if isinstance(evidence_summary, dict) else {}

    def _i(name: str) -> int:
        try:
            return int(es.get(name) or 0)
        except Exception:
            return 0

    sources = es.get("sources")
    source_ids = es.get("source_ids")
    sources = sources if isinstance(sources, list) else []
    source_ids = source_ids if isinstance(source_ids, list) else []

    provider_status = es.get("provider_status")
    provider_status = (
        provider_status
        if provider_status in ("OK", "EMPTY", "UNAVAILABLE")
        else "EMPTY"
    )

    return {
        "provider_status": provider_status,
        "authoritative_count": _i("authoritative_count"),
        "secondary_count": _i("secondary_count"),
        "non_authoritative_count": _i("non_authoritative_count"),
        "fresh_count": _i("fresh_count"),
        "stale_count": _i("stale_count"),
        "sources": list(sources),
        "source_ids": list(source_ids),
    }


def evaluate_grounding_gate(
    *,
    prompt: str,
    question_class: QuestionClass,
    evidence_summary: Dict[str, Any],
) -> GroundingGateResult:
    es = _normalize_evidence_summary(evidence_summary)
    provider_status: ProviderStatus = es.get("provider_status")  # type: ignore[assignment]

    if question_class == "META_SYSTEM":
        return {
            "question_class": question_class,
            "decision": "ALLOW",
            "reason_code": "GROUNDING_META_DETERMINISTIC",
            "evidence_summary": es,
            "downstream_constraint": "META_ONLY",
        }

    if question_class == "ADVISORY":
        return {
            "question_class": question_class,
            "decision": "ALLOW",
            "reason_code": "GROUNDING_ADVISORY_ASSUMPTIONS_ONLY",
            "evidence_summary": es,
            "downstream_constraint": "NO_SSOT_FACT_CLAIMS",
        }

    # FACT_SENSITIVE
    if provider_status == "UNAVAILABLE":
        return {
            "question_class": question_class,
            "decision": "FAIL_CLOSED",
            "reason_code": "GROUNDING_PROVIDER_UNAVAILABLE",
            "evidence_summary": es,
            "downstream_constraint": "REFUSE_FACT_ANSWER",
        }

    authoritative = int(es.get("authoritative_count") or 0)
    fresh = int(es.get("fresh_count") or 0)
    stale = int(es.get("stale_count") or 0)

    if authoritative >= 1 and fresh >= 1 and stale == 0:
        return {
            "question_class": question_class,
            "decision": "ALLOW",
            "reason_code": "GROUNDING_OK",
            "evidence_summary": es,
            "downstream_constraint": "EVIDENCE_BACKED_FACTS_ONLY",
        }

    if stale >= 1 and fresh == 0:
        return {
            "question_class": question_class,
            "decision": "FAIL_CLOSED",
            "reason_code": "GROUNDING_EVIDENCE_STALE",
            "evidence_summary": es,
            "downstream_constraint": "REFUSE_FACT_ANSWER",
        }

    return {
        "question_class": question_class,
        "decision": "FAIL_CLOSED",
        "reason_code": "GROUNDING_FACT_SENSITIVE_NO_EVIDENCE",
        "evidence_summary": es,
        "downstream_constraint": "REFUSE_FACT_ANSWER",
    }


def apply_block3_trace(
    content: Dict[str, Any],
    *,
    continuity: Optional[Dict[str, Any]],
    grounding: Optional[Dict[str, Any]],
) -> None:
    """Attach Block 3 trace under trace.turn_gate.* without creating trace."""

    if not isinstance(content, dict):
        return
    tr = content.get("trace")
    if not isinstance(tr, dict):
        return
    tg = tr.get("turn_gate")
    if not isinstance(tg, dict):
        return

    if isinstance(continuity, dict) and continuity:
        tg["continuity"] = continuity
    if isinstance(grounding, dict) and grounding:
        tg["grounding"] = grounding

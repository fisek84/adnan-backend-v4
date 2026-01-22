from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def _env_true(name: str, default: str = "true") -> bool:
    return (os.getenv(name, default) or "").strip().lower() == "true"


def _stable_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(
            obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except Exception:
        return json.dumps(str(obj), ensure_ascii=False)


def _sha256_hex(obj: Any) -> str:
    data = _stable_json_dumps(obj).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _now_iso() -> str:
    # ISO-ish without importing datetime (keep tiny + deterministic)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _tokenize(text: str) -> List[str]:
    t = (text or "").strip().lower()
    if not t:
        return []
    # super-simple deterministic tokenization
    out: List[str] = []
    cur: List[str] = []
    for ch in t:
        if ch.isalnum() or ch in {"_", "-"}:
            cur.append(ch)
        else:
            if cur:
                out.append("".join(cur))
                cur = []
    if cur:
        out.append("".join(cur))

    # de-noise trivial stopwords (minimal)
    stop = {
        "i",
        "a",
        "the",
        "da",
        "je",
        "su",
        "sam",
        "smo",
        "ste",
        "ko",
        "šta",
        "sta",
        "kako",
        "koja",
        "koji",
        "koje",
        "na",
        "u",
        "za",
        "od",
        "do",
        "se",
    }
    return [w for w in out if w and w not in stop]


def _is_business_plan_query(prompt: str) -> bool:
    t = (prompt or "").strip().lower()
    if not t:
        return False
    return bool(re.search(r"(?i)\b(biznis\s+plan|business\s+plan)\b", t))


def _unwrap_snapshot_payload(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    payload = snapshot.get("payload")
    if isinstance(payload, dict):
        return payload
    return snapshot


def _count_list(d: Dict[str, Any], key: str) -> int:
    v = d.get(key)
    if isinstance(v, list):
        return len(v)
    if isinstance(v, dict):
        return len(v)
    return 0


@dataclass(frozen=True)
class KBRetrievalResult:
    selected_entries: List[Dict[str, Any]]
    used_entry_ids: List[str]


class GroundingPackService:
    """Builds a deterministic "Grounding Pack" for CEO Advisor.

    Contract goals:
    - no network / no Notion live reads
    - deterministic selection of KB entries
    - stable meta + hashes for drift detection
    """

    KB_MAX_ENTRIES = 6

    @classmethod
    def _env_int(cls, name: str, default: int) -> int:
        try:
            v = int((os.getenv(name) or str(default)).strip())
            return v if v >= 0 else default
        except Exception:
            return default

    @classmethod
    def _env_bool(cls, name: str, default: str) -> bool:
        return _env_true(name, default)

    @classmethod
    def notion_targeted_reads_enabled(cls) -> bool:
        return cls._env_bool("CEO_NOTION_TARGETED_READS_ENABLED", "false")

    @classmethod
    def enabled(cls) -> bool:
        return _env_true("CEO_GROUNDING_PACK_ENABLED", "true")

    @classmethod
    def _load_identity_pack(cls) -> Dict[str, Any]:
        try:
            from services.identity_loader import load_ceo_identity_pack  # noqa: PLC0415

            pack = load_ceo_identity_pack()
            return pack if isinstance(pack, dict) else {}
        except Exception as exc:  # noqa: BLE001
            return {
                "available": False,
                "source": "identity_loader",
                "identity": None,
                "kernel": None,
                "decision_engine": None,
                "static_memory": None,
                "memory": None,
                "agents": None,
                "errors": [{"section": "identity_pack", "error": str(exc)}],
            }

    @classmethod
    def _load_kb_file(cls) -> Dict[str, Any]:
        try:
            from services.identity_loader import load_json_file, resolve_path  # noqa: PLC0415

            # Allow tests to override KB file without redirecting the whole identity directory.
            kb_path = (os.getenv("IDENTITY_KNOWLEDGE_PATH") or "").strip()
            if kb_path:
                kb = load_json_file(os.path.abspath(kb_path))
            else:
                kb = load_json_file(resolve_path("knowledge.json"))
            return kb if isinstance(kb, dict) else {}
        except Exception as exc:  # noqa: BLE001
            return {
                "version": "unknown",
                "description": "kb_load_failed",
                "entries": [],
                "_error": str(exc),
            }

    @classmethod
    def _retrieve_kb(cls, *, prompt: str, kb: Dict[str, Any]) -> KBRetrievalResult:
        entries = kb.get("entries")
        items = entries if isinstance(entries, list) else []
        toks = _tokenize(prompt)

        # Prevent low-signal matches that cause false positives (e.g., "plan" matching agent roles).
        low_signal = {"plan", "plans", "planning"}
        toks_high = [t for t in toks if t not in low_signal]

        scored: List[Tuple[float, Dict[str, Any]]] = []
        for e in items:
            if not isinstance(e, dict):
                continue
            content = " ".join(
                [
                    str(e.get("title") or ""),
                    " ".join(
                        [str(x) for x in (e.get("tags") or []) if isinstance(x, str)]
                    ),
                    str(e.get("content") or ""),
                ]
            ).lower()

            # Tokenize content to avoid substring false positives.
            content_tokens = set(_tokenize(content))

            overlap_total = 0
            overlap_high = 0
            for t in toks:
                if t and t in content_tokens:
                    overlap_total += 1
                    if t in toks_high:
                        overlap_high += 1

            pr = e.get("priority")
            try:
                prf = float(pr)
            except Exception:
                prf = 0.0

            # Coverage gating:
            # - If prompt has >=2 meaningful tokens, require >=2 total overlaps AND at least
            #   one overlap from a non-generic token (prevents "plan"-only matches).
            # - If prompt has 0/1 tokens, require >=1 overlap.
            if len(toks) >= 2:
                if overlap_total < 2 or overlap_high < 1:
                    continue
            else:
                if overlap_total <= 0:
                    continue
                continue

            # Deterministic score: overlap dominates; priority breaks ties.
            score = float(overlap_total) * 10.0 + prf
            scored.append((score, e))

        # Deterministic sorting
        scored.sort(
            key=lambda pair: (
                -pair[0],
                str(pair[1].get("id") or ""),
            )
        )

        selected = [e for _, e in scored[: cls.KB_MAX_ENTRIES]]
        used_ids: List[str] = []
        for e in selected:
            _id = e.get("id")
            if isinstance(_id, str) and _id.strip():
                used_ids.append(_id.strip())

        return KBRetrievalResult(selected_entries=selected, used_entry_ids=used_ids)

    @classmethod
    def build(
        cls,
        *,
        prompt: str,
        knowledge_snapshot: Dict[str, Any],
        memory_public_snapshot: Dict[str, Any],
        legacy_trace: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not cls.enabled():
            return {
                "enabled": False,
                "feature_flags": {"CEO_GROUNDING_PACK_ENABLED": False},
            }

        t_start = time.perf_counter()

        identity_pack = cls._load_identity_pack()
        identity_hash = _sha256_hex(identity_pack)

        kb_file = cls._load_kb_file()
        kb_hash = _sha256_hex(kb_file)

        t_kb0 = time.perf_counter()
        kb_retrieval = cls._retrieve_kb(prompt=prompt, kb=kb_file)
        t_kb1 = time.perf_counter()

        # Deterministic domain diagnostics: business plan questions must be backed by
        # a dedicated KB entry; otherwise we force unknown-mode downstream.
        business_plan_missing = False
        if _is_business_plan_query(prompt):
            used = set(
                [x for x in (kb_retrieval.used_entry_ids or []) if isinstance(x, str)]
            )
            if "plans_business_plan_001" not in used:
                business_plan_missing = True

        # Notion snapshot (SSOT wrapper is already stable)
        notion_snapshot = (
            knowledge_snapshot if isinstance(knowledge_snapshot, dict) else {}
        )
        notion_payload = _unwrap_snapshot_payload(notion_snapshot)

        # Memory snapshot (read-only exported)
        mem = memory_public_snapshot if isinstance(memory_public_snapshot, dict) else {}
        mem_hash = _sha256_hex(mem)

        counts = {
            "goals": _count_list(notion_payload, "goals"),
            "tasks": _count_list(notion_payload, "tasks"),
            "projects": _count_list(notion_payload, "projects"),
            "memory_decision_outcomes": _count_list(mem, "decision_outcomes"),
            "memory_write_audit_events": _count_list(mem, "write_audit_events"),
        }

        missing_keys: List[str] = []
        if not identity_pack.get("available", True):
            missing_keys.append("identity_pack")
        kb_entries = kb_file.get("entries")
        if not isinstance(kb_entries, list) or len(kb_entries or []) == 0:
            missing_keys.append("kb_snapshot")

        if business_plan_missing:
            missing_keys.append("plans_business_plan_001")

        errors: List[Dict[str, Any]] = []
        if isinstance(identity_pack.get("errors"), list):
            for e in identity_pack.get("errors"):
                if isinstance(e, dict):
                    errors.append({"source": "identity_pack", **e})
        kb_err = kb_file.get("_error")
        if isinstance(kb_err, str) and kb_err.strip():
            errors.append({"source": "kb", "error": kb_err.strip()})

        # Budgets / perf (hard caps; targeted reads are feature-flagged)
        budgets = {
            "schema_version": "v1",
            "notion": {
                "targeted_reads_enabled": bool(cls.notion_targeted_reads_enabled()),
                "max_calls": cls._env_int("CEO_NOTION_MAX_CALLS", 3),
                "max_payload_bytes": cls._env_int(
                    "CEO_NOTION_MAX_PAYLOAD_BYTES", 25000
                ),
                "max_latency_ms": cls._env_int("CEO_NOTION_MAX_LATENCY_MS", 1500),
            },
            "kb": {"max_entries": cls.KB_MAX_ENTRIES},
        }

        # Payload bytes (used for budget enforcement)
        payload_bytes = {
            "notion_snapshot": len(_stable_json_dumps(notion_snapshot).encode("utf-8")),
            "kb_snapshot": len(_stable_json_dumps(kb_file).encode("utf-8")),
            "memory_snapshot": len(_stable_json_dumps(mem).encode("utf-8")),
        }

        # Enforce Notion payload size budget INSIDE grounding_pack only.
        budget_exceeded = False
        budget_exceeded_detail: Dict[str, Any] = {}
        max_payload = budgets.get("notion", {}).get("max_payload_bytes")
        try:
            max_payload_i = int(max_payload)
        except Exception:
            max_payload_i = 25000

        if max_payload_i > 0 and payload_bytes["notion_snapshot"] > max_payload_i:
            budget_exceeded = True
            budget_exceeded_detail = {
                "type": "notion_payload_bytes",
                "actual": payload_bytes["notion_snapshot"],
                "limit": max_payload_i,
            }

            # Redact notion snapshot payload (keep meta + empty lists)
            redacted_payload = {
                "goals": [],
                "tasks": [],
                "projects": [],
            }
            redacted_meta = {
                "payload_redacted": True,
                "original_counts": {
                    "goals": counts.get("goals"),
                    "tasks": counts.get("tasks"),
                    "projects": counts.get("projects"),
                },
                "budget": budget_exceeded_detail,
            }

            # Preserve top-level wrapper keys best-effort
            notion_snapshot = {
                "schema_version": notion_snapshot.get("schema_version"),
                "status": notion_snapshot.get("status"),
                "generated_at": notion_snapshot.get("generated_at"),
                "last_sync": notion_snapshot.get("last_sync"),
                "ready": notion_snapshot.get("ready"),
                "expired": notion_snapshot.get("expired"),
                "ttl_seconds": notion_snapshot.get("ttl_seconds"),
                "age_seconds": notion_snapshot.get("age_seconds"),
                "payload": redacted_payload,
                "meta": redacted_meta,
            }

        # Deterministic recommendation (router/agent still decides proposals)
        recommended_action = None
        if bool(notion_snapshot.get("expired") is True) or (
            counts["goals"] == 0 and counts["tasks"] == 0
        ):
            recommended_action = "refresh_snapshot"

        # Trace v2
        legacy = legacy_trace if isinstance(legacy_trace, dict) else {}
        llm_used = bool(legacy.get("llm_used") is True)

        # Heuristic: KB-only questions should not consume Notion.
        t_prompt = (prompt or "").strip().lower()
        wants_notion = bool(
            any(
                k in t_prompt
                for k in (
                    "notion",
                    "cilj",
                    "ciljevi",
                    "goal",
                    "goals",
                    "task",
                    "tasks",
                    "zadat",
                    "kpi",
                    "projekat",
                    "project",
                )
            )
        )

        used_sources: List[str] = []
        not_used: List[Dict[str, Any]] = []

        if identity_pack.get("available", True):
            used_sources.append("identity_pack")
        else:
            not_used.append({"source": "identity_pack", "skipped_reason": "missing"})

        kb_status = "ok"
        if "kb_snapshot" in missing_keys:
            kb_status = "missing"
        if isinstance(kb_err, str) and kb_err.strip():
            kb_status = "error"

        if kb_status == "ok":
            used_sources.append("kb_snapshot")
        else:
            not_used.append({"source": "kb_snapshot", "skipped_reason": kb_status})

        # Notion snapshot is always present as an object, but may be intentionally not used.
        notion_calls = 0
        try:
            if isinstance(legacy, dict) and isinstance(legacy.get("notion_calls"), int):
                notion_calls = int(legacy.get("notion_calls"))
        except Exception:
            notion_calls = 0

        notion_read_ids: List[str] = []
        if budget_exceeded:
            not_used.append(
                {"source": "notion_snapshot", "skipped_reason": "budget_exceeded"}
            )
        elif wants_notion:
            # Targeted reads are feature-flagged; default is zero calls.
            if not cls.notion_targeted_reads_enabled():
                not_used.append(
                    {
                        "source": "notion_snapshot",
                        "skipped_reason": "targeted_reads_disabled",
                    }
                )
            else:
                # IO happens outside this service; here we only report.
                not_used.append(
                    {
                        "source": "notion_snapshot",
                        "skipped_reason": "no_targeted_reads_performed_in_builder",
                    }
                )
        else:
            not_used.append(
                {"source": "notion_snapshot", "skipped_reason": "kb_only_question"}
            )

        # Memory snapshot is included in the pack but marked as not used unless explicitly needed.
        if "memory" in t_prompt or "audit" in t_prompt:
            used_sources.append("memory_snapshot")
        else:
            not_used.append(
                {
                    "source": "memory_snapshot",
                    "skipped_reason": "not_required_for_prompt",
                }
            )

        trace_v2 = {
            "schema_version": "v1",
            "agent_id": agent_id,
            "kb_first": True,
            "used_sources": used_sources,
            "not_used": not_used,
            "notion_calls": notion_calls,
            "budget_exceeded": bool(budget_exceeded),
            "budget_exceeded_detail": budget_exceeded_detail,
            "read_ids": {
                "notion": notion_read_ids,
                "kb": list(kb_retrieval.used_entry_ids),
                "memory": [],
            },
            "stale_flags": {
                "notion_snapshot_expired": bool(notion_snapshot.get("expired") is True),
                "notion_snapshot_status": notion_snapshot.get("status"),
            },
            "timing_ms": {
                "kb_retrieval": int(round((t_kb1 - t_kb0) * 1000.0)),
            },
            "payload_bytes": payload_bytes,
            "budgets": budgets,
            "legacy_trace": legacy,
            "llm_used": llm_used,
        }

        diagnostics = {
            "schema_version": "v1",
            "generated_at": _now_iso(),
            "missing_keys": missing_keys,
            "recommended_action": (
                "add_identity_kb_entry" if business_plan_missing else recommended_action
            ),
            "last_sync": notion_snapshot.get("last_sync"),
            "errors": errors,
            "counts": counts,
            "perf": {
                "kb_retrieval_ms": int(round((t_kb1 - t_kb0) * 1000.0)),
            },
        }

        if budget_exceeded:
            mk = diagnostics.get("missing_keys")
            if not isinstance(mk, list):
                mk = []
            mk.append("notion_budget_exceeded")
            diagnostics["missing_keys"] = mk
            diagnostics["recommended_action"] = "reduce_notion_payload"

        pack = {
            "enabled": True,
            "schema_version": "v1",
            "feature_flags": {"CEO_GROUNDING_PACK_ENABLED": True},
            "identity_pack": {
                "hash": identity_hash,
                "payload": identity_pack,
            },
            "kb_snapshot": {
                "hash": kb_hash,
                "source": "identity/knowledge.json",
                "status": kb_status,
                "version": kb_file.get("version"),
                "description": kb_file.get("description"),
                "payload": kb_file if kb_status == "ok" else None,
                # Back-compat convenience (retrieval results live in kb_retrieved)
                "selected_entries": kb_retrieval.selected_entries,
                "used_entry_ids": kb_retrieval.used_entry_ids,
            },
            "kb_retrieved": {
                "max_entries": cls.KB_MAX_ENTRIES,
                "used_entry_ids": kb_retrieval.used_entry_ids,
                "entries": kb_retrieval.selected_entries,
                "refs": [
                    {"kb_entry_id": _id, "path": f"entries[id={_id}]"}
                    for _id in kb_retrieval.used_entry_ids
                ],
            },
            "notion_snapshot": notion_snapshot,
            "memory_snapshot": {
                "hash": mem_hash,
                "payload": mem,
            },
            "diagnostics": diagnostics,
            "trace": trace_v2,
            "budgets": budgets,
            "perf": {
                "total_ms": int(round((time.perf_counter() - t_start) * 1000.0)),
            },
        }

        return pack

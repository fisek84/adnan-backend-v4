from __future__ import annotations

import hashlib
import json
import os
import re
import time
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from services.grounding_policy import classify_prompt


logger = logging.getLogger(__name__)


_KB_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _run_coro_in_worker(coro: Any) -> Any:
    """Run an async coroutine from sync code, even when an event loop is already running."""

    def _runner() -> Any:
        return asyncio.run(coro)

    return _KB_EXECUTOR.submit(_runner).result()


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

    KB_MAX_ENTRIES = 12

    @classmethod
    def _kb_search_top_k(cls) -> int:
        # How many candidates to request from KB store.search().
        # Must be >=8 to avoid pathological single-hit collapses.
        default_v = max(8, cls._kb_max_entries())
        v = cls._env_int("CEO_KB_SEARCH_TOP_K", default_v)
        try:
            v = int(v)
        except Exception:
            v = int(default_v)
        if v < 8:
            v = 8
        if v > 50:
            v = 50
        return v

    @classmethod
    def _kb_max_entries(cls) -> int:
        # Allow tuning without code changes; keep within a safe, budgeted range.
        # Requested minimal standard is 5–20; default is 12.
        v = cls._env_int("CEO_KB_MAX_ENTRIES", cls.KB_MAX_ENTRIES)
        try:
            v = int(v)
        except Exception:
            v = cls.KB_MAX_ENTRIES
        if v < 1:
            v = 1
        if v > 20:
            v = 20
        return v

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
        # Tests must remain offline/deterministic.
        if (os.getenv("TESTING") or "").strip() == "1" or (
            "PYTEST_CURRENT_TEST" in os.environ
        ):
            return False
        return cls._env_bool("CEO_NOTION_TARGETED_READS_ENABLED", "true")

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
    def _load_kb_file(
        cls, *, ctx: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Any]:
        """Load KB payload.

        Back-compat guarantee:
        - Default (KB_SOURCE unset) uses FILE and returns payload compatible with the
          previous `identity/knowledge.json` loader.
        - Only the KB entries source can change (file vs Notion).
        """

        try:
            from services.kb_get_store import get_kb_store  # noqa: PLC0415
            from services.kb_file_store import FileKBStore  # noqa: PLC0415

            store = get_kb_store()
            meta: Dict[str, Any] = (
                store.get_meta() if hasattr(store, "get_meta") else {}
            )

            # Preserve top-level payload fields from the file format when possible.
            kb_file: Dict[str, Any] = {
                "version": "unknown",
                "description": None,
                "entries": [],
            }

            if isinstance(store, FileKBStore):
                payload, entries = store.load_payload_and_entries()
                kb_file = payload if isinstance(payload, dict) else kb_file
                kb_file["entries"] = entries
                meta = store.get_meta()
            else:
                entries = _run_coro_in_worker(store.get_entries(ctx))
                kb_file = {
                    "version": "notion",
                    "description": "notion_kb",
                    "entries": entries if isinstance(entries, list) else [],
                }
                meta = store.get_meta()

            return kb_file, (meta if isinstance(meta, dict) else {}), store
        except Exception as exc:  # noqa: BLE001
            return (
                {
                    "version": "unknown",
                    "description": "kb_load_failed",
                    "entries": [],
                    "_error": str(exc),
                },
                {
                    "source": "file",
                    "cache_hit": False,
                    "last_sync": None,
                    "error_code": getattr(exc, "error_code", None),
                },
                None,
            )

    @classmethod
    def _retrieve_kb(
        cls, *, prompt: str, kb: Dict[str, Any], intent: Optional[str] = None
    ) -> KBRetrievalResult:
        from services.text_normalization import (  # noqa: PLC0415
            kb_entry_searchable_text,
            normalize_text,
            tokenize_normalized,
        )

        entries = kb.get("entries")
        items = entries if isinstance(entries, list) else []

        toks_all = tokenize_normalized(prompt)

        # Prevent low-signal matches that cause false positives (e.g., "plan" matching agent roles).
        low_signal = {"plan", "plans", "planning"}

        # Very small stopword list for prompts like "Objasni X kao da sam...".
        # Keep minimal to avoid surprising recall regressions.
        stop = {
            "kao",
            "da",
            "sam",
            "si",
            "smo",
            "ste",
            "su",
            "ali",
            "samo",
            "objasni",
            "objasnite",
            "koristi",
        }

        toks_sig = [
            t
            for t in toks_all
            if isinstance(t, str)
            and len(t) >= 3
            and t not in low_signal
            and t not in stop
        ]
        toks_sig_set = set(toks_sig)
        q_has_wysiati = "wysiati" in set(toks_all)

        intent_norm = (intent or "").strip().lower()
        gate_enabled = intent_norm in {"advisory", "state_query", "identity"}

        def _entry_applies_to(entry: Dict[str, Any]) -> List[str]:
            raw = entry.get("applies_to")
            if isinstance(raw, list):
                out = [
                    str(x).strip().lower()
                    for x in raw
                    if isinstance(x, str) and str(x).strip()
                ]
                return out or ["all"]
            return ["all"]

        scored: List[Tuple[float, Dict[str, Any]]] = []
        for e in items:
            if not isinstance(e, dict):
                continue

            if gate_enabled:
                applies_to = _entry_applies_to(e)
                if (intent_norm not in applies_to) and ("all" not in applies_to):
                    continue

            entry_id = str(e.get("id") or "")
            title_raw = str(e.get("title") or "")

            id_norm = normalize_text(entry_id)
            title_norm = normalize_text(title_raw)

            search_norm = normalize_text(kb_entry_searchable_text(e))
            content_tokens = set(tokenize_normalized(search_norm))
            id_title_tokens = set(tokenize_normalized(f"{id_norm} {title_norm}"))

            # Must-include rule: if query mentions WYSIATI, force include matching entry.
            must_include = False
            if q_has_wysiati and (
                "wysiati" in id_title_tokens or "wysiati" in content_tokens
            ):
                must_include = True

            id_title_hits = (
                sum(1 for t in toks_sig_set if t in id_title_tokens)
                if toks_sig_set
                else 0
            )
            content_hits = (
                sum(1 for t in toks_sig_set if t in content_tokens)
                if toks_sig_set
                else 0
            )

            # Phrase match is still useful for exact-quote lookups.
            phrase_hit = False
            prompt_norm = normalize_text(prompt)
            if prompt_norm:
                phrase_hit = (
                    prompt_norm in search_norm
                    or prompt_norm in title_norm
                    or prompt_norm in id_norm
                )

            if not (
                must_include or phrase_hit or id_title_hits > 0 or content_hits > 0
            ):
                continue

            pr = e.get("priority")
            try:
                prf = float(pr)
            except Exception:
                prf = 0.0

            # Ranking bias: prefer direct id/title token matches heavily.
            score = 0.0
            if must_include:
                score += 1_000_000.0
            if phrase_hit:
                score += 50_000.0
            score += float(id_title_hits) * 10_000.0
            score += float(content_hits) * 100.0
            score += prf

            scored.append((score, e))

        # Deterministic sorting
        scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("id") or "")))

        selected = [e for _, e in scored[: cls._kb_max_entries()]]
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

        ctx: Dict[str, Any] = {}
        if isinstance(agent_id, str) and agent_id.strip():
            ctx["agent_id"] = agent_id.strip()
        if isinstance(legacy_trace, dict):
            rid = legacy_trace.get("request_id") or legacy_trace.get("requestId")
            if isinstance(rid, str) and rid.strip():
                ctx["request_id"] = rid.strip()

        t_kb_load0 = time.perf_counter()
        kb_file, kb_meta, kb_store = cls._load_kb_file(ctx=ctx)
        t_kb_load1 = time.perf_counter()
        kb_hash = _sha256_hex(kb_file)

        t_kb0 = time.perf_counter()
        kb_search: Dict[str, Any] = {}
        search_attempted = False
        intent_for_kb: Optional[str] = None
        if isinstance(legacy_trace, dict):
            it = legacy_trace.get("intent")
            if isinstance(it, str) and it.strip():
                intent_for_kb = it.strip()
        try:
            if kb_store is not None and hasattr(kb_store, "search"):
                try:
                    kb_search = _run_coro_in_worker(
                        kb_store.search(
                            prompt,
                            top_k=cls._kb_search_top_k(),
                            intent=intent_for_kb,
                        )
                    )
                except TypeError:
                    kb_search = _run_coro_in_worker(
                        kb_store.search(prompt, top_k=cls._kb_search_top_k())
                    )
                search_attempted = isinstance(kb_search, dict) and any(
                    k in kb_search for k in ("entries", "used_entry_ids", "meta")
                )
        except Exception:
            kb_search = {}
            search_attempted = False

        used_entry_ids: List[str] = []
        selected_entries: List[Dict[str, Any]] = []
        kb_search_meta: Dict[str, Any] = {}

        if isinstance(kb_search, dict):
            raw_entries = kb_search.get("entries")
            raw_ids = kb_search.get("used_entry_ids")
            raw_meta = kb_search.get("meta")

            if isinstance(raw_entries, list):
                selected_entries = [x for x in raw_entries if isinstance(x, dict)]
            if isinstance(raw_ids, list):
                used_entry_ids = [
                    x for x in raw_ids if isinstance(x, str) and x.strip()
                ]
            if isinstance(raw_meta, dict):
                kb_search_meta = raw_meta

            # Back-compat fallback: some store.search() implementations may omit `meta`.
            # We still want trace to show that KB was loaded even with 0 hits.
            if not kb_search_meta:
                kb_search_meta = kb_meta if isinstance(kb_meta, dict) else {}

        # Back-compat fallback: if store.search isn't implemented or failed to return
        # a structured response, fall back to deterministic token-overlap retrieval.
        if not search_attempted:
            kb_retrieval = cls._retrieve_kb(
                prompt=prompt, kb=kb_file, intent=intent_for_kb
            )
            used_entry_ids = list(kb_retrieval.used_entry_ids)
            selected_entries = list(kb_retrieval.selected_entries)
            kb_search_meta = kb_meta if isinstance(kb_meta, dict) else {}

        # Normalize KB meta so trace/contracts remain stable regardless of store.
        # Ensure required fields exist even when hits == 0.
        kb_entries_all = kb_file.get("entries") if isinstance(kb_file, dict) else None
        total_entries_loaded = (
            len(kb_entries_all)
            if isinstance(kb_entries_all, list)
            else int(kb_search_meta.get("total_entries") or 0)
            if isinstance(kb_search_meta, dict)
            else 0
        )

        meta_norm: Dict[str, Any] = (
            dict(kb_search_meta) if isinstance(kb_search_meta, dict) else {}
        )
        src0 = meta_norm.get("source")
        if not isinstance(src0, str) or not src0.strip():
            src0 = kb_meta.get("source") if isinstance(kb_meta, dict) else None
        src = (src0 if isinstance(src0, str) and src0.strip() else None) or "file"
        mode0 = meta_norm.get("mode")
        if not isinstance(mode0, str) or not mode0.strip():
            mode0 = "notion" if src == "notion" else "file"

        hits = len([x for x in (selected_entries or []) if isinstance(x, dict)])
        meta_norm.setdefault("mode", mode0)
        meta_norm.setdefault("source", src)
        meta_norm.setdefault(
            "ttl_s",
            kb_meta.get("ttl_s")
            if isinstance(kb_meta, dict)
            else meta_norm.get("ttl_s"),
        )
        meta_norm.setdefault(
            "fetched_at",
            kb_meta.get("fetched_at")
            if isinstance(kb_meta, dict)
            else meta_norm.get("fetched_at"),
        )
        meta_norm.setdefault(
            "last_fetch_iso",
            kb_meta.get("last_fetch_iso")
            if isinstance(kb_meta, dict)
            else meta_norm.get("last_fetch_iso"),
        )
        meta_norm.setdefault(
            "cache_hit",
            kb_meta.get("cache_hit")
            if isinstance(kb_meta, dict)
            else meta_norm.get("cache_hit"),
        )
        meta_norm["total_entries"] = int(
            meta_norm.get("total_entries")
            if isinstance(meta_norm.get("total_entries"), int)
            else meta_norm.get("total_entries")
            if isinstance(meta_norm.get("total_entries"), float)
            else total_entries_loaded
        )
        meta_norm.setdefault("hit_count", hits)
        meta_norm.setdefault("hits", hits)

        kb_err2 = kb_file.get("_error") if isinstance(kb_file, dict) else None
        if isinstance(kb_err2, str) and kb_err2.strip():
            meta_norm.setdefault("kb_error", kb_err2.strip())

        if isinstance(kb_meta, dict) and isinstance(kb_meta.get("error_code"), str):
            meta_norm.setdefault("error_code", kb_meta.get("error_code"))

        kb_search_meta = meta_norm

        t_kb1 = time.perf_counter()

        try:
            src = (
                kb_meta.get("source") if isinstance(kb_meta, dict) else None
            ) or "file"
            cache_hit = (
                bool(kb_meta.get("cache_hit")) if isinstance(kb_meta, dict) else False
            )
            fallback_used = src == "file_fallback"
            logger.info(
                "KB retrieval loaded",
                extra={
                    "kb_source": src,
                    "cache_hit": cache_hit,
                    "entries_count": len(kb_file.get("entries") or [])
                    if isinstance(kb_file.get("entries"), list)
                    else 0,
                    "fallback_used": fallback_used,
                    "latency_ms": int(round((t_kb_load1 - t_kb_load0) * 1000.0)),
                    "request_id": ctx.get("request_id"),
                    "error_code": kb_meta.get("error_code") if fallback_used else None,
                },
            )
        except Exception:
            pass

        # Deterministic domain diagnostics: business plan questions must be backed by
        # a dedicated KB entry; otherwise we force unknown-mode downstream.
        business_plan_missing = False
        if _is_business_plan_query(prompt):
            used = set([x for x in (used_entry_ids or []) if isinstance(x, str)])
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
            "kb": {"max_entries": cls._kb_max_entries()},
        }

        # Payload bytes (used for budget enforcement)
        payload_bytes = {
            "notion_snapshot": len(_stable_json_dumps(notion_snapshot).encode("utf-8")),
            "kb_snapshot": len(_stable_json_dumps(kb_file).encode("utf-8")),
            "memory_snapshot": len(_stable_json_dumps(mem).encode("utf-8")),
        }

        # Enforce Notion budgets:
        # - payload_bytes budget (inside grounding_pack)
        # - read budget as reported by Notion snapshot meta (max_calls/max_latency)
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

        policy = classify_prompt(prompt)

        # Deterministic override: ensure Notion snapshot is included for
        # goals/tasks/projects questions (unless budget exceeded).
        #
        # Important: do not force this for all CEO Advisor prompts; KB-only
        # questions should remain KB-only.
        force_notion = False
        try:
            t = (prompt or "").lower()
            if any(
                s in t
                for s in (
                    "task",
                    "tasks",
                    "zadat",
                    "goal",
                    "goals",
                    "cilj",
                    "project",
                    "projects",
                    "projekt",
                )
            ):
                force_notion = True
        except Exception:
            force_notion = False

        needs_notion = bool(getattr(policy, "needs_notion", False) or force_notion)

        # Notion budget exceeded can be reported by snapshot meta (max_calls/max_latency).
        notion_meta = (
            notion_snapshot.get("meta") if isinstance(notion_snapshot, dict) else None
        )
        notion_meta = notion_meta if isinstance(notion_meta, dict) else {}
        meta_budget = (
            notion_meta.get("budget")
            if isinstance(notion_meta.get("budget"), dict)
            else {}
        )
        meta_budget_exceeded = bool(meta_budget.get("exceeded") is True)
        meta_budget_kind = meta_budget.get("exceeded_kind")
        meta_budget_detail = meta_budget.get("exceeded_detail")
        if meta_budget_exceeded and not budget_exceeded:
            budget_exceeded = True
            budget_exceeded_detail = {
                "type": "notion_budget",
                "kind": meta_budget_kind,
                "detail": meta_budget_detail
                if isinstance(meta_budget_detail, dict)
                else {},
            }

        # Also detect budget_exceeded in meta errors (legacy snapshots).
        try:
            errs = notion_meta.get("errors")
            if isinstance(errs, list) and any(
                isinstance(e, str) and ":budget_exceeded:" in e for e in errs
            ):
                if not budget_exceeded:
                    budget_exceeded = True
                    budget_exceeded_detail = {
                        "type": "notion_budget",
                        "kind": meta_budget_kind or "max_calls",
                        "detail": meta_budget_detail
                        if isinstance(meta_budget_detail, dict)
                        else {},
                    }
        except Exception:
            pass

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
                # Per-request (targeted) reads only.
                notion_calls = int(legacy.get("notion_calls"))
        except Exception:
            notion_calls = 0

        notion_read_ids: List[str] = []
        notion_has_data = bool(
            counts.get("tasks", 0) > 0
            or counts.get("projects", 0) > 0
            or counts.get("goals", 0) > 0
        )

        if needs_notion and not budget_exceeded:
            used_sources.append("notion_snapshot")
        else:
            if needs_notion:
                if budget_exceeded:
                    not_used.append(
                        {
                            "source": "notion_snapshot",
                            "skipped_reason": "budget_exceeded",
                        }
                    )
                elif not cls.notion_targeted_reads_enabled() and not notion_has_data:
                    not_used.append(
                        {
                            "source": "notion_snapshot",
                            "skipped_reason": "targeted_reads_disabled",
                        }
                    )
                elif not notion_has_data:
                    not_used.append(
                        {"source": "notion_snapshot", "skipped_reason": "missing_data"}
                    )
                else:
                    not_used.append(
                        {"source": "notion_snapshot", "skipped_reason": "not_used"}
                    )
            else:
                not_used.append(
                    {
                        "source": "notion_snapshot",
                        "skipped_reason": "not_required_for_prompt",
                    }
                )

        # Memory snapshot: ONLY when user explicitly asks for memory/audit.
        if policy.needs_memory_snapshot:
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
                "kb": list(used_entry_ids),
                "memory": [],
            },
            # Contract/debug helpers (also surfaced by routers/chat_router.py)
            "kb_meta": kb_search_meta,
            "kb_used_entry_ids": list(used_entry_ids)[:16],
            "kb_hits": int(len(selected_entries)),
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
                "selected_entries": selected_entries,
                "used_entry_ids": used_entry_ids,
            },
            "kb_retrieved": {
                "max_entries": cls._kb_max_entries(),
                "used_entry_ids": used_entry_ids,
                "entries": selected_entries,
                "meta": kb_search_meta,
                "refs": [
                    {"kb_entry_id": _id, "path": f"entries[id={_id}]"}
                    for _id in used_entry_ids
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

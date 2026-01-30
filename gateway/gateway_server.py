# gateway/gateway_server.py
# ruff: noqa: E402
# FULL FILE — replace the whole gateway_server.py with this.

from __future__ import annotations

import asyncio
import json
import inspect
import logging
import os
import re
import threading
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

# Ensure clients (PowerShell 5.1 / curl / browsers) decode BHS special chars correctly.
# This changes only the Content-Type header (no payload changes).
JSONResponse.media_type = "application/json; charset=utf-8"

from system_version import ARCH_LOCK, RELEASE_CHANNEL, SYSTEM_NAME, VERSION
from models.canon import PROPOSAL_WRAPPER_INTENT
from models.ceo_console_snapshot import CeoConsoleSnapshotResponse


# ================================================================
# GATEWAY FALLBACK: MINIMAL 2-TURN MEMORY (DEV)
#
# This is intentionally in-memory and only applied when
# router_version == "gateway-fallback-proposals-disabled-for-nonwrite-v1".
# ================================================================
_FALLBACK_WEEKLY_FOCUS_BY_SESSION_ID: Dict[str, str] = {}
_FALLBACK_WEEKLY_FOCUS_LOCK = threading.Lock()

_ZAPAMTI_RE = re.compile(r"^\s*zapamti\s*:\s*(.+?)\s*$", re.IGNORECASE)
_FOKUS_SEDMICE_Q_RE = re.compile(r"koji\s+fokus\s+sedmic", re.IGNORECASE)


def _openai_api_mode() -> str:
    return (os.getenv("OPENAI_API_MODE") or "assistants").strip().lower()


def _responses_mode_enabled() -> bool:
    return _openai_api_mode() == "responses"


def _env_int(name: str, default: int) -> int:
    v = (os.getenv(name) or "").strip()
    if not v:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _kb_min_entries_required() -> int:
    # Optional, opt-in strict guard for gateway fallback only.
    # Default disabled (0) to avoid changing existing deployments.
    v = _env_int("KB_MIN_ENTRIES", 0)
    if v < 0:
        v = 0
    if v > 20:
        v = 20
    return v


def _compute_kb_ids_used_from_grounding_pack(gp: Any) -> List[str]:
    kb_ids: List[str] = []
    if isinstance(gp, dict):
        kb = gp.get("kb_retrieved") if isinstance(gp.get("kb_retrieved"), dict) else {}
        if isinstance(kb, dict):
            raw = kb.get("used_entry_ids")
            if isinstance(raw, list):
                kb_ids = [x for x in raw if isinstance(x, str) and x.strip()]
    return kb_ids


def _count_kb_entries_injected(gp: Any) -> int:
    if not isinstance(gp, dict):
        return 0
    kb = gp.get("kb_retrieved") if isinstance(gp.get("kb_retrieved"), dict) else {}
    entries = kb.get("entries") if isinstance(kb, dict) else None
    if not isinstance(entries, list):
        return 0
    return len([x for x in entries if isinstance(x, dict)])


def _should_gate_gateway_proposal(pc: Any) -> bool:
    """Match CEO Advisor Notion Ops gating semantics on dict-shaped proposals."""

    if not isinstance(pc, dict):
        return False

    cmd = str(pc.get("command") or "").strip()
    if cmd == "notion_write":
        return True

    if cmd != PROPOSAL_WRAPPER_INTENT:
        return False

    # Memory writes are allowed even when Notion Ops is disarmed.
    intent = pc.get("intent")
    if isinstance(intent, str) and intent.strip() == "memory_write":
        return False

    args = pc.get("args")
    if not isinstance(args, dict):
        args = pc.get("params") if isinstance(pc.get("params"), dict) else None
    if isinstance(args, dict) and args.get("schema_version") == "memory_write.v1":
        return False

    return True


def _apply_gateway_notion_ops_gating_and_trace(
    result: Dict[str, Any], *, notion_ops_armed: bool
) -> int:
    if bool(notion_ops_armed is True):
        return 0

    pcs = result.get("proposed_commands")
    if not isinstance(pcs, list) or not pcs:
        return 0

    kept: List[Any] = []
    removed = 0
    for pc in pcs:
        if _should_gate_gateway_proposal(pc):
            removed += 1
            continue
        kept.append(pc)

    if removed:
        result["proposed_commands"] = kept
        tr = _ensure_dict(result.get("trace"))
        tr["notion_ops_gate"] = {
            "applied": True,
            "removed_write_proposals": removed,
            "reason": "notion_ops_disarmed",
        }
        result["trace"] = tr

        note = "\n\nNotion Ops nije aktiviran — ne vraćam write-proposals. Ako želiš, napiši: 'notion ops aktiviraj'."
        if isinstance(result.get("text"), str) and note.strip() not in (
            result.get("text") or ""
        ):
            result["text"] = (result.get("text") or "").rstrip() + note
            result["summary"] = result["text"]

    return removed


def _ensure_gateway_trace_contract(
    result: Dict[str, Any],
    *,
    used_sources: List[str],
    missing_inputs: List[str],
    notion_ops: Dict[str, Any],
    kb_ids_used: List[str],
) -> None:
    tr = _ensure_dict(result.get("trace"))
    if not isinstance(tr.get("used_sources"), list):
        tr["used_sources"] = list(used_sources)
    if not isinstance(tr.get("missing_inputs"), list):
        tr["missing_inputs"] = list(missing_inputs)
    if not isinstance(tr.get("notion_ops"), dict):
        tr["notion_ops"] = notion_ops
    if not isinstance(tr.get("kb_ids_used"), list):
        tr["kb_ids_used"] = list(kb_ids_used)
    result["trace"] = tr


def _set_readonly_text(result: Dict[str, Any], text_out: str) -> None:
    # Keep response consistent for UI/clients: text + summary.
    result["text"] = text_out
    result["summary"] = text_out
    result["read_only"] = True
    result["proposed_commands"] = []


def _apply_gateway_fallback_memory_patch(
    result: Dict[str, Any], *, prompt: str, session_id: Optional[str]
) -> bool:
    if not (isinstance(session_id, str) and session_id.strip()):
        return False

    text = (prompt or "").strip()
    if not text:
        return False

    m = _ZAPAMTI_RE.match(text)
    if m:
        focus_raw = (m.group(1) or "").strip()
        focus = focus_raw

        # If the user phrase includes an explicit marker like "fokus je ...",
        # store just the focus part.
        m2 = re.search(r"\bfokus\s+je\s+(.+)$", focus_raw, flags=re.IGNORECASE)
        if m2:
            focus = (m2.group(1) or "").strip()

        focus = focus.strip().rstrip(".?!")

        if focus:
            with _FALLBACK_WEEKLY_FOCUS_LOCK:
                _FALLBACK_WEEKLY_FOCUS_BY_SESSION_ID[session_id.strip()] = focus

        # Read-only confirmation; never emit proposals.
        _set_readonly_text(result, "Zapamćeno.")

        tr = _ensure_dict(result.get("trace"))
        tr["gateway_fallback_memory"] = True
        tr["gateway_fallback_memory_action"] = "store"
        tr.setdefault("used_sources", ["memory"])
        tr.setdefault("missing_inputs", ["identity_pack", "notion_snapshot", "kb"])
        tr.setdefault("notion_ops", {"armed": False, "session_id": session_id})
        tr.setdefault("kb_ids_used", [])
        result["trace"] = tr
        return True

    if _FOKUS_SEDMICE_Q_RE.search(text):
        with _FALLBACK_WEEKLY_FOCUS_LOCK:
            focus = _FALLBACK_WEEKLY_FOCUS_BY_SESSION_ID.get(session_id.strip())
        if isinstance(focus, str) and focus.strip():
            _set_readonly_text(result, focus.strip())

            tr = _ensure_dict(result.get("trace"))
            tr["gateway_fallback_memory"] = True
            tr["gateway_fallback_memory_action"] = "recall"
            tr.setdefault("used_sources", ["memory"])
            tr.setdefault("missing_inputs", ["identity_pack", "notion_snapshot", "kb"])
            tr.setdefault("notion_ops", {"armed": False, "session_id": session_id})
            tr.setdefault("kb_ids_used", [])
            result["trace"] = tr
            return True

    return False


def _build_ceo_read_context(
    *, prompt: str, session_id: Optional[str], request_headers: Optional[Dict[str, str]]
) -> Dict[str, Any]:
    """Best-effort context collector for gateway fallback.

    Reuses existing read paths:
    - SystemReadExecutor.snapshot (identity_pack, knowledge_snapshot, ceo_notion_snapshot)
    - ReadOnlyMemoryService.export_public_snapshot
    - GroundingPackService.build (deterministic KB retrieval + wrappers)
    """

    out: Dict[str, Any] = {
        "identity_json": None,
        "snapshot": None,
        "kb_hits": None,
        "memory_stm": None,
        "memory_ltm": None,
        "conversation_state": None,
        "missing": [],
        "trace": {
            "service": "gateway_fallback_context_bridge",
            "headers_present": bool(request_headers),
            "session_id_present": bool(
                isinstance(session_id, str) and session_id.strip()
            ),
        },
    }

    # Memory (read-only export)
    mem_public: Dict[str, Any] = {}
    try:
        from services.memory_read_only import ReadOnlyMemoryService  # type: ignore

        mem_public = ReadOnlyMemoryService().export_public_snapshot()
        if not isinstance(mem_public, dict):
            mem_public = {}
    except Exception as e:  # noqa: BLE001
        out["trace"]["memory_error"] = str(e)
        mem_public = {}

    out["memory_stm"] = mem_public

    # Conversation state (persisted multi-turn summary; best-effort)
    if isinstance(session_id, str) and session_id.strip():
        try:
            from services.ceo_conversation_state_store import ConversationStateStore  # type: ignore

            cs = ConversationStateStore.get_summary(conversation_id=session_id.strip())
            out["conversation_state"] = (
                cs.summary_text if hasattr(cs, "summary_text") else None
            )
            out["trace"]["conversation_state_turns"] = getattr(cs, "turns_used", 0)
        except Exception as e:  # noqa: BLE001
            out["trace"]["conversation_state_error"] = str(e)
            out["conversation_state"] = None

    # Consolidated system snapshot (identity + knowledge + optional Notion dashboard snapshot)
    sys_snap: Dict[str, Any] = {}
    try:
        from services.system_read_executor import SystemReadExecutor  # type: ignore

        sys_snap = SystemReadExecutor().snapshot()
        if not isinstance(sys_snap, dict):
            sys_snap = {"available": False}
    except Exception as e:  # noqa: BLE001
        out["trace"]["system_snapshot_error"] = str(e)
        sys_snap = {"available": False}

    identity_pack = sys_snap.get("identity_pack") if isinstance(sys_snap, dict) else {}
    if not isinstance(identity_pack, dict):
        identity_pack = {}

    # Prefer identity_pack payload if present (matches CEO instruction builder expectations)
    identity_json = identity_pack
    out["identity_json"] = identity_json

    knowledge_snapshot = (
        sys_snap.get("knowledge_snapshot") if isinstance(sys_snap, dict) else {}
    )
    if not isinstance(knowledge_snapshot, dict):
        knowledge_snapshot = {}

    out["snapshot"] = knowledge_snapshot

    # Grounding pack (deterministic)
    gp: Dict[str, Any] = {}
    try:
        from services.grounding_pack_service import GroundingPackService  # type: ignore

        gp = GroundingPackService.build(
            prompt=(prompt or "").strip(),
            knowledge_snapshot=knowledge_snapshot,
            memory_public_snapshot=mem_public,
            legacy_trace=None,
            agent_id="ceo_advisor",
        )
        if not isinstance(gp, dict):
            gp = {}
    except Exception as e:  # noqa: BLE001
        out["trace"]["grounding_pack_error"] = str(e)
        gp = {}

    kb_hits = None
    try:
        kb_retrieved = gp.get("kb_retrieved") if isinstance(gp, dict) else None
        if isinstance(kb_retrieved, dict):
            kb_hits = kb_retrieved.get("entries")
    except Exception:
        kb_hits = None
    out["kb_hits"] = kb_hits

    # Missing keys (best-effort)
    missing: List[str] = []
    if not (
        isinstance(identity_pack, dict) and identity_pack.get("available") is not False
    ):
        missing.append("identity_json")

    ready = (
        knowledge_snapshot.get("ready")
        if isinstance(knowledge_snapshot, dict)
        else None
    )
    if ready is not True:
        missing.append("snapshot")

    if (
        not isinstance(kb_hits, list)
        or len([x for x in kb_hits if isinstance(x, dict)]) == 0
    ):
        missing.append("kb_hits")

    if not isinstance(mem_public, dict) or not mem_public:
        missing.append("memory_stm")
    # No distinct LTM provider found in current codebase; signal missing.
    missing.append("memory_ltm")

    out["missing"] = sorted(
        set([m for m in missing if isinstance(m, str) and m.strip()])
    )

    # Extra trace
    out["trace"]["system_snapshot_available"] = bool(sys_snap.get("available") is True)
    out["trace"]["knowledge_ready"] = bool(ready is True)
    out["trace"]["grounding_pack_enabled"] = (
        bool(gp.get("enabled") is True) if isinstance(gp, dict) else False
    )
    out["trace"]["kb_hits_count"] = len(kb_hits) if isinstance(kb_hits, list) else 0
    out["trace"]["missing"] = out["missing"]

    out["grounding_pack"] = gp
    return out


def _derive_used_sources_and_missing_inputs(
    *, ctx_bridge: Dict[str, Any]
) -> Tuple[List[str], List[str]]:
    """Derive stable used_sources/missing_inputs for gateway fallback.

    Keep it compatible with both real and monkeypatched grounding_pack shapes in tests.
    """

    used_sources: List[str] = []
    missing_inputs: List[str] = []

    gp = ctx_bridge.get("grounding_pack") if isinstance(ctx_bridge, dict) else None
    gp = gp if isinstance(gp, dict) else {}

    # Prefer trace v2 from grounding_pack_service if present.
    tr2 = gp.get("trace") if isinstance(gp.get("trace"), dict) else {}
    tr2_used = (
        tr2.get("used_sources") if isinstance(tr2.get("used_sources"), list) else []
    )
    tr2_used = [x for x in tr2_used if isinstance(x, str) and x.strip()]

    # Map grounding names to CEO Advisor contract names.
    mapping = {
        "kb_snapshot": "kb",
        "memory_snapshot": "memory",
    }
    for src in tr2_used:
        used_sources.append(mapping.get(src, src))

    # Missing inputs: prefer gateway-collected missing list (more direct).
    missing_raw = (
        ctx_bridge.get("missing") if isinstance(ctx_bridge.get("missing"), list) else []
    )
    missing_raw = [x for x in missing_raw if isinstance(x, str) and x.strip()]

    if "identity_json" in missing_raw:
        missing_inputs.append("identity_pack")
    if "snapshot" in missing_raw:
        missing_inputs.append("notion_snapshot")
    if "kb_hits" in missing_raw:
        missing_inputs.append("kb")
    if "memory_stm" in missing_raw:
        missing_inputs.append("memory")
    if "memory_ltm" in missing_raw:
        missing_inputs.append("memory_ltm")

    # If we couldn't infer used_sources from trace, do a best-effort inference.
    if not used_sources:
        identity_json = ctx_bridge.get("identity_json")
        if isinstance(identity_json, dict) and identity_json:
            used_sources.append("identity_pack")

        snap = ctx_bridge.get("snapshot")
        if isinstance(snap, dict) and snap:
            used_sources.append("notion_snapshot")

        kb_hits = ctx_bridge.get("kb_hits")
        if isinstance(kb_hits, list) and any(isinstance(x, dict) for x in kb_hits):
            used_sources.append("kb")

        mem = ctx_bridge.get("memory_stm")
        if isinstance(mem, dict) and mem:
            used_sources.append("memory")

    used_sources = sorted(
        set([x for x in used_sources if isinstance(x, str) and x.strip()])
    )
    missing_inputs = sorted(
        set([x for x in missing_inputs if isinstance(x, str) and x.strip()])
    )
    return used_sources, missing_inputs


async def _generate_ceo_readonly_answer(
    *, prompt: str, session_id: Optional[str], context: Dict[str, Any]
) -> Dict[str, Any]:
    """Generate a CEO Advisor answer for gateway fallback using the same agent.

    This keeps fallback and normal paths aligned:
    - Responses-mode grounding guards
    - KB_CONTEXT / MEMORY_CONTEXT / CONVERSATION_STATE / NOTION_OPS_STATE injection
    - Notion Ops gating semantics
    - Trace contract + server-side kb_ids_used
    """

    prompt_in = (prompt or "").strip()
    missing = context.get("missing") if isinstance(context.get("missing"), list) else []
    missing = [x for x in missing if isinstance(x, str) and x.strip()]

    used_sources, missing_inputs = _derive_used_sources_and_missing_inputs(
        ctx_bridge=context if isinstance(context, dict) else {}
    )

    # If a key input is missing, prefer an explicit deterministic ask rather than a generic refusal.
    if "identity_json" in missing:
        txt = "Identity/Operating Schema nije učitan (READ). Pošalji identity_pack ili pokreni refresh, pa ponovi pitanje."
        return {
            "text": txt,
            "summary": txt,
            "trace": {
                "exit_reason": "fallback.missing_identity",
                "used_sources": used_sources,
                "missing_inputs": sorted(set(missing_inputs + ["identity_pack"])),
            },
        }

    if "snapshot" in missing:
        txt = (
            "Snapshot nije dostavljen/učitan (READ). Pošalji Notion snapshot ili pokreni refresh snapshot, "
            "pa ponovi pitanje."
        )
        return {
            "text": txt,
            "summary": txt,
            "trace": {
                "exit_reason": "fallback.missing_snapshot",
                "used_sources": used_sources,
                "missing_inputs": sorted(set(missing_inputs + ["notion_snapshot"])),
            },
        }

    gp = (
        context.get("grounding_pack")
        if isinstance(context.get("grounding_pack"), dict)
        else {}
    )

    missing_memory_snapshot = _responses_mode_enabled() and not isinstance(
        gp.get("memory_snapshot"), dict
    )
    bypass_missing_memory_snapshot_for_advisory = False

    response_class = None
    if _responses_mode_enabled():
        # Reuse the same deterministic response-class classifier as CEO advisor.
        # Default to "answer safely" (ADVISORY) unless we are confident about FACT_LOOKUP.
        try:
            from services.ceo_advisor_agent import (  # type: ignore
                ResponseClass,
                _classify_response_class,
                _responses_missing_grounding_text,
            )
            from services.intent_precedence import classify_intent  # type: ignore

            intent = classify_intent(prompt_in)
            response_class = _classify_response_class(
                prompt_in, orchestration_intent=intent
            )
            bypass_missing_memory_snapshot_for_advisory = bool(
                missing_memory_snapshot and response_class == ResponseClass.ADVISORY
            )
        except Exception:
            response_class = None

    # Responses-mode grounding guard: require required snapshot shapes.
    # This keeps the fallback bridge from calling any executor/LLM when the
    # request did not supply the minimum read context.
    if _responses_mode_enabled():
        if missing_memory_snapshot:
            # Canon: never block ADVISORY due to missing memory_snapshot.
            # Keep FACT_LOOKUP blocked with the canonical no-answer fallback.
            try:
                from services.ceo_advisor_agent import ResponseClass  # type: ignore

                if response_class == ResponseClass.FACT_LOOKUP:
                    txt = _responses_missing_grounding_text(english_output=False)
                    return {
                        "text": txt,
                        "summary": txt,
                        "trace": {
                            "exit_reason": "blocked.missing_grounding",
                            "used_sources": used_sources,
                            "missing_inputs": sorted(set(missing_inputs + ["memory"])),
                        },
                    }
            except Exception:
                # If classification isn't available, fall back to a strict heuristic:
                # treat clear question forms as fact-lookup; otherwise allow advisory.
                if "?" in prompt_in:
                    txt = "Ne mogu dati smislen odgovor na to kako je trenutno napisano. Napiši tačno šta želiš (pitanje ili zadatak) u jednoj rečenici."
                    return {
                        "text": txt,
                        "summary": txt,
                        "trace": {
                            "exit_reason": "blocked.missing_grounding",
                            "used_sources": used_sources,
                            "missing_inputs": sorted(set(missing_inputs + ["memory"])),
                        },
                    }

    # Optional strict guard (opt-in): require at least N injected KB entries in Responses-mode.
    if _responses_mode_enabled():
        min_kb = _kb_min_entries_required()
        if min_kb > 0 and _count_kb_entries_injected(gp) < min_kb:
            txt = (
                "Nemam dovoljno KB konteksta u ovom requestu da dam pouzdan odgovor. "
                "Pošalji/omogući KB_CONTEXT (retrieval) pa ponovi pitanje."
            )
            return {
                "text": txt,
                "summary": txt,
                "trace": {
                    "exit_reason": "blocked.kb_min_entries",
                    "used_sources": used_sources,
                    "missing_inputs": sorted(set(missing_inputs + ["kb"])),
                },
            }

    try:
        # In offline/test runs we may prefer the executor path (when tests monkeypatch it)
        # or the CEO agent path (when tests monkeypatch create_ceo_advisor_agent).
        from services.ceo_advisor_agent import _llm_is_configured  # type: ignore

        is_test_mode = (os.getenv("TESTING") or "").strip() == "1" or (
            "PYTEST_CURRENT_TEST" in os.environ
        )

        use_executor = False

        if is_test_mode:
            # In pytest, only use executor when get_executor itself is monkeypatched.
            try:
                from services.agent_router.executor_factory import (
                    get_executor as _get_executor,
                )  # type: ignore

                mod = str(getattr(_get_executor, "__module__", "") or "")
                if mod.startswith("tests"):
                    use_executor = True
            except Exception:
                pass
        else:
            # In real runs with no LLM config, always use executor fallback.
            if not _llm_is_configured():
                use_executor = True

        if use_executor:
            from services.agent_router.executor_factory import get_executor  # type: ignore

            executor = get_executor(purpose="ceo_advisor")
            ex_ctx: Dict[str, Any] = {
                "grounding_pack": gp,
                "identity_pack": context.get("identity_json")
                if isinstance(context.get("identity_json"), dict)
                else {},
                "snapshot": context.get("snapshot")
                if isinstance(context.get("snapshot"), dict)
                else {},
                "memory": context.get("memory_stm")
                if isinstance(context.get("memory_stm"), dict)
                else {},
                "metadata": {"session_id": session_id, "initiator": "gateway_fallback"},
            }

            ex_ctx["conversation_state"] = context.get("conversation_state")

            ex_out = await executor.ceo_command(prompt_in, ex_ctx)
            ex_text = str((ex_out or {}).get("text") or "").strip()
            if not ex_text:
                ex_text = "Treba mi više konkretnog konteksta (snapshot/KB/memory) da odgovorim."

            ex_pcs = (ex_out or {}).get("proposed_commands")
            ex_pcs_list = ex_pcs if isinstance(ex_pcs, list) else []
            if bypass_missing_memory_snapshot_for_advisory:
                ex_pcs_list = []

            return {
                "text": ex_text,
                "summary": ex_text,
                "proposed_commands": ex_pcs_list,
                "read_only": True,
                "notion_ops": None,
                "trace": {
                    "deterministic": True,
                    "exit_reason": "fallback.offline_executor",
                    "used_sources": used_sources,
                    "missing_inputs": missing_inputs,
                },
            }

        from models.agent_contract import AgentInput  # type: ignore
        from services.ceo_advisor_agent import create_ceo_advisor_agent  # type: ignore

        agent_in = AgentInput(
            message=prompt_in,
            snapshot=context.get("snapshot")
            if isinstance(context.get("snapshot"), dict)
            else {},
            identity_pack=context.get("identity_json")
            if isinstance(context.get("identity_json"), dict)
            else {},
            metadata={"session_id": session_id, "initiator": "gateway_fallback"},
        )

        agent_ctx: Dict[str, Any] = {
            "grounding_pack": gp,
            "memory": context.get("memory_stm")
            if isinstance(context.get("memory_stm"), dict)
            else {},
            "conversation_state": context.get("conversation_state"),
        }

        out = await create_ceo_advisor_agent(agent_in, agent_ctx)
        out_dict = (
            out.model_dump(by_alias=True)
            if hasattr(out, "model_dump")
            else out.dict(by_alias=True)
        )

        text_out = str(out_dict.get("text") or "").strip()
        if not text_out:
            text_out = (
                "Treba mi više konkretnog konteksta (snapshot/KB/memory) da odgovorim."
            )

        pcs = out_dict.get("proposed_commands")
        pcs_list = pcs if isinstance(pcs, list) else []
        if bypass_missing_memory_snapshot_for_advisory:
            pcs_list = []

        return {
            "text": text_out,
            "summary": text_out,
            "proposed_commands": pcs_list,
            "read_only": True,
            "notion_ops": out_dict.get("notion_ops")
            if isinstance(out_dict.get("notion_ops"), dict)
            else None,
            "trace": out_dict.get("trace")
            if isinstance(out_dict.get("trace"), dict)
            else {},
        }
    except Exception as e:  # noqa: BLE001
        parts = []
        if missing:
            parts.append("Nedostaje: " + ", ".join(sorted(set(missing))) + ".")
        parts.append("Pošalji nedostajući READ kontekst pa ponovi pitanje.")
        txt = (
            " ".join(parts).strip()
            or "Pošalji više konteksta (snapshot/KB/memory) pa ponovi pitanje."
        )
        return {
            "text": txt,
            "summary": txt,
            "proposed_commands": [],
            "read_only": True,
            "trace": {
                "exit_reason": "fallback.agent_error",
                "error": str(e),
                "used_sources": used_sources,
                "missing_inputs": missing_inputs,
            },
        }


# ================================================================
# ENV / BOOTSTRAP
# ================================================================
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # noqa: BLE001
    load_dotenv = None  # type: ignore

if os.getenv("RENDER") != "true" and load_dotenv:
    _env_path = Path(__file__).resolve().parents[1] / ".env"  # repo root .env
    load_dotenv(dotenv_path=_env_path, override=False)


def _env_true(name: str, default: str = "false") -> bool:
    return (os.getenv(name, default) or "").strip().lower() == "true"


def _is_test_mode() -> bool:
    # Keep unit tests stable even if developer shell exports prod guards.
    return (os.getenv("TESTING") or "").strip() == "1" or (
        "PYTEST_CURRENT_TEST" in os.environ
    )


def _extra_routers_enabled() -> bool:
    return _env_true("ENABLE_EXTRA_ROUTERS", "false")


def _ops_safe_mode() -> bool:
    if _is_test_mode() and not _env_true("OPS_SAFE_MODE_TESTS", "false"):
        return False
    return _env_true("OPS_SAFE_MODE", "false")


def _enterprise_preview_editor_enabled() -> bool:
    # Default OFF.
    v = (
        os.getenv("ENTERPRISE_PREVIEW_EDITOR")
        or os.getenv("ENTERPRISE_PREVIEW_EDITOR_ENABLED")
        or ""
    )
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


def _ceo_token_enforcement_enabled() -> bool:
    if _is_test_mode() and not _env_true("CEO_TOKEN_ENFORCEMENT_TESTS", "false"):
        return False
    return _env_true("CEO_TOKEN_ENFORCEMENT", "false")


def _require_ceo_token_if_enforced(request: Request) -> None:
    if not _ceo_token_enforcement_enabled():
        return

    expected = (os.getenv("CEO_APPROVAL_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="CEO token enforcement enabled but CEO_APPROVAL_TOKEN is not set",
        )

    provided = (request.headers.get("X-CEO-Token") or "").strip()

    if not provided:
        auth = (request.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()

    if provided != expected:
        raise HTTPException(status_code=403, detail="CEO token required")


def _is_ceo_request(request: Request) -> bool:
    """
    Check if the request is from a CEO user.
    CEO users are identified by:
    1. Valid X-CEO-Token header (if CEO_TOKEN_ENFORCEMENT is enabled)
    2. X-Initiator == "ceo_chat" or similar CEO indicators
    """
    # If enforcement is enabled, check for valid token
    if _ceo_token_enforcement_enabled():
        expected = (os.getenv("CEO_APPROVAL_TOKEN", "") or "").strip()
        provided = (request.headers.get("X-CEO-Token") or "").strip()
        if expected and provided == expected:
            return True

    # Check for CEO indicators in request (for non-enforced mode)
    initiator = (request.headers.get("X-Initiator") or "").strip().lower()
    if initiator in ("ceo_chat", "ceo_dashboard", "ceo"):
        return True

    return False


def _guard_write_bulk(request: Request) -> None:
    # CEO users bypass OPS_SAFE_MODE and approval checks
    if _is_ceo_request(request):
        _require_ceo_token_if_enforced(request)
        return

    if _ops_safe_mode():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )
    _require_ceo_token_if_enforced(request)


OS_ENABLED = _env_true("OS_ENABLED", "true")

_BOOT_READY = False
_BOOT_ERROR: Optional[str] = None


def _append_boot_error(msg: str) -> None:
    global _BOOT_ERROR
    msg = (msg or "").strip()
    if not msg:
        return
    if not _BOOT_ERROR:
        _BOOT_ERROR = msg
        return
    _BOOT_ERROR = f"{_BOOT_ERROR}; {msg}"


# ================================================================
# PATHS (repo-root aware)
# ================================================================
REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIST_DIR = REPO_ROOT / "gateway" / "frontend" / "dist"


def _agents_registry_path() -> Path:
    p = (os.getenv("AGENTS_JSON_PATH") or "").strip()
    if p:
        return Path(p)

    p2 = (os.getenv("AGENTS_REGISTRY_PATH") or "").strip()
    if p2:
        return Path(p2)

    return REPO_ROOT / "config" / "agents.json"


# ================================================================
# LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("gateway")


# ================================================================
# RUNTIME ENV VALIDATION (SSOT when starting via gateway_server:app)
# ================================================================
REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY",
    "NOTION_API_KEY",
    "NOTION_GOALS_DB_ID",
    "NOTION_TASKS_DB_ID",
    "NOTION_PROJECTS_DB_ID",
]


def _is_test_mode() -> bool:
    # Pytest sets PYTEST_CURRENT_TEST; we also allow explicit TESTING=1.
    return (os.getenv("TESTING") or "").strip() == "1" or (
        "PYTEST_CURRENT_TEST" in os.environ
    )


def validate_runtime_env_or_raise() -> None:
    required = list(REQUIRED_ENV_VARS)
    # Tests run with network disabled; allow missing OpenAI key.
    if _is_test_mode() and "OPENAI_API_KEY" in required:
        required.remove("OPENAI_API_KEY")

    missing = [k for k in required if not (os.getenv(k) or "").strip()]
    if missing:
        logger.critical("Missing ENV vars: %s", ", ".join(missing))
        raise RuntimeError(f"Missing ENV vars: {', '.join(missing)}")
    logger.info("Environment variables validated.")
    # Helpful boot-time flags (do NOT print secrets).
    logger.info(
        "LLM flags: OPENAI_API_MODE=%s CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE=%s CEO_ADVISOR_STRICT_LLM=%s",
        (os.getenv("OPENAI_API_MODE") or "").strip() or "(unset)",
        (os.getenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE") or "").strip() or "0",
        (os.getenv("CEO_ADVISOR_STRICT_LLM") or "").strip() or "0",
    )


# ================================================================
# CORE SERVICES
# ================================================================
from models.ai_command import AICommand
from routers.chat_router import build_chat_router
from routers.voice_router import router as voice_router
from services.ai_command_service import AICommandService
from services.approval_state_service import get_approval_state
from services.coo_conversation_service import COOConversationService
from services.coo_translation_service import COOTranslationService
from services.execution_orchestrator import ExecutionOrchestrator
from services.execution_registry import get_execution_registry

# ================================================================
# IDENTITY / MODE / STATE (READ-ONLY LOADS OK AT IMPORT)
# ================================================================
from services.adnan_mode_service import load_mode
from services.adnan_state_service import load_state
from services.identity_loader import load_identity

from services.ceo_console_snapshot_service import CEOConsoleSnapshotService

# ================================================================
# NOTION SERVICE (KANONSKI INIT) — NO SIDE EFFECTS AT IMPORT
# ================================================================
from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.notion_service import (
    init_notion_service_from_env_or_raise,
    try_get_notion_service,
)

# ================================================================
# WEEKLY MEMORY SERVICE (CEO DASHBOARD)
# ================================================================
from services.ai_summary_service import get_ai_summary_service
from services.weekly_memory_service import get_weekly_memory_service

# ================================================================
# AGENT REGISTRY + ROUTER + CHAT
# ================================================================
from services.agent_registry_service import get_agent_registry_service
from services.agent_router_service import AgentRouterService

_agent_registry = get_agent_registry_service()
_agent_router = AgentRouterService(_agent_registry)
_chat_router = build_chat_router(_agent_router)

# ================================================================
# ROUTERS (OTHER)
# ================================================================
from routers.adnan_ai_router import router as adnan_ai_router
from routers.ai_ops_router import ai_ops_router
from routers.alerting_router import router as alerting_router
from routers.audit_router import router as audit_router
from routers.goals_router import router as goals_router
from routers.metrics_router import router as metrics_router
from routers.notion_ops_router import router as notion_ops_router
from routers.projects_router import router as projects_router
from routers.sync_router import router as sync_router
from routers.tasks_router import router as tasks_router

import routers.ai_ops_router as ai_ops_router_module
import routers.ai_router as ai_router_module
import routers.ceo_console_router as ceo_console_module

# ================================================================
# APPLICATION BOOTSTRAP
# ================================================================
from services.app_bootstrap import bootstrap_application

# ================================================================
# INITIAL LOAD
# ================================================================
if not OS_ENABLED:
    logger.critical("OS_ENABLED=false - system will not start.")
    raise RuntimeError("OS is disabled by configuration.")

identity = load_identity()
mode = load_mode()
state = load_state()

# ================================================================
# CANON: NO SERVICE CONSTRUCTION AT IMPORT TIME
# ================================================================
ai_command_service: Optional[AICommandService] = None
coo_translation_service: Optional[COOTranslationService] = None
coo_conversation_service: Optional[COOConversationService] = None

_execution_registry = None  # type: ignore[assignment]
_execution_orchestrator: Optional[ExecutionOrchestrator] = None


def _require_boot_services() -> (
    Tuple[
        AICommandService,
        COOTranslationService,
        COOConversationService,
        Any,
        ExecutionOrchestrator,
    ]
):
    if not _BOOT_READY:
        raise HTTPException(status_code=503, detail=_BOOT_ERROR or "System not ready")

    if (
        ai_command_service is None
        or coo_translation_service is None
        or coo_conversation_service is None
        or _execution_orchestrator is None
        or _execution_registry is None
    ):
        raise HTTPException(status_code=503, detail="Boot services not initialized")

    return (
        ai_command_service,
        coo_translation_service,
        coo_conversation_service,
        _execution_registry,
        _execution_orchestrator,
    )


# ================================================================
# HARD-BLOCK: META-COMMANDS MUST NEVER CREATE APPROVAL OR EXECUTE
# ================================================================
# These commands are either UI/control-plane operations or otherwise unsupported
# by the execution orchestrator. They must remain read-only even if a client
# attempts to send them to /api/execute/raw.
_HARD_READ_ONLY_INTENTS = {
    "ceo_console.next_step",
    "notion_ops_toggle",
}


# ================================================================
# META-COMMANDS MUST NOT ENTER EXECUTION/APPROVAL
# ================================================================
def _ai_command_field_names() -> set[str]:
    model_fields = getattr(AICommand, "model_fields", None)
    if isinstance(model_fields, dict):
        return set(model_fields.keys())
    v1_fields = getattr(AICommand, "__fields__", None)
    if isinstance(v1_fields, dict):
        return set(v1_fields.keys())
    return set()


def _ensure_execution_id(ai_command: AICommand) -> str:
    existing = getattr(ai_command, "execution_id", None)
    if isinstance(existing, str) and existing.strip():
        return existing

    new_id = str(uuid.uuid4())
    try:
        ai_command.execution_id = new_id  # type: ignore[attr-defined]
    except Exception:
        md = getattr(ai_command, "metadata", None)
        if not isinstance(md, dict):
            md = {}
        md["execution_id"] = new_id
        ai_command.metadata = md
    return new_id


def _ensure_trace_on_command(ai_command: AICommand, *, approval_id: str) -> None:
    md = getattr(ai_command, "metadata", None)
    if not isinstance(md, dict):
        md = {}
    md["approval_id"] = approval_id
    ai_command.metadata = md

    fields = _ai_command_field_names()
    if "approval_id" in fields:
        try:
            ai_command.approval_id = approval_id  # type: ignore[attr-defined]
        except Exception:
            pass


def _safe_command_summary(ai_command: AICommand) -> Dict[str, Any]:
    try:
        if hasattr(ai_command, "model_dump"):
            out = ai_command.model_dump()
            return out if isinstance(out, dict) else {}
    except Exception:
        pass
    try:
        if hasattr(ai_command, "dict"):
            out = ai_command.dict()
            return out if isinstance(out, dict) else {}
    except Exception:
        pass

    params = getattr(ai_command, "params", None)
    intent = getattr(ai_command, "intent", None)
    cmd = getattr(ai_command, "command", None)

    summary = {
        "command": cmd,
        "intent": intent,
        "params": params if isinstance(params, dict) else {},
    }

    md = getattr(ai_command, "metadata", None)
    if isinstance(md, dict) and isinstance(md.get("confidence_risk"), dict):
        summary["confidence_risk"] = md.get("confidence_risk")

    return summary


def _to_serializable(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(v) for v in obj]
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        try:
            return {k: _to_serializable(v) for k, v in obj.__dict__.items()}
        except Exception:
            pass
    return str(obj)


def _noop_executable_from_wrapper(
    *,
    wrapper_command: str,
    wrapper_intent: str,
    prompt: str,
    initiator: str,
    metadata: Dict[str, Any],
) -> AICommand:
    md = dict(metadata or {})
    md.setdefault("canon", "execute_raw_wrapper_noop")
    md.setdefault("endpoint", "/api/execute/raw")
    md.setdefault("wrapper", {})
    if isinstance(md.get("wrapper"), dict):
        md["wrapper"].setdefault("command", wrapper_command)
        md["wrapper"].setdefault("intent", wrapper_intent)
        md["wrapper"].setdefault("prompt", (prompt or "").strip())

    return AICommand(
        command="ceo_console.next_step",
        intent="ceo_console.next_step",
        params={"prompt": (prompt or "").strip()},
        initiator=initiator,
        read_only=False,
        metadata=md,
    )


# ================================================================
# ? REPLACED FUNCTION (robust prompt extraction)
# ================================================================
def _extract_wrapper_patch_from_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Extract fill_missing patch from wrapper params.

    Canon: wrapper args/params contain prompt + optional fields (Status/Priority/Deadline/...).
    Gateway must ignore prompt and forward the rest as wrapper_patch.
    """
    if not isinstance(params, dict) or not params:
        return {}

    # Wrapper params often contain routing hints (intent/type/etc). We only want
    # user-fillable Notion field values.
    reserved = {
        "prompt",
        "intent",
        "intent_hint",
        "type",
        "command",
        "ai_command",
        "metadata",
        "session_id",
        "source",
        "db_key",
        "database",
        "operations",
    }

    patch: Dict[str, Any] = {}
    for k, v in params.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if k in reserved:
            continue
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        patch[k] = v
    return patch


def _apply_wrapper_patch_to_ai_command(
    ai_command: AICommand, wrapper_patch: Dict[str, Any]
) -> None:
    """Apply UI fill_missing patch to translated AICommand (post-translate).

    HARD RULES:
      - Only apply to notion_write/create_page.
      - Do not mutate prompt/title mapping except explicit patch overrides.
      - Use COOTranslationService normalizers.
      - If translation produced next_step/noop, caller must skip patch.
    """
    if not isinstance(wrapper_patch, dict) or not wrapper_patch:
        return

    if getattr(ai_command, "command", None) != "notion_write":
        return
    intent = getattr(ai_command, "intent", None)
    if intent not in {"create_page", "create_goal", "create_task", "create_project"}:
        return

    params = getattr(ai_command, "params", None)
    if not isinstance(params, dict):
        params = {}
        ai_command.params = params

    # For create_page we patch property_specs; for create_goal/task/project we patch params fields.
    property_specs = params.get("property_specs")
    if not isinstance(property_specs, dict):
        property_specs = {}
        params["property_specs"] = property_specs

    # Determine Status property type: goals use status, tasks use select.
    status_type = "select"
    db_key = params.get("db_key")
    if isinstance(db_key, str) and db_key.strip():
        lk = db_key.strip().lower()
        if lk in {"goals", "goal"}:
            status_type = "status"
        elif lk in {"tasks", "task"}:
            status_type = "select"

    if "Status" in wrapper_patch:
        raw = wrapper_patch.get("Status")
        if isinstance(raw, str) and raw.strip():
            name = COOTranslationService._normalize_status(raw)
            if intent == "create_page":
                property_specs["Status"] = {"type": status_type, "name": name}
            else:
                params["status"] = name

    if "Priority" in wrapper_patch:
        raw = wrapper_patch.get("Priority")
        if isinstance(raw, str) and raw.strip():
            name = COOTranslationService._normalize_priority(raw)
            if intent == "create_page":
                property_specs["Priority"] = {"type": "select", "name": name}
            else:
                params["priority"] = name

    if "Deadline" in wrapper_patch:
        raw = wrapper_patch.get("Deadline")
        if isinstance(raw, str) and raw.strip():
            iso = COOTranslationService._try_parse_date_to_iso(raw)
            if iso:
                if intent == "create_page":
                    property_specs["Deadline"] = {"type": "date", "start": iso}
                else:
                    params["deadline"] = iso

    if "Due Date" in wrapper_patch:
        raw = wrapper_patch.get("Due Date")
        if isinstance(raw, str) and raw.strip():
            iso = COOTranslationService._try_parse_date_to_iso(raw)
            if iso:
                if intent == "create_page":
                    property_specs["Due Date"] = {"type": "date", "start": iso}
                else:
                    params["deadline"] = iso

    if "Description" in wrapper_patch:
        raw = wrapper_patch.get("Description")
        if isinstance(raw, str) and raw.strip():
            if intent == "create_page":
                property_specs["Description"] = {
                    "type": "rich_text",
                    "text": raw.strip(),
                }
            else:
                params["description"] = raw.strip()

    params["property_specs"] = property_specs
    ai_command.params = params


def _unwrap_proposal_wrapper_or_raise(
    *,
    command: str,
    intent: str,
    params: Dict[str, Any],
    initiator: str,
    read_only: bool,
    metadata: Dict[str, Any],
) -> AICommand:
    is_wrapper = (intent == PROPOSAL_WRAPPER_INTENT) or (
        command == PROPOSAL_WRAPPER_INTENT
    )
    if not is_wrapper:
        return AICommand(
            command=command,
            intent=intent,
            params=params,
            initiator=initiator,
            read_only=read_only,
            metadata=metadata,
        )

    wrapper_patch = _extract_wrapper_patch_from_params(
        params if isinstance(params, dict) else {}
    )

    # ============================================================
    # CANON: memory_write.v1 proposals do NOT require prompt.
    # They are executable, strict JSON payloads.
    # ============================================================
    if isinstance(params, dict):
        sv = params.get("schema_version")
        if isinstance(sv, str) and sv.strip() == "memory_write.v1":
            return AICommand(
                command="memory_write",
                intent="memory_write",
                params=params,
                initiator=initiator,
                read_only=False,
                metadata=metadata,
            )

    # SSOT: prompt normalization + patch extraction lives in one place.
    from services.notion_write_intent_normalizer import (  # noqa: PLC0415
        coerce_create_page_name_from_prompt,
        normalize_prompt_for_property_parse,
        normalize_wrapper_prompt_and_patch,
        strip_prefixes_for_title,
    )

    # ? Robust prompt extraction: params.prompt OR metadata.prompt OR metadata.wrapper.prompt
    prompt: Optional[str] = None
    if isinstance(params, dict):
        p0 = params.get("prompt")
        if isinstance(p0, str) and p0.strip():
            prompt = p0.strip()

    # Legacy/compat: some callers nest wrapper prompt under params.ai_command.prompt
    if prompt is None and isinstance(params, dict):
        ac0 = params.get("ai_command")
        if isinstance(ac0, dict):
            p_ac = ac0.get("prompt")
            if isinstance(p_ac, str) and p_ac.strip():
                prompt = p_ac.strip()

    if prompt is None and isinstance(metadata, dict):
        p1 = metadata.get("prompt")
        if isinstance(p1, str) and p1.strip():
            prompt = p1.strip()

    if prompt is None and isinstance(metadata, dict):
        w = metadata.get("wrapper")
        if isinstance(w, dict):
            p2 = w.get("prompt")
            if isinstance(p2, str) and p2.strip():
                prompt = p2.strip()

    if not isinstance(prompt, str) or not prompt.strip():
        raise HTTPException(
            status_code=400,
            detail="ceo.command.propose cannot enter execution. Missing prompt for unwrap/translation (expected params.prompt or metadata.wrapper.prompt).",
        )

    # Merge prompt-derived patches with explicit UI patch (UI wins).
    try:
        _title0, merged = normalize_wrapper_prompt_and_patch(
            prompt=prompt, wrapper_patch=wrapper_patch
        )
        wrapper_patch = merged
    except Exception:
        pass

    # ============================================================
    # ENTERPRISE FAST-PATH: deterministic intent hints from NotionOpsAgent
    # ============================================================
    hint_intent: Optional[str] = None
    hint_type: Optional[str] = None
    if isinstance(params, dict):
        p_intent = params.get("intent") or params.get("intent_hint")
        if isinstance(p_intent, str) and p_intent.strip():
            hint_intent = p_intent.strip()
        p_type = params.get("type")
        if isinstance(p_type, str) and p_type.strip():
            hint_type = p_type.strip()

    # NOTE: strip_prefixes_for_title + normalize_prompt_for_property_parse now come from SSOT module.

    def _extract_relation_title_from_prompt(
        prompt_text: str, *, kind: str
    ) -> Optional[str]:
        """Best-effort extract of a relation target title from natural prompt.

        Examples (bs/en):
          - "povezi sa ciljem ADNAN RAMBO"
          - "sa ciljem: ADNAN RAMBO"
          - "with goal ADNAN RAMBO"
          - "goal: ADNAN RAMBO"
        """
        s = (prompt_text or "").strip()
        if not s:
            return None

        if kind == "goal":
            token = r"(?:ciljem|cilj|goal)"
        elif kind == "project":
            token = r"(?:projektom|projekat|projekt|project)"
        else:
            return None

        patterns = [
            rf"(?i)\b(?:povezi|pove\u017ei|link(?:aj)?|connect|attach)\s+(?:sa|with)\s+{token}\s*[:\-–—]?\s*([^,;\n]+)",
            rf"(?i)\b(?:sa|with)\s+{token}\s*[:\-–—]?\s*([^,;\n]+)",
            rf"(?i)\b{token}\s*[:=]\s*([^,;\n]+)",
        ]

        for pat in patterns:
            m = re.search(pat, s)
            if not m:
                continue
            val = (m.group(1) or "").strip().strip("\"'")
            if val:
                return val
        return None

    # Branch/batch requests: build operations list deterministically.
    try:
        if (hint_type or "").lower() in {"branch_request", "batch_request"} or (
            isinstance(hint_intent, str)
            and hint_intent.strip().lower()
            in {"batch_request", "batch", "branch_request"}
        ):
            # UI/enterprise path: allow explicit operations list.
            ops_in = params.get("operations") if isinstance(params, dict) else None
            if isinstance(ops_in, list) and ops_in:
                ai_command = AICommand(
                    command="notion_write",
                    intent="batch_request",
                    read_only=False,
                    params={
                        "operations": ops_in,
                        "source_prompt": prompt.strip(),
                        "wrapper_patch": dict(wrapper_patch) if wrapper_patch else None,
                    },
                    initiator=initiator,
                    validated=True,
                    metadata={
                        **(metadata if isinstance(metadata, dict) else {}),
                        "canon": "execute_raw_unwrap_batch_explicit_ops",
                        "endpoint": "/api/execute/raw",
                        "wrapper": {
                            "prompt": prompt.strip(),
                            "wrapper_patch": wrapper_patch,
                        },
                    },
                )

                # Ensure downstream executor can apply schema-backed patches.
                try:
                    if isinstance(ai_command.params, dict) and wrapper_patch:
                        ai_command.params["wrapper_patch"] = dict(wrapper_patch)
                except Exception:
                    pass

                return ai_command

            from services.branch_request_handler import BranchRequestHandler  # noqa: PLC0415

            br = BranchRequestHandler.process_branch_request(prompt.strip())
            ops = br.get("operations") if isinstance(br, dict) else None
            if isinstance(ops, list) and ops:
                ai_command = AICommand(
                    command="notion_write",
                    intent="batch_request",
                    read_only=False,
                    params={
                        "operations": ops,
                        "source_prompt": prompt.strip(),
                        "wrapper_patch": dict(wrapper_patch) if wrapper_patch else None,
                    },
                    initiator=initiator,
                    validated=True,
                    metadata={
                        **(metadata if isinstance(metadata, dict) else {}),
                        "canon": "execute_raw_unwrap_batch_fast_path",
                        "endpoint": "/api/execute/raw",
                        "wrapper": {
                            "prompt": prompt.strip(),
                            "wrapper_patch": wrapper_patch,
                        },
                    },
                )

                # Ensure downstream executor can apply schema-backed patches.
                try:
                    if isinstance(ai_command.params, dict) and wrapper_patch:
                        ai_command.params["wrapper_patch"] = dict(wrapper_patch)
                except Exception:
                    pass

                return ai_command
    except Exception:
        pass

    # Explicit goal + numbered task list (enterprise UX): convert to batch_request.
    try:
        from services.goal_task_batch_parser import (  # noqa: PLC0415
            build_batch_operations_from_parsed,
            parse_goal_with_explicit_tasks,
        )

        parsed = parse_goal_with_explicit_tasks(prompt.strip())
        if parsed:
            ops = build_batch_operations_from_parsed(parsed)
            if ops:
                ai_command = AICommand(
                    command="notion_write",
                    intent="batch_request",
                    read_only=False,
                    params={
                        "operations": ops,
                        "source_prompt": prompt.strip(),
                        "wrapper_patch": dict(wrapper_patch) if wrapper_patch else None,
                    },
                    initiator=initiator,
                    validated=True,
                    metadata={
                        **(metadata if isinstance(metadata, dict) else {}),
                        "canon": "execute_raw_unwrap_explicit_goal_task_batch",
                        "endpoint": "/api/execute/raw",
                        "wrapper": {
                            "prompt": prompt.strip(),
                            "wrapper_patch": wrapper_patch,
                        },
                    },
                )

                try:
                    if isinstance(ai_command.params, dict) and wrapper_patch:
                        ai_command.params["wrapper_patch"] = dict(wrapper_patch)
                except Exception:
                    pass

                return ai_command
    except Exception:
        pass

    # If NotionOpsAgent didn't pass an explicit hint, try deterministic local detection.
    if not (isinstance(hint_intent, str) and hint_intent.strip()):
        try:
            from services.notion_keyword_mapper import NotionKeywordMapper  # noqa: PLC0415

            auto = NotionKeywordMapper.detect_intent(prompt.strip())
            if isinstance(auto, str) and auto.strip():
                hint_intent = auto.strip()
        except Exception:
            pass

    # If this looks like a batch/branch request, force batch_request so we do NOT enter create_goal/create_task fast-path.
    try:
        from services.notion_keyword_mapper import NotionKeywordMapper  # noqa: PLC0415

        if NotionKeywordMapper.is_batch_request(prompt.strip()):
            hint_intent = "batch_request"
    except Exception:
        pass

    # Create intents with explicit/detected hint: build minimal executable without LLM translation.
    try:
        if isinstance(hint_intent, str) and hint_intent.strip():
            hi = hint_intent.strip().lower()
            if hi in {"create_task", "create_goal", "create_project", "create_page"}:
                raw_prompt = prompt.strip()
                norm_prompt = normalize_prompt_for_property_parse(raw_prompt)
                title = strip_prefixes_for_title(norm_prompt)
                if title:
                    # create_page uses property_specs, while create_* uses structured params.
                    extra_params: Dict[str, Any]
                    if hi == "create_page":
                        extra_params = {
                            "db_key": None,
                            "property_specs": {
                                "Name": {"type": "title", "text": title},
                            },
                        }

                        # Attempt to infer db_key (required for schema-backed fills).
                        dk0 = None
                        if isinstance(params, dict):
                            dk0 = params.get("db_key")
                        if isinstance(dk0, str) and dk0.strip():
                            extra_params["db_key"] = dk0.strip()
                        else:
                            ht = (hint_type or "").strip().lower()
                            if ht in {"tasks", "task"}:
                                extra_params["db_key"] = "tasks"
                            elif ht in {"goals", "goal", "cilj", "ciljevi"}:
                                extra_params["db_key"] = "goals"
                            elif ht in {"projects", "project", "projekat", "projekt"}:
                                extra_params["db_key"] = "projects"

                        # If we still don't know db_key, skip this fast-path.
                        if (
                            not isinstance(extra_params.get("db_key"), str)
                            or not str(extra_params.get("db_key")).strip()
                        ):
                            raise RuntimeError("create_page fast-path requires db_key")
                    else:
                        extra_params = {"title": title}

                    # Reuse branch/property NLP so CEO Console single-input
                    # follows the same backend rules (status/priority/deadline, assignees).
                    try:
                        from services.branch_request_handler import (  # noqa: PLC0415
                            BranchRequestHandler,
                        )

                        props = BranchRequestHandler._extract_properties(  # type: ignore[attr-defined]
                            norm_prompt
                        )
                    except Exception:
                        props = {}

                    if isinstance(props, dict) and props:
                        # Map extracted properties into fast-path params.
                        prio = props.get("priority")
                        status = props.get("status")
                        deadline = props.get("deadline")
                        assignees = props.get("assignees")

                        if hi == "create_page":
                            ps = extra_params.get("property_specs")
                            ps = ps if isinstance(ps, dict) else {}
                            extra_params["property_specs"] = ps

                            if isinstance(status, str) and status.strip():
                                ps.setdefault(
                                    "Status", {"type": "select", "name": status.strip()}
                                )
                            if isinstance(prio, str) and prio.strip():
                                ps.setdefault(
                                    "Priority",
                                    {"type": "select", "name": prio.strip()},
                                )
                            if isinstance(deadline, str) and deadline.strip():
                                # Prefer Due Date for tasks; schema-backed fill will reconcile.
                                ps.setdefault(
                                    "Due Date",
                                    {"type": "date", "start": deadline.strip()},
                                )
                            if isinstance(assignees, list) and assignees:
                                # Store as wrapper_patch to resolve by schema (people/multi_select/etc)
                                wrapper_patch.setdefault(
                                    "Assigned To", ", ".join(map(str, assignees))
                                )
                        else:
                            if isinstance(prio, str) and prio.strip():
                                extra_params.setdefault("priority", prio.strip())
                            if isinstance(status, str) and status.strip():
                                extra_params.setdefault("status", status.strip())
                            if isinstance(deadline, str) and deadline.strip():
                                extra_params.setdefault("deadline", deadline.strip())
                            if isinstance(assignees, list) and assignees:
                                extra_params.setdefault("assignees", assignees)

                    # Preserve relation intent if user specified it by title.
                    if hi == "create_task":
                        goal_title = _extract_relation_title_from_prompt(
                            raw_prompt, kind="goal"
                        )
                        if goal_title:
                            extra_params["goal_title"] = goal_title
                        project_title = _extract_relation_title_from_prompt(
                            raw_prompt, kind="project"
                        )
                        if project_title:
                            extra_params["project_title"] = project_title

                    if hi == "create_project":
                        goal_title = _extract_relation_title_from_prompt(
                            raw_prompt, kind="goal"
                        )
                        if goal_title:
                            extra_params["primary_goal_title"] = goal_title

                    ai_command = AICommand(
                        command="notion_write",
                        intent=hi,
                        read_only=False,
                        params=extra_params,
                        initiator=initiator,
                        validated=True,
                        metadata={
                            **(metadata if isinstance(metadata, dict) else {}),
                            "canon": "execute_raw_unwrap_intent_hint_fast_path",
                            "endpoint": "/api/execute/raw",
                            "wrapper": {
                                "prompt": raw_prompt,
                                "wrapper_patch": wrapper_patch,
                            },
                        },
                    )

                    try:
                        if isinstance(ai_command.params, dict) and wrapper_patch:
                            ai_command.params["wrapper_patch"] = dict(wrapper_patch)
                    except Exception:
                        pass

                    return ai_command
    except Exception:
        pass

    # require translation service to exist (booted)
    _, trans, _, _, _ = _require_boot_services()

    ai_command = None
    try:
        ai_command = trans.translate(
            raw_input=prompt.strip(),
            source="system",
            context={
                "mode": "execute",
                "via": "execute_raw_unwrap",
                "wrapper_patch": wrapper_patch,
            },
        )
    except Exception:
        ai_command = None

    # Never allow wrapper to remain wrapper after translate (avoid loops)
    if ai_command and getattr(ai_command, "intent", None) == PROPOSAL_WRAPPER_INTENT:
        ai_command = None

    if not ai_command:
        return _noop_executable_from_wrapper(
            wrapper_command=command,
            wrapper_intent=intent,
            prompt=prompt,
            initiator=initiator,
            metadata=metadata,
        )

    # Pass wrapper_patch through so execution can apply schema-backed patching.
    if (
        isinstance(wrapper_patch, dict)
        and wrapper_patch
        and getattr(ai_command, "command", None) == "notion_write"
    ):
        p0 = getattr(ai_command, "params", None)
        if not isinstance(p0, dict):
            p0 = {}
        p0["wrapper_patch"] = dict(wrapper_patch)
        ai_command.params = p0

    ai_command.initiator = initiator
    ai_command.read_only = False

    md = getattr(ai_command, "metadata", None)
    if not isinstance(md, dict):
        md = {}
    md.setdefault("canon", "execute_raw_unwrap")
    md.setdefault("endpoint", "/api/execute/raw")
    md.setdefault("wrapper", {})
    if isinstance(md.get("wrapper"), dict):
        md["wrapper"].setdefault("command", command)
        md["wrapper"].setdefault("intent", intent)
        md["wrapper"].setdefault("prompt", prompt.strip())
        if isinstance(wrapper_patch, dict) and wrapper_patch:
            md["wrapper"].setdefault("patch", dict(wrapper_patch))

    if isinstance(metadata, dict):
        for k, v in metadata.items():
            md[k] = v
    ai_command.metadata = md

    # Safety net (SSOT): if translation produced a polluted Name for create_page,
    # rewrite it from wrapper prompt.
    try:
        if (
            getattr(ai_command, "command", None) == "notion_write"
            and (getattr(ai_command, "intent", None) or "") == "create_page"
            and isinstance(prompt, str)
            and prompt.strip()
        ):
            p0 = getattr(ai_command, "params", None)
            p0 = p0 if isinstance(p0, dict) else {}
            ps0 = p0.get("property_specs")
            if isinstance(ps0, dict) and ps0:
                ps1 = coerce_create_page_name_from_prompt(
                    prompt=prompt.strip(), property_specs=ps0
                )
                if ps1 is not ps0:
                    p0 = dict(p0)
                    p0["property_specs"] = ps1
                    ai_command.params = p0
    except Exception:
        pass

    return ai_command


# ================================================================
# BOOT/SHUTDOWN ROUTINES (SINGLE SSOT)
# ================================================================
_boot_lock = asyncio.Lock()


async def _boot_once() -> None:
    global _BOOT_READY, _BOOT_ERROR
    global ai_command_service, coo_translation_service, coo_conversation_service
    global _execution_registry, _execution_orchestrator

    async with _boot_lock:
        if _BOOT_READY:
            return

        _BOOT_READY = False
        _BOOT_ERROR = None

        # ensure globals start clean (reload-safe)
        ai_command_service = None
        coo_translation_service = None
        coo_conversation_service = None
        _execution_registry = None
        _execution_orchestrator = None

        try:
            try:
                validate_runtime_env_or_raise()
            except Exception as exc:  # noqa: BLE001
                _append_boot_error(f"env_invalid:{exc}")
                logger.critical("Boot aborted due to invalid env: %s", exc)
                raise

            # Legacy domain DI (goals/tasks/projects/sync) uses dependencies.py globals.
            # Ensure they are initialized before routers are exercised in minimal uvicorn runs.
            try:
                from dependencies import (
                    get_sync_service,
                    init_services,
                    services_status,
                )

                init_services()

                # Optional verification hook: proves idempotency in logs without adding new call sites.
                if os.getenv("SSOT_DI_VERIFY", "false").strip().lower() == "true":
                    init_services()

                try:
                    from routers import sync_router as _sync_router_module

                    _sync_router_module.set_sync_service(get_sync_service())
                except Exception:
                    # Best-effort: sync/status already has a safe fallback.
                    pass
                logger.info(
                    "Legacy dependencies initialized (goals/tasks/projects/sync)"
                )

                st = services_status()
                missing = [
                    k for k in ("goals", "tasks", "projects", "sync") if not st.get(k)
                ]
                if missing:
                    logger.warning("Legacy DI missing services: %s", ",".join(missing))
            except Exception as exc:  # noqa: BLE001
                _append_boot_error(f"dependencies_init_failed:{exc}")
                logger.critical("Legacy dependencies init failed: %s", exc)
                raise

            # SSOT: init NotionService singleton here
            try:
                init_notion_service_from_env_or_raise()
                logger.info("NotionService singleton initialized (SSOT via env)")
            except Exception as exc:  # noqa: BLE001
                _append_boot_error(f"notion_init_failed:{exc}")
                logger.critical("NotionService init failed: %s", exc)
                raise

            # BOOTSTRAP app wiring (safe after Notion init)
            bootstrap_application()

            # construct all dependent services AFTER Notion init
            try:
                ai_command_service = AICommandService()
                coo_translation_service = COOTranslationService()
                coo_conversation_service = COOConversationService()

                _execution_registry = get_execution_registry()
                _execution_orchestrator = ExecutionOrchestrator()

                logger.info(
                    "Boot services initialized (orchestrator/translation/command)"
                )
            except Exception as exc:  # noqa: BLE001
                _append_boot_error(f"boot_services_init_failed:{exc}")
                logger.critical("Boot services init failed: %s", exc)
                raise

            # agent registry load (best-effort)
            try:
                p = _agents_registry_path()
                load_result = _agent_registry.load_from_agents_json(str(p), clear=True)
                logger.info(
                    "Agent registry loaded (SSOT): path=%s loaded=%s version=%s",
                    load_result.get("path"),
                    load_result.get("loaded"),
                    load_result.get("version"),
                )
            except Exception as exc:  # noqa: BLE001
                _append_boot_error(f"agents_registry_load_failed:{exc}")
                logger.warning("Agent registry load failed: %s", exc)

            # inject AI router services (now guaranteed initialized)
            try:
                if not hasattr(ai_router_module, "set_ai_services"):
                    raise RuntimeError("ai_router_init_hook_not_found")

                ai_router_module.set_ai_services(
                    command_service=ai_command_service,
                    conversation_service=coo_conversation_service,
                    translation_service=coo_translation_service,
                )
                logger.info("AI router services initialized")
            except Exception as exc:  # noqa: BLE001
                _append_boot_error(f"ai_router_init_failed:{exc}")
                logger.warning("AI router init failed: %s", exc)

            # inject AI ops services (best-effort)
            try:
                hook = getattr(ai_ops_router_module, "set_ai_ops_services", None)
                if callable(hook):
                    hook(
                        orchestrator=_execution_orchestrator,
                        approvals=get_approval_state(),
                    )
                    logger.info(
                        "AI Ops router services injected (shared orchestrator/approvals)"
                    )
            except Exception as exc:  # noqa: BLE001
                _append_boot_error(f"ai_ops_injection_failed:{exc}")
                logger.warning("AI Ops services injection failed: %s", exc)

            # best-effort knowledge sync
            # NOTE: For offline smoke verification (curl proof), allow explicitly skipping
            # this boot-time Notion sync to avoid *any* network calls.
            skip_knowledge_sync = (
                os.getenv("GATEWAY_SKIP_KNOWLEDGE_SYNC") or ""
            ).strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            if skip_knowledge_sync:
                logger.info(
                    "Skipping knowledge snapshot sync (GATEWAY_SKIP_KNOWLEDGE_SYNC=1)"
                )
            else:
                try:
                    try:
                        from dependencies import get_sync_service  # type: ignore

                        sync_service = get_sync_service()
                        await sync_service.sync_knowledge_snapshot()
                    except Exception as exc:
                        _append_boot_error(f"knowledge_snapshot_sync_failed:{exc}")
                        logger.warning(
                            "Knowledge snapshot sync failed (best-effort): %s", exc
                        )
                except Exception as exc:  # noqa: BLE001
                    _append_boot_error(f"notion_sync_failed:{exc}")
                    logger.warning("Notion knowledge snapshot sync failed: %s", exc)

            _BOOT_READY = True
            logger.info("System boot completed. READY.")
            logger.info("SSOT boot complete")
        except Exception:
            _BOOT_READY = False
            raise


async def _shutdown_best_effort() -> None:
    global _BOOT_READY
    global ai_command_service, coo_translation_service, coo_conversation_service
    global _execution_registry, _execution_orchestrator

    try:
        ns = try_get_notion_service()
        if ns is not None:
            close_fn = getattr(ns, "aclose", None)
            if callable(close_fn):
                await close_fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("NotionService shutdown close failed: %s", exc)

    ai_command_service = None
    coo_translation_service = None
    coo_conversation_service = None
    _execution_registry = None
    _execution_orchestrator = None

    _BOOT_READY = False
    logger.info("System shutdown — boot_ready=False.")


def _is_boot_exempt_path(path: str) -> bool:
    p = (path or "").strip()
    if not p:
        return True
    if p in {"/health", "/health/services", "/ready", "/", "/favicon.ico"}:
        return True
    if p.startswith("/docs") or p.startswith("/openapi") or p.startswith("/redoc"):
        return True
    if p.startswith("/assets") or p.startswith("/static"):
        return True
    if p in {"/api/ceo-console/status", "/ceo-console/status"}:
        return True
    return False


async def _ensure_boot_if_needed(request: Request) -> None:
    if _BOOT_READY:
        return
    if _is_boot_exempt_path(request.url.path):
        return
    try:
        await _boot_once()
    except Exception:
        raise HTTPException(
            status_code=503, detail=_BOOT_ERROR or "System not ready"
        ) from None


# ================================================================
# LIFESPAN
# ================================================================
@asynccontextmanager
async def lifespan(_: FastAPI):
    await _boot_once()
    try:
        yield
    finally:
        await _shutdown_best_effort()


# ================================================================
# APP INIT
# ================================================================
app = FastAPI(
    title=SYSTEM_NAME,
    version=VERSION,
    lifespan=lifespan,
)


@app.on_event("startup")
async def _startup_event() -> None:
    # Minimal diagnostics for staging: do NOT log secret values.
    try:
        import openai  # type: ignore

        openai_ver = getattr(openai, "__version__", "unknown")
    except Exception:
        openai_ver = "unavailable"

    logger.info(
        "STARTUP_DIAG openai_version=%s env_present={OPENAI_API_KEY:%s,CEO_ADVISOR_ASSISTANT_ID:%s,NOTION_OPS_ASSISTANT_ID:%s} OPENAI_API_MODE=%s",
        openai_ver,
        bool((os.getenv("OPENAI_API_KEY") or "").strip()),
        bool((os.getenv("CEO_ADVISOR_ASSISTANT_ID") or "").strip()),
        bool((os.getenv("NOTION_OPS_ASSISTANT_ID") or "").strip()),
        (os.getenv("OPENAI_API_MODE") or "").strip() or "(unset)",
    )

    # Optional fail-fast for local/dev: validate OpenAI auth early to avoid
    # wasting time on reload/child-process env mismatches.
    vff = (os.getenv("OPENAI_FAIL_FAST_ON_STARTUP") or "").strip().lower()
    if vff in {"1", "true", "yes", "on"}:
        try:
            from openai import OpenAI, AuthenticationError  # type: ignore
            from services.agent_router.openai_key_diag import get_openai_key_diag

            d = get_openai_key_diag()
            api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
            if not api_key:
                raise RuntimeError(
                    "OPENAI_FAIL_FAST_ON_STARTUP=1 but OPENAI_API_KEY is missing"
                )

            base_url = d.get("base_url")
            client = (
                OpenAI(api_key=api_key, base_url=base_url)
                if base_url
                else OpenAI(api_key=api_key)
            )

            # Validate the same runtime family used in logs (chat.completions).
            model = (
                os.getenv("OPENAI_RESPONSES_MODEL") or ""
            ).strip() or "gpt-4.1-mini"
            await __import__("asyncio").to_thread(
                client.chat.completions.create,
                model=model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
        except Exception as exc:  # noqa: BLE001
            try:
                from openai import AuthenticationError  # type: ignore

                if isinstance(exc, AuthenticationError):
                    status = getattr(exc, "status_code", None)
                    resp = getattr(exc, "response", None)
                    if status is None and resp is not None:
                        status = getattr(resp, "status_code", None)

                    body = getattr(exc, "body", None)
                    code = None
                    if isinstance(body, dict):
                        err0 = body.get("error")
                        if isinstance(err0, dict):
                            code = err0.get("code")

                    if int(status or 0) == 401 and str(code or "") == "invalid_api_key":
                        from services.agent_router.openai_key_diag import (
                            get_openai_key_diag,
                        )

                        d = get_openai_key_diag()
                        logger.error(
                            "[OPENAI_FAIL_FAST] Authentication failed: status=401 code=invalid_api_key fp=%s source=%s mode=%s base_url=%s",
                            d.get("fingerprint"),
                            d.get("source"),
                            d.get("mode"),
                            d.get("base_url"),
                        )
                        logger.error(
                            "[OPENAI_FAIL_FAST] Fix by setting OPENAI_API_KEY in the process that starts uvicorn (reload spawns a child); prefer repo-root .env or set env before starting."
                        )
                        raise RuntimeError(
                            "OpenAI auth failed on startup (401 invalid_api_key). "
                            f"fp={d.get('fingerprint')} source={d.get('source')} mode={d.get('mode')} base_url={d.get('base_url')}"
                        ) from None
            except Exception:
                # If detection fails, do not block startup.
                pass
    await _boot_once()


@app.on_event("shutdown")
async def _shutdown_event() -> None:
    await _shutdown_best_effort()


# ================================================================
# REQUEST TRACE
# ================================================================
@app.middleware("http")
async def request_trace_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.req_id = req_id

    await _ensure_boot_if_needed(request)

    try:
        resp = await call_next(request)
        resp.headers["X-Request-ID"] = req_id
        return resp
    except Exception:
        logger.exception("REQ_FAIL req_id=%s path=%s", req_id, request.url.path)
        raise


# ================================================================
# RESPONSE CONTRACT ENFORCER (NO INTERNAL TEXT LEAK)
#
# Production bug: internal/system boilerplate (e.g. assistant memory template)
# must never be shown as the user-facing `text` in /api/chat.
#
# This middleware is intentionally narrow:
# - Only inspects JSON responses for /api/chat (and compatible chat aliases).
# - Only triggers on known internal memory-boilerplate markers.
# - Skips when the user explicitly asked about memory/snapshot/governance.
# - On trigger: moves text to metadata.debug.internal_system_text and replaces
#   `text` with a safe deterministic answer; also clears sticky meta-intent.
# ================================================================

_INTERNAL_MEMORY_BOILERPLATE_MARKERS: Tuple[str, ...] = (
    "Vrste pamćenja koje koristim",
    "Imam dvije vrste pamćenja",
    "Kratkoročno:",
    "Dugoročno",
    "WRITE ide",
    "propose → approve → execute",
)

# NEW PROD INCIDENT (verbatim): CEO Advisor intro/how-to-ask template leaked to user-visible text.
# Marker set must expand ONLY from real prod snippets.
_INTERNAL_CEO_INTRO_TEMPLATE_MARKERS: Tuple[str, ...] = (
    "Ja sam CEO Advisor u ovom workspace-u",
    "Kako radim:",
    "Kako da pitaš:",
)

_LEAK_GUARD_LOCK = threading.Lock()
_LAST_INTERNAL_TEMPLATE_HASH_BY_SESSION: Dict[str, str] = {}


def _bhs_normalize(text: str) -> str:
    t0 = (text or "").strip().lower()
    return (
        t0.replace("č", "c")
        .replace("ć", "c")
        .replace("š", "s")
        .replace("đ", "dj")
        .replace("ž", "z")
    )


def _user_explicitly_asked_memory_or_snapshot(prompt: str) -> bool:
    t = _bhs_normalize(prompt)
    if not t:
        return False
    return bool(
        re.search(
            r"(?i)\b(pamcenj\w*|memorij\w*|snapshot|grounding|governance|sistemsk\w*\s+tekst|system\s+text)\b",
            t,
        )
    )


def _user_explicitly_asked_identity_or_howto(prompt: str) -> bool:
    t = _bhs_normalize(prompt)
    if not t:
        return False

    # Enterprise hardening: do not allowlist long pasted content (e.g., plan text).
    # Meta questions should be short and explicit.
    if len(t) > 300:
        return False

    # Never allowlist plan-analysis prompts.
    if re.search(r"(?i)\b(plan|analiz\w*|analysis|review|procitaj)\b", t):
        return False

    # Strict allowlist (enterprise): only allow intro/how-to template when explicitly asked.
    return bool(
        re.search(
            r"(?i)\b("
            r"ko\s+si|"
            r"sta\s+si|"
            r"\u0161ta\s+si|"
            r"kako\s+radis|"
            r"kako\s+da\s+pitam|"
            r"uputstv\w*|"
            r"help|guidelines|"
            r"who\s+are\s+you|how\s+do\s+you\s+work|how\s+to\s+ask"
            r")\b",
            t,
        )
    )


def _is_canonical_ceo_advisor_identity_response(*, body_obj: Dict[str, Any]) -> bool:
    """True only for the canonical CEO Advisor identity response.

    Bypass is intentionally strict to avoid re-allowing intro-template leaks in
    non-identity contexts (e.g. plan/review). We only bypass when server-side
    metadata says this is the assistant-identity intent.
    """

    if not isinstance(body_obj, dict):
        return False

    # Explicit server-side override (if present).
    tr = body_obj.get("trace")
    if isinstance(tr, dict) and tr.get("canonical_identity") is True:
        return True

    agent_id = str(body_obj.get("agent_id") or "").strip()
    if agent_id != "ceo_advisor":
        return False

    if not isinstance(tr, dict):
        return False

    return str(tr.get("intent") or "").strip() == "assistant_identity"


def _looks_like_internal_memory_boilerplate(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False

    # Require at least one of the unique memory boilerplate headers AND one supporting marker.
    has_header = (
        "Vrste pamćenja koje koristim" in s
        or "Imam dvije vrste pamćenja" in s
        or "Memory types I use" in s
        or "I have two kinds of memory" in s
    )
    if not has_header:
        return False

    supporting = 0
    for m in _INTERNAL_MEMORY_BOILERPLATE_MARKERS:
        if m in s:
            supporting += 1

    return supporting >= 2


def _looks_like_internal_ceo_intro_template(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False

    # Enterprise invariant (exact markers):
    # - If it contains the unique intro line, treat as the template.
    # - Otherwise require both section headers.
    if _INTERNAL_CEO_INTRO_TEMPLATE_MARKERS[0] in s:
        return True
    return (
        _INTERNAL_CEO_INTRO_TEMPLATE_MARKERS[1] in s
        and _INTERNAL_CEO_INTRO_TEMPLATE_MARKERS[2] in s
    )


def sanitize_user_visible_answer(
    *,
    body_obj: Dict[str, Any],
    prompt: str,
    session_id: str,
    conversation_id: str,
) -> Optional[Dict[str, Any]]:
    """Enforce enterprise response contract for user-visible assistant text.

    - Sanitizes known internal templates from the outgoing `text` field.
    - Allowlist decisions MUST be based only on the current user prompt.
    - On sanitize: move leaked text to metadata.debug.internal_system_text,
      replace `text` with deterministic read-only content, and clear sticky meta.

    Returns a new dict if changes are applied, else None.
    """

    if not isinstance(body_obj, dict):
        return None

    text = body_obj.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    is_memory_tpl = _looks_like_internal_memory_boilerplate(text)
    is_intro_tpl = _looks_like_internal_ceo_intro_template(text)
    if not (is_memory_tpl or is_intro_tpl):
        return None

    # HOTFIX: If this is already the canonical CEO Advisor identity answer, do not
    # sanitize it into a generic fallback.
    if is_intro_tpl and _is_canonical_ceo_advisor_identity_response(body_obj=body_obj):
        return None

    # Allow meta explanations only when explicitly requested in THIS turn.
    if is_memory_tpl and _user_explicitly_asked_memory_or_snapshot(prompt):
        return None
    if is_intro_tpl and _user_explicitly_asked_identity_or_howto(prompt):
        return None

    # Anti-loop bookkeeping: if we detect the same internal template repeatedly,
    # treat as mode-lock and clear sticky meta intent.
    tpl_hash = ""
    try:
        import hashlib

        tpl_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    except Exception:
        tpl_hash = ""

    if session_id and tpl_hash:
        with _LEAK_GUARD_LOCK:
            prev = _LAST_INTERNAL_TEMPLATE_HASH_BY_SESSION.get(session_id)
            _LAST_INTERNAL_TEMPLATE_HASH_BY_SESSION[session_id] = tpl_hash
            if prev == tpl_hash and conversation_id:
                _clear_sticky_meta_intent(conversation_id)

    if conversation_id:
        _clear_sticky_meta_intent(conversation_id)

    out = dict(body_obj)

    md = out.get("metadata")
    md = md if isinstance(md, dict) else {}
    dbg = md.get("debug")
    dbg = dbg if isinstance(dbg, dict) else {}
    dbg.setdefault("internal_system_text", text)
    md["debug"] = dbg
    out["metadata"] = md
    out["text"] = _safe_replacement_text_for_prompt(prompt)
    return out


def _safe_replacement_text_for_prompt(prompt: str) -> str:
    # Prefer a deterministic, domain-specific replacement when possible.
    try:
        from services.ceo_advisor_agent import (  # noqa: PLC0415
            _is_agent_registry_question,
            _render_agent_registry_text,
        )

        if _is_agent_registry_question(prompt):
            return _render_agent_registry_text(english_output=False)
    except Exception:
        pass

    # Deterministic plan-review fallback (read-only): provide actionable feedback
    # without any system/snapshot boilerplate.
    t = _bhs_normalize(prompt)
    if t and (
        ("plan" in t)
        or ("procitaj" in t)
        or ("reci mi sta mislis" in t)
        or ("sta mislis" in t)
        or ("feedback" in t)
        or ("povratn" in t)
        or ("slabost" in t)
    ):
        if re.search(r"(?i)\bslabost\w*\b", t):
            return (
                "Evo 3 moguće slabosti u planu (read-only feedback):\n"
                "1) Nisu jasno definisani mjerljivi KPI-jevi / kriterij uspjeha.\n"
                "2) Rizici i pretpostavke nisu eksplicitno navedeni (i bez plana mitigacije).\n"
                "3) Naredni koraci nisu razbijeni na vlasnika, rok i prioritet.\n\n"
                "Ako pošalješ konkretan dio plana (cilj, tržište, budžet, rok), mogu precizirati komentare."
            )

        return (
            "Evo brzog feedbacka na plan (read-only):\n\n"
            "Snage:\n"
            "- Imaš jasnu namjeru i strukturu (vidi se smjer).\n"
            "- Postoji osnova za prioritetizaciju i izvedbu.\n\n"
            "Poboljšanja (konkretno):\n"
            "1) Dodaj 2–3 mjerljive metrike uspjeha (KPI) i pragove.\n"
            "2) Eksplicitno napiši rizike + pretpostavke i kako ih mitigiraš.\n"
            "3) Razbij naredne korake na: vlasnik → rok → ishod.\n"
        )

    # Generic read-only safe guidance (no system/snapshot leakage).
    return (
        "Mogu pomoći u read-only modu. Reci mi cilj i kontekst (npr. šta pokušavaš postići, rok i ograničenja), "
        "pa ću predložiti konkretne naredne korake."
    )


def _clear_sticky_meta_intent(conversation_id: str) -> None:
    cid = (conversation_id or "").strip()
    if not cid:
        return
    try:
        from services.ceo_conversation_state_store import (  # noqa: PLC0415
            ConversationStateStore,
        )

        ConversationStateStore.update_meta(
            conversation_id=cid,
            updates={
                "assistant_last_meta_intent": None,
                "assistant_last_meta_intent_at": 0.0,
            },
        )
    except Exception:
        pass


@app.middleware("http")
async def prevent_internal_text_leak_middleware(request: Request, call_next):
    # Apply contract enforcement globally for POST JSON responses.
    # This covers all frontend chat entrypoints (including legacy wrappers),
    # and avoids missing /api-less aliases.
    if (request.method or "").upper() != "POST":
        return await call_next(request)

    # Best-effort extract prompt + ids from request JSON.
    prompt = ""
    session_id = (request.headers.get("X-Session-Id") or "").strip()
    conversation_id = ""
    try:
        raw = await request.body()
        if raw:
            req_obj = json.loads(raw.decode("utf-8"))
            if isinstance(req_obj, dict):
                prompt = str(
                    req_obj.get("message")
                    or req_obj.get("input_text")
                    or req_obj.get("text")
                    or ""
                )
                conversation_id = str(req_obj.get("conversation_id") or "").strip()
                sid0 = str(req_obj.get("session_id") or "").strip()
                if sid0:
                    session_id = sid0
    except Exception:
        pass

    if not conversation_id:
        conversation_id = session_id

    resp = await call_next(request)

    ctype = (resp.headers.get("content-type") or "").lower()
    if "application/json" not in ctype:
        return resp

    # Extract body bytes (works for JSONResponse and StreamingResponse).
    body_bytes: bytes = b""
    consumed_iterator = False
    try:
        body_attr = getattr(resp, "body", None)
        if isinstance(body_attr, (bytes, bytearray, memoryview)):
            body_bytes = bytes(body_attr)

        if (not body_bytes) and hasattr(resp, "body_iterator"):
            chunks: List[bytes] = []
            async for chunk in resp.body_iterator:  # type: ignore[attr-defined]
                if isinstance(chunk, (bytes, bytearray)):
                    chunks.append(bytes(chunk))
            body_bytes = b"".join(chunks)
            consumed_iterator = True
    except Exception:
        return resp

    if not body_bytes:
        return resp

    # If we consumed the iterator, we must rebuild the response; otherwise downstream
    # (TestClient/proxies) will receive an empty body.
    if consumed_iterator:
        rebuilt = Response(
            content=body_bytes,
            status_code=resp.status_code,
            media_type=getattr(resp, "media_type", None),
            background=getattr(resp, "background", None),
        )
        for k, v in resp.headers.items():
            if k.lower() == "content-length":
                continue
            rebuilt.headers[k] = v
        resp = rebuilt

    try:
        body_obj = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return resp

    if not isinstance(body_obj, dict):
        return resp

    text = body_obj.get("text")
    if not isinstance(text, str) or not text.strip():
        return resp

    sanitized = sanitize_user_visible_answer(
        body_obj=body_obj,
        prompt=prompt,
        session_id=session_id,
        conversation_id=conversation_id,
    )
    if sanitized is None:
        return resp

    # Rebuild JSON response, preserving headers/status.
    new_resp = JSONResponse(content=sanitized, status_code=resp.status_code)
    for k, v in resp.headers.items():
        if k.lower() == "content-length":
            continue
        new_resp.headers[k] = v
    return new_resp


# ================================================================
# CORS
# ================================================================
def _parse_origins(env_value: str) -> List[str]:
    return [o.strip() for o in (env_value or "").split(",") if o.strip()]


cors_origins: List[str] = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
cors_origins += _parse_origins(os.getenv("CORS_ORIGINS", ""))

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================================================================
# REQUEST MODELS
# ================================================================
class ExecuteInput(BaseModel):
    text: str


class ExecuteRawInput(BaseModel):
    command: str
    intent: str
    params: Dict[str, Any] = Field(default_factory=dict)


class CeoCommandInput(BaseModel):
    input_text: str
    smart_context: Optional[Dict[str, Any]] = None
    source: str = "ceo_dashboard"


class ProposalExecuteInput(BaseModel):
    proposal: Any
    initiator: str = "ceo"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecuteRawInput2(BaseModel):
    command: str
    intent: str
    params: Dict[str, Any] = Field(default_factory=dict)
    initiator: str = "ceo"
    read_only: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NotionReadResponse(BaseModel):
    ok: bool
    title: Optional[str] = None
    notion_url: Optional[str] = None
    content_markdown: Optional[str] = None
    error: Optional[str] = None


# ================================================================
# HELPERS
# ================================================================
def _preprocess_ceo_nl_input(
    raw_text: str, smart_context: Optional[Dict[str, Any]]
) -> str:
    text = (raw_text or "").strip()
    if not text:
        return text

    if smart_context:
        command_type = smart_context.get("command_type")
        goal_ctx = smart_context.get("goal") or {}
        goal_name = (goal_ctx.get("name") or "").strip()
        priority = (goal_ctx.get("priority") or "").strip()
        status = (goal_ctx.get("status") or "").strip()
        due = (goal_ctx.get("due") or "").strip()
        project = (goal_ctx.get("project") or "").strip()

        if command_type == "create_goal" and goal_name:
            parts: List[str] = [goal_name]
            if priority:
                parts.append(f"prioritet {priority}")
            if status:
                parts.append(f"status {status}")
            if due:
                parts.append(f"due {due}")
            if project:
                parts.append(f"projekt {project}")
            return ", ".join(parts)

    cleaned = re.sub(
        r"^(kreiraj|napravi|create)\s+cilj[a]?(?:\s+u\s+notionu)?\s*[:\-–—,;]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or text


def _derive_legacy_goal_task_summaries_from_ceo_snapshot(
    ceo_dash_snapshot: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    goals_summary: List[Dict[str, Any]] = []
    tasks_summary: List[Dict[str, Any]] = []

    try:
        dashboard = (
            ceo_dash_snapshot.get("dashboard")
            if isinstance(ceo_dash_snapshot, dict)
            else None
        )
        if not isinstance(dashboard, dict):
            return {"goals_summary": goals_summary, "tasks_summary": tasks_summary}

        goals = dashboard.get("goals") or []
        tasks = dashboard.get("tasks") or []

        if isinstance(goals, list):
            for g in goals:
                if not isinstance(g, dict):
                    continue
                goals_summary.append(
                    {
                        "name": g.get("name") or g.get("title") or "(bez naziva)",
                        "status": g.get("status") or "-",
                        "priority": g.get("priority") or "-",
                        "due_date": g.get("deadline")
                        or g.get("due_date")
                        or g.get("due")
                        or "-",
                    }
                )

        if isinstance(tasks, list):
            for t in tasks:
                if not isinstance(t, dict):
                    continue
                tasks_summary.append(
                    {
                        "title": t.get("title") or t.get("name") or "(bez naziva)",
                        "status": t.get("status") or "-",
                        "priority": t.get("priority") or "-",
                        "due_date": t.get("due_date")
                        or t.get("deadline")
                        or t.get("due")
                        or "-",
                    }
                )
    except Exception:
        pass

    return {"goals_summary": goals_summary, "tasks_summary": tasks_summary}


def _ensure_list(x: Any) -> List[Any]:
    return x if isinstance(x, list) else []


def _ensure_dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _ensure_str(x: Any) -> str:
    return x if isinstance(x, str) else ""


def _proposal_wrapper_dict(*, prompt: str, source: str) -> Dict[str, Any]:
    safe_prompt = (prompt or "").strip() or "noop"
    return {
        "command": PROPOSAL_WRAPPER_INTENT,  # ceo.command.propose
        "args": {"prompt": safe_prompt},
        "intent": PROPOSAL_WRAPPER_INTENT,
        "reason": "Notion write intent ide kroz approval pipeline; predlažem komandu za promotion/execute.",
        "dry_run": True,
        "requires_approval": True,
        "risk": "LOW",
        "scope": "api_execute_raw",
        "payload_summary": {
            "endpoint": "/api/execute/raw",
            "canon": "CEO_CONSOLE_EXECUTION_FLOW",
            "source": source,
        },
    }


def _normalize_gateway_proposed_commands(pcs: Any) -> List[Dict[str, Any]]:
    items = _ensure_list(pcs)
    out: List[Dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict):
            out.append(it)
            continue
        if hasattr(it, "model_dump"):
            try:
                d = it.model_dump(by_alias=False)  # type: ignore[attr-defined]
                if isinstance(d, dict):
                    out.append(d)
                    continue
            except Exception:
                pass
        if hasattr(it, "dict"):
            try:
                d = it.dict()  # type: ignore[attr-defined]
                if isinstance(d, dict):
                    out.append(d)
                    continue
            except Exception:
                pass
    return out


def _inject_fallback_proposed_commands(result: Dict[str, Any], *, prompt: str) -> None:
    pcs = result.get("proposed_commands")
    pcs_list = _normalize_gateway_proposed_commands(pcs)

    # If backend already provided proposals, just normalize and exit.
    if len(pcs_list) > 0:
        result["proposed_commands"] = pcs_list
        tr0 = _ensure_dict(result.get("trace"))
        tr0.setdefault("fallback_proposed_commands", False)
        tr0.setdefault("router_version", "gateway-proposed-commands-normalize-v1")
        result["trace"] = tr0
        return

    text = (prompt or "").strip().lower()
    # Conservative write intent: require BOTH an action verb and an explicit write target.
    # This prevents advisory prompts like "napravim plan" from being misrouted as write proposals.
    action = bool(
        re.search(
            r"(?i)\b(create|kreiraj|napravi|dodaj|update|azuriraj|izmijeni|promijeni|delete|obrisi|ukloni)\b",
            text,
        )
    )
    target = bool(
        re.search(
            r"(?i)\b(task|zadatak|goal|cilj|project|projekat|notion)\b",
            text,
        )
    )
    write_like = bool(action and target)

    if not write_like:
        result["proposed_commands"] = []
        tr = _ensure_dict(result.get("trace"))
        tr["fallback_proposed_commands"] = False
        tr["router_version"] = "gateway-fallback-proposals-disabled-for-nonwrite-v1"
        result["trace"] = tr
        return

    # CANON FALLBACK (SSOT): emit notion_write envelope directly (NO ceo.command.propose wrapper).
    pc = {
        "command": PROPOSAL_WRAPPER_INTENT,  # ceo.command.propose
        "intent": PROPOSAL_WRAPPER_INTENT,  # ceo.command.propose
        "dry_run": True,
        "requires_approval": True,
        "risk": "LOW",
        "scope": "api_execute_raw",
        "params": {
            "ai_command": {
                # Keep prompt so backend can translate later if needed.
                "intent": PROPOSAL_WRAPPER_INTENT,
                "prompt": (prompt or "").strip(),
                "target": None,
                "operations": [],
            }
        },
        "payload_summary": {
            "endpoint": "/api/execute/raw",
            "canon": "CEO_CONSOLE_EXECUTION_FLOW",
            "source": "ceo_console",
        },
        "reason": "Approval required (write intent detected).",
    }

    result["proposed_commands"] = [pc]

    tr = _ensure_dict(result.get("trace"))
    tr["fallback_proposed_commands"] = True
    tr["router_version"] = "gateway-fallback-proposed-commands-writeonly-v2-canon"
    result["trace"] = tr


def _compute_confidence_risk_block(
    *,
    prompt: str,
    trace: Dict[str, Any],
    proposed_commands: List[Dict[str, Any]],
) -> Dict[str, Any]:
    tr = trace if isinstance(trace, dict) else {}
    pcs = proposed_commands if isinstance(proposed_commands, list) else []

    fallback = bool(tr.get("fallback_proposed_commands") is True)

    assumption_count = 1 if fallback else 0

    risk_level = "low"
    if len(pcs) > 0:
        risk_level = "medium"

    for p in pcs:
        if not isinstance(p, dict):
            continue
        r = (p.get("risk") or p.get("risk_hint") or "").strip().lower()
        if r in {"high", "critical"}:
            risk_level = "high"
            break

    confidence_score = 0.90
    if fallback:
        confidence_score = 0.60

    if not (prompt or "").strip():
        confidence_score = min(confidence_score, 0.50)

    try:
        confidence_score_f = float(confidence_score)
    except Exception:
        confidence_score_f = 0.50
    if confidence_score_f < 0.0:
        confidence_score_f = 0.0
    if confidence_score_f > 1.0:
        confidence_score_f = 1.0

    if risk_level not in {"low", "medium", "high"}:
        risk_level = "low"

    if not isinstance(assumption_count, int) or assumption_count < 0:
        assumption_count = 0

    return {
        "confidence_score": confidence_score_f,
        "risk_level": risk_level,
        "assumption_count": assumption_count,
    }


# ===========================
# PHASE A FIX: robust normalize
# ===========================
def _normalize_execute_raw_payload_dict(body: Dict[str, Any]) -> ExecuteRawInput2:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")

    cmd = (
        body.get("command")
        or body.get("name")
        or body.get("command_type")
        or body.get("type")
        or ""
    )
    if not isinstance(cmd, str) or not cmd.strip():
        raise HTTPException(status_code=422, detail="Field 'command' is required")
    cmd = cmd.strip()

    intent_val = body.get("intent")
    if isinstance(intent_val, str) and intent_val.strip():
        intent = intent_val.strip()
    else:
        intent = cmd

    params = body.get("params")
    if not isinstance(params, dict):
        params = {}

    if not params:
        args0 = body.get("args")
        if isinstance(args0, dict):
            params = dict(args0)

    if not params:
        payload0 = body.get("payload")
        if isinstance(payload0, dict):
            params = dict(payload0)

    # Compatibility: some proposals wrap the real executable command under params.ai_command.
    # Example (observed from CEO Console proposals):
    #   { command: "notion_write", intent: "notion_write", params: { ai_command: { command:"notion_write", intent:"create_page", params:{...} } } }
    # If we don't unwrap, the orchestrator will attempt to execute intent="notion_write" and NotionService will reject it.
    if isinstance(params, dict):
        ac = params.get("ai_command")
        if isinstance(ac, dict):
            ac_cmd = ac.get("command")
            ac_intent = ac.get("intent")
            ac_params = ac.get("params")
            ac_args = ac.get("args")

            # Unwrap only when ai_command looks like an actual command envelope.
            if (
                isinstance(ac_cmd, str)
                and ac_cmd.strip()
                and (isinstance(ac_params, dict) or isinstance(ac_args, dict))
            ):
                cmd = ac_cmd.strip()
                if isinstance(ac_intent, str) and ac_intent.strip():
                    intent = ac_intent.strip()
                else:
                    intent = cmd

                if isinstance(ac_params, dict):
                    params = dict(ac_params)
                elif isinstance(ac_args, dict):
                    params = dict(ac_args)

    if (
        (intent == PROPOSAL_WRAPPER_INTENT or cmd == PROPOSAL_WRAPPER_INTENT)
        and "prompt" not in params
        and not (
            isinstance(params, dict)
            and isinstance(params.get("schema_version"), str)
            and params.get("schema_version") == "memory_write.v1"
        )
    ):
        args = body.get("args")
        if isinstance(args, dict):
            prompt = args.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                params["prompt"] = prompt.strip()

        if "prompt" not in params:
            payload = body.get("payload")
            if isinstance(payload, dict):
                prompt = payload.get("prompt")
                if isinstance(prompt, str) and prompt.strip():
                    params["prompt"] = prompt.strip()

        if "prompt" not in params:
            prompt = body.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                params["prompt"] = prompt.strip()

    initiator = body.get("initiator")
    if not isinstance(initiator, str) or not initiator.strip():
        initiator = "ceo"
    else:
        initiator = initiator.strip()

    read_only = bool(body.get("read_only") or False)

    metadata = body.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    # Merge envelope metadata if present.
    if isinstance(body.get("params"), dict):
        ac0 = body["params"].get("ai_command")
        if isinstance(ac0, dict) and isinstance(ac0.get("metadata"), dict):
            merged_md = dict(ac0.get("metadata") or {})
            merged_md.update(metadata)
            metadata = merged_md

    payload_summary = body.get("payload_summary")
    if isinstance(payload_summary, dict):
        merged = dict(payload_summary)
        merged.update(metadata)
        metadata = merged

    metadata.setdefault("canon", "CEO_CONSOLE_EXECUTION_FLOW")
    metadata.setdefault("endpoint", "/api/execute/raw")
    metadata.setdefault("source", metadata.get("source") or "ceo_console")

    return ExecuteRawInput2(
        command=cmd,
        intent=intent,
        params=params,
        initiator=initiator,
        read_only=read_only,
        metadata=metadata,
    )


def _notion_properties_preview_from_property_specs(
    property_specs: Dict[str, Any],
) -> Dict[str, Any]:
    """Best-effort preview of the Notion `properties` payload.

    IMPORTANT:
      - No Notion schema lookups and no network calls.
      - Mirrors the core mapping logic in NotionService for common types.
      - Execution-time schema normalization (status vs select, option name
        resolution) may still adjust the final payload.
    """
    out: Dict[str, Any] = {}
    if not isinstance(property_specs, dict) or not property_specs:
        return out

    for prop_name, spec in property_specs.items():
        if not isinstance(prop_name, str) or not prop_name.strip():
            continue
        if not isinstance(spec, dict):
            continue

        pn = prop_name.strip()
        stype = _ensure_str(spec.get("type")).lower()

        if stype == "title":
            txt = _ensure_str(spec.get("text") or spec.get("value") or "")
            out[pn] = {"title": [{"text": {"content": txt.strip()}}]}
            continue

        if stype in ("rich_text", "text"):
            txt = _ensure_str(spec.get("text") or spec.get("value") or "")
            out[pn] = {"rich_text": [{"text": {"content": txt.strip()}}]}
            continue

        if stype == "select":
            name = _ensure_str(spec.get("name") or spec.get("value") or "").strip()
            out[pn] = {"select": {"name": name}} if name else {"select": None}
            continue

        if stype == "status":
            name = _ensure_str(spec.get("name") or spec.get("value") or "").strip()
            out[pn] = {"status": {"name": name}} if name else {"status": None}
            continue

        if stype == "date":
            date_str = _ensure_str(spec.get("start") or spec.get("value") or "").strip()
            out[pn] = {"date": {"start": date_str}} if date_str else {"date": None}
            continue

        if stype == "number":
            raw_n = spec.get("number")
            if raw_n is None:
                raw_n = spec.get("value")
            try:
                out[pn] = {"number": float(raw_n)}
            except Exception:
                # ignore invalid
                pass
            continue

        if stype == "checkbox":
            raw_v = spec.get("checkbox")
            if raw_v is None:
                raw_v = spec.get("value")
            v = raw_v
            if isinstance(v, str):
                sv = v.strip().lower()
                if sv in {"true", "yes", "da", "1"}:
                    v = True
                elif sv in {"false", "no", "ne", "0"}:
                    v = False
            if isinstance(v, bool):
                out[pn] = {"checkbox": v}
            continue

        if stype == "multi_select":
            raw_names = spec.get("names")
            names: List[str] = []
            if isinstance(raw_names, list):
                names = [
                    _ensure_str(x).strip() for x in raw_names if _ensure_str(x).strip()
                ]
            else:
                s_val = _ensure_str(spec.get("value") or "").strip()
                if s_val:
                    names = [x.strip() for x in s_val.split(",") if x.strip()]
            out[pn] = (
                {"multi_select": [{"name": n} for n in names]}
                if names
                else {"multi_select": []}
            )
            continue

        if stype == "relation":
            raw_ids = spec.get("ids")
            ids: List[str] = []
            if isinstance(raw_ids, list):
                ids = [
                    _ensure_str(x).strip() for x in raw_ids if _ensure_str(x).strip()
                ]
            else:
                raw_one = spec.get("id") or spec.get("value") or ""
                s_one = _ensure_str(raw_one).strip()
                if s_one:
                    ids = [x.strip() for x in s_one.split(",") if x.strip()]
            out[pn] = (
                {"relation": [{"id": x} for x in ids]} if ids else {"relation": []}
            )
            continue

        if stype == "people":
            raw_ids = spec.get("ids")
            ids: List[str] = []
            if isinstance(raw_ids, list):
                ids = [
                    _ensure_str(x).strip() for x in raw_ids if _ensure_str(x).strip()
                ]
            if ids:
                out[pn] = {"people": [{"id": x} for x in ids]}
                continue

            tokens: List[str] = []
            for key in ("emails", "names"):
                raw_list = spec.get(key)
                if isinstance(raw_list, list):
                    tokens.extend(
                        [
                            _ensure_str(x).strip()
                            for x in raw_list
                            if _ensure_str(x).strip()
                        ]
                    )
            if not tokens:
                raw_value = spec.get("value") or spec.get("name") or ""
                s_val = _ensure_str(raw_value).strip()
                if s_val:
                    tokens = [t.strip() for t in s_val.split(",") if t.strip()]

            out[pn] = (
                {"people": [{"name": t} for t in tokens]} if tokens else {"people": []}
            )
            continue

        # Unknown types ignored by design
        continue

    return out


def _sanitize_property_specs_for_preview(
    *, db_key: Optional[str], property_specs: Dict[str, Any]
) -> Dict[str, Any]:
    """Sanitize property_specs for preview UI.

    - Drops computed types (formula/rollup/etc.)
    - Drops registry read_only properties (local SSOT)
    - No network calls
    """
    if not isinstance(property_specs, dict) or not property_specs:
        return {}

    computed_types = {
        "formula",
        "rollup",
        "created_time",
        "last_edited_time",
        "created_by",
        "last_edited_by",
        "unique_id",
    }

    read_only_cf: set[str] = set()
    try:
        from services.notion_schema_registry import (  # noqa: PLC0415
            NotionSchemaRegistry,
        )

        k = (db_key or "").strip().lower()
        if k:
            # tolerate singular/plural
            candidates = [k]
            if k.endswith("s"):
                candidates.append(k[:-1])
            else:
                candidates.append(k + "s")
            db_entry = None
            for cand in candidates:
                v = NotionSchemaRegistry.DATABASES.get(cand)
                if isinstance(v, dict):
                    db_entry = v
                    break
            props = db_entry.get("properties") if isinstance(db_entry, dict) else None
            if isinstance(props, dict):
                for pn, meta in props.items():
                    if (
                        isinstance(pn, str)
                        and isinstance(meta, dict)
                        and meta.get("read_only") is True
                    ):
                        read_only_cf.add(pn.strip().casefold())
    except Exception:
        read_only_cf = set()

    out: Dict[str, Any] = {}
    for pn, spec in property_specs.items():
        if not isinstance(pn, str) or not pn.strip():
            continue
        if not isinstance(spec, dict):
            continue

        stype = _ensure_str(spec.get("type")).strip().lower()
        if stype in computed_types:
            continue

        if pn.strip().casefold() in read_only_cf:
            continue

        out[pn.strip()] = spec

    return out


def _notion_patch_validation_mode() -> str:
    """Global validation mode.

    - warn (default): surface warnings, never blocks.
    - strict: treat key validation issues as errors.
    """

    v = os.getenv("NOTION_PATCH_VALIDATION_MODE") or os.getenv("NOTION_VALIDATION_MODE")
    v = (v or "").strip().lower()
    return "strict" if v == "strict" else "warn"


# ================================================================
# /api/execute — EXECUTION PATH (NL INPUT)
# ================================================================
@app.post("/api/execute")
async def execute_command(payload: ExecuteInput):
    cleaned_text = _preprocess_ceo_nl_input(payload.text, smart_context=None)

    _, trans, _, registry, orchestrator = _require_boot_services()

    ai_command = trans.translate(
        raw_input=cleaned_text,
        source="system",
        context={"mode": "execute"},
    )

    if not ai_command:
        req = ceo_console_module.CEOCommandRequest(
            text=cleaned_text,
            initiator="api_execute_fallback",
            session_id=None,
            context_hint={"source": "api_execute"},
        )

        advice = await ceo_console_module.ceo_command(req)

        return {
            "status": "COMPLETED",
            "execution_state": "COMPLETED",
            "mode": "ceo_advisory",
            "channel": "ceo_console",
            "advisory": advice,
        }

    if not getattr(ai_command, "initiator", None):
        ai_command.initiator = "ceo"

    execution_id = _ensure_execution_id(ai_command)

    approval_state = get_approval_state()
    approval = approval_state.create(
        command=getattr(ai_command, "command", None) or "execute",
        payload_summary=_safe_command_summary(ai_command),
        scope="api_execute",
        risk_level="unknown",
        execution_id=execution_id,
    )
    approval_id = approval.get("approval_id")
    if not approval_id:
        raise HTTPException(
            status_code=500, detail="Approval create failed: missing approval_id"
        )

    _ensure_trace_on_command(ai_command, approval_id=approval_id)

    orchestrator.registry.register(ai_command)
    registry.register(ai_command)

    result = await orchestrator.execute(ai_command)

    if isinstance(result, dict):
        result.setdefault("approval_id", approval_id)
        result.setdefault("execution_id", execution_id)

    return result


@app.post("/api/execute/raw")
async def execute_raw_command(payload: Dict[str, Any] = Body(...)):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")

    enterprise_enabled = _enterprise_preview_editor_enabled()
    patches_in = payload.get("patches") if isinstance(payload, dict) else None

    normalized = _normalize_execute_raw_payload_dict(payload)

    # Read-only directive: refresh_snapshot should execute immediately and return
    # deterministic meta so UI can refresh without going through approvals.
    if (normalized.intent == "refresh_snapshot") or (
        normalized.command == "refresh_snapshot"
    ):
        try:
            _, _, _, registry, orchestrator = _require_boot_services()
        except HTTPException as exc:
            ks = KnowledgeSnapshotService.get_snapshot()
            snapshot_meta = {
                "schema_version": ks.get("schema_version"),
                "status": ks.get("status"),
                "generated_at": ks.get("generated_at"),
                "last_sync": ks.get("last_sync"),
                "expired": bool(ks.get("expired")),
                "ready": bool(ks.get("ready")),
                "ttl_seconds": ks.get("ttl_seconds"),
                "age_seconds": ks.get("age_seconds"),
            }

            # Contract: never return result:null; include deterministic error object.
            return {
                "status": "FAILED",
                "execution_state": "FAILED",
                "read_only": True,
                "execution_id": str(uuid.uuid4()),
                "approval_id": None,
                "command": normalized.command or "refresh_snapshot",
                "intent": normalized.intent or "refresh_snapshot",
                "snapshot_meta": snapshot_meta,
                "result": {
                    "ok": False,
                    "success": False,
                    "read_only": True,
                    "intent": "refresh_snapshot",
                    "error": str(getattr(exc, "detail", "boot_not_ready")),
                    "error_type": "boot_not_ready",
                    "snapshot_meta": snapshot_meta,
                    "knowledge_snapshot": ks,
                    "trace": {
                        "canon": "execute_raw_refresh_snapshot_fail_soft",
                        "endpoint": "/api/execute/raw",
                        "reason": "boot_services_unavailable",
                    },
                },
            }

        ai_command = AICommand(
            command=normalized.command or "refresh_snapshot",
            intent=normalized.intent or "refresh_snapshot",
            params=normalized.params if isinstance(normalized.params, dict) else {},
            initiator=normalized.initiator,
            read_only=True,
            metadata=normalized.metadata
            if isinstance(normalized.metadata, dict)
            else {},
        )
        ai_command.read_only = True
        _ensure_execution_id(ai_command)

        orchestrator.registry.register(ai_command)
        registry.register(ai_command)

        out = await orchestrator.execute(ai_command)

        ks = KnowledgeSnapshotService.get_snapshot()
        snapshot_meta = {
            "schema_version": ks.get("schema_version"),
            "status": ks.get("status"),
            "generated_at": ks.get("generated_at"),
            "last_sync": ks.get("last_sync"),
            "expired": bool(ks.get("expired")),
            "ready": bool(ks.get("ready")),
            "ttl_seconds": ks.get("ttl_seconds"),
            "age_seconds": ks.get("age_seconds"),
        }

        if not isinstance(out, dict):
            return {
                "status": "FAILED",
                "execution_state": "FAILED",
                "read_only": True,
                "execution_id": getattr(ai_command, "execution_id", None),
                "approval_id": None,
                "command": getattr(ai_command, "command", None),
                "intent": getattr(ai_command, "intent", None),
                "snapshot_meta": snapshot_meta,
                "result": {
                    "ok": False,
                    "success": False,
                    "error": "invalid_orchestrator_response",
                    "snapshot_meta": snapshot_meta,
                    "knowledge_snapshot": ks,
                },
            }

        out.setdefault("result", {})
        if isinstance(out.get("result"), dict):
            out["result"].setdefault("snapshot_meta", snapshot_meta)
            out["result"].setdefault("knowledge_snapshot", ks)

        exec_state = out.get("execution_state")
        status = (
            "COMPLETED" if exec_state == "COMPLETED" else (exec_state or "COMPLETED")
        )

        return {
            "status": status,
            "execution_state": exec_state or "COMPLETED",
            "read_only": True,
            "execution_id": out.get("execution_id")
            or getattr(ai_command, "execution_id", None),
            "approval_id": out.get("approval_id"),
            "command": getattr(ai_command, "command", None),
            "intent": getattr(ai_command, "intent", None),
            "snapshot_meta": snapshot_meta,
            "result": out.get("result"),
            "failure": out.get("failure"),
            "ok": out.get("ok"),
            "text": out.get("text"),
            "trace": out.get("trace"),
        }

    if (normalized.intent in _HARD_READ_ONLY_INTENTS) or (
        normalized.command in _HARD_READ_ONLY_INTENTS
    ):
        execution_id = str(uuid.uuid4())
        return {
            "status": "COMPLETED",
            "execution_state": "COMPLETED",
            "read_only": True,
            "execution_id": execution_id,
            "approval_id": None,
            "command": normalized.command,
            "intent": normalized.intent,
            "params": normalized.params if isinstance(normalized.params, dict) else {},
            "proposed_commands": [],
            "trace": {
                "canon": "execute_raw_hard_block_read_only",
                "endpoint": "/api/execute/raw",
                "hard_block_intent": normalized.intent,
                "hard_block_command": normalized.command,
                "note": "next_step hard-block only; wrapper intents proceed to unwrap+approval",
            },
        }

    _, _, _, registry, orchestrator = _require_boot_services()

    ai_command = _unwrap_proposal_wrapper_or_raise(
        command=normalized.command,
        intent=normalized.intent,
        params=normalized.params if isinstance(normalized.params, dict) else {},
        initiator=normalized.initiator,
        read_only=normalized.read_only,
        metadata=normalized.metadata if isinstance(normalized.metadata, dict) else {},
    )

    # Enterprise preview editor: apply the same server-side patches at execution creation time.
    # This guarantees the registered canonical command (later resumed by approval) is 1:1.
    if enterprise_enabled and patches_in is not None:
        patch_issues_by_op_id: Dict[str, List[Dict[str, Any]]] = {}
        patch_global_issues: List[Dict[str, Any]] = []

        if not (
            getattr(ai_command, "command", None) == "notion_write"
            and getattr(ai_command, "intent", None)
            in {"batch_request", "batch", "branch_request"}
        ):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "validation_failed",
                    "message": "Patches are only supported for Notion batch proposals.",
                    "validation": {
                        "mode": "strict",
                        "issues": [
                            {
                                "severity": "error",
                                "code": "patches_not_supported",
                                "source": "patches",
                                "message": "Patches are only supported for Notion batch proposals.",
                            }
                        ],
                        "can_approve": False,
                        "summary": {"errors": 1, "warnings": 0},
                    },
                },
            )

        params0 = getattr(ai_command, "params", None)
        params0 = params0 if isinstance(params0, dict) else {}
        ops0 = params0.get("operations")
        if not isinstance(ops0, list) or not ops0:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "validation_failed",
                    "message": "Patches require a non-empty operations list.",
                    "validation": {
                        "mode": "strict",
                        "issues": [
                            {
                                "severity": "error",
                                "code": "missing_operations",
                                "source": "patches",
                                "message": "Missing operations[] for batch patching.",
                            }
                        ],
                        "can_approve": False,
                        "summary": {"errors": 1, "warnings": 0},
                    },
                },
            )

        try:
            from services.enterprise_preview_patches import (  # noqa: PLC0415
                apply_patches_to_batch_operations,
            )
            from services.notion_schema_registry import (  # noqa: PLC0415
                NotionSchemaRegistry,
            )
            from services.notion_patch_validation import (  # noqa: PLC0415
                merge_validation_reports,
                validate_notion_payload,
            )

            db_keys0: List[str] = []
            for op0 in ops0:
                if not isinstance(op0, dict):
                    continue
                pl0 = op0.get("payload")
                pl0 = pl0 if isinstance(pl0, dict) else {}
                dk0 = pl0.get("db_key")
                if isinstance(dk0, str) and dk0.strip():
                    db_keys0.append(dk0.strip())
                else:
                    oi0 = (op0.get("intent") or "").strip().lower()
                    if oi0 == "create_goal":
                        db_keys0.append("goals")
                    elif oi0 == "create_task":
                        db_keys0.append("tasks")
                    elif oi0 == "create_project":
                        db_keys0.append("projects")

            db_keys0 = [k for k in [str(x).strip() for x in db_keys0] if k]
            db_keys0 = list(dict.fromkeys(db_keys0))
            schema_by_db_key = {
                dk: NotionSchemaRegistry.offline_validation_schema(dk)
                for dk in db_keys0
            }

            patched_ops, issues_by_op, global_issues = (
                apply_patches_to_batch_operations(
                    operations=[op for op in ops0 if isinstance(op, dict)],
                    patches=patches_in,
                    schema_by_db_key=schema_by_db_key,
                )
            )

            patch_issues_by_op_id = (
                issues_by_op if isinstance(issues_by_op, dict) else {}
            )
            patch_global_issues = (
                global_issues if isinstance(global_issues, list) else []
            )

            # Install patched operations as the canonical executable command.
            params_new = dict(params0)
            params_new["operations"] = patched_ops
            ai_command.params = params_new

            # Fail-closed strict validation for patched operations.
            per_op_reports: List[Dict[str, Any]] = []
            for op1 in patched_ops:
                if not isinstance(op1, dict):
                    continue
                op_id1 = op1.get("op_id") if isinstance(op1.get("op_id"), str) else None
                op_intent1 = (op1.get("intent") or "").strip()
                pl1 = op1.get("payload")
                pl1 = pl1 if isinstance(pl1, dict) else {}

                db_key1 = (
                    pl1.get("db_key") if isinstance(pl1.get("db_key"), str) else None
                )
                if not db_key1:
                    oi1 = op_intent1.strip().lower()
                    if oi1 == "create_goal":
                        db_key1 = "goals"
                    elif oi1 == "create_task":
                        db_key1 = "tasks"
                    elif oi1 == "create_project":
                        db_key1 = "projects"

                schema1 = schema_by_db_key.get(db_key1 or "") if db_key1 else {}
                if not isinstance(schema1, dict) or not schema1:
                    schema1 = (
                        NotionSchemaRegistry.offline_validation_schema(db_key1 or "")
                        if db_key1
                        else {}
                    )

                ps1 = pl1.get("property_specs")
                ps1 = ps1 if isinstance(ps1, dict) else {}

                base_report = validate_notion_payload(
                    db_key=(db_key1 or ""),
                    schema=schema1 if isinstance(schema1, dict) else {},
                    wrapper_patch=None,
                    property_specs=ps1,
                    mode="strict",
                )

                extra = None
                if op_id1 and op_id1 in patch_issues_by_op_id:
                    extra_issues = patch_issues_by_op_id.get(op_id1)
                    if isinstance(extra_issues, list) and extra_issues:
                        errs = sum(
                            1
                            for it in extra_issues
                            if isinstance(it, dict) and it.get("severity") == "error"
                        )
                        warns = sum(
                            1
                            for it in extra_issues
                            if isinstance(it, dict) and it.get("severity") == "warning"
                        )
                        extra = {
                            "mode": "strict",
                            "db_key": (db_key1 or "").strip() or None,
                            "issues": extra_issues,
                            "can_approve": errs == 0,
                            "summary": {"errors": errs, "warnings": warns},
                        }

                per_op_reports.append(
                    merge_validation_reports(base_report, extra)
                    if isinstance(extra, dict)
                    else base_report
                )

            merged = merge_validation_reports(*per_op_reports)
            if patch_global_issues:
                its = (
                    merged.get("issues")
                    if isinstance(merged.get("issues"), list)
                    else []
                )
                its = list(its) + [
                    x for x in patch_global_issues if isinstance(x, dict)
                ]
                merged["issues"] = its
                merged["summary"] = {
                    "errors": sum(1 for it in its if it.get("severity") == "error"),
                    "warnings": sum(1 for it in its if it.get("severity") == "warning"),
                }
                merged["can_approve"] = merged["summary"].get("errors", 0) == 0

            if merged.get("can_approve") is False:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "validation_failed",
                        "message": "Validation failed for enterprise preview patches.",
                        "validation": merged,
                    },
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "validation_failed",
                    "message": "Failed to apply/validate enterprise preview patches.",
                    "validation": {
                        "mode": "strict",
                        "issues": [
                            {
                                "severity": "error",
                                "code": "patch_apply_failed",
                                "source": "patches",
                                "message": "Failed to apply/validate patches.",
                            }
                        ],
                        "can_approve": False,
                        "summary": {"errors": 1, "warnings": 0},
                    },
                },
            )

    # Strict-mode validation: block creation of executions that would be rejected later.
    # Default is warn-only (no blocking) unless NOTION_PATCH_VALIDATION_MODE=strict.
    try:
        if (
            _notion_patch_validation_mode() == "strict"
            and getattr(ai_command, "command", None) == "notion_write"
        ):
            intent0 = getattr(ai_command, "intent", None)
            params0 = getattr(ai_command, "params", None)
            params0 = params0 if isinstance(params0, dict) else {}

            db_key0: Optional[str] = None
            if intent0 in {"create_goal"}:
                db_key0 = "goals"
            elif intent0 in {"create_task"}:
                db_key0 = "tasks"
            elif intent0 in {"create_project"}:
                db_key0 = "projects"
            elif intent0 in {"create_page", "update_page"}:
                dk = params0.get("db_key")
                if isinstance(dk, str) and dk.strip():
                    db_key0 = dk.strip()

            if db_key0:
                wrapper_patch0 = params0.get("wrapper_patch")
                wrapper_patch0 = (
                    wrapper_patch0 if isinstance(wrapper_patch0, dict) else None
                )

                property_specs0: Dict[str, Any] = {}
                if intent0 in {"create_page", "update_page"}:
                    raw_specs0 = (
                        params0.get("property_specs")
                        or params0.get("properties")
                        or params0.get("notion_properties")
                    )
                    if isinstance(raw_specs0, dict):
                        property_specs0 = dict(raw_specs0)
                else:
                    # Mirror preview mapping for create_goal/create_task/create_project.
                    title0 = _ensure_str(params0.get("title")).strip()
                    desc0 = _ensure_str(params0.get("description")).strip()
                    deadline0 = _ensure_str(params0.get("deadline")).strip()
                    priority0 = _ensure_str(params0.get("priority")).strip()
                    status0 = _ensure_str(params0.get("status")).strip()
                    if title0:
                        property_specs0["Name"] = {"type": "title", "text": title0}
                    if desc0:
                        property_specs0["Description"] = {
                            "type": "rich_text",
                            "text": desc0,
                        }
                    if deadline0:
                        property_specs0["Deadline"] = {
                            "type": "date",
                            "start": deadline0,
                        }
                    if priority0:
                        property_specs0["Priority"] = {
                            "type": "select",
                            "name": priority0,
                        }
                    if status0:
                        property_specs0["Status"] = {"type": "status", "name": status0}
                    extra0 = params0.get("property_specs")
                    if isinstance(extra0, dict) and extra0:
                        property_specs0.update(extra0)

                try:
                    from services.notion_service import get_or_init_notion_service  # noqa: PLC0415

                    svc0 = get_or_init_notion_service()
                    schema0 = (
                        await svc0.get_fields_schema(db_key0)
                        if svc0 is not None
                        else {}
                    )
                except Exception:
                    schema0 = {}

                try:
                    from services.notion_patch_validation import (  # noqa: PLC0415
                        fallback_schema_for_db_key,
                        validate_notion_payload,
                    )

                    if not isinstance(schema0, dict) or not schema0:
                        schema0 = fallback_schema_for_db_key(db_key0)

                    report0 = validate_notion_payload(
                        db_key=db_key0,
                        schema=schema0 if isinstance(schema0, dict) else {},
                        wrapper_patch=wrapper_patch0,
                        property_specs=property_specs0,
                        mode="strict",
                    )
                    if (
                        isinstance(report0, dict)
                        and report0.get("can_approve") is False
                    ):
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "error": "validation_failed",
                                "message": "Strict validation failed for Notion payload.",
                                "validation": report0,
                            },
                        )
                except HTTPException:
                    raise
                except Exception:
                    # Do not fail hard on validator errors.
                    pass
    except HTTPException:
        raise
    except Exception:
        pass

    # CRITICAL: wrapper unwrapping may yield a meta-command (next_step).
    # Hard-block those *after* unwrap so they never enter approval/execution.
    if (getattr(ai_command, "intent", None) in _HARD_READ_ONLY_INTENTS) or (
        getattr(ai_command, "command", None) in _HARD_READ_ONLY_INTENTS
    ):
        execution_id = _ensure_execution_id(ai_command)
        return {
            "status": "COMPLETED",
            "execution_state": "COMPLETED",
            "read_only": True,
            "execution_id": execution_id,
            "approval_id": None,
            "text": "Need more information before executing. Please answer the CEO Console questions, then retry.",
            "command": getattr(ai_command, "command", None),
            "intent": getattr(ai_command, "intent", None),
            "params": getattr(ai_command, "params", None)
            if isinstance(getattr(ai_command, "params", None), dict)
            else {},
            "proposed_commands": [],
            "trace": {
                "canon": "execute_raw_hard_block_after_unwrap",
                "endpoint": "/api/execute/raw",
                "hard_block_intent": getattr(ai_command, "intent", None),
                "hard_block_command": getattr(ai_command, "command", None),
            },
        }

    execution_id = _ensure_execution_id(ai_command)

    approval_state = get_approval_state()

    # PHASE A FIX: robust scope/risk extraction
    scope_val = payload.get("scope") or payload.get("scope_hint") or "api_execute_raw"
    risk_val = (
        payload.get("risk")
        or payload.get("risk_level")
        or payload.get("risk_hint")
        or "unknown"
    )

    approval = approval_state.create(
        command=getattr(ai_command, "command", None) or "execute_raw",
        payload_summary=_safe_command_summary(ai_command),
        scope=scope_val,
        risk_level=risk_val,
        execution_id=execution_id,
    )

    approval_id = approval.get("approval_id")
    if not approval_id:
        raise HTTPException(
            status_code=500, detail="Approval create failed: missing approval_id"
        )

    _ensure_trace_on_command(ai_command, approval_id=approval_id)

    orchestrator.registry.register(ai_command)
    registry.register(ai_command)

    return {
        "status": "BLOCKED",
        "execution_state": "BLOCKED",
        "approval_id": approval_id,
        "execution_id": execution_id,
        "command": (
            ai_command.model_dump()
            if hasattr(ai_command, "model_dump")
            else _to_serializable(ai_command)
        ),
    }


@app.post("/api/execute/preview")
async def execute_preview_command(
    request: Request, payload: Dict[str, Any] = Body(...)
):
    """Preview the *exact* command payload (no approvals, no execution).

    Intended for CEO Console UI so the user can confirm Notion mapping
    (property_specs -> properties) before hitting Approve.
    """
    if not _is_ceo_request(request):
        raise HTTPException(
            status_code=403, detail="This endpoint is restricted to CEO users only"
        )
    _require_ceo_token_if_enforced(request)

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")

    enterprise_enabled = _enterprise_preview_editor_enabled()
    patches_in = payload.get("patches") if isinstance(payload, dict) else None

    normalized = _normalize_execute_raw_payload_dict(payload)

    # Hard read-only intents stay read-only.
    if (normalized.intent in _HARD_READ_ONLY_INTENTS) or (
        normalized.command in _HARD_READ_ONLY_INTENTS
    ):
        return {
            "ok": True,
            "read_only": True,
            "command": {
                "command": normalized.command,
                "intent": normalized.intent,
                "params": normalized.params
                if isinstance(normalized.params, dict)
                else {},
                "initiator": normalized.initiator,
                "metadata": normalized.metadata
                if isinstance(normalized.metadata, dict)
                else {},
            },
            "notion": None,
            "trace": {
                "canon": "execute_preview_hard_block_read_only",
                "endpoint": "/api/execute/preview",
            },
        }

    # Read-only directive: refresh_snapshot preview
    if (normalized.intent == "refresh_snapshot") or (
        normalized.command == "refresh_snapshot"
    ):
        return {
            "ok": True,
            "read_only": True,
            "command": {
                "command": normalized.command or "refresh_snapshot",
                "intent": normalized.intent or "refresh_snapshot",
                "params": normalized.params
                if isinstance(normalized.params, dict)
                else {},
                "initiator": normalized.initiator,
                "metadata": normalized.metadata
                if isinstance(normalized.metadata, dict)
                else {},
            },
            "notion": None,
            "review": None,
            "trace": {
                "canon": "execute_preview_refresh_snapshot",
                "endpoint": "/api/execute/preview",
                "intent": "refresh_snapshot",
            },
        }

    ai_command = _unwrap_proposal_wrapper_or_raise(
        command=normalized.command,
        intent=normalized.intent,
        params=normalized.params if isinstance(normalized.params, dict) else {},
        initiator=normalized.initiator,
        read_only=True,
        metadata=normalized.metadata if isinstance(normalized.metadata, dict) else {},
    )

    patch_issues_by_op_id: Dict[str, List[Dict[str, Any]]] = {}
    patch_global_issues: List[Dict[str, Any]] = []
    force_validation_mode: Optional[str] = None

    # Enterprise preview editor: optional patches applied server-side.
    if enterprise_enabled and patches_in is not None:
        try:
            if getattr(ai_command, "command", None) == "notion_write" and getattr(
                ai_command, "intent", None
            ) in {"batch_request", "batch", "branch_request"}:
                params0 = getattr(ai_command, "params", None)
                params0 = params0 if isinstance(params0, dict) else {}
                ops0 = params0.get("operations")
                if isinstance(ops0, list) and ops0:
                    from services.enterprise_preview_patches import (  # noqa: PLC0415
                        apply_patches_to_batch_operations,
                    )
                    from services.notion_schema_registry import (  # noqa: PLC0415
                        NotionSchemaRegistry,
                    )

                    db_keys0: List[str] = []
                    for op0 in ops0:
                        if not isinstance(op0, dict):
                            continue
                        pl0 = op0.get("payload")
                        pl0 = pl0 if isinstance(pl0, dict) else {}
                        dk0 = pl0.get("db_key")
                        if isinstance(dk0, str) and dk0.strip():
                            db_keys0.append(dk0.strip())
                        else:
                            oi0 = (op0.get("intent") or "").strip().lower()
                            if oi0 == "create_goal":
                                db_keys0.append("goals")
                            elif oi0 == "create_task":
                                db_keys0.append("tasks")
                            elif oi0 == "create_project":
                                db_keys0.append("projects")

                    db_keys0 = [k for k in [str(x).strip() for x in db_keys0] if k]
                    db_keys0 = list(dict.fromkeys(db_keys0))
                    schema_by_db_key = {
                        dk: NotionSchemaRegistry.offline_validation_schema(dk)
                        for dk in db_keys0
                    }

                    patched_ops, issues_by_op, global_issues = (
                        apply_patches_to_batch_operations(
                            operations=[op for op in ops0 if isinstance(op, dict)],
                            patches=patches_in,
                            schema_by_db_key=schema_by_db_key,
                        )
                    )

                    patch_issues_by_op_id = (
                        issues_by_op if isinstance(issues_by_op, dict) else {}
                    )
                    patch_global_issues = (
                        global_issues if isinstance(global_issues, list) else []
                    )
                    force_validation_mode = "strict"

                    params_new = dict(params0)
                    params_new["operations"] = patched_ops
                    ai_command.params = params_new
                else:
                    patch_global_issues.append(
                        {
                            "severity": "error",
                            "code": "patches_not_supported",
                            "source": "patches",
                            "message": "Patches are only supported for batch operations.",
                        }
                    )
                    force_validation_mode = "strict"
            else:
                patch_global_issues.append(
                    {
                        "severity": "error",
                        "code": "patches_not_supported",
                        "source": "patches",
                        "message": "Patches are only supported for Notion batch proposals.",
                    }
                )
                force_validation_mode = "strict"
        except Exception:
            # Fail closed for approval: treat patch subsystem failure as a validation error.
            patch_global_issues.append(
                {
                    "severity": "error",
                    "code": "patch_apply_failed",
                    "source": "patches",
                    "message": "Failed to apply patches.",
                }
            )
            force_validation_mode = "strict"

    # Preview should always be treated as read-only.
    ai_command.read_only = True
    md = getattr(ai_command, "metadata", None)
    if not isinstance(md, dict):
        md = {}
    md["canon"] = "execute_preview"
    md["endpoint"] = "/api/execute/preview"
    md["preview"] = True
    ai_command.metadata = md

    cmd_dump = (
        ai_command.model_dump()
        if hasattr(ai_command, "model_dump")
        else _to_serializable(ai_command)
    )

    notion_block = None
    review_block = None

    # If this came from a proposal wrapper, we can deterministically provide a review schema
    # so UI can fill missing Status/Priority/Deadline/etc before approval.
    try:
        from services.review_contract import detect_write_create_review_contract  # noqa: PLC0415

        prompt = None
        md0 = getattr(ai_command, "metadata", None)
        if isinstance(md0, dict):
            w0 = md0.get("wrapper")
            if isinstance(w0, dict):
                p0 = w0.get("prompt")
                if isinstance(p0, str) and p0.strip():
                    prompt = p0.strip()

        if isinstance(prompt, str) and prompt.strip():
            ok, intent_type, missing_fields, fields_schema = (
                detect_write_create_review_contract(prompt)
            )
            if ok and isinstance(fields_schema, dict) and fields_schema:
                review_block = {
                    "type": "command_review",
                    "mode": "fill_missing" if missing_fields else "approve",
                    "title": "Complete fields before approval",
                    "summary": "Add or confirm Notion field values (Status/Priority/Deadline/etc).",
                    "missing_fields": missing_fields,
                    "fields_schema": fields_schema,
                }
    except Exception:
        review_block = None

    # Enterprise UX: always try to provide DB schema for table preview.
    async def _fallback_fields_schema(db_key: str) -> Dict[str, Any]:
        k = (db_key or "").strip().lower()
        base: Dict[str, Any] = {
            "Name": {"type": "title"},
            "Status": {"type": "status"},
            "Priority": {"type": "select"},
            "Deadline": {"type": "date"},
            "Due Date": {"type": "date"},
            "Description": {"type": "rich_text"},
        }
        # Deterministic options when we don't have live Notion schema.
        try:
            from services.review_contract import (  # noqa: PLC0415
                GOAL_STATUS_OPTIONS,
                KPI_STATUS_OPTIONS,
                PRIORITY_OPTIONS,
                PROJECT_STATUS_OPTIONS,
                TASK_STATUS_OPTIONS,
            )

            if "Priority" in base:
                base["Priority"].setdefault("options", list(PRIORITY_OPTIONS))
            if k in {"goals", "goal"}:
                base["Status"].setdefault("options", list(GOAL_STATUS_OPTIONS))
            elif k in {"tasks", "task"}:
                base["Status"].setdefault("options", list(TASK_STATUS_OPTIONS))
            elif k in {"projects", "project"}:
                base["Status"].setdefault("options", list(PROJECT_STATUS_OPTIONS))
            elif k in {"kpi", "kpis"}:
                base["Status"].setdefault("options", list(KPI_STATUS_OPTIONS))
        except Exception:
            pass
        if k in {"tasks", "task"}:
            base.setdefault("Goal", {"type": "relation"})
            base.setdefault("Project", {"type": "relation"})
            base.setdefault("Owner", {"type": "people"})
        if k in {"projects", "project"}:
            base.setdefault("Primary Goal", {"type": "relation"})
        return base

    async def _best_effort_fields_schema(db_key: str) -> Tuple[Dict[str, Any], str]:
        db_key = (db_key or "").strip()
        if not db_key:
            return {}, "none"
        try:
            from services.notion_service import get_or_init_notion_service  # noqa: PLC0415

            svc = get_or_init_notion_service()
            if svc is not None:
                schema = await svc.get_fields_schema(db_key)
                if isinstance(schema, dict) and schema:
                    return schema, "notion"
        except Exception:
            pass

        # Prefer offline SSOT schema when Notion schema can't be fetched.
        # This keeps preview/UI usable ("Show all" can list full field set) without new endpoints.
        try:
            from services.notion_schema_registry import (  # noqa: PLC0415
                NotionSchemaRegistry,
            )

            off = NotionSchemaRegistry.offline_validation_schema(db_key)
            if isinstance(off, dict) and off:
                return off, "offline"
        except Exception:
            pass

        fb = await _fallback_fields_schema(db_key)
        return (fb if isinstance(fb, dict) else {}), "fallback"

    # Determine DB keys involved so we can attach schema even if notion_block is empty.
    db_keys: List[str] = []
    try:
        if getattr(ai_command, "command", None) == "notion_write":
            intent0 = getattr(ai_command, "intent", None)
            params0 = getattr(ai_command, "params", None)
            params0 = params0 if isinstance(params0, dict) else {}

            if intent0 in {"create_goal"}:
                db_keys = ["goals"]
            elif intent0 in {"create_task"}:
                db_keys = ["tasks"]
            elif intent0 in {"create_project"}:
                db_keys = ["projects"]
            elif intent0 in {"create_page", "update_page"}:
                dk = params0.get("db_key")
                if isinstance(dk, str) and dk.strip():
                    db_keys = [dk.strip()]
            elif intent0 in {"batch_request", "batch", "branch_request"}:
                ops0 = params0.get("operations")
                if isinstance(ops0, list):
                    for op in ops0:
                        if not isinstance(op, dict):
                            continue
                        payload0 = op.get("payload")
                        payload0 = payload0 if isinstance(payload0, dict) else {}
                        dk = payload0.get("db_key")
                        if isinstance(dk, str) and dk.strip():
                            db_keys.append(dk.strip())
                        else:
                            oi = (op.get("intent") or "").strip().lower()
                            if oi == "create_goal":
                                db_keys.append("goals")
                            elif oi == "create_task":
                                db_keys.append("tasks")
                            elif oi == "create_project":
                                db_keys.append("projects")
    except Exception:
        db_keys = []

    # If we couldn't infer db keys from the translated command, infer from wrapper prompt.
    if not db_keys:
        try:
            prompt0 = None
            md0 = getattr(ai_command, "metadata", None)
            if isinstance(md0, dict):
                w0 = md0.get("wrapper")
                if isinstance(w0, dict):
                    p0 = w0.get("prompt")
                    if isinstance(p0, str) and p0.strip():
                        prompt0 = p0.strip()

            if isinstance(prompt0, str) and prompt0:
                from services.notion_keyword_mapper import NotionKeywordMapper  # noqa: PLC0415

                auto_intent = NotionKeywordMapper.detect_intent(prompt0)
                ai = (auto_intent or "").strip().lower()
                if ai == "create_goal":
                    db_keys = ["goals"]
                elif ai == "create_task":
                    db_keys = ["tasks"]
                elif ai == "create_project":
                    db_keys = ["projects"]

                # Heuristic: if prompt mentions both goal and task, attach both schemas.
                if not db_keys:
                    p_low = prompt0.lower()
                    has_goal = bool(re.search(r"\b(cilj\w*|goal\w*)\b", p_low))
                    has_task = bool(re.search(r"\b(zadat\w*|task\w*)\b", p_low))
                    if has_goal and has_task:
                        db_keys = ["goals", "tasks"]
        except Exception:
            pass

    # Normalize + de-dupe
    db_keys = [k for k in [str(x).strip() for x in db_keys] if k]
    db_keys = list(dict.fromkeys(db_keys))

    # Attach schema to review block (single union) and keep per-db map for debugging.
    try:
        if db_keys:
            union_schema: Dict[str, Any] = {}
            by_db: Dict[str, Any] = {}
            sources: Dict[str, str] = {}
            for dk in db_keys:
                sch, src = await _best_effort_fields_schema(dk)
                if isinstance(sch, dict) and sch:
                    by_db[dk] = sch
                    sources[dk] = src
                    for k, v in sch.items():
                        if k not in union_schema:
                            union_schema[k] = v

            if union_schema:
                if not isinstance(review_block, dict):
                    review_block = {
                        "type": "command_review",
                        "mode": "approve",
                        "title": "Notion schema",
                        "summary": "Notion database schema (best-effort) for preview/fill-missing.",
                        "missing_fields": [],
                        "fields_schema": union_schema,
                    }
                else:
                    fs0 = review_block.get("fields_schema")
                    # Merge (don't replace): review_contract may provide a minimal schema
                    # (e.g. Status/Priority only). For "Show all" UX, we want the full
                    # best-effort DB schema to be available while preserving any existing
                    # prompt-derived specs/options.
                    if not isinstance(fs0, dict) or not fs0:
                        review_block["fields_schema"] = union_schema
                    else:
                        merged: Dict[str, Any] = dict(fs0)
                        for k, v in union_schema.items():
                            if k not in merged:
                                merged[k] = v
                        review_block["fields_schema"] = merged
                review_block["fields_schema_by_db_key"] = by_db
                review_block["schema_source_by_db_key"] = sources
    except Exception:
        pass

    try:
        if getattr(ai_command, "command", None) == "notion_write":
            intent = getattr(ai_command, "intent", None)
            params = getattr(ai_command, "params", None)
            params = params if isinstance(params, dict) else {}

            wrapper_patch0 = params.get("wrapper_patch")
            wrapper_patch0 = (
                wrapper_patch0 if isinstance(wrapper_patch0, dict) else None
            )

            validation_mode = force_validation_mode or _notion_patch_validation_mode()

            async def _best_effort_schema_for_db_key(
                db_key: Optional[str],
            ) -> Dict[str, Any]:
                dk = (db_key or "").strip()
                if not dk:
                    return {}
                # Prefer schema already attached to review block.
                if isinstance(review_block, dict):
                    by_db0 = review_block.get("fields_schema_by_db_key")
                    if isinstance(by_db0, dict):
                        sch0 = by_db0.get(dk)
                        if isinstance(sch0, dict) and sch0:
                            return sch0

                # Fallback to offline SSOT schema (no Notion API calls).
                try:
                    from services.notion_schema_registry import (  # noqa: PLC0415
                        NotionSchemaRegistry,
                    )

                    return NotionSchemaRegistry.offline_validation_schema(dk)
                except Exception:
                    return {}

            async def _validation_for_preview(
                *, db_key: Optional[str], property_specs: Dict[str, Any]
            ) -> Optional[Dict[str, Any]]:
                dk = (db_key or "").strip()
                if not dk:
                    return None
                try:
                    from services.notion_patch_validation import (  # noqa: PLC0415
                        validate_notion_payload,
                    )

                    schema0 = await _best_effort_schema_for_db_key(dk)
                    return validate_notion_payload(
                        db_key=dk,
                        schema=schema0 if isinstance(schema0, dict) else {},
                        wrapper_patch=wrapper_patch0,
                        property_specs=property_specs,
                        mode=validation_mode,
                    )
                except Exception:
                    return None

            def _build_specs_for_preview(
                *,
                db_key: Optional[str],
                property_specs: Dict[str, Any],
            ) -> Dict[str, Any]:
                dk = (db_key or "").strip()
                if not dk:
                    return {
                        "property_specs": property_specs,
                        "wrapper_patch_out": dict(wrapper_patch0)
                        if isinstance(wrapper_patch0, dict)
                        else {},
                        "warnings": [],
                        "validated": True,
                    }

                try:
                    from services.notion_property_specs_builder import (  # noqa: PLC0415
                        validate_and_build_property_specs,
                    )

                    return validate_and_build_property_specs(
                        db_key=dk,
                        property_specs_in=property_specs,
                        wrapper_patch_in=wrapper_patch0
                        if isinstance(wrapper_patch0, dict)
                        else None,
                    )
                except Exception:
                    return {
                        "property_specs": property_specs,
                        "wrapper_patch_out": dict(wrapper_patch0)
                        if isinstance(wrapper_patch0, dict)
                        else {},
                        "warnings": [],
                        "validated": True,
                    }

            def _build_property_specs_from_payload(
                payload: Dict[str, Any],
            ) -> Dict[str, Any]:
                payload = payload if isinstance(payload, dict) else {}
                title = _ensure_str(
                    payload.get("title") or payload.get("name") or payload.get("Name")
                ).strip()
                description = _ensure_str(
                    payload.get("description") or payload.get("Description")
                ).strip()
                deadline = _ensure_str(
                    payload.get("deadline")
                    or payload.get("due_date")
                    or payload.get("Deadline")
                    or payload.get("Due Date")
                ).strip()
                priority = _ensure_str(
                    payload.get("priority") or payload.get("Priority")
                ).strip()
                status = _ensure_str(
                    payload.get("status") or payload.get("Status")
                ).strip()

                ps: Dict[str, Any] = {}
                if title:
                    ps["Name"] = {"type": "title", "text": title}
                if description:
                    ps["Description"] = {"type": "rich_text", "text": description}
                if deadline:
                    ps["Deadline"] = {"type": "date", "start": deadline}
                if priority:
                    ps["Priority"] = {"type": "select", "name": priority}
                if status:
                    ps["Status"] = {"type": "status", "name": status}

                extra_specs = payload.get("property_specs")
                if isinstance(extra_specs, dict) and extra_specs:
                    # Let explicit specs override derived ones.
                    ps.update(extra_specs)
                return ps

            # create_page/update_page carry property_specs directly.
            if intent in {"create_page", "update_page"}:
                db_key = params.get("db_key")
                raw_specs = (
                    params.get("property_specs")
                    or params.get("properties")
                    or params.get("notion_properties")
                )
                if isinstance(raw_specs, dict):
                    property_specs = _sanitize_property_specs_for_preview(
                        db_key=db_key, property_specs=raw_specs
                    )
                else:
                    property_specs = {}

                built = _build_specs_for_preview(
                    db_key=db_key, property_specs=property_specs
                )
                property_specs = _sanitize_property_specs_for_preview(
                    db_key=db_key,
                    property_specs=built.get("property_specs")
                    if isinstance(built.get("property_specs"), dict)
                    else {},
                )

                notion_block = {
                    "op_id": cmd_dump.get("op_id")
                    if isinstance(cmd_dump, dict)
                    else None,
                    "intent": intent,
                    "db_key": db_key,
                    "property_specs": property_specs,
                    "properties_preview": _notion_properties_preview_from_property_specs(
                        property_specs
                    ),
                    "build": {
                        "validated": bool(built.get("validated") is True),
                        "warnings": built.get("warnings")
                        if isinstance(built.get("warnings"), list)
                        else [],
                        "wrapper_patch_out": built.get("wrapper_patch_out")
                        if isinstance(built.get("wrapper_patch_out"), dict)
                        else {},
                    },
                    "validation": await _validation_for_preview(
                        db_key=db_key, property_specs=property_specs
                    ),
                    "note": "Preview does not hit Notion. Final execution may still normalize select/status types based on DB schema.",
                }

            # create_goal/create_task/create_project derive property_specs at execution time.
            elif intent in {"create_goal", "create_task", "create_project"}:
                db_key = (
                    "goals"
                    if intent == "create_goal"
                    else "tasks"
                    if intent == "create_task"
                    else "projects"
                )

                title = _ensure_str(params.get("title")).strip()
                description = _ensure_str(params.get("description")).strip()
                deadline = _ensure_str(params.get("deadline")).strip()
                priority = _ensure_str(params.get("priority")).strip()
                status = _ensure_str(params.get("status")).strip()

                property_specs: Dict[str, Any] = {}
                if title:
                    property_specs["Name"] = {"type": "title", "text": title}
                if description:
                    property_specs["Description"] = {
                        "type": "rich_text",
                        "text": description,
                    }
                if deadline:
                    property_specs["Deadline"] = {"type": "date", "start": deadline}
                if priority:
                    property_specs["Priority"] = {"type": "select", "name": priority}
                if status:
                    property_specs["Status"] = {"type": "status", "name": status}

                extra_specs = params.get("property_specs")
                if isinstance(extra_specs, dict) and extra_specs:
                    property_specs.update(extra_specs)

                built = _build_specs_for_preview(
                    db_key=db_key, property_specs=property_specs
                )

                property_specs = _sanitize_property_specs_for_preview(
                    db_key=db_key,
                    property_specs=built.get("property_specs")
                    if isinstance(built.get("property_specs"), dict)
                    else {},
                )

                notion_block = {
                    "op_id": cmd_dump.get("op_id")
                    if isinstance(cmd_dump, dict)
                    else None,
                    "intent": intent,
                    "db_key": db_key,
                    "property_specs": property_specs,
                    "properties_preview": _notion_properties_preview_from_property_specs(
                        property_specs
                    ),
                    "build": {
                        "validated": bool(built.get("validated") is True),
                        "warnings": built.get("warnings")
                        if isinstance(built.get("warnings"), list)
                        else [],
                        "wrapper_patch_out": built.get("wrapper_patch_out")
                        if isinstance(built.get("wrapper_patch_out"), dict)
                        else {},
                    },
                    "validation": await _validation_for_preview(
                        db_key=db_key, property_specs=property_specs
                    ),
                    "note": "Preview does not hit Notion. create_goal/create_task/create_project derive properties at execution time; this mirrors that mapping.",
                }

            # batch_request: preview each operation as a table row
            elif intent in {"batch_request", "batch", "branch_request"}:
                ops = params.get("operations")
                if isinstance(ops, list) and ops:
                    rows: List[Dict[str, Any]] = []

                    def _merge_patch_issues(
                        *,
                        base: Optional[Dict[str, Any]],
                        db_key: Optional[str],
                        op_id: Optional[str],
                    ) -> Optional[Dict[str, Any]]:
                        if not enterprise_enabled:
                            return base
                        oid = (op_id or "").strip()
                        if not oid:
                            return base
                        extra = patch_issues_by_op_id.get(oid)
                        if not isinstance(extra, list) or not extra:
                            return base

                        try:
                            from services.notion_patch_validation import (  # noqa: PLC0415
                                merge_validation_reports,
                            )

                            errs = sum(
                                1
                                for it in extra
                                if isinstance(it, dict)
                                and it.get("severity") == "error"
                            )
                            warns = sum(
                                1
                                for it in extra
                                if isinstance(it, dict)
                                and it.get("severity") == "warning"
                            )
                            extra_report = {
                                "mode": "strict",
                                "db_key": (db_key or "").strip() or None,
                                "issues": extra,
                                "can_approve": errs == 0,
                                "summary": {"errors": errs, "warnings": warns},
                            }
                            if isinstance(base, dict):
                                return merge_validation_reports(base, extra_report)
                            return merge_validation_reports(extra_report)
                        except Exception:
                            return base

                    def _format_ref(v: Any) -> Optional[str]:
                        if v is None:
                            return None
                        if isinstance(v, str):
                            s = v.strip()
                            if not s:
                                return None
                            # Convention used by BranchRequestHandler: "$op_id" references.
                            if s.startswith("$") and len(s) > 1:
                                return f"ref:{s[1:]}"
                            return s
                        # Keep non-string refs readable (numbers, dicts)
                        try:
                            return str(v)
                        except Exception:
                            return None

                    for idx, op in enumerate(ops):
                        if not isinstance(op, dict):
                            continue
                        op_id = op.get("op_id")
                        op_intent = (
                            _ensure_str(op.get("intent") or "").strip() or "unknown"
                        )
                        payload = op.get("payload")
                        payload = payload if isinstance(payload, dict) else {}

                        db_key = payload.get("db_key")
                        if not isinstance(db_key, str) or not db_key.strip():
                            db_key = (
                                "goals"
                                if op_intent == "create_goal"
                                else "tasks"
                                if op_intent == "create_task"
                                else "projects"
                                if op_intent == "create_project"
                                else None
                            )

                        # Try to build a Notion-like properties preview for create intents.
                        ps: Dict[str, Any] = {}
                        if op_intent in {
                            "create_goal",
                            "create_task",
                            "create_project",
                        }:
                            ps = _build_property_specs_from_payload(payload)
                        elif op_intent in {"create_page", "update_page"}:
                            sp0 = payload.get("property_specs") or payload.get(
                                "properties"
                            )
                            if isinstance(sp0, dict) and sp0:
                                ps = dict(sp0)

                        built_row = None
                        if ps and isinstance(db_key, str) and db_key.strip():
                            built_row = _build_specs_for_preview(
                                db_key=db_key, property_specs=ps
                            )
                            if isinstance(built_row, dict) and isinstance(
                                built_row.get("property_specs"), dict
                            ):
                                ps = built_row.get("property_specs")

                        ps = _sanitize_property_specs_for_preview(
                            db_key=db_key, property_specs=ps
                        )

                        row: Dict[str, Any] = {
                            "op_index": idx,
                            "op_id": op_id,
                            "intent": op_intent,
                            "db_key": db_key,
                        }

                        # Relationship hints (pre-execution): show readable refs even before Notion IDs exist.
                        goal_ref = _format_ref(
                            payload.get("goal_id") or payload.get("primary_goal_id")
                        )
                        project_ref = _format_ref(payload.get("project_id"))
                        parent_goal_ref = _format_ref(payload.get("parent_goal_id"))
                        if goal_ref:
                            row["Goal Ref"] = goal_ref
                        if project_ref:
                            row["Project Ref"] = project_ref
                        if parent_goal_ref:
                            row["Parent Goal Ref"] = parent_goal_ref

                        if ps:
                            row["property_specs"] = ps
                            row["properties_preview"] = (
                                _notion_properties_preview_from_property_specs(ps)
                            )
                            if isinstance(built_row, dict):
                                row["build"] = {
                                    "validated": bool(
                                        built_row.get("validated") is True
                                    ),
                                    "warnings": built_row.get("warnings")
                                    if isinstance(built_row.get("warnings"), list)
                                    else [],
                                    "wrapper_patch_out": built_row.get(
                                        "wrapper_patch_out"
                                    )
                                    if isinstance(
                                        built_row.get("wrapper_patch_out"), dict
                                    )
                                    else {},
                                }
                            row["validation"] = _merge_patch_issues(
                                base=await _validation_for_preview(
                                    db_key=db_key, property_specs=ps
                                ),
                                db_key=db_key,
                                op_id=op_id if isinstance(op_id, str) else None,
                            )
                        rows.append(row)

                    # Summary for table UI.
                    errors = 0
                    warnings = 0
                    for r0 in rows:
                        v0 = r0.get("validation")
                        if not isinstance(v0, dict):
                            continue
                        s0 = v0.get("summary")
                        if isinstance(s0, dict):
                            try:
                                errors += int(s0.get("errors") or 0)
                            except Exception:
                                pass
                            try:
                                warnings += int(s0.get("warnings") or 0)
                            except Exception:
                                pass

                    global_errs = 0
                    global_warns = 0
                    if enterprise_enabled and patch_global_issues:
                        for it in patch_global_issues:
                            if not isinstance(it, dict):
                                continue
                            if it.get("severity") == "warning":
                                global_warns += 1
                            else:
                                global_errs += 1

                    notion_block = {
                        "type": "batch_preview",
                        "operations": (
                            (cmd_dump.get("params", {}).get("operations") or [])
                            if isinstance(cmd_dump, dict)
                            else []
                        ),
                        "rows": rows,
                        "validation": {
                            "mode": validation_mode,
                            "summary": {
                                "errors": errors + global_errs,
                                "warnings": warnings + global_warns,
                            },
                            "can_approve": (errors + global_errs) == 0,
                        },
                        "note": "Preview does not hit Notion. Final execution may still normalize select/status types based on DB schema.",
                    }

                    if enterprise_enabled:
                        notion_block["canonical_preview_operations"] = notion_block.get(
                            "operations"
                        )
                        if patch_global_issues:
                            notion_block["validation"]["issues"] = patch_global_issues
    except Exception:
        # Fail-closed: return a deterministic validation object so UI can block approval.
        notion_block = {
            "type": "preview_error",
            "validation": {
                "mode": "strict" if enterprise_enabled else validation_mode,
                "issues": [
                    {
                        "severity": "error",
                        "code": "preview_failed",
                        "source": "server",
                        "message": "Failed to build Notion preview.",
                    }
                ],
                "summary": {"errors": 1, "warnings": 0},
                "can_approve": False,
            },
            "note": "Preview failed; no execution can be approved from this response.",
        }

    return {
        "ok": True,
        "read_only": True,
        "command": cmd_dump,
        "notion": notion_block,
        "review": review_block,
        "trace": {
            "canon": "execute_preview",
            "endpoint": "/api/execute/preview",
            "preview_version": "2026-01-20-preview-v2",
            "server_version": VERSION,
        },
    }


# ================================================================
# /api/proposals/execute
# ================================================================
@app.post("/api/proposals/execute")
async def execute_proposal(payload: ProposalExecuteInput):
    proposal = payload.proposal
    initiator = (payload.initiator or "ceo").strip() or "ceo"
    meta_in = payload.metadata if isinstance(payload.metadata, dict) else {}

    _, _, _, registry, orchestrator = _require_boot_services()

    proposal_cmd: Optional[str] = None
    proposal_intent: Optional[str] = None
    proposal_params: Dict[str, Any] = {}
    proposal_meta: Dict[str, Any] = {}

    if isinstance(proposal, dict):
        proposal_cmd = (
            proposal.get("command")
            or proposal.get("command_type")
            or proposal.get("type")
        )
        proposal_intent = proposal.get("intent") or proposal_cmd

        p_params = proposal.get("params")
        if isinstance(p_params, dict):
            proposal_params = dict(p_params)

        if not proposal_params:
            p_args = proposal.get("args")
            if isinstance(p_args, dict):
                proposal_params = dict(p_args)
        if not proposal_params:
            p_payload = proposal.get("payload")
            if isinstance(p_payload, dict):
                proposal_params = dict(p_payload)

        p_md = proposal.get("metadata")
        if isinstance(p_md, dict):
            proposal_meta = dict(p_md)

        proposal_scope = proposal.get("scope")
        proposal_risk = proposal.get("risk") or proposal.get("risk_hint")
    else:
        proposal_cmd = (
            getattr(proposal, "command", None)
            or getattr(proposal, "command_type", None)
            or getattr(proposal, "type", None)
        )
        proposal_intent = getattr(proposal, "intent", None) or proposal_cmd

        p2 = getattr(proposal, "params", None)
        if isinstance(p2, dict):
            proposal_params = dict(p2)
        if not proposal_params:
            a2 = getattr(proposal, "args", None)
            if isinstance(a2, dict):
                proposal_params = dict(a2)
        if not proposal_params:
            pl2 = getattr(proposal, "payload", None)
            if isinstance(pl2, dict):
                proposal_params = dict(pl2)

        m2 = getattr(proposal, "metadata", None)
        if isinstance(m2, dict):
            proposal_meta = dict(m2)

        proposal_scope = getattr(proposal, "scope", None)
        proposal_risk = getattr(proposal, "risk", None) or getattr(
            proposal, "risk_hint", None
        )

    proposal_cmd = (proposal_cmd or "").strip() or None
    proposal_intent = (proposal_intent or "").strip() or None

    if not proposal_cmd or not proposal_intent:
        raise HTTPException(
            status_code=400, detail="Invalid proposal: missing command/intent"
        )

    if (
        proposal_cmd != PROPOSAL_WRAPPER_INTENT
        and proposal_intent != PROPOSAL_WRAPPER_INTENT
    ):
        raise HTTPException(
            status_code=400,
            detail="Unsupported proposal payload (only ceo.command.propose)",
        )

    merged_md: Dict[str, Any] = {}
    if isinstance(proposal_meta, dict):
        merged_md.update(proposal_meta)
    if isinstance(meta_in, dict):
        merged_md.update(meta_in)

    cr = None
    if isinstance(proposal_meta, dict):
        cr = proposal_meta.get("confidence_risk")
    if cr is None and isinstance(meta_in, dict):
        cr = meta_in.get("confidence_risk")

    if isinstance(cr, dict):
        merged_md["confidence_risk"] = cr

    ai_command = _unwrap_proposal_wrapper_or_raise(
        command=proposal_cmd,
        intent=proposal_intent,
        params=proposal_params if isinstance(proposal_params, dict) else {},
        initiator=initiator,
        read_only=False,
        metadata=merged_md,
    )

    # Same post-unwrapping hard-block as /api/execute/raw.
    if (getattr(ai_command, "intent", None) in _HARD_READ_ONLY_INTENTS) or (
        getattr(ai_command, "command", None) in _HARD_READ_ONLY_INTENTS
    ):
        execution_id = _ensure_execution_id(ai_command)
        return {
            "status": "COMPLETED",
            "execution_state": "COMPLETED",
            "read_only": True,
            "execution_id": execution_id,
            "approval_id": None,
            "text": "Need more information before executing. Please answer the questions, then retry.",
            "command": getattr(ai_command, "command", None),
            "intent": getattr(ai_command, "intent", None),
            "params": getattr(ai_command, "params", None)
            if isinstance(getattr(ai_command, "params", None), dict)
            else {},
            "proposed_commands": [],
            "trace": {
                "canon": "proposals_execute_hard_block_after_unwrap",
                "endpoint": "/api/proposals/execute",
            },
        }

    md = getattr(ai_command, "metadata", None)
    if not isinstance(md, dict):
        md = {}
    md.setdefault("promotion", {})
    if isinstance(md.get("promotion"), dict):
        md["promotion"].setdefault("source", "/api/proposals/execute")
        md["promotion"].setdefault("proposal_command", proposal_cmd)
        md["promotion"].setdefault("proposal_intent", proposal_intent)
        md["promotion"].setdefault("risk", proposal_risk)
        md["promotion"].setdefault("scope", proposal_scope)
    md.setdefault("endpoint", "/api/proposals/execute")
    md.setdefault("canon", "proposal_promotion_v2_execute_raw_unwrap")
    ai_command.metadata = md

    execution_id = _ensure_execution_id(ai_command)

    approval_state = get_approval_state()
    approval = approval_state.create(
        command=getattr(ai_command, "command", None) or "execute_proposal",
        payload_summary=_safe_command_summary(ai_command),
        scope=(proposal_scope or "api_proposals_execute"),
        risk_level=(proposal_risk or "UNKNOWN"),
        execution_id=execution_id,
    )
    approval_id = approval.get("approval_id")
    if not approval_id:
        raise HTTPException(
            status_code=500, detail="Approval create failed: missing approval_id"
        )

    _ensure_trace_on_command(ai_command, approval_id=approval_id)
    orchestrator.registry.register(ai_command)
    registry.register(ai_command)

    result = await orchestrator.execute(ai_command)
    if isinstance(result, dict):
        result.setdefault("approval_id", approval_id)
        result.setdefault("execution_id", execution_id)
        result.setdefault("status", "BLOCKED")
    return result


# ================================================================
# NOTION READ — READ ONLY (NO APPROVAL / NO EXECUTION)
# ================================================================
@app.post("/api/notion/read", response_model=NotionReadResponse)
async def notion_read(payload: Any = Body(None)) -> Any:
    def _model_to_dict(m: NotionReadResponse) -> Dict[str, Any]:
        if hasattr(m, "model_dump"):
            try:
                d = m.model_dump()  # type: ignore[attr-defined]
                return d if isinstance(d, dict) else {}
            except Exception:
                pass
        try:
            d2 = m.dict()  # type: ignore[attr-defined]
            return d2 if isinstance(d2, dict) else {}
        except Exception:
            return {}

    def _json(resp: NotionReadResponse) -> JSONResponse:
        return JSONResponse(
            content=_model_to_dict(resp),
            media_type="application/json; charset=utf-8",
        )

    def _resp_err(msg: str) -> JSONResponse:
        return _json(
            NotionReadResponse(
                ok=False,
                title=None,
                notion_url=None,
                content_markdown=None,
                error=msg,
            )
        )

    if payload is None:
        return _resp_err("Body must be an object")
    if not isinstance(payload, dict):
        return _resp_err("Body must be an object")

    mode0 = payload.get("mode")
    if not isinstance(mode0, str) or not mode0.strip():
        return _resp_err("Field 'mode' is required")
    mode0 = mode0.strip()

    if mode0 != "page_by_title":
        return _resp_err("Unsupported mode. Allowed: 'page_by_title'")

    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        return _resp_err("Field 'query' is required")
    query = query.strip()

    try:
        from services.notion_read_service import read_page_as_markdown

        res = await read_page_as_markdown(query)
        if not isinstance(res, dict):
            return _resp_err("Notion read failed: invalid service response")

        title = res.get("title") if isinstance(res.get("title"), str) else ""
        url = res.get("url") if isinstance(res.get("url"), str) else ""
        md = (
            res.get("content_markdown")
            if isinstance(res.get("content_markdown"), str)
            else ""
        )

        title = (title or "").strip()
        url = (url or "").strip()
        md = (md or "").strip()

        if not title and not url and not md:
            return _json(
                NotionReadResponse(
                    ok=False,
                    title=None,
                    notion_url=None,
                    content_markdown=None,
                    error=f"Page not found for query: {query}",
                )
            )

        return _json(
            NotionReadResponse(
                ok=True,
                title=title or None,
                notion_url=url or None,
                content_markdown=md or None,
                error=None,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _resp_err(f"Notion read failed: {exc}")


# ================================================================
# NOTION OPS — LIST DATABASES (READ ONLY)
# ================================================================
@app.get("/api/notion-ops/databases")
@app.get("/notion-ops/databases")
async def notion_ops_list_databases():
    from services.notion_service import get_notion_service

    ns = get_notion_service()

    dbs: Dict[str, str] = {}
    if isinstance(getattr(ns, "db_ids", None), dict):
        for k, v in ns.db_ids.items():
            if isinstance(k, str) and isinstance(v, str):
                kk = k.strip()
                vv = v.strip()
                if kk and vv:
                    dbs[kk] = vv

    return {
        "ok": True,
        "read_only": True,
        "ops_safe_mode": _ops_safe_mode(),
        "databases": dbs,
    }


@app.get("/databases")
async def databases_alias():
    return await notion_ops_list_databases()


@app.get("/api/databases")
async def databases_alias_api():
    return await notion_ops_list_databases()


# ================================================================
# NOTION BULK OPS
# ================================================================
_ALLOWED_BULK_TYPES = {
    "goal",
    "goals",
    "task",
    "tasks",
    "project",
    "projects",
    "kpi",
    "kpis",
    "lead",
    "leads",
    "agent_exchange",
    "ai_summary",
}


def _validate_bulk_items(items: Any) -> List[Dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="items must be a list")

    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            raise HTTPException(status_code=400, detail="each item must be an object")
        t = it.get("type")
        if not isinstance(t, str) or not t.strip():
            raise HTTPException(
                status_code=400, detail="each item must have non-empty 'type'"
            )
        tt = t.strip().lower()
        if tt not in _ALLOWED_BULK_TYPES:
            raise HTTPException(status_code=400, detail=f"invalid type: {t}")
        out.append(it)
    return out


@app.post("/api/notion-ops/bulk/create")
@app.post("/notion-ops/bulk/create")
async def notion_bulk_create(request: Request, payload: Dict[str, Any] = Body(...)):
    _guard_write_bulk(request)

    items = _validate_bulk_items(payload.get("items"))

    created: List[Dict[str, Any]] = []
    for it in items:
        created.append(
            {
                "id": str(uuid.uuid4()),
                "type": str(it.get("type")),
                "title": it.get("title"),
                "input": it,
                "status": "created",
            }
        )

    return {"created": created}


@app.post("/api/notion-ops/bulk/update")
@app.post("/notion-ops/bulk/update")
async def notion_bulk_update(request: Request, payload: Dict[str, Any] = Body(...)):
    _guard_write_bulk(request)

    items = _validate_bulk_items(payload.get("items"))

    updated: List[Dict[str, Any]] = []
    for it in items:
        updated.append(
            {
                "id": it.get("id") or str(uuid.uuid4()),
                "type": str(it.get("type")),
                "title": it.get("title"),
                "input": it,
                "status": "updated",
            }
        )

    return {"updated": updated}


def _normalize_notion_query_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    q = payload.get("query")
    if isinstance(q, dict):
        return dict(q)

    out: Dict[str, Any] = {}
    if isinstance(payload.get("filter"), dict):
        out["filter"] = payload["filter"]
    if isinstance(payload.get("sorts"), list):
        out["sorts"] = payload["sorts"]
    if isinstance(payload.get("start_cursor"), str) and payload["start_cursor"].strip():
        out["start_cursor"] = payload["start_cursor"].strip()
    if isinstance(payload.get("page_size"), int):
        out["page_size"] = int(payload["page_size"])
    return out


def _looks_like_uuid(s: str) -> bool:
    try:
        uuid.UUID((s or "").strip())
        return True
    except Exception:
        return False


def _resolve_db_id_from_service(notion_service: Any, db_key: str) -> str:
    key = (db_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="db_key is required")

    if _looks_like_uuid(key):
        return key

    lk = key.lower()

    db_ids = getattr(notion_service, "db_ids", None)
    if isinstance(db_ids, dict):
        for candidate in (lk, lk.rstrip("s"), lk + "s"):
            v = db_ids.get(candidate)
            if isinstance(v, str) and v.strip():
                return v.strip()

    for candidate in (lk, lk.rstrip("s"), lk + "s"):
        if candidate == "goals":
            v = getattr(notion_service, "goals_db_id", None) or getattr(
                notion_service, "_goals_db_id", None
            )
            if isinstance(v, str) and v.strip():
                return v.strip()
        if candidate == "tasks":
            v = getattr(notion_service, "tasks_db_id", None) or getattr(
                notion_service, "_tasks_db_id", None
            )
            if isinstance(v, str) and v.strip():
                return v.strip()
        if candidate == "projects":
            v = getattr(notion_service, "projects_db_id", None) or getattr(
                notion_service, "_projects_db_id", None
            )
            if isinstance(v, str) and v.strip():
                return v.strip()

    raise HTTPException(status_code=400, detail=f"Unknown db_key: {db_key}")


def _extract_db_key_or_database_id(d: Dict[str, Any]) -> Optional[str]:
    v = d.get("db_key")
    if isinstance(v, str) and v.strip():
        return v.strip()
    v2 = d.get("database_id")
    if isinstance(v2, str) and v2.strip():
        return v2.strip()
    return None


async def _call_maybe_async(fn: Any, *args: Any, **kwargs: Any) -> Any:
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    out = fn(*args, **kwargs)
    if asyncio.iscoroutine(out):
        return await out
    return out


async def _query_notion_database(db_key: str, query: Dict[str, Any]) -> Dict[str, Any]:
    from services.notion_service import get_notion_service

    notion_service = get_notion_service()

    for name in ("query_database", "database_query", "query_db", "query"):
        fn = getattr(notion_service, name, None)
        if callable(fn):
            try:
                res = await _call_maybe_async(fn, db_key=db_key, query=query)
                if isinstance(res, dict):
                    return res
            except TypeError:
                pass
            try:
                res = await _call_maybe_async(fn, db_key=db_key, **query)
                if isinstance(res, dict):
                    return res
            except TypeError:
                pass
            try:
                res = await _call_maybe_async(fn, db_key, query)
                if isinstance(res, dict):
                    return res
            except TypeError:
                pass

    try:
        from notion_client import Client  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=(
                "Notion query failed: NotionService has no query method and notion_client "
                f"is unavailable: {exc}"
            ),
        ) from exc

    api_key = (
        getattr(notion_service, "api_key", None)
        or getattr(notion_service, "_api_key", None)
        or (os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN") or "").strip()
    )
    if not isinstance(api_key, str) or not api_key.strip():
        raise HTTPException(
            status_code=500, detail="NOTION_API_KEY/NOTION_TOKEN not set"
        )

    db_id = _resolve_db_id_from_service(notion_service, db_key)
    client = Client(auth=api_key.strip())

    try:
        res = await asyncio.to_thread(
            lambda: client.databases.query(database_id=db_id, **(query or {}))
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Notion databases.query failed: {exc}"
        ) from exc

    if not isinstance(res, dict):
        return {
            "results": [],
            "has_more": False,
            "next_cursor": None,
            "database_id": db_id,
        }

    res.setdefault("database_id", db_id)
    return res


@app.post("/api/notion-ops/bulk/query")
@app.post("/notion-ops/bulk/query")
async def notion_bulk_query(payload: Any = Body(None)):
    if payload is None:
        return {"results": []}

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")

    top_db_key = _extract_db_key_or_database_id(payload)
    if isinstance(top_db_key, str) and top_db_key.strip():
        q = _normalize_notion_query_payload(payload)
        res = await _query_notion_database(top_db_key.strip(), q)
        items = res.get("results") if isinstance(res.get("results"), list) else []
        return {
            "results": [
                {
                    "query": {"db_key": top_db_key.strip(), **q},
                    "db_key": top_db_key.strip(),
                    "items": items,
                    "notion": res,
                    "response": res,
                }
            ]
        }

    queries = payload.get("queries")
    if queries is None:
        queries = []
    if not isinstance(queries, list):
        raise HTTPException(status_code=400, detail="queries must be a list")

    if len(queries) == 0:
        return {"results": []}

    out: List[Dict[str, Any]] = []
    for q0 in queries:
        if not isinstance(q0, dict):
            raise HTTPException(status_code=400, detail="each query must be an object")

        db_key = _extract_db_key_or_database_id(q0)
        if not isinstance(db_key, str) or not db_key.strip():
            out.append(
                {
                    "query": q0,
                    "db_key": None,
                    "items": [],
                    "notion": {"results": [], "has_more": False, "next_cursor": None},
                    "response": {"results": [], "has_more": False, "next_cursor": None},
                }
            )
            continue

        nq = _normalize_notion_query_payload(q0)
        res = await _query_notion_database(db_key.strip(), nq)
        items = res.get("results") if isinstance(res.get("results"), list) else []
        out.append(
            {
                "query": {"db_key": db_key.strip(), **nq},
                "db_key": db_key.strip(),
                "items": items,
                "notion": res,
                "response": res,
            }
        )

    return {"results": out}


# ================================================================
# LEGACY CEO COMMAND ENDPOINTS (READ-ONLY WRAPPERS)
# ================================================================
def _extract_text_from_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    for key in ("input_text", "text", "message", "prompt"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("input_text", "text", "message", "prompt"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()

    return ""


def _extract_smart_context(payload: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None

    def _pick(d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sc = (
            d.get("smart_context")
            or d.get("context")
            or d.get("context_hint")
            or d.get("ui_context_hint")
        )
        return sc if isinstance(sc, dict) else None

    sc = _pick(payload)
    if sc is not None:
        return sc

    data = payload.get("data")
    if isinstance(data, dict):
        return _pick(data)

    return None


def _extract_source(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "ceo_dashboard"
    s = payload.get("source") or payload.get("initiator")
    if isinstance(s, str) and s.strip():
        return s.strip()
    return "ceo_dashboard"


async def _ceo_command_core(
    payload_dict: Dict[str, Any], request: Optional[Request] = None
) -> JSONResponse:
    raw_text = _extract_text_from_payload(payload_dict)
    smart_context = _extract_smart_context(payload_dict)
    source = _extract_source(payload_dict)

    cleaned_text = _preprocess_ceo_nl_input(raw_text, smart_context)

    if not isinstance(cleaned_text, str) or not cleaned_text.strip():
        raise HTTPException(
            status_code=422,
            detail="Missing text. Provide one of: input_text | text | message | prompt (optionally under data).",
        )

    session_id = payload_dict.get("session_id")
    if session_id is None and isinstance(payload_dict.get("data"), dict):
        session_id = payload_dict["data"].get("session_id")

    req = ceo_console_module.CEOCommandRequest(
        text=cleaned_text.strip(),
        initiator=source,
        session_id=session_id,
        context_hint=smart_context,
        read_only=True,
        require_approval=False,
    )

    result_obj = await ceo_console_module.ceo_command(req)

    try:
        if hasattr(result_obj, "model_dump"):
            result = result_obj.model_dump(by_alias=False)  # type: ignore[attr-defined]
        else:
            result = jsonable_encoder(result_obj, by_alias=False)
    except Exception:
        result = jsonable_encoder(result_obj)

    if not isinstance(result, dict):
        result = {"ok": True, "summary": str(result_obj), "trace": {}}

    result["read_only"] = True

    if not result.get("text"):
        result["text"] = result.get("summary") or ""

    tr = result.get("trace")
    if isinstance(tr, dict):
        tr["normalized_input_text"] = cleaned_text.strip()
        tr["normalized_input_source"] = source
        tr["normalized_input_has_smart_context"] = bool(smart_context)
        tr["normalized_input_session_id_present"] = bool(session_id)
        if result.get("text"):
            tr["agent_router_empty_text"] = False
            tr["agent_output_text_len"] = len(str(result.get("text") or ""))

    if not isinstance(result.get("proposed_commands"), list):
        result["proposed_commands"] = []

    tr2 = _ensure_dict(result.get("trace"))
    if not isinstance(tr2.get("confidence_risk"), dict):
        tr2["confidence_risk"] = _compute_confidence_risk_block(
            prompt=cleaned_text.strip(),
            trace=tr2,
            proposed_commands=_ensure_list(result.get("proposed_commands")),
        )
    result["trace"] = tr2

    # === CANON PATCH: propagate confidence/risk into proposal payloads ===
    cr = tr2.get("confidence_risk")
    if isinstance(cr, dict):
        for pc in result.get("proposed_commands", []):
            if not isinstance(pc, dict):
                continue

            ps = pc.get("payload_summary")
            if not isinstance(ps, dict):
                ps = {}
                pc["payload_summary"] = ps

            ps.setdefault("confidence_score", cr.get("confidence_score"))
            ps.setdefault("assumption_count", cr.get("assumption_count", 0))
            ps.setdefault("recommendation_type", "OPERATIONAL")

            rl = cr.get("risk_level")
            if isinstance(rl, str):
                pc.setdefault(
                    "risk",
                    {"low": "LOW", "medium": "MED", "high": "HIGH"}.get(rl, "LOW"),
                )

            # PHASE A FIX: also propagate to proposal metadata
            md0 = pc.get("metadata")
            if not isinstance(md0, dict):
                md0 = {}
                pc["metadata"] = md0
            md0.setdefault("confidence_risk", cr)
    # === END CANON PATCH ===

    # === CANON STABILITY PATCH: ensure args.prompt exists ===
    for pc in result.get("proposed_commands", []):
        if not isinstance(pc, dict):
            continue

        if pc.get("command") == "ceo.command.propose":
            args = pc.get("args")
            if not isinstance(args, dict):
                args = {}
                pc["args"] = args

            if "prompt" not in args or not isinstance(args.get("prompt"), str):
                args["prompt"] = cleaned_text.strip()
    # === END CANON STABILITY PATCH ===

    # Fallback proposal injection for CEO Console:
    # - If backend returns no proposed_commands *and* does not provide the stable
    #   trace contract fields, we enter gateway fallback mode.
    # - If backend already provides trace.used_sources/missing_inputs/kb_ids_used,
    #   we stay on the normal path (prevents unnecessary fallback/bridge).
    if (
        isinstance(result.get("proposed_commands"), list)
        and len(result.get("proposed_commands")) == 0
    ):
        tr_pre = _ensure_dict(result.get("trace"))
        has_trace_contract = (
            isinstance(tr_pre.get("used_sources"), list)
            and isinstance(tr_pre.get("missing_inputs"), list)
            and isinstance(tr_pre.get("kb_ids_used"), list)
        )

        if not has_trace_contract:
            _inject_fallback_proposed_commands(result, prompt=cleaned_text.strip())

    # Minimal 2-turn memory ONLY in nonwrite gateway fallback.
    tr_gw = _ensure_dict(result.get("trace"))
    if (
        tr_gw.get("router_version")
        == "gateway-fallback-proposals-disabled-for-nonwrite-v1"
    ):
        notion_ops_state = {"armed": False, "armed_at": None}
        notion_ops_armed = False
        if isinstance(session_id, str) and session_id.strip():
            try:
                from services.notion_ops_state import get_state as _get_notion_ops_state  # type: ignore
                from services.notion_ops_state import is_armed as _notion_ops_is_armed  # type: ignore

                notion_ops_state = await _get_notion_ops_state(session_id.strip())
                notion_ops_armed = await _notion_ops_is_armed(session_id.strip())
            except Exception:
                notion_ops_state = {"armed": False, "armed_at": None}
                notion_ops_armed = False

        did_mem = _apply_gateway_fallback_memory_patch(
            result,
            prompt=cleaned_text.strip(),
            session_id=session_id if isinstance(session_id, str) else None,
        )

        # Attach Notion Ops state consistently in fallback mode.
        result["notion_ops"] = {
            "armed": bool(notion_ops_armed is True),
            "armed_at": notion_ops_state.get("armed_at")
            if isinstance(notion_ops_state, dict)
            else None,
            "session_id": session_id,
            "armed_state": notion_ops_state,
        }

        # Ensure trace contract even for Zapamti/prisjeti se path.
        if did_mem:
            tr_mem = _ensure_dict(result.get("trace"))
            used_sources_mem = (
                tr_mem.get("used_sources")
                if isinstance(tr_mem.get("used_sources"), list)
                else ["memory"]
            )
            missing_inputs_mem = (
                tr_mem.get("missing_inputs")
                if isinstance(tr_mem.get("missing_inputs"), list)
                else ["identity_pack", "notion_snapshot", "kb"]
            )
            _ensure_gateway_trace_contract(
                result,
                used_sources=[
                    x for x in used_sources_mem if isinstance(x, str) and x.strip()
                ],
                missing_inputs=[
                    x for x in missing_inputs_mem if isinstance(x, str) and x.strip()
                ],
                notion_ops={
                    "armed": bool(notion_ops_armed is True),
                    "session_id": session_id,
                },
                kb_ids_used=[],
            )
            _apply_gateway_notion_ops_gating_and_trace(
                result, notion_ops_armed=bool(notion_ops_armed is True)
            )

        # If not handled by the Zapamti/prisjeti se micro-patch, bridge to CEO read-only LLM.
        if not did_mem:
            try:
                headers_dict: Optional[Dict[str, str]] = None
                if request is not None:
                    headers_dict = {k: v for k, v in request.headers.items()}

                ctx_bridge = _build_ceo_read_context(
                    prompt=cleaned_text.strip(),
                    session_id=session_id if isinstance(session_id, str) else None,
                    request_headers=headers_dict,
                )
                llm_ans = await _generate_ceo_readonly_answer(
                    prompt=cleaned_text.strip(),
                    session_id=session_id if isinstance(session_id, str) else None,
                    context=ctx_bridge,
                )

                # Force read-only invariants, but preserve any safe proposals
                # (notably memory_write) returned by the canonical CEO agent.
                text_out = str(llm_ans.get("text") or "").strip()
                result["text"] = text_out
                result["summary"] = text_out
                result["read_only"] = True
                pcs_out = llm_ans.get("proposed_commands")
                result["proposed_commands"] = (
                    pcs_out if isinstance(pcs_out, list) else []
                )

                tr3 = _ensure_dict(result.get("trace"))
                tr_llm = (
                    llm_ans.get("trace")
                    if isinstance(llm_ans.get("trace"), dict)
                    else {}
                )
                # Merge key debug fields from agent trace (do not override router_version).
                for k in ("intent", "exit_reason"):
                    if isinstance(tr_llm.get(k), str) and tr_llm.get(k):
                        tr3[k] = tr_llm.get(k)
                # Keep the rest of agent trace under a namespaced key.
                tr3.setdefault("ceo_agent_trace", tr_llm)

                used_sources, missing_inputs = _derive_used_sources_and_missing_inputs(
                    ctx_bridge=ctx_bridge
                )
                kb_ids_used = _compute_kb_ids_used_from_grounding_pack(
                    ctx_bridge.get("grounding_pack")
                    if isinstance(ctx_bridge, dict)
                    else {}
                )

                # Apply canonical gating semantics (strip only Notion writes when disarmed).
                _apply_gateway_notion_ops_gating_and_trace(
                    result, notion_ops_armed=bool(notion_ops_armed is True)
                )

                _ensure_gateway_trace_contract(
                    result,
                    used_sources=used_sources,
                    missing_inputs=missing_inputs,
                    notion_ops={
                        "armed": bool(notion_ops_armed is True),
                        "session_id": session_id,
                    },
                    kb_ids_used=kb_ids_used,
                )

                tr3 = _ensure_dict(result.get("trace"))
                tr3["gateway_fallback_context_bridge"] = {
                    "used_sources": {
                        "system_read_executor": True,
                        "grounding_pack": bool(
                            isinstance(ctx_bridge.get("grounding_pack"), dict)
                            and ctx_bridge.get("grounding_pack", {}).get("enabled")
                            is True
                        ),
                        "memory_read_only": True,
                        "executor": True,
                    },
                    "missing": ctx_bridge.get("missing")
                    if isinstance(ctx_bridge.get("missing"), list)
                    else [],
                    "trace": ctx_bridge.get("trace")
                    if isinstance(ctx_bridge.get("trace"), dict)
                    else {},
                    "llm": llm_ans.get("trace")
                    if isinstance(llm_ans.get("trace"), dict)
                    else {},
                }
                result["trace"] = tr3
            except Exception as e:  # noqa: BLE001
                # Fail-soft: keep existing result, but add bridge error.
                tr3 = _ensure_dict(result.get("trace"))
                tr3.setdefault(
                    "notion_ops",
                    {
                        "armed": bool(notion_ops_armed is True),
                        "session_id": session_id,
                    },
                )
                tr3["gateway_fallback_context_bridge"] = {
                    "error": str(e),
                    "used_sources": {"executor": False},
                }
                result["trace"] = tr3

        # Final fallback: enforce trace contract on every response.
        tr_any = _ensure_dict(result.get("trace"))
        used_any = (
            tr_any.get("used_sources")
            if isinstance(tr_any.get("used_sources"), list)
            else []
        )
        missing_any = (
            tr_any.get("missing_inputs")
            if isinstance(tr_any.get("missing_inputs"), list)
            else []
        )
        kb_any = (
            tr_any.get("kb_ids_used")
            if isinstance(tr_any.get("kb_ids_used"), list)
            else []
        )
        _ensure_gateway_trace_contract(
            result,
            used_sources=[x for x in used_any if isinstance(x, str) and x.strip()],
            missing_inputs=[x for x in missing_any if isinstance(x, str) and x.strip()],
            notion_ops={
                "armed": bool(notion_ops_armed is True),
                "session_id": session_id,
            },
            kb_ids_used=[x for x in kb_any if isinstance(x, str) and x.strip()],
        )

    # === POST-FALLBACK STABILITY PATCH: ensure args.prompt exists ===
    for pc in result.get("proposed_commands", []):
        if not isinstance(pc, dict):
            continue
        if pc.get("command") == "ceo.command.propose":
            args = pc.get("args")
            if not isinstance(args, dict):
                args = {}
                pc["args"] = args
            if (
                "prompt" not in args
                or not isinstance(args.get("prompt"), str)
                or not args.get("prompt")
            ):
                args["prompt"] = cleaned_text.strip()
    # === END POST-FALLBACK STABILITY PATCH ===
    # === POST-FALLBACK EXECUTION PATCH: ensure params.prompt + metadata.wrapper.prompt ===
    for pc in result.get("proposed_commands", []):
        if not isinstance(pc, dict):
            continue
        if pc.get("command") != "ceo.command.propose":
            continue

        # ensure args.prompt (already for happy-path script)
        args = pc.get("args")
        if not isinstance(args, dict):
            args = {}
            pc["args"] = args
        if not isinstance(args.get("prompt"), str) or not args.get("prompt"):
            args["prompt"] = cleaned_text.strip()

        # ensure params.prompt (required by /api/proposals/execute)
        params = pc.get("params")
        if not isinstance(params, dict):
            params = {}
            pc["params"] = params
        if not isinstance(params.get("prompt"), str) or not params.get("prompt"):
            params["prompt"] = args.get("prompt") or cleaned_text.strip()

        # ensure metadata.wrapper.prompt (also accepted by gateway)
        md = pc.get("metadata")
        if not isinstance(md, dict):
            md = {}
            pc["metadata"] = md
        wrapper = md.get("wrapper")
        if not isinstance(wrapper, dict):
            wrapper = {}
            md["wrapper"] = wrapper
        if not isinstance(wrapper.get("prompt"), str) or not wrapper.get("prompt"):
            wrapper["prompt"] = (
                params.get("prompt") or args.get("prompt") or cleaned_text.strip()
            )
    # === END POST-FALLBACK EXECUTION PATCH ===

    # === POST-FALLBACK CANON PATCH: ensure payload_summary fields on injected proposals ===
    cr2 = _ensure_dict(_ensure_dict(result.get("trace")).get("confidence_risk"))
    if isinstance(cr2, dict):
        for pc in result.get("proposed_commands", []):
            if not isinstance(pc, dict):
                continue

            ps = pc.get("payload_summary")
            if not isinstance(ps, dict):
                ps = {}
                pc["payload_summary"] = ps

            cs = ps.get("confidence_score", None)
            if cs is None:
                cs2 = cr2.get("confidence_score")
                cs = float(cs2) if isinstance(cs2, (int, float)) else 0.50
            if cs < 0.0:
                cs = 0.0
            if cs > 1.0:
                cs = 1.0
            ps["confidence_score"] = float(cs)

            ac = ps.get("assumption_count", None)
            if not isinstance(ac, int) or ac < 0:
                ac2 = cr2.get("assumption_count")
                ac = int(ac2) if isinstance(ac2, int) and ac2 >= 0 else 0
            ps["assumption_count"] = ac

            rt = ps.get("recommendation_type")
            if not isinstance(rt, str) or not rt.strip():
                ps["recommendation_type"] = "OPERATIONAL"
    # === END POST-FALLBACK CANON PATCH ===

    # Final contract enforcement (last-write-wins): ensure fallback responses
    # always carry the required trace fields.
    tr_end = _ensure_dict(result.get("trace"))
    if (
        tr_end.get("router_version")
        == "gateway-fallback-proposals-disabled-for-nonwrite-v1"
    ):
        used_end = (
            tr_end.get("used_sources")
            if isinstance(tr_end.get("used_sources"), list)
            else []
        )
        missing_end = (
            tr_end.get("missing_inputs")
            if isinstance(tr_end.get("missing_inputs"), list)
            else []
        )
        kb_end = (
            tr_end.get("kb_ids_used")
            if isinstance(tr_end.get("kb_ids_used"), list)
            else []
        )

        no = (
            result.get("notion_ops")
            if isinstance(result.get("notion_ops"), dict)
            else {}
        )
        notion_ops_min = {
            "armed": bool(no.get("armed") is True),
            "session_id": no.get("session_id"),
        }

        _ensure_gateway_trace_contract(
            result,
            used_sources=[x for x in used_end if isinstance(x, str) and x.strip()],
            missing_inputs=[x for x in missing_end if isinstance(x, str) and x.strip()],
            notion_ops=notion_ops_min,
            kb_ids_used=[x for x in kb_end if isinstance(x, str) and x.strip()],
        )
    return JSONResponse(content=result, media_type="application/json; charset=utf-8")


@app.post("/api/ceo/command")
async def ceo_dashboard_command_api(
    request: Request, payload: Dict[str, Any] = Body(...)
):
    return await _ceo_command_core(payload, request)


@app.post("/api/ceo-console/command")
async def ceo_console_command_api(
    request: Request, payload: Dict[str, Any] = Body(...)
):
    return await _ceo_command_core(payload, request)


@app.post("/api/ceo-console/command/internal")
async def ceo_console_command_api_internal(
    request: Request, payload: Dict[str, Any] = Body(...)
):
    return await _ceo_command_core(payload, request)


@app.post("/ceo/command")
async def ceo_dashboard_command_public(
    request: Request, payload: Dict[str, Any] = Body(...)
):
    return await _ceo_command_core(payload, request)


@app.post("/ceo-console/command")
async def ceo_console_command_public(
    request: Request, payload: Dict[str, Any] = Body(...)
):
    return await _ceo_command_core(payload, request)


@app.post("/ceo-console/command/internal")
async def ceo_console_command_public_internal(
    request: Request, payload: Dict[str, Any] = Body(...)
):
    return await _ceo_command_core(payload, request)


# ================================================================
# CEO CONSOLE STATUS
# ================================================================
@app.get("/api/ceo-console/status")
async def ceo_console_status_api():
    ops_safe = _ops_safe_mode()
    return {
        "ok": True,
        "read_only": True,
        "system": SYSTEM_NAME,
        "version": VERSION,
        "boot_ready": _BOOT_READY,
        "boot_error": _BOOT_ERROR,
        "ops_safe_mode": ops_safe,
        "canon": {
            "chat_is_read_only": True,
            "no_side_effects": True,
            "ops_safe_mode": ops_safe,
            "boot_ready": _BOOT_READY,
        },
    }


@app.get("/ceo-console/status")
async def ceo_console_status_public():
    return await ceo_console_status_api()


# ================================================================
# CEO CONSOLE SNAPSHOT
# ================================================================
@app.get("/api/ceo/console/snapshot")
async def ceo_console_snapshot() -> CeoConsoleSnapshotResponse:
    approval_state = get_approval_state()
    approvals_map: Dict[str, Dict[str, Any]] = getattr(approval_state, "_approvals", {})
    approvals_list = list(approvals_map.values())

    pending = [a for a in approvals_list if a.get("status") == "pending"]
    approved = [a for a in approvals_list if a.get("status") == "approved"]
    rejected = [a for a in approvals_list if a.get("status") == "rejected"]
    failed = [a for a in approvals_list if a.get("status") == "failed"]
    completed = [a for a in approvals_list if a.get("status") == "completed"]

    ks = KnowledgeSnapshotService.get_snapshot()

    snapshot_meta = {
        "knowledge_last_sync": ks.get("last_sync"),
        "knowledge_ready": bool(ks.get("ready")),
        "knowledge_expired": bool(ks.get("expired")),
        "knowledge_ttl_seconds": ks.get("ttl_seconds"),
        "knowledge_age_seconds": ks.get("age_seconds"),
    }

    # Expose full knowledge snapshot (payload included, even when expired).
    knowledge_snapshot = ks

    ceo_dash = CEOConsoleSnapshotService().snapshot()
    legacy = _derive_legacy_goal_task_summaries_from_ceo_snapshot(ceo_dash)

    snapshot: Dict[str, Any] = {
        "system": {
            "name": SYSTEM_NAME,
            "version": VERSION,
            "release_channel": RELEASE_CHANNEL,
            "arch_lock": ARCH_LOCK,
            "os_enabled": OS_ENABLED,
            "ops_safe_mode": _ops_safe_mode(),
            "boot_ready": _BOOT_READY,
            "boot_error": _BOOT_ERROR,
        },
        "identity": _to_serializable(identity),
        "mode": _to_serializable(mode),
        "state": _to_serializable(state),
        "approvals": {
            "total": len(approvals_list),
            "pending_count": len(pending),
            "approved_count": len(approved),
            "rejected_count": len(rejected),
            "failed_count": len(failed),
            "completed_count": len(completed),
            "pending": pending,
        },
        "snapshot_meta": snapshot_meta,
        "knowledge_snapshot": knowledge_snapshot,
        "ceo_dashboard_snapshot": _to_serializable(ceo_dash),
        "goals_summary": legacy["goals_summary"],
        "tasks_summary": legacy["tasks_summary"],
    }

    # Grounding Pack (additive; does not break legacy contract)
    try:
        from dependencies import get_memory_read_only_service  # noqa: PLC0415
        from services.grounding_pack_service import (  # noqa: PLC0415
            GroundingPackService,
        )

        mem_ro = get_memory_read_only_service()
        mem_snapshot = mem_ro.export_public_snapshot() if mem_ro else {}

        gp = GroundingPackService.build(
            prompt="ceo_console_snapshot",
            knowledge_snapshot=knowledge_snapshot
            if isinstance(knowledge_snapshot, dict)
            else {},
            memory_public_snapshot=mem_snapshot,
            legacy_trace={"source": "ceo_console_snapshot"},
            agent_id="ceo_console_snapshot",
        )
    except Exception:
        gp = {"enabled": False, "feature_flags": {"CEO_GROUNDING_PACK_ENABLED": False}}

    snapshot["console_snapshot"] = {
        "grounding_pack": gp,
        "diagnostics": gp.get("diagnostics") if isinstance(gp, dict) else None,
        "trace_v2": gp.get("trace") if isinstance(gp, dict) else None,
    }
    return snapshot  # type: ignore[return-value]


@app.get("/ceo/console/snapshot")
async def ceo_console_snapshot_public():
    return await ceo_console_snapshot()


@app.get("/api/ceo/console/weekly-memory")
async def ceo_weekly_memory():
    wm_snapshot = get_weekly_memory_service().get_snapshot()
    return {"weekly_memory": _to_serializable(wm_snapshot)}


@app.get("/ceo/weekly-priority-memory")
async def ceo_weekly_priority_memory():
    try:
        items = get_ai_summary_service().get_this_week_priorities()
    except Exception as exc:
        logger.exception("Failed to load Weekly Priority Memory from AI SUMMARY DB")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load Weekly Priority Memory from AI SUMMARY DB: {exc}",
        ) from exc
    return {"items": [i.model_dump() for i in items]}


# ================================================================
# HEALTH / READY
# ================================================================
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "version": VERSION,
        "boot_ready": _BOOT_READY,
        "boot_error": _BOOT_ERROR,
        "ops_safe_mode": _ops_safe_mode(),
    }


@app.get("/health/services")
async def health_services():
    from dependencies import services_status

    st = services_status()
    core = {
        k: ("OK" if st.get(k) else "NOT_CONFIGURED")
        for k in ("goals", "tasks", "projects", "sync")
    }
    return {
        "ok": True,
        "boot_ready": _BOOT_READY,
        "services": core,
        "details": st,
    }


@app.get("/ready")
async def ready_check():
    if not _BOOT_READY:
        raise HTTPException(status_code=503, detail=_BOOT_ERROR or "System not ready")
    return {
        "status": "ready",
        "version": VERSION,
        "boot_ready": _BOOT_READY,
        "ops_safe_mode": _ops_safe_mode(),
    }


# ================================================================
# INCLUDE ROUTERS
# ================================================================
app.include_router(audit_router, prefix="/api")
app.include_router(voice_router, prefix="/api")
app.include_router(adnan_ai_router, prefix="/api")
app.include_router(ai_router_module.router, prefix="/api")
app.include_router(ai_ops_router, prefix="/api")
app.include_router(notion_ops_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(alerting_router, prefix="/api")
app.include_router(goals_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(sync_router, prefix="/api")

# Extra routers (feature-flagged)
if _extra_routers_enabled():
    enabled: List[str] = []
    failed: List[str] = []

    try:
        from routers.sop_query_router import router as sop_query_router

        app.include_router(sop_query_router, prefix="/api")
        enabled.append("routers.sop_query_router")
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "ENABLE_EXTRA_ROUTERS: failed to include sop_query_router: %s", exc
        )
        failed.append("routers.sop_query_router")

    try:
        from routers.adnan_ai_action_router import router as adnan_ai_action_router

        app.include_router(adnan_ai_action_router, prefix="/api")
        enabled.append("routers.adnan_ai_action_router")
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "ENABLE_EXTRA_ROUTERS: failed to include adnan_ai_action_router: %s",
            exc,
        )
        failed.append("routers.adnan_ai_action_router")

    try:
        from routers.adnan_ai_data_router import router as adnan_ai_data_router

        app.include_router(adnan_ai_data_router, prefix="/api")
        enabled.append("routers.adnan_ai_data_router")
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "ENABLE_EXTRA_ROUTERS: failed to include adnan_ai_data_router: %s", exc
        )
        failed.append("routers.adnan_ai_data_router")

    logger.info(
        "ENABLE_EXTRA_ROUTERS=true enabled=%s failed=%s",
        ",".join(enabled) if enabled else "-",
        ",".join(failed) if failed else "-",
    )
if _chat_router is not None:
    app.include_router(_chat_router, prefix="/api")  # /api/chat
    app.include_router(_chat_router, prefix="")  # /chat alias
else:
    logger.warning("chat_router is None — chat endpoints disabled")
app.include_router(ceo_console_module.router, prefix="/api/internal")


# ================================================================
# GLOBAL ERROR HANDLER
# ================================================================
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException):
    detail = getattr(exc, "detail", None)

    content: Dict[str, Any] = {"detail": detail}
    content["status"] = "error"
    content["message"] = detail

    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    err_id = str(uuid.uuid4())
    req_id = getattr(getattr(request, "state", None), "req_id", None)
    path = getattr(getattr(request, "url", None), "path", None)

    # Log full traceback with a stable error id for correlating Render logs.
    logger.exception(
        "UNHANDLED_EXCEPTION err_id=%s req_id=%s path=%s", err_id, req_id, path
    )
    logger.error("TRACEBACK err_id=%s\n%s", err_id, traceback.format_exc())

    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": "internal_error", "error_id": err_id},
    )


# ================================================================
# REACT FRONTEND (PROD BUILD) — SERVE dist/
# ================================================================
if not FRONTEND_DIST_DIR.is_dir():
    logger.warning("React dist directory not found: %s", FRONTEND_DIST_DIR)
else:

    @app.head("/", include_in_schema=False)
    async def head_root():
        return Response(status_code=200)

    app.mount(
        "/",
        StaticFiles(directory=str(FRONTEND_DIST_DIR), html=True),
        name="frontend",
    )

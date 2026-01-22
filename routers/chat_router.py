# routers/chat_router.py
# PHASE 6: Notion Ops ARMED Gate

from __future__ import annotations

import os
import re

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.ceo_advisor_agent import create_ceo_advisor_agent
from dependencies import get_memory_read_only_service

# Must match gateway_server.PROPOSAL_WRAPPER_INTENT
from models.canon import PROPOSAL_WRAPPER_INTENT

# PHASE 6: Import shared Notion Ops state management
from services.notion_ops_state import (
    set_armed as _set_armed_shared,
    get_state as _get_state_shared,
)

# Commands that are NOT considered "structured/actionable proposals" for fallback detection.
_NON_ACTIONABLE_PROPOSALS = {"refresh_snapshot", "notion_ops_toggle"}

# Activation keywords (exact per spec)
_ACTIVATE_KEYWORDS = (
    "notion ops active",
    "notion ops aktivan",
    "notion ops aktiviraj",
    "notion ops uključi",
    "notion ops ukljuci",
)

# Deactivation keywords (exact per spec + Bosnian variants mentioned)
_DEACTIVATE_KEYWORDS = (
    "stop notion ops",
    "notion ops deaktiviraj",
    "notion ops ugasi",
    "notion ops isključi",
    "notion ops iskljuci",
    "notion ops deactivate",
)


def build_chat_router(agent_router: Optional[Any] = None) -> APIRouter:
    router = APIRouter()

    def _grounding_bundle(
        *,
        prompt: str,
        knowledge_snapshot: Dict[str, Any],
        memory_snapshot: Dict[str, Any],
        legacy_trace: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            from services.grounding_pack_service import (  # noqa: PLC0415
                GroundingPackService,
            )

            gp = GroundingPackService.build(
                prompt=prompt,
                knowledge_snapshot=knowledge_snapshot,
                memory_public_snapshot=memory_snapshot,
                legacy_trace=legacy_trace,
                agent_id=agent_id,
            )
        except Exception:
            gp = {
                "enabled": False,
                "feature_flags": {"CEO_GROUNDING_PACK_ENABLED": False},
            }

        out: Dict[str, Any] = {"grounding_pack": gp}
        if isinstance(gp, dict):
            diag = gp.get("diagnostics")
            tr2 = gp.get("trace")
            if isinstance(diag, dict):
                out["diagnostics"] = diag
            if isinstance(tr2, dict):
                out["trace_v2"] = tr2
        return out

    def _knowledge_bundle() -> Dict[str, Any]:
        """Enterprise contract: /api/chat always returns SSOT snapshot fields."""
        try:
            from services.knowledge_snapshot_service import (  # noqa: PLC0415
                KnowledgeSnapshotService,
            )

            ks = KnowledgeSnapshotService.get_snapshot()
        except Exception:
            ks = {}

        if not isinstance(ks, dict):
            ks = {}

        snapshot_meta = {
            "knowledge_status": ks.get("status"),
            "knowledge_last_sync": ks.get("last_sync"),
            "knowledge_generated_at": ks.get("generated_at"),
            "knowledge_ready": bool(ks.get("ready"))
            if isinstance(ks.get("ready"), bool)
            else bool(ks.get("ready")),
            "knowledge_expired": bool(ks.get("expired"))
            if isinstance(ks.get("expired"), bool)
            else bool(ks.get("expired")),
            "knowledge_ttl_seconds": ks.get("ttl_seconds"),
            "knowledge_age_seconds": ks.get("age_seconds"),
            "schema_version": ks.get("schema_version"),
        }

        return {"knowledge_snapshot": ks, "snapshot_meta": snapshot_meta}

    def _extract_prompt(payload: AgentInput) -> str:
        for k in ("message", "text", "input_text", "prompt"):
            v = getattr(payload, k, None)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def _extract_session_id(payload: AgentInput) -> Optional[str]:
        """
        PHASE 6: Notion Ops ARMED Gate
        Best-effort extraction. We do NOT invent a global key.
        If no session_id is available, we keep Notion Ops DISARMED.
        """
        for attr in ("session_id", "sessionId"):
            v = getattr(payload, attr, None)
            if isinstance(v, str) and v.strip():
                return v.strip()

        md = getattr(payload, "metadata", None)
        if isinstance(md, dict):
            v = md.get("session_id") or md.get("sessionId")
            if isinstance(v, str) and v.strip():
                return v.strip()

        return None

    def _norm_text(s: str) -> str:
        return " ".join((s or "").strip().lower().split())

    def _is_activate(text: str) -> bool:
        t = _norm_text(text)
        return any(k in t for k in _ACTIVATE_KEYWORDS)

    def _is_deactivate(text: str) -> bool:
        t = _norm_text(text)
        return any(k in t for k in _DEACTIVATE_KEYWORDS)

    async def _set_armed(
        session_id: str, armed: bool, *, prompt: str
    ) -> Dict[str, Any]:
        """
        PHASE 6: Notion Ops ARMED Gate
        SSOT session state - delegates to shared state module.

        Note: This function sets the state for ANY session_id.
        Access control should be handled by the caller (e.g., chat endpoint).
        CEO users can activate without restrictions.
        """
        return await _set_armed_shared(session_id, armed, prompt=prompt)

    async def _get_state(session_id: str) -> Dict[str, Any]:
        """
        PHASE 6: Notion Ops ARMED Gate
        Gets session state - delegates to shared state module.
        """
        return await _get_state_shared(session_id)

    def _debug_enabled(payload: AgentInput) -> bool:
        md = getattr(payload, "metadata", None)
        include_debug = False
        if isinstance(md, dict):
            v = md.get("include_debug")
            include_debug = v is True or (
                isinstance(v, str) and v.strip().lower() in {"1", "true", "yes", "on"}
            )

        env = (os.getenv("DEBUG_API_RESPONSES") or "").strip().lower()
        env_debug = env in {"1", "true", "yes", "on"}
        return bool(include_debug or env_debug)

    def _minimal_trace_intent(trace_obj: Any) -> Dict[str, Any]:
        if not isinstance(trace_obj, dict):
            return {}
        intent = trace_obj.get("intent")
        if isinstance(intent, str) and intent.strip():
            return {"intent": intent.strip()}
        return {}

    def _normalize_proposed_commands(raw: Any) -> List[ProposedCommand]:
        if raw is None:
            return []
        items = [raw] if isinstance(raw, dict) else raw if isinstance(raw, list) else []
        out: List[ProposedCommand] = []
        for item in items:
            try:
                pc = (
                    ProposedCommand.model_validate(item)
                    if hasattr(ProposedCommand, "model_validate")
                    else ProposedCommand.parse_obj(item)
                )
            except Exception:
                d = item if isinstance(item, dict) else {}
                args = d.get("args") or d.get("params") or {}
                pc = ProposedCommand(
                    command=str(d.get("command") or ""),
                    args=args if isinstance(args, dict) else {},
                )

            try:
                pc.dry_run = True
            except Exception:
                pass

            out.append(pc)

        return out

    def _looks_like_write_intent(text: str) -> bool:
        t = (text or "").strip().lower()
        if not t:
            return False
        # IMPORTANT:
        # - /api/chat is canonical read-only.
        # - We only want to enforce the ARMED gate when the user is asking for
        #   an actual write operation (create/update/delete/archive), not when
        #   they mention concepts like "goal/cilj/task" in advisory questions.
        write_verbs = (
            "create",
            "kreiraj",
            "napravi",
            "dodaj",
            "update",
            "azuriraj",
            "ažuriraj",
            "izmijeni",
            "izmeni",
            "promijeni",
            "promeni",
            "delete",
            "obrisi",
            "obriši",
            "ukloni",
            "archive",
            "arhiviraj",
        )

        explicit_targeting = (
            "db:",
            "database:",
            "database id",
            "database_id",
            "page_id",
        )

        if any(k in t for k in explicit_targeting):
            return True

        return any(k in t for k in write_verbs)

    def _armed_write_ack(prompt: str, *, has_actionable: bool) -> str:
        if has_actionable:
            return "Notion Ops je spreman. Pregledaj prijedlog i odobri izvršenje."
        # write intent but no structured proposal
        return (
            "Zahtjev izgleda kao write, ali treba dodatno preciziranje prije izvršenja."
        )

    def _build_contract_noop_wrapper(prompt: str, *, reason: str) -> ProposedCommand:
        safe_prompt = (prompt or "").strip() or "noop"
        pc = ProposedCommand(
            command=PROPOSAL_WRAPPER_INTENT,
            args={"prompt": safe_prompt},
            reason=reason,
            dry_run=True,
            requires_approval=False,
            risk="NONE",
            scope="none",
            payload_summary={
                "canon": "CEO_CONSOLE_EXECUTION_FLOW",
                "source": "api_chat",
                "kind": "contract_noop",
            },
        )
        return pc

    def _build_approval_wrapper(prompt: str, *, reason: str) -> ProposedCommand:
        safe_prompt = (prompt or "").strip() or "noop"
        pc = ProposedCommand(
            command=PROPOSAL_WRAPPER_INTENT,
            args={"prompt": safe_prompt},
            reason=reason,
            dry_run=True,
            requires_approval=True,
            risk="LOW",
            scope="api_execute_raw",
            payload_summary={
                "endpoint": "/api/execute/raw",
                "canon": "CEO_CONSOLE_EXECUTION_FLOW",
                "source": "api_chat",
                "confidence_score": 0.5,
                "assumption_count": 0,
                "recommendation_type": "OPERATIONAL",
            },
        )
        return pc

    def _pc_to_dict(pc: ProposedCommand, *, prompt: str) -> Dict[str, Any]:
        d = (
            pc.model_dump(by_alias=False)
            if hasattr(pc, "model_dump")
            else pc.dict(by_alias=False)
        )
        if not isinstance(d, dict):
            return {}
        args = d.get("args")
        if not isinstance(args, dict):
            args = {}
            d["args"] = args

        # Legacy behavior: wrapper proposals expect a prompt for Notion translation.
        # Canonical exception: memory_write.v1 proposals must not carry free-form prompt.
        if d.get("command") == PROPOSAL_WRAPPER_INTENT:
            schema = args.get("schema_version")
            is_memory_write_v1 = (
                isinstance(schema, str) and schema.strip() == "memory_write.v1"
            )
            if not is_memory_write_v1:
                p = args.get("prompt")
                if not isinstance(p, str) or not p.strip():
                    args["prompt"] = (prompt or "").strip() or "noop"
        return d

    def _ensure_payload_summary_contract(pc_dict: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(pc_dict, dict):
            return {}

        ps = pc_dict.get("payload_summary")
        if not isinstance(ps, dict):
            ps = {}
            pc_dict["payload_summary"] = ps

        kind = ps.get("kind")
        is_noop = kind == "contract_noop"

        cs = ps.get("confidence_score")
        if not isinstance(cs, (int, float)):
            cs = 1.0 if is_noop else 0.5
        csf = float(cs)
        if csf < 0.0:
            csf = 0.0
        if csf > 1.0:
            csf = 1.0
        ps["confidence_score"] = csf

        ac = ps.get("assumption_count")
        if not isinstance(ac, int) or ac < 0:
            ac = 0
        ps["assumption_count"] = ac

        rt = ps.get("recommendation_type")
        if not isinstance(rt, str) or not rt.strip():
            ps["recommendation_type"] = "INFORMATIONAL" if is_noop else "OPERATIONAL"

        return pc_dict

    def _is_actionable(pc: ProposedCommand) -> bool:
        cmd = getattr(pc, "command", None)
        if not isinstance(cmd, str) or not cmd.strip():
            return False
        if cmd == PROPOSAL_WRAPPER_INTENT:
            return False
        if cmd in _NON_ACTIONABLE_PROPOSALS:
            return False
        return True

    def _finalize_actionable(pc: ProposedCommand) -> None:
        try:
            pc.dry_run = True
        except Exception:
            pass

        try:
            if getattr(pc, "requires_approval", None) is not True:
                pc.requires_approval = True
        except Exception:
            pass

        try:
            scope = getattr(pc, "scope", None)
            if not isinstance(scope, str) or not scope.strip():
                pc.scope = "api_execute_raw"
        except Exception:
            pass

        try:
            risk = getattr(pc, "risk", None)
            if not isinstance(risk, str) or not risk.strip():
                pc.risk = "LOW"
        except Exception:
            pass

    def _blocked_response(
        *,
        out: Any,
        prompt: str,
        session_id: Optional[str],
        state: Dict[str, Any],
        why: str,
        kb: Dict[str, Any],
        grounding: Dict[str, Any],
        debug_on: bool,
    ) -> JSONResponse:
        msg = "Notion Ops nije aktivan. Želiš aktivirati? (napiši: 'notion ops aktiviraj' / 'notion ops uključi')"
        if isinstance(why, str) and why.strip():
            msg = f"{msg}\n\nReason: {why}"

        pcs_out: List[Dict[str, Any]] = []
        # For a blocked write-intent request, the only meaningful proposal is to arm Notion Ops.
        if isinstance(session_id, str) and session_id.strip():
            arm = ProposedCommand(
                command="notion_ops_toggle",
                args={"session_id": session_id.strip(), "armed": True},
                reason="Notion write intent detected; arm Notion Ops to continue.",
                requires_approval=True,
                risk="LOW",
                dry_run=True,
                scope="api_notion_ops_toggle",
                payload_summary={
                    "endpoint": "/api/notion-ops/toggle",
                    "canon": "NOTION_OPS_ARM_SUGGESTION",
                    "source": "api_chat",
                },
            )
            pcs_out.append(
                _ensure_payload_summary_contract(_pc_to_dict(arm, prompt=prompt))
            )

        tr = out.trace or {} if hasattr(out, "trace") else {}
        if not isinstance(tr, dict):
            tr = {}
        tr.setdefault("phase6_notion_ops_gate", {})
        tr["phase6_notion_ops_gate"] = {
            "armed": False,
            "session_id_present": bool(session_id),
            "why": why,
        }

        content: Dict[str, Any] = {
            "text": (getattr(out, "text", "") or "").strip() or msg,
            "proposed_commands": pcs_out,
            "agent_id": getattr(out, "agent_id", None),
            "read_only": True,
            "notion_ops": {
                "armed": False,
                "armed_at": None,
                "session_id": session_id,
                "armed_state": state,
            },
        }

        if debug_on:
            content["trace"] = tr
            content.update(kb)
            content.update(grounding)
        else:
            mt = _minimal_trace_intent(tr)
            if mt:
                content["trace"] = mt

        return JSONResponse(content=content)

    @router.post("/chat", response_model=AgentOutput, response_model_by_alias=False)
    async def chat(payload: AgentInput):
        mem_ro = get_memory_read_only_service()
        mem_snapshot = mem_ro.export_public_snapshot() if mem_ro else {}

        prompt = _extract_prompt(payload)
        session_id = _extract_session_id(payload)
        notion_calls_for_trace: Optional[int] = None
        debug_on = _debug_enabled(payload)

        def _is_test_mode() -> bool:
            return (os.getenv("TESTING") or "").strip() == "1" or (
                "PYTEST_CURRENT_TEST" in os.environ
            )

        def _snapshot_meta_from_ks(ks: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "knowledge_status": ks.get("status"),
                "knowledge_last_sync": ks.get("last_sync"),
                "knowledge_generated_at": ks.get("generated_at"),
                "knowledge_ready": bool(ks.get("ready"))
                if isinstance(ks.get("ready"), bool)
                else bool(ks.get("ready")),
                "knowledge_expired": bool(ks.get("expired"))
                if isinstance(ks.get("expired"), bool)
                else bool(ks.get("expired")),
                "knowledge_ttl_seconds": ks.get("ttl_seconds"),
                "knowledge_age_seconds": ks.get("age_seconds"),
                "schema_version": ks.get("schema_version"),
            }

        kb = _knowledge_bundle()
        ks_for_gp = kb.get("knowledge_snapshot") if isinstance(kb, dict) else {}
        if not isinstance(ks_for_gp, dict):
            ks_for_gp = {}

        # ------------------------------------------------------------
        # READ SNAPSHOT INJECTION (CANON)
        # The UI may send an empty snapshot; for dashboard/show *and* planning/advisory
        # prompts that depend on goals/tasks/projects/KPIs context, we should hydrate
        # from server-side read snapshot (no Notion Ops arming required for reads).
        # ------------------------------------------------------------
        try:
            t0 = (prompt or "").strip().lower()

            # Adaptive grounding policy: read-only Notion targeted reads for operational questions.
            # This is best-effort and cached per session. Tests remain offline.
            try:
                from services.grounding_policy import classify_prompt  # noqa: PLC0415
                from services.session_snapshot_cache import (
                    SESSION_SNAPSHOT_CACHE,
                )  # noqa: PLC0415
                from services.notion_service import (  # noqa: PLC0415
                    get_or_init_notion_service,
                )

                pol = classify_prompt(prompt)
                snap_in0 = getattr(payload, "snapshot", None)
                has_snap0 = isinstance(snap_in0, dict) and bool(snap_in0)

                def _needs_notion_refresh(snap: Any) -> bool:
                    if not isinstance(snap, dict):
                        return True
                    status = snap.get("status")
                    if isinstance(status, str) and status.strip() in {"missing_data"}:
                        return True
                    payload0 = (
                        snap.get("payload")
                        if isinstance(snap.get("payload"), dict)
                        else snap
                    )
                    if not isinstance(payload0, dict):
                        return True
                    # If none of the required collections have data, treat as missing.
                    for k in pol.notion_db_keys:
                        v = payload0.get(k)
                        if isinstance(v, list) and len(v) > 0:
                            return False
                    return True

                if (
                    not _is_test_mode()
                    and pol.needs_notion
                    and pol.notion_db_keys
                    and (not has_snap0 or _needs_notion_refresh(snap_in0))
                    and (os.getenv("CEO_NOTION_TARGETED_READS_ENABLED") or "true")
                    .strip()
                    .lower()
                    == "true"
                ):
                    db_keys_csv = ",".join(pol.notion_db_keys)
                    ttl_s_raw = (
                        os.getenv("CEO_CHAT_SNAPSHOT_TTL_SECONDS") or "60"
                    ).strip()
                    try:
                        ttl_s = int(ttl_s_raw)
                    except Exception:
                        ttl_s = 60

                    cached = None
                    if isinstance(session_id, str) and session_id.strip():
                        cached = SESSION_SNAPSHOT_CACHE.get(
                            session_id=session_id.strip(), db_keys_csv=db_keys_csv
                        )
                    if isinstance(cached, dict) and cached:
                        payload.snapshot = cached
                        kb = {
                            "knowledge_snapshot": cached,
                            "snapshot_meta": _snapshot_meta_from_ks(cached),
                        }
                        ks_for_gp = cached
                    else:
                        notion = get_or_init_notion_service()
                        if notion is not None:
                            max_items = {"tasks": 50, "projects": 30, "goals": 30}
                            snap = await notion.build_knowledge_snapshot(
                                db_keys=list(pol.notion_db_keys),
                                max_items_by_db=max_items,
                            )
                            if isinstance(snap, dict) and snap:
                                payload.snapshot = snap
                                kb = {
                                    "knowledge_snapshot": snap,
                                    "snapshot_meta": _snapshot_meta_from_ks(snap),
                                }
                                ks_for_gp = snap
                                try:
                                    m = (
                                        snap.get("meta")
                                        if isinstance(snap.get("meta"), dict)
                                        else {}
                                    )
                                    if isinstance(m.get("notion_calls"), int):
                                        notion_calls_for_trace = int(
                                            m.get("notion_calls")
                                        )
                                except Exception:
                                    notion_calls_for_trace = None
                                if isinstance(session_id, str) and session_id.strip():
                                    SESSION_SNAPSHOT_CACHE.set(
                                        session_id=session_id.strip(),
                                        db_keys_csv=db_keys_csv,
                                        value=snap,
                                        ttl_seconds=ttl_s,
                                    )
            except Exception:
                # Fail-soft: never block chat on Notion targeted reads.
                pass

            wants_target = bool(
                re.search(
                    r"(?i)\b(cilj\w*|goal\w*|task\w*|zadat\w*|zadac\w*|kpi\w*|project\w*|projekat\w*)\b",
                    t0,
                )
            )

            wants_show = bool(
                re.search(
                    r"(?i)\b(pokazi|poka\u017ei|prika\u017ei|prikazi|izlistaj|show|list|pogledaj|procitaj|read|what\s+goals|which\s+goals|which\s+tasks)\b",
                    t0,
                )
                and wants_target
            )

            wants_plan = bool(
                re.search(
                    r"(?i)\b(predlo\u017ei|predlozi|predlag\w*|suggest|recommend|idej\w*)\b",
                    t0,
                )
                and wants_target
                and ("notion" in t0 or "zapis" in t0 or "upis" in t0)
            )

            snap_in = getattr(payload, "snapshot", None)
            has_snap = isinstance(snap_in, dict) and bool(snap_in)

            if wants_show and not has_snap:
                from services.system_read_executor import SystemReadExecutor  # noqa: PLC0415

                sys_snap = SystemReadExecutor().snapshot()
                ceo_snap = sys_snap.get("ceo_notion_snapshot")
                if isinstance(ceo_snap, dict) and ceo_snap:
                    payload.snapshot = ceo_snap
                else:
                    ks = sys_snap.get("knowledge_snapshot")
                    if isinstance(ks, dict) and ks:
                        payload.snapshot = ks

            # Planning: prefer cached knowledge snapshot (do not hit Notion live here).
            if wants_plan and not has_snap and not wants_show:
                try:
                    from services.knowledge_snapshot_service import (  # noqa: PLC0415
                        KnowledgeSnapshotService,
                    )

                    ks2 = KnowledgeSnapshotService.get_snapshot()
                    if isinstance(ks2, dict) and ks2:
                        payload.snapshot = ks2
                except Exception:
                    pass

            # Final fallback: if still no snapshot, inject the SSOT knowledge wrapper.
            # This is read-only, has no IO, and improves grounding/traceability.
            snap_in2 = getattr(payload, "snapshot", None)
            has_snap2 = isinstance(snap_in2, dict) and bool(snap_in2)
            if not has_snap2:
                try:
                    from services.knowledge_snapshot_service import (  # noqa: PLC0415
                        KnowledgeSnapshotService,
                    )

                    ks3 = KnowledgeSnapshotService.get_snapshot()
                    if isinstance(ks3, dict) and ks3:
                        payload.snapshot = ks3
                except Exception:
                    pass
        except Exception:
            # Fail-soft: never break /api/chat because snapshot hydration failed.
            pass

        # PHASE 6: Notion Ops ARMED Gate (activation/deactivation)
        if session_id and _is_activate(prompt):
            st = await _set_armed(session_id, True, prompt=prompt)
            tr = {
                "phase6_notion_ops_gate": {"event": "armed", "session_id": session_id}
            }
            grounding = _grounding_bundle(
                prompt=prompt,
                knowledge_snapshot=ks_for_gp,
                memory_snapshot=mem_snapshot,
                legacy_trace=tr,
                agent_id=None,
            )
            content: Dict[str, Any] = {
                "text": "NOTION OPS: ARMED",
                "proposed_commands": [],
                "agent_id": None,
                "read_only": True,
                "notion_ops": {
                    "armed": True,
                    "armed_at": st.get("armed_at"),
                    "session_id": session_id,
                    "armed_state": st,
                },
            }
            if debug_on:
                content["trace"] = tr
                content.update(kb)
                content.update(grounding)
            return JSONResponse(content=content)

        if session_id and _is_deactivate(prompt):
            st = await _set_armed(session_id, False, prompt=prompt)
            tr = {
                "phase6_notion_ops_gate": {
                    "event": "disarmed",
                    "session_id": session_id,
                }
            }
            grounding = _grounding_bundle(
                prompt=prompt,
                knowledge_snapshot=ks_for_gp,
                memory_snapshot=mem_snapshot,
                legacy_trace=tr,
                agent_id=None,
            )
            content: Dict[str, Any] = {
                "text": "NOTION OPS: DISARMED",
                "proposed_commands": [],
                "agent_id": None,
                "read_only": True,
                "notion_ops": {
                    "armed": False,
                    "armed_at": None,
                    "session_id": session_id,
                    "armed_state": st,
                },
            }
            if debug_on:
                content["trace"] = tr
                content.update(kb)
                content.update(grounding)
            return JSONResponse(content=content)

        # Determine armed state (default false if no session_id)
        st = (
            await _get_state(session_id)
            if session_id
            else {"armed": False, "armed_at": None}
        )
        armed = bool(st.get("armed") is True)

        # Build a first grounding pack early so the agent can cite KB ids deterministically.
        pre_grounding = _grounding_bundle(
            prompt=prompt,
            knowledge_snapshot=ks_for_gp,
            memory_snapshot=mem_snapshot,
            legacy_trace=None,
            agent_id="ceo_advisor",
        )
        gp_for_agent = (
            pre_grounding.get("grounding_pack")
            if isinstance(pre_grounding, dict)
            else None
        )
        gp_for_agent = gp_for_agent if isinstance(gp_for_agent, dict) else {}

        # Call advisor agent
        out = await create_ceo_advisor_agent(
            payload,
            {"memory": mem_snapshot, "grounding_pack": gp_for_agent},
        )

        legacy_trace = out.trace or {}
        if isinstance(legacy_trace, dict) and isinstance(notion_calls_for_trace, int):
            legacy_trace["notion_calls"] = int(notion_calls_for_trace)
        grounding = _grounding_bundle(
            prompt=prompt,
            knowledge_snapshot=ks_for_gp,
            memory_snapshot=mem_snapshot,
            legacy_trace=legacy_trace if isinstance(legacy_trace, dict) else {},
            agent_id=getattr(out, "agent_id", None),
        )

        pcs = getattr(out, "proposed_commands", None)
        normalized = _normalize_proposed_commands(pcs)
        actionable = [pc for pc in normalized if _is_actionable(pc)]

        # PHASE 6: hard gate when not ARMED
        if not armed:
            if actionable or _looks_like_write_intent(prompt):
                return _blocked_response(
                    out=out,
                    prompt=prompt,
                    session_id=session_id,
                    state=st,
                    why="Write intent detected but Notion Ops is not ARMED.",
                    kb=kb,
                    grounding=grounding,
                    debug_on=debug_on,
                )

            # If the advisor returned non-actionable proposal wrappers (e.g. approval-gated
            # memory/knowledge write proposals), keep them even when Notion Ops is DISARMED.
            # This preserves the enterprise workflow: propose → approve → execute.
            wrappers = [
                pc
                for pc in normalized
                if getattr(pc, "command", None) == PROPOSAL_WRAPPER_INTENT
            ]
            if wrappers:
                pcs_out: List[Dict[str, Any]] = []
                for pc in wrappers:
                    d = _pc_to_dict(pc, prompt=prompt)
                    pcs_out.append(_ensure_payload_summary_contract(d))

                # Enterprise UX: when Notion Ops is DISARMED, include an explicit arm suggestion
                # as a separate proposal (never auto-executed).
                if isinstance(session_id, str) and session_id.strip():
                    arm = ProposedCommand(
                        command="notion_ops_toggle",
                        args={"session_id": session_id.strip(), "armed": True},
                        reason="Optional: arm Notion Ops for Notion writes (not required for memory_write).",
                        requires_approval=True,
                        risk="LOW",
                        dry_run=True,
                        scope="api_notion_ops_toggle",
                        payload_summary={
                            "endpoint": "/api/notion-ops/toggle",
                            "canon": "NOTION_OPS_ARM_SUGGESTION",
                            "source": "api_chat",
                        },
                    )
                    pcs_out.append(
                        _ensure_payload_summary_contract(
                            _pc_to_dict(arm, prompt=prompt)
                        )
                    )

                content: Dict[str, Any] = {
                    "text": out.text,
                    "proposed_commands": pcs_out,
                    "agent_id": out.agent_id,
                    "read_only": True,
                    "notion_ops": {
                        "armed": False,
                        "armed_at": None,
                        "session_id": session_id,
                        "armed_state": st,
                    },
                }
                if debug_on:
                    content["trace"] = out.trace or {}
                    content.update(kb)
                    content.update(grounding)
                else:
                    minimal_trace = _minimal_trace_intent(out.trace)
                    if minimal_trace:
                        content["trace"] = minimal_trace
                return JSONResponse(content=content)

            content: Dict[str, Any] = {
                "text": out.text,
                "proposed_commands": [],
                "agent_id": out.agent_id,
                "read_only": True,
                "notion_ops": {
                    "armed": False,
                    "armed_at": None,
                    "session_id": session_id,
                    "armed_state": st,
                },
            }
            if debug_on:
                content["trace"] = out.trace or {}
                content.update(kb)
                content.update(grounding)
            else:
                minimal_trace = _minimal_trace_intent(out.trace)
                if minimal_trace:
                    content["trace"] = minimal_trace
            return JSONResponse(content=content)

        # ARMED: allow actionable, otherwise allow approval-wrapper fallback
        if actionable:
            for pc in actionable:
                _finalize_actionable(pc)

            pcs_out: List[Dict[str, Any]] = []
            for pc in actionable:
                d = (
                    pc.model_dump(by_alias=False)
                    if hasattr(pc, "model_dump")
                    else pc.dict(by_alias=False)
                )
                if isinstance(d, dict):
                    pcs_out.append(_ensure_payload_summary_contract(d))

            tr = out.trace or {}
            if not isinstance(tr, dict):
                tr = {}
            tr.setdefault("phase6_notion_ops_gate", {})
            tr["phase6_notion_ops_gate"] = {
                "armed": True,
                "session_id_present": bool(session_id),
            }

            text_out = out.text
            if _looks_like_write_intent(prompt):
                text_out = _armed_write_ack(prompt, has_actionable=True)

            content: Dict[str, Any] = {
                "text": text_out,
                "proposed_commands": pcs_out,
                "agent_id": out.agent_id,
                "read_only": True,
                "notion_ops": {
                    "armed": True,
                    "armed_at": st.get("armed_at"),
                    "session_id": session_id,
                    "armed_state": st,
                },
            }
            if debug_on:
                content["trace"] = tr
                content.update(kb)
                content.update(grounding)
            else:
                minimal_trace = _minimal_trace_intent(tr)
                if minimal_trace:
                    content["trace"] = minimal_trace
            return JSONResponse(content=content)

        # No actionable → fallback:
        if _looks_like_write_intent(prompt):
            fallback = _build_approval_wrapper(
                prompt,
                reason="Approval required (write intent, but no structured proposal returned).",
            )
        else:
            fallback = None

        out.read_only = True

        tr = out.trace or {}
        if not isinstance(tr, dict):
            tr = {}
        tr.setdefault("phase6_notion_ops_gate", {})
        tr["phase6_notion_ops_gate"] = {
            "armed": True,
            "session_id_present": bool(session_id),
            "fallback": True,
        }

        text_out = out.text
        if _looks_like_write_intent(prompt):
            text_out = _armed_write_ack(prompt, has_actionable=False)

        content: Dict[str, Any] = {
            "text": text_out,
            "proposed_commands": [
                _ensure_payload_summary_contract(_pc_to_dict(fallback, prompt=prompt))
            ]
            if isinstance(fallback, ProposedCommand)
            else [],
            "agent_id": out.agent_id,
            "read_only": True,
            "notion_ops": {
                "armed": True,
                "armed_at": st.get("armed_at"),
                "session_id": session_id,
                "armed_state": st,
            },
        }
        if debug_on:
            content["trace"] = tr
            content.update(kb)
            content.update(grounding)
        else:
            minimal_trace = _minimal_trace_intent(tr)
            if minimal_trace:
                content["trace"] = minimal_trace
        return JSONResponse(content=content)

    return router

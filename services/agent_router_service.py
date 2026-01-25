from __future__ import annotations

import importlib
import inspect
from typing import Any, Callable, Dict, List, Tuple

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.agent_registry_service import AgentRegistryEntry, AgentRegistryService

# Callable može vratiti AgentOutput ili awaitable AgentOutput
AgentCallable = Callable[[AgentInput, Dict[str, Any]], Any]


class AgentRouterService:
    """
    Deterministički router preko registry-ja (SSOT via AgentRegistryService).

    MODES:
    - read_only=True  -> READ/PROPOSE ONLY (nikad ne izvršava)
    - read_only=False -> execution-capable routing, ali ProposedCommand contract i dalje može ostati proposal-only
                         (u ovom kodu status READY/BLOCKED je signal; dry_run ostaje True jer je kanonski).
    """

    def __init__(self, registry: AgentRegistryService) -> None:
        self.registry = registry

    def _get_flags(self, agent_input: AgentInput) -> Tuple[bool, bool]:
        """
        Izvlači read_only i require_approval iz agent_input.metadata (primarno),
        uz fallback na identity_pack.

        Sigurni defaulti:
        - read_only default True
        - require_approval default True
        """
        md = getattr(agent_input, "metadata", None)
        if not isinstance(md, dict):
            md = {}

        ip = getattr(agent_input, "identity_pack", None)
        if not isinstance(ip, dict):
            ip = {}

        ro_raw = md.get("read_only", ip.get("read_only", True))
        ra_raw = md.get("require_approval", ip.get("require_approval", True))

        read_only = bool(ro_raw) if ro_raw is not None else True
        require_approval = bool(ra_raw) if ra_raw is not None else True

        # persist flags back (da agenti vide konzistentno)
        md["read_only"] = read_only
        md["require_approval"] = require_approval
        md.setdefault(
            "canon",
            "ceo_console_router" if not read_only else "read_propose_only",
        )
        agent_input.metadata = md  # type: ignore[assignment]

        return read_only, require_approval

    def _enforce_read_only_input(self, agent_input: AgentInput) -> None:
        """
        Defense-in-depth: kad smo u read_only modu, osiguraj da se ulaz tretira kao read-only.
        """
        md = getattr(agent_input, "metadata", None)
        if not isinstance(md, dict):
            md = {}
        md["read_only"] = True
        md.setdefault("canon", "read_propose_only")
        agent_input.metadata = md  # type: ignore[assignment]

        if hasattr(agent_input, "read_only"):
            try:
                agent_input.read_only = True  # type: ignore[attr-defined]
            except Exception:
                pass

    async def route(self, agent_input: AgentInput) -> AgentOutput:
        read_only, require_approval = self._get_flags(agent_input)

        if read_only:
            self._enforce_read_only_input(agent_input)

        agents = self.registry.list_agents(enabled_only=True)
        if not agents:
            return AgentOutput(
                text="No agents available (registry empty or all disabled).",
                proposed_commands=[],
                agent_id="none",
                read_only=read_only,
                trace={
                    "reason": "no_enabled_agents",
                    "read_only": read_only,
                    "require_approval": require_approval,
                },
            )

        selected, trace = self._select_agent(agent_input, agents)

        if not selected.entrypoint:
            return AgentOutput(
                text="Selected agent is missing entrypoint (registry entry.entrypoint).",
                proposed_commands=[],
                agent_id=selected.id,
                read_only=read_only,
                trace={
                    **trace,
                    "error": "missing_entrypoint",
                    "read_only": read_only,
                    "require_approval": require_approval,
                },
            )

        callable_fn = self._load_callable(selected.entrypoint)

        md = getattr(agent_input, "metadata", None)
        if not isinstance(md, dict):
            md = {}
        ctx_extra = md.get("agent_ctx")
        ctx_for_agent: Dict[str, Any] = {
            "registry_entry": selected,
            "trace": trace,
        }
        if isinstance(ctx_extra, dict):
            for k, v in ctx_extra.items():
                # Do not allow clobbering router-provided keys.
                if k in {"registry_entry", "trace"}:
                    continue
                ctx_for_agent[k] = v

        try:
            routed = callable_fn(agent_input, ctx_for_agent)
            if inspect.isawaitable(routed):
                routed = await routed
            out = routed

            # Normalize dict -> AgentOutput
            if isinstance(out, dict):
                out = AgentOutput(
                    text=str(out.get("text") or out.get("summary") or ""),
                    proposed_commands=out.get("proposed_commands") or [],
                    agent_id=str(out.get("agent_id") or selected.id),
                    read_only=bool(out.get("read_only", read_only)),
                    trace=out.get("trace") or {},
                )

            if not isinstance(out, AgentOutput):
                out = AgentOutput(
                    text="Agent returned unsupported output type.",
                    proposed_commands=[],
                    agent_id=selected.id,
                    read_only=read_only,
                    trace={**trace, "error": f"unsupported_output_type:{type(out)}"},
                )

        except Exception as e:  # noqa: BLE001
            out = AgentOutput(
                text="Agent execution failed.",
                proposed_commands=[],
                agent_id=selected.id,
                read_only=read_only,
                trace={
                    **trace,
                    "error": repr(e),
                    "read_only": read_only,
                    "require_approval": require_approval,
                },
            )

        # Router SSOT for agent_id + flags
        out.agent_id = selected.id
        out.read_only = read_only

        # Merge trace
        merged_trace = dict(trace)
        extra_trace = out.trace if isinstance(out.trace, dict) else {}
        merged_trace.update(extra_trace)
        merged_trace["router"] = "AgentRouterService"
        merged_trace["selected_agent_id"] = selected.id
        merged_trace["selected_entrypoint"] = selected.entrypoint
        merged_trace["read_only"] = read_only
        merged_trace["require_approval"] = require_approval
        out.trace = merged_trace

        # =========================================================
        # Approval gating / proposal policy
        # - ProposedCommand is proposal-only in your contract (dry_run hard-True)
        # - We use status READY/BLOCKED as the only execution signal
        # =========================================================
        pcs = out.proposed_commands or []
        normalized_pcs: List[ProposedCommand] = []

        for pc in pcs:
            try:
                if isinstance(pc, dict):
                    pc = ProposedCommand(
                        command=str(
                            pc.get("command")
                            or pc.get("command_type")
                            or pc.get("type")
                            or ""
                        ),
                        args=pc.get("args")
                        if isinstance(pc.get("args"), dict)
                        else (
                            pc.get("payload")
                            if isinstance(pc.get("payload"), dict)
                            else {}
                        ),
                        reason=pc.get("reason"),
                        requires_approval=pc.get("requires_approval", True),
                        risk=pc.get("risk"),
                        dry_run=pc.get("dry_run", True),
                    )

                if not isinstance(pc, ProposedCommand):
                    continue

                # Always enforce dry_run True (contract-aligned)
                pc.dry_run = True

                # Determine requires_approval safely
                pc_requires = True
                try:
                    if hasattr(pc, "requires_approval"):
                        pc_requires = (
                            bool(pc.requires_approval)
                            if pc.requires_approval is not None
                            else True
                        )
                except Exception:
                    pc_requires = True

                # Decide status
                status = "BLOCKED"
                if read_only:
                    status = "BLOCKED"
                    # in read-only, even "requires_approval=False" still stays blocked (proposal-only endpoint semantics)
                else:
                    # execution-capable routing: if approval required, block; else ready
                    if require_approval and pc_requires:
                        status = "BLOCKED"
                    else:
                        status = "READY"

                # Set optional attributes if they exist
                try:
                    if hasattr(pc, "status"):
                        pc.status = status  # type: ignore[attr-defined]
                except Exception:
                    pass

                normalized_pcs.append(pc)

            except Exception:
                continue

        out.proposed_commands = normalized_pcs
        return out

    def _select_agent(
        self,
        agent_input: AgentInput,
        agents: List[AgentRegistryEntry],
    ) -> Tuple[AgentRegistryEntry, Dict[str, Any]]:
        msg = (agent_input.message or "").lower()

        preferred_id = getattr(agent_input, "preferred_agent_id", None)
        if preferred_id:
            explicit = self.registry.get_agent(preferred_id)
            if explicit and explicit.enabled:
                return explicit, {
                    "selected_by": "preferred_agent_id",
                    "preferred_agent_id": preferred_id,
                    "candidates": [a.id for a in agents],
                }

        msg_tokens = _tokenize(msg)
        msg_set = set(msg_tokens)

        scores: List[Tuple[AgentRegistryEntry, int, List[str]]] = []
        for a in agents:
            kw = [k.lower() for k in (a.keywords or [])]
            hits = [k for k in kw if k in msg_set or k in msg]
            scores.append((a, len(hits), hits))

        def _prio(x: Any) -> int:
            try:
                return int(x) if x is not None else 0
            except Exception:
                return 0

        scores.sort(key=lambda t: (-t[1], -_prio(t[0].priority), t[0].id))

        chosen, _score, _hits = scores[0]
        trace = {
            "selected_by": "keyword_score",
            "message_tokens": msg_tokens[:64],
            "ranking": [
                {
                    "agent": s[0].id,
                    "score": s[1],
                    "hits": s[2],
                    "priority": s[0].priority,
                    "enabled": s[0].enabled,
                }
                for s in scores
            ],
        }
        return chosen, trace

    def _load_callable(self, entrypoint: str) -> AgentCallable:
        module_path, fn_name = entrypoint.split(":", 1)
        mod = importlib.import_module(module_path)
        fn = getattr(mod, fn_name, None)
        if fn is None or not callable(fn):
            raise ValueError(
                f"Invalid agent entrypoint; callable not found: {entrypoint}"
            )
        return fn


def _tokenize(text: str) -> List[str]:
    buf: List[str] = []
    cur: List[str] = []
    for ch in text:
        if ch.isalnum() or ch in ("_", "-"):
            cur.append(ch)
        else:
            if cur:
                buf.append("".join(cur))
                cur = []
    if cur:
        buf.append("".join(cur))
    return buf

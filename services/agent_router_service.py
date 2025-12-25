from __future__ import annotations

import importlib
from typing import Any, Callable, Dict, List, Tuple

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.agent_registry_service import AgentRegistryEntry, AgentRegistryService

AgentCallable = Callable[[AgentInput, Dict[str, Any]], AgentOutput]


class AgentRouterService:
    """
    Deterministički router preko registry-ja (SSOT via AgentRegistryService).

    FAZA 4 CANON:
    - /api/chat je READ/PROPOSE ONLY
    - router NE SMIJE izvršavati ništa, samo vraća AgentOutput
    - deterministički izbor + trace

    Očekivanja od AgentRegistryService:
    - list_agents(enabled_only=True) -> List[AgentRegistryEntry]
    - get_agent(agent_id) -> Optional[AgentRegistryEntry]
    """

    def __init__(self, registry: AgentRegistryService) -> None:
        self.registry = registry

    def route(self, agent_input: AgentInput) -> AgentOutput:
        agents = self.registry.list_agents(enabled_only=True)
        if not agents:
            return AgentOutput(
                text="No agents available (registry empty or all disabled).",
                proposed_commands=[],
                agent_id="none",
                read_only=True,
                trace={"reason": "no_enabled_agents"},
            )

        selected, trace = self._select_agent(agent_input, agents)

        if not selected.entrypoint:
            return AgentOutput(
                text="Selected agent is missing entrypoint (registry entry.entrypoint).",
                proposed_commands=[],
                agent_id=selected.id,
                read_only=True,
                trace={**trace, "error": "missing_entrypoint"},
            )

        callable_fn = self._load_callable(selected.entrypoint)

        try:
            out = callable_fn(agent_input, {"registry_entry": selected, "trace": trace})
        except Exception as e:  # noqa: BLE001
            # Fail closed: i dalje read-only i bez execute.
            out = AgentOutput(
                text="Agent execution failed in read-only mode.",
                proposed_commands=[],
                agent_id=selected.id,
                read_only=True,
                trace={**trace, "error": repr(e)},
            )

        # Enforce CANON requirement: read-only response
        out.read_only = True
        out.agent_id = selected.id
        out.trace = {**trace, **(out.trace or {})}

        for pc in out.proposed_commands or []:
            pc.dry_run = True

        return out

    # =========================================================
    # INTERNALS
    # =========================================================
    def _select_agent(
        self,
        agent_input: AgentInput,
        agents: List[AgentRegistryEntry],
    ) -> Tuple[AgentRegistryEntry, Dict[str, Any]]:
        msg = (agent_input.message or "").lower()

        # 1) Explicit override (if valid and enabled)
        preferred_id = getattr(agent_input, "preferred_agent_id", None)
        if preferred_id:
            explicit = self.registry.get_agent(preferred_id)
            if explicit and explicit.enabled:
                return explicit, {
                    "selected_by": "preferred_agent_id",
                    "preferred_agent_id": preferred_id,
                    "candidates": [a.id for a in agents],
                }

        # 2) Keyword scoring (deterministički)
        msg_tokens = _tokenize(msg)
        msg_set = set(msg_tokens)

        scores: List[Tuple[AgentRegistryEntry, int, List[str]]] = []
        for a in agents:
            kw = [k.lower() for k in (a.keywords or [])]
            hits = [k for k in kw if k in msg_set or k in msg]
            scores.append((a, len(hits), hits))

        # Sort: score desc, priority desc, id asc
        scores.sort(key=lambda t: (-t[1], -t[0].priority, t[0].id))

        chosen, _score, hits = scores[0]
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
                f"Invalid agent entrypoint; callable not found: {entrypoint}",
            )
        return fn


def _tokenize(text: str) -> List[str]:
    # Minimal tokenizer, stabilan i determinističan.
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


# ---------------------------------------------------------------------
# Minimal agent implementations (READ/PROPOSE ONLY)
# ---------------------------------------------------------------------


def ceo_clone_agent(agent_input: AgentInput, ctx: Dict[str, Any]) -> AgentOutput:
    msg = (agent_input.message or "").strip()
    proposed: List[ProposedCommand] = []

    lower = msg.lower()
    if any(x in lower for x in ["goal", "kpi", "plan", "strategy", "priorities"]):
        proposed.append(
            ProposedCommand(
                command="ceo.plan.propose",
                args={"prompt": msg},
                reason=(
                    "User is asking for CEO-level planning; proposing a planning "
                    "command for the write/approval pipeline."
                ),
                requires_approval=True,
                risk="MED",
                dry_run=True,
            ),
        )

    text = (
        "CEO Clone (read-only): Primio sam upit i mogu pomoći sa analizom i "
        "prijedlogom narednih koraka. Ako želiš da sistem kasnije izvrši bilo "
        "kakav write, to mora ići kroz approval/ops pipeline; ovdje samo "
        "predlažem.\n\n"
        f"Sažetak upita: {msg}"
    )

    return AgentOutput(
        text=text,
        proposed_commands=proposed,
        agent_id="ceo_clone",
        read_only=True,
        trace={"agent": "ceo_clone"},
    )


def specialist_notion_agent(
    agent_input: AgentInput,
    ctx: Dict[str, Any],
) -> AgentOutput:
    msg = (agent_input.message or "").strip()
    lower = msg.lower()
    proposed: List[ProposedCommand] = []

    if "notion" in lower or any(
        x in lower for x in ["database", "page", "property", "schema"]
    ):
        proposed.append(
            ProposedCommand(
                command="notion.read.propose",
                args={"query": msg},
                reason=(
                    "User is asking for Notion-related info; proposing a read/query "
                    "command."
                ),
                requires_approval=False,
                risk="LOW",
                dry_run=True,
            ),
        )

        if any(x in lower for x in ["create", "add", "update", "delete"]):
            proposed.append(
                ProposedCommand(
                    command="notion.write.propose",
                    args={"intent": msg},
                    reason=(
                        "User request implies a write in Notion; proposing it for "
                        "approval workflow."
                    ),
                    requires_approval=True,
                    risk="HIGH",
                    dry_run=True,
                ),
            )

    text = (
        "Notion Specialist (read-only): Mogu mapirati tvoj zahtjev na Notion "
        "operacije i vratiti prijedloge komandi. Ovdje se ništa ne izvršava.\n\n"
        f"Sažetak upita: {msg}"
    )

    return AgentOutput(
        text=text,
        proposed_commands=proposed,
        agent_id="specialist_notion",
        read_only=True,
        trace={"agent": "specialist_notion"},
    )

from __future__ import annotations

import importlib
import inspect
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.agent_registry_service import AgentRegistryEntry, AgentRegistryService

AgentCallable = Callable[[AgentInput, Dict[str, Any]], AgentOutput]


class AgentRouterService:
    """
    Deterministički router preko registry-ja (SSOT via AgentRegistryService).

    MODES:
    - read_only=True  -> READ/PROPOSE ONLY (nikad ne izvršava)
    - read_only=False -> EXECUTION CAPABLE (agent može raditi “full” logiku),
                         ali ako require_approval=True, komande koje traže approval
                         ostaju dry_run/BLOCKED dok ne dođe approve.

    Očekivanja od AgentRegistryService:
    - list_agents(enabled_only=True) -> List[AgentRegistryEntry]
    - get_agent(agent_id) -> Optional[AgentRegistryEntry]
    """

    def __init__(self, registry: AgentRegistryService) -> None:
        self.registry = registry

    def _get_flags(self, agent_input: AgentInput) -> Tuple[bool, bool]:
        """
        Izvlači read_only i require_approval iz agent_input.metadata (primarno),
        uz fallback na identity_pack.

        Defaults:
        - read_only default True (sigurni default za generičke chat rute)
        - require_approval default True (sigurni default za write scenarije)
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

        # persist flags back (da ih agenti vide konzistentno)
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
        # ✅ poštuj flags iz requesta
        read_only, require_approval = self._get_flags(agent_input)

        # Ako je read-only, enforce (kao prije). Ako nije, NE diramo u read_only.
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

        # Execute agent callable. Allow sync or async agent implementations.
        try:
            routed = callable_fn(
                agent_input, {"registry_entry": selected, "trace": trace}
            )
            if inspect.isawaitable(routed):
                routed = await routed

            out = routed

            # Safety: ako agent vrati dict umjesto AgentOutput, probaj normalizovati
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

        # Always set agent_id (router SSOT)
        out.agent_id = selected.id

        # Preserve/force read_only according to input flags (router contract)
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

        # ✅ Approval gating / dry-run policy
        pcs = out.proposed_commands or []
        normalized_pcs: List[ProposedCommand] = []

        for pc in pcs:
            try:
                # Ako agent vrati dict umjesto ProposedCommand, probaj normalizovati
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

                # U read_only modu: sve je dry-run
                if read_only:
                    pc.dry_run = True
                    if hasattr(pc, "execute"):
                        pc.execute = False  # type: ignore[attr-defined]
                    if hasattr(pc, "approved"):
                        pc.approved = False  # type: ignore[attr-defined]
                    if (
                        hasattr(pc, "requires_approval")
                        and pc.requires_approval is None
                    ):
                        pc.requires_approval = True
                    if hasattr(pc, "status"):
                        pc.status = "BLOCKED"  # type: ignore[attr-defined]
                    normalized_pcs.append(pc)
                    continue

                # U execution-capable modu:
                # - ako require_approval=True i komanda traži approval -> dry_run + BLOCKED
                pc_requires = True
                if hasattr(pc, "requires_approval"):
                    try:
                        pc_requires = (
                            bool(pc.requires_approval)
                            if pc.requires_approval is not None
                            else True
                        )
                    except Exception:
                        pc_requires = True

                if require_approval and pc_requires:
                    pc.dry_run = True
                    if hasattr(pc, "execute"):
                        pc.execute = False  # type: ignore[attr-defined]
                    if hasattr(pc, "approved"):
                        pc.approved = False  # type: ignore[attr-defined]
                    if hasattr(pc, "status"):
                        pc.status = "BLOCKED"  # type: ignore[attr-defined]
                else:
                    # Nije tražen approval: može biti “ready”
                    if hasattr(pc, "dry_run"):
                        pc.dry_run = False
                    if hasattr(pc, "execute"):
                        pc.execute = True  # type: ignore[attr-defined]
                    if hasattr(pc, "status"):
                        st = getattr(pc, "status", None)
                        if st in (None, "", "BLOCKED"):
                            pc.status = "READY"  # type: ignore[attr-defined]

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


# =========================================================
# CONTEXT HELPERS (READ-ONLY)
# =========================================================
def _safe_get_ceo_system_snapshot() -> Dict[str, Any]:
    """
    Best-effort konsolidovani snapshot za READ odgovor.
    Ne baca exception (fail-soft).
    """
    try:
        from services.system_read_executor import SystemReadExecutor  # type: ignore

        ex = SystemReadExecutor()
        snap = ex.snapshot()
        if isinstance(snap, dict):
            return snap
    except Exception:
        pass

    out: Dict[str, Any] = {}

    try:
        from services.ceo_console_snapshot_service import (  # type: ignore
            CEOConsoleSnapshotService,
        )

        out["ceo_notion_snapshot"] = CEOConsoleSnapshotService().snapshot()
    except Exception:
        out["ceo_notion_snapshot"] = {"available": False}

    try:
        from services.knowledge_snapshot_service import (  # type: ignore
            KnowledgeSnapshotService,
        )

        out["knowledge_snapshot"] = KnowledgeSnapshotService.get_snapshot()
    except Exception:
        out["knowledge_snapshot"] = {"available": False}

    try:
        from services.identity_loader import load_ceo_identity_pack  # type: ignore

        out["identity_pack"] = load_ceo_identity_pack()
    except Exception:
        out["identity_pack"] = {"available": False}

    return out


def _dig(snapshot: Dict[str, Any], path: Tuple[str, ...]) -> Any:
    cur: Any = snapshot
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _extract_list(
    snapshot: Dict[str, Any], candidates: List[Tuple[str, ...]]
) -> List[Dict[str, Any]]:
    for path in candidates:
        v = _dig(snapshot, path)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    return []


def _extract_goals(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _extract_list(
        snapshot,
        [
            ("ceo_notion_snapshot", "dashboard", "goals"),
            ("ceo_dashboard_snapshot", "dashboard", "goals"),
            ("ceo_console_snapshot", "dashboard", "goals"),
        ],
    )


def _extract_tasks(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _extract_list(
        snapshot,
        [
            ("ceo_notion_snapshot", "dashboard", "tasks"),
            ("ceo_dashboard_snapshot", "dashboard", "tasks"),
            ("ceo_console_snapshot", "dashboard", "tasks"),
        ],
    )


def _extract_projects(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _extract_list(
        snapshot,
        [
            ("knowledge_snapshot", "projects"),
            ("ceo_notion_snapshot", "dashboard", "projects"),
        ],
    )


def _extract_kpis(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _extract_list(
        snapshot,
        [
            ("knowledge_snapshot", "kpi"),
            ("knowledge_snapshot", "kpis"),
            ("ceo_notion_snapshot", "dashboard", "kpi"),
        ],
    )


def _extract_identity_name(snapshot: Dict[str, Any]) -> Optional[str]:
    ip = snapshot.get("identity_pack")
    if isinstance(ip, dict):
        ident = ip.get("identity")
        if isinstance(ident, dict):
            nm = ident.get("name") or ident.get("display_name")
            if isinstance(nm, str) and nm.strip():
                return nm.strip()
    return None


def _normalize_ascii(s: str) -> str:
    repl = {
        "š": "s",
        "đ": "d",
        "č": "c",
        "ć": "c",
        "ž": "z",
        "Š": "s",
        "Đ": "d",
        "Č": "c",
        "Ć": "c",
        "Ž": "z",
    }
    return "".join(repl.get(ch, ch) for ch in (s or ""))


def _parse_limit(text: str, default: int = 25, max_limit: int = 100) -> int:
    t = (text or "").lower()
    m = re.search(r"(?:limit|top|prvih)\s*[:=]?\s*(\d{1,4})", t)
    if not m:
        return default
    try:
        n = int(m.group(1))
    except Exception:
        return default
    if n < 1:
        return default
    return min(n, max_limit)


def _parse_filter(text: str, key: str) -> Optional[str]:
    t = (text or "").strip()
    if not t:
        return None

    stop = r"(?:\b(?:limit|top|prvih|priority|prioritet|status)\b\s*[:=]|\b(?:limit|top|prvih|priority|prioritet|status)\b\s+\S)"
    m = re.search(
        rf"(?:\b{re.escape(key)}\b)\s*[:=]\s*(.+?)(?=\s+{stop}|\s*$)",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        v = (m.group(1) or "").strip()
        v = re.split(
            r"\b(?:limit|top|prvih|priority|prioritet|status)\b\s*[:=]",
            v,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        return v or None

    m2 = re.search(
        rf"(?:\b{re.escape(key)}\b)\s+(.+?)(?=\s+{stop}|\s*$)",
        t,
        flags=re.IGNORECASE,
    )
    if m2:
        v = (m2.group(1) or "").strip()
        v = re.split(
            r"\b(?:limit|top|prvih|priority|prioritet|status)\b\s*[:=]",
            v,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        return v or None

    return None


def _filter_items(
    items: List[Dict[str, Any]], *, status: Optional[str], priority: Optional[str]
) -> List[Dict[str, Any]]:
    out = items
    if status:
        s = status.strip().lower()
        out = [x for x in out if str(x.get("status", "")).strip().lower() == s]
    if priority:
        p = priority.strip().lower()
        out = [x for x in out if str(x.get("priority", "")).strip().lower() == p]
    return out


def _render_items(items: List[Dict[str, Any]], kind: str, *, limit: int) -> str:
    if not items:
        return "Nema rezultata."

    lines: List[str] = []
    for x in items[: max(1, limit)]:
        if kind == "goals":
            name = str(x.get("name") or x.get("title") or "(bez naziva)").strip()
            _id = str(x.get("id") or "-").strip()
            status = str(x.get("status") or "-").strip()
            prio = str(x.get("priority") or "-").strip()
            due = str(x.get("deadline") or x.get("due_date") or "-").strip()
            lines.append(
                f"- {name} | id: {_id} | status: {status} | prioritet: {prio} | deadline: {due}"
            )
        elif kind == "tasks":
            title = str(x.get("title") or x.get("name") or "(bez naziva)").strip()
            _id = str(x.get("id") or "-").strip()
            status = str(x.get("status") or "-").strip()
            prio = str(x.get("priority") or "-").strip()
            due = str(x.get("due_date") or x.get("deadline") or "-").strip()
            lines.append(
                f"- {title} | id: {_id} | status: {status} | prioritet: {prio} | due: {due}"
            )
        elif kind == "kpis":
            name = str(x.get("name") or x.get("title") or "(bez naziva)").strip()
            val = str(x.get("value") or x.get("current") or "-").strip()
            tgt = str(x.get("target") or "-").strip()
            status = str(x.get("status") or "-").strip()
            lines.append(f"- {name} | value: {val} | target: {tgt} | status: {status}")
        elif kind == "projects":
            name = str(x.get("name") or x.get("title") or "(bez naziva)").strip()
            status = str(x.get("status") or "-").strip()
            prio = str(x.get("priority") or "-").strip()
            lines.append(f"- {name} | status: {status} | prioritet: {prio}")
        else:
            lines.append(f"- {x}")

    if len(items) > limit:
        lines.append(f"(+ još {len(items) - limit})")
    return "\n".join(lines)


def _inventory(snapshot: Dict[str, Any]) -> str:
    keys = sorted([k for k in snapshot.keys() if isinstance(k, str)])
    goals = _extract_goals(snapshot)
    tasks = _extract_tasks(snapshot)
    kpis = _extract_kpis(snapshot)
    projects = _extract_projects(snapshot)

    extra_dbs = _dig(snapshot, ("knowledge_snapshot", "extra_databases"))
    extra_count = len(extra_dbs) if isinstance(extra_dbs, dict) else 0

    return (
        "INVENTORY (READ-only snapshot):\n"
        f"- root_keys: {', '.join(keys)}\n"
        f"- goals: {len(goals)}\n"
        f"- tasks: {len(tasks)}\n"
        f"- kpis: {len(kpis)}\n"
        f"- projects: {len(projects)}\n"
        f"- extra_databases: {extra_count}\n\n"
        "Primjeri upita:\n"
        "- pokazi/pokaži ciljeve status:Aktivan limit:20\n"
        "- pokazi/pokaži taskove status:To Do limit:20\n"
        "- pokazi/pokaži kpi limit:50\n"
        "- pokazi/pokaži properties goal:<id>\n"
        "- pokazi/pokaži baze\n"
    )


def _stringify_value(v: Any, max_chars: int) -> str:
    try:
        s = str(v)
    except Exception:
        s = repr(v)
    if len(s) > max_chars:
        return s[: max_chars - 1] + "…"
    return s


def _try_properties(snapshot: Dict[str, Any], *, kind: str, item_id: str) -> str:
    item_id = (item_id or "").strip()
    if not item_id:
        return "Nedostaje id. Primjer: pokaži properties goal:<id>"

    if kind == "goal":
        items = _extract_goals(snapshot)
    elif kind == "task":
        items = _extract_tasks(snapshot)
    else:
        return "Podržano: goal ili task. Primjer: pokaži properties goal:<id>"

    found: Optional[Dict[str, Any]] = None
    for x in items:
        if str(x.get("id") or "").strip() == item_id:
            found = x
            break

    if not isinstance(found, dict):
        return f"Nisam našao {kind} sa id={item_id} u trenutnom snapshot-u."

    props_text = found.get("properties_text")
    props_raw = found.get("properties")

    if isinstance(props_text, dict) and props_text:
        keys = sorted(list(props_text.keys()))[:200]
        lines = [f"Properties (normalized) ({kind} id={item_id}):"]
        for k in keys:
            v = props_text.get(k)
            lines.append(f"- {k}: {_stringify_value(v, 500)}")
        remaining = len(props_text) - len(keys)
        if remaining > 0:
            lines.append(f"(+ još {remaining} properties)")
        return "\n".join(lines)

    if isinstance(props_raw, dict) and props_raw:
        keys = sorted(list(props_raw.keys()))[:200]
        lines = [f"Properties (raw) ({kind} id={item_id}):"]
        for k in keys:
            v = props_raw.get(k)
            lines.append(f"- {k}: {_stringify_value(v, 500)}")
        remaining = len(props_raw) - len(keys)
        if remaining > 0:
            lines.append(f"(+ još {remaining} properties)")
        return "\n".join(lines)

    avail = sorted([k for k in found.keys() if isinstance(k, str)])
    return (
        f"Snapshot trenutno nema 'properties' za ovaj {kind} (id={item_id}).\n"
        f"Dostupna polja u snapshotu: {', '.join(avail)}"
    )


# ---------------------------------------------------------------------
# Agent implementations (READ/PROPOSE ONLY)
# ---------------------------------------------------------------------
def ceo_clone_agent(agent_input: AgentInput, ctx: Dict[str, Any]) -> AgentOutput:
    msg = (agent_input.message or "").strip()
    lower_ascii = _normalize_ascii((msg or "").lower())

    snap = _safe_get_ceo_system_snapshot()
    who = _extract_identity_name(snap) or "Adnan.AI"

    proposed: List[ProposedCommand] = []

    if any(
        x in lower_ascii
        for x in [
            "inventory",
            "sta imas",
            "šta imaš",
            "what do you have",
            "help",
            "pomoc",
            "pomoć",
        ]
    ):
        return AgentOutput(
            text=_inventory(snap),
            proposed_commands=[],
            agent_id="ceo_clone",
            read_only=True,
            trace={
                "agent": "ceo_clone",
                "intent": "inventory",
                **(ctx.get("trace") or {}),
            },
        )

    if any(x in lower_ascii for x in ["ko si ti", "tko si ti", "who are you", "ko si"]):
        text = (
            f"{who} (CEO Advisor): Ja sam CEO advisory sloj unutar Adnan.AI OS-a. "
            "Mogu vratiti analizu + prijedloge komandi. Izvršenje write ide kroz approval."
        )
        return AgentOutput(
            text=text,
            proposed_commands=[],
            agent_id="ceo_clone",
            read_only=True,
            trace={
                "agent": "ceo_clone",
                "intent": "who_am_i",
                **(ctx.get("trace") or {}),
            },
        )

    m_props = re.search(
        r"(?:properties|props)\s+(goal|task)\s*[:=]\s*([0-9a-fA-F\-]{16,})",
        msg,
        flags=re.IGNORECASE,
    )
    if m_props:
        kind = (m_props.group(1) or "").strip().lower()
        _id = (m_props.group(2) or "").strip()
        text = _try_properties(snap, kind=kind, item_id=_id)
        return AgentOutput(
            text=text,
            proposed_commands=[],
            agent_id="ceo_clone",
            read_only=True,
            trace={
                "agent": "ceo_clone",
                "intent": "show_properties",
                "kind": kind,
                **(ctx.get("trace") or {}),
            },
        )

    if any(
        x in lower_ascii
        for x in [
            "pokazi baze",
            "pokaži baze",
            "databases",
            "baze",
            "db list",
            "lista baza",
        ]
    ):
        extra = _dig(snap, ("knowledge_snapshot", "extra_databases"))
        lines = ["Baze (best-effort iz snapshot-a):"]
        core = [
            "goals",
            "tasks",
            "projects",
            "kpi",
            "leads",
            "agent_exchange",
            "ai_summary",
        ]
        lines.append(f"- core: {', '.join(core)}")
        if isinstance(extra, dict) and extra:
            names = sorted(list(extra.keys()))[:200]
            lines.append(f"- extra_databases ({len(extra)}): " + ", ".join(names))
        else:
            lines.append("- extra_databases: (nema ili nije učitano u snapshot)")
        return AgentOutput(
            text="\n".join(lines),
            proposed_commands=[],
            agent_id="ceo_clone",
            read_only=True,
            trace={
                "agent": "ceo_clone",
                "intent": "list_databases",
                **(ctx.get("trace") or {}),
            },
        )

    limit = _parse_limit(msg, default=25, max_limit=100)
    status = _parse_filter(msg, "status")
    priority = _parse_filter(msg, "priority") or _parse_filter(msg, "prioritet")

    if any(
        x in lower_ascii
        for x in ["pokazi ciljeve", "pokaži ciljeve", "ciljevi", "goals"]
    ):
        base = _extract_goals(snap)
        goals = _filter_items(base, status=status, priority=priority)
        if base and not goals and (status or priority):
            text = (
                "Ciljevi (snapshot):\n"
                f"Nema rezultata za filtere: status={status or '-'}, prioritet={priority or '-'}.\n"
                f"(ukupno u snapshotu: {len(base)})"
            )
        else:
            text = "Ciljevi (snapshot):\n" + _render_items(goals, "goals", limit=limit)
        return AgentOutput(
            text=text,
            proposed_commands=[],
            agent_id="ceo_clone",
            read_only=True,
            trace={
                "agent": "ceo_clone",
                "intent": "show_goals",
                "limit": limit,
                "status": status,
                "priority": priority,
                **(ctx.get("trace") or {}),
            },
        )

    if any(
        x in lower_ascii
        for x in ["pokazi taskove", "pokaži taskove", "taskovi", "tasks"]
    ):
        base = _extract_tasks(snap)
        tasks = _filter_items(base, status=status, priority=priority)
        if base and not tasks and (status or priority):
            text = (
                "Taskovi (snapshot):\n"
                f"Nema rezultata za filtere: status={status or '-'}, prioritet={priority or '-'}.\n"
                f"(ukupno u snapshotu: {len(base)})"
            )
        else:
            text = "Taskovi (snapshot):\n" + _render_items(tasks, "tasks", limit=limit)
        return AgentOutput(
            text=text,
            proposed_commands=[],
            agent_id="ceo_clone",
            read_only=True,
            trace={
                "agent": "ceo_clone",
                "intent": "show_tasks",
                "limit": limit,
                "status": status,
                "priority": priority,
                **(ctx.get("trace") or {}),
            },
        )

    if any(x in lower_ascii for x in ["pokazi kpi", "pokaži kpi", "kpi"]):
        kpis = _extract_kpis(snap)
        text = "KPI (snapshot):\n" + _render_items(kpis, "kpis", limit=limit)
        return AgentOutput(
            text=text,
            proposed_commands=[],
            agent_id="ceo_clone",
            read_only=True,
            trace={
                "agent": "ceo_clone",
                "intent": "show_kpis",
                "limit": limit,
                **(ctx.get("trace") or {}),
            },
        )

    if any(
        x in lower_ascii
        for x in ["pokazi projekte", "pokaži projekte", "projekti", "projects"]
    ):
        base = _extract_projects(snap)
        projects = _filter_items(base, status=status, priority=priority)
        if base and not projects and (status or priority):
            text = (
                "Projekti (snapshot):\n"
                f"Nema rezultata za filtere: status={status or '-'}, prioritet={priority or '-'}.\n"
                f"(ukupno u snapshotu: {len(base)})"
            )
        else:
            text = "Projekti (snapshot):\n" + _render_items(
                projects, "projects", limit=limit
            )
        return AgentOutput(
            text=text,
            proposed_commands=[],
            agent_id="ceo_clone",
            read_only=True,
            trace={
                "agent": "ceo_clone",
                "intent": "show_projects",
                "limit": limit,
                "status": status,
                "priority": priority,
                **(ctx.get("trace") or {}),
            },
        )

    write_markers = [
        "kreiraj",
        "napravi",
        "dodaj",
        "azuriraj",
        "ažuriraj",
        "promijeni",
        "obrisi",
        "create",
        "add",
        "update",
        "delete",
        "remove",
        "edit",
        "set",
        "change",
    ]
    if any(m in lower_ascii for m in write_markers):
        proposed.append(
            ProposedCommand(
                command="ceo.command.propose",
                args={"prompt": msg},
                reason="Detektovan intent koji implicira write; predlažem komandu za approval/write gateway.",
                requires_approval=True,
                risk="HIGH",
                dry_run=True,
            )
        )

    text = (
        f"{who} (CEO Advisor): Razumio sam poruku. Mogu odgovoriti na osnovu snapshot-a.\n\n"
        "Primjeri:\n"
        "- inventory\n"
        "- pokazi ciljeve status:Aktivan limit:20\n"
        "- pokazi taskove status:To Do limit:20\n"
        "- pokazi baze\n\n"
        f"Upit: {msg}"
    )

    return AgentOutput(
        text=text,
        proposed_commands=proposed,
        agent_id="ceo_clone",
        read_only=True,
        trace={
            "agent": "ceo_clone",
            "intent": "general_advice",
            **(ctx.get("trace") or {}),
        },
    )


def specialist_notion_agent(
    agent_input: AgentInput, ctx: Dict[str, Any]
) -> AgentOutput:
    msg = (agent_input.message or "").strip()
    lower_ascii = _normalize_ascii((msg or "").lower())

    proposed: List[ProposedCommand] = []

    is_notion_topic = ("notion" in lower_ascii) or any(
        x in lower_ascii
        for x in [
            "database",
            "page",
            "property",
            "schema",
            "workspace",
            "db",
            "tablica",
            "baza",
        ]
    )

    if is_notion_topic:
        proposed.append(
            ProposedCommand(
                command="notion.read.propose",
                args={"query": msg},
                reason="Notion-related upit; predlažem read/query komandu.",
                requires_approval=False,
                risk="LOW",
                dry_run=True,
            )
        )

        if any(
            x in lower_ascii
            for x in [
                "create",
                "add",
                "update",
                "delete",
                "kreiraj",
                "dodaj",
                "ažuriraj",
                "azuriraj",
                "obrisi",
            ]
        ):
            proposed.append(
                ProposedCommand(
                    command="notion.write.propose",
                    args={"intent": msg},
                    reason="Upit implicira write u Notion; predlažem kroz approval workflow.",
                    requires_approval=True,
                    risk="HIGH",
                    dry_run=True,
                )
            )

    text = (
        "Notion Specialist: Mogu mapirati zahtjev na Notion operacije i vratiti prijedloge komandi. "
        "Izvršenje write ide kroz approval.\n\n"
        f"Upit: {msg}"
    )

    return AgentOutput(
        text=text,
        proposed_commands=proposed,
        agent_id="specialist_notion",
        read_only=True,
        trace={"agent": "specialist_notion", **(ctx.get("trace") or {})},
    )

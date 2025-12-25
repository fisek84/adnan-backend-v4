# services/agent_registry_service.py
"""
AGENT REGISTRY SERVICE — CANONICAL

Uloga:
- CENTRALNI REGISTRY svih agenata u sistemu
- jedini izvor istine (SSOT) u runtime-u
- READ-ONLY iz perspektive executiona
- NEMA execution
- NEMA routing

FAZA 4 dodatak:
- učitavanje i validacija iz config/agents.json (SSOT)

KOMPATIBILNOST (FAZA 4):
- AgentRouterService očekuje AgentRegistryEntry + list_agents(enabled_only=True) + get_agent(agent_id)
- Loader mora podržati oba oblika agents.json:
  A) legacy/top-level: enabled/priority/entrypoint/keywords
  B) canonical/meta: status + metadata.entrypoint/metadata.priority/metadata.keywords
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional


# =========================================================
# DATA CONTRACT (for router)
# =========================================================


@dataclass(frozen=True)
class AgentRegistryEntry:
    id: str
    name: str
    enabled: bool
    priority: int
    entrypoint: str
    keywords: List[str] = field(default_factory=list)
    version: str = "1"
    capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# =========================================================
# PATH RESOLUTION (Render-safe)
# =========================================================


def _repo_root() -> Path:
    # services/agent_registry_service.py -> services -> repo root
    return Path(__file__).resolve().parent.parent


def _resolve_agents_json_path(path: str) -> Path:
    """
    Render/CI friendly: relativni path može failati jer CWD nije repo root.
    Ovdje pokušavamo deterministički naći config/agents.json.

    Prioritet:
    1) ENV override: AGENTS_JSON_PATH
    2) Ako je path apsolutan i postoji
    3) Relativno na CWD
    4) Relativno na repo root
    """
    env_override = (os.getenv("AGENTS_JSON_PATH") or "").strip()
    if env_override:
        p = Path(env_override).expanduser()
        if p.is_file():
            return p
        raise FileNotFoundError(f"AGENTS_JSON_PATH points to missing file: {p}")

    raw = (path or "config/agents.json").strip()
    p0 = Path(raw).expanduser()

    # absolute path
    if p0.is_absolute():
        if p0.is_file():
            return p0
        raise FileNotFoundError(f"agents.json not found at absolute path: {p0}")

    # relative to CWD
    cwd_candidate = Path.cwd() / p0
    if cwd_candidate.is_file():
        return cwd_candidate

    # relative to repo root
    root_candidate = _repo_root() / p0
    if root_candidate.is_file():
        return root_candidate

    raise FileNotFoundError(
        f"agents.json not found. Tried: {cwd_candidate} and {root_candidate}"
    )


# =========================================================
# SERVICE
# =========================================================


class AgentRegistryService:
    def __init__(self) -> None:
        # In-memory registry (kanonski runtime SSOT)
        # Key: agent_id (deterministički)
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

    # =========================================================
    # REGISTRATION
    # =========================================================
    def register_agent(
        self,
        *,
        agent_name: str,
        agent_id: str,
        capabilities: List[str],
        version: str,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "active",  # active | disabled
    ) -> Dict[str, Any]:
        """
        Registruje ili ažurira agenta (READ-only registar; nema execution).
        """
        if not agent_name or not agent_id:
            raise ValueError("agent_name and agent_id are required")

        if not isinstance(capabilities, list):
            raise ValueError("capabilities must be a list")

        if status not in ("active", "disabled"):
            raise ValueError("status must be 'active' or 'disabled'")

        # Deterministic capabilities (unique + stable order)
        caps = [str(c).strip() for c in capabilities if str(c).strip()]
        caps = sorted(set(caps))

        now = datetime.utcnow().isoformat()

        # Store a deepcopy to prevent external mutation
        md = deepcopy(metadata) if isinstance(metadata, dict) else {}

        with self._lock:
            existing = self._agents.get(agent_id, {})
            registered_at = existing.get("registered_at", now)

            agent = {
                "agent_name": str(agent_name),
                "agent_id": str(agent_id),
                "capabilities": caps,  # store as LIST (deterministic)
                "version": str(version or "1"),
                "status": status,
                "registered_at": registered_at,
                "updated_at": now,
                "metadata": md,
            }

            self._agents[agent_id] = agent
            return deepcopy(agent)

    # =========================================================
    # SSOT LOAD (FAZA 4)
    # =========================================================
    def load_from_agents_json(
        self,
        path: str = "config/agents.json",
        *,
        clear: bool = True,
    ) -> Dict[str, Any]:
        """
        Učita SSOT registry iz agents.json i mapira u in-memory registry.

        Podržani formati:
        - Legacy: {enabled, priority, entrypoint, keywords} na top-level
        - Canon:  {status, metadata:{entrypoint,priority,keywords}} + optional capabilities/version

        Mapping:
        - key u registry: agent_id (a["id"])
        - status:
            enabled=true -> active
            enabled=false -> disabled
            ili a["status"] ("active"/"disabled")
        - entrypoint/priority/keywords:
            prvo top-level, pa metadata.*
        """
        p = _resolve_agents_json_path(path)

        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)

        self._validate_agents_json(data)

        if clear:
            with self._lock:
                self._agents = {}

        file_version = str(data.get("version", "1"))
        agents = data.get("agents", [])
        loaded = 0

        for a in agents:
            if not isinstance(a, dict):
                continue

            agent_id = str(a.get("id", "")).strip()
            if not agent_id:
                continue

            display_name = str(a.get("name") or agent_id).strip() or agent_id

            md = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}

            # Resolve entrypoint/priority/keywords from legacy or metadata.*
            entrypoint = str(a.get("entrypoint") or md.get("entrypoint") or "").strip()

            priority_raw = a.get("priority", md.get("priority", 0))
            try:
                priority_int = int(priority_raw)
            except Exception:
                priority_int = 0

            kw_raw = a.get("keywords")
            if kw_raw is None:
                kw_raw = md.get("keywords")
            if not isinstance(kw_raw, list):
                kw_raw = []
            keywords = [str(k).strip().lower() for k in kw_raw if str(k).strip()]
            # Deterministic keywords: unique + stable order via sort
            keywords = sorted(set(keywords))

            # status: prefer explicit status, else enabled flag
            status_val = a.get("status")
            if isinstance(status_val, str) and status_val.strip():
                status_norm = status_val.strip().lower()
                if status_norm not in ("active", "disabled"):
                    raise ValueError(
                        f"Invalid status for agent '{agent_id}': {status_val}"
                    )
                status = status_norm
            else:
                enabled = bool(a.get("enabled", True))
                status = "active" if enabled else "disabled"

            # capabilities: optional, else minimal ["chat"]
            caps_raw = a.get("capabilities")
            if isinstance(caps_raw, list) and caps_raw:
                capabilities = [str(c).strip() for c in caps_raw if str(c).strip()]
            else:
                capabilities = ["chat"]

            # agent version: per-agent overrides file version if present
            agent_version = str(a.get("version") or file_version or "1")

            # Canonical runtime metadata (keep original + derived)
            merged_meta: Dict[str, Any] = {}
            if isinstance(md, dict):
                merged_meta.update(deepcopy(md))

            # normalize/force known keys
            merged_meta["display_name"] = display_name
            merged_meta["entrypoint"] = entrypoint
            merged_meta["priority"] = priority_int
            merged_meta["keywords"] = keywords
            merged_meta["source"] = str(p)
            merged_meta["read_only"] = True
            merged_meta["loaded_at"] = datetime.utcnow().isoformat()

            self.register_agent(
                agent_name=agent_id,  # stabilan ključ
                agent_id=agent_id,
                capabilities=capabilities,
                version=agent_version,
                status=status,
                metadata=merged_meta,
            )
            loaded += 1

        return {"loaded": loaded, "path": str(p), "version": file_version}

    def _validate_agents_json(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise ValueError("agents.json must be a JSON object")

        agents = data.get("agents")
        if not isinstance(agents, list):
            raise ValueError("agents.json must contain 'agents' as a list")

        if len(agents) < 1:
            raise ValueError("agents.json must register at least 1 agent")

        seen = set()
        for a in agents:
            if not isinstance(a, dict):
                raise ValueError("Each agent entry must be an object")

            agent_id = str(a.get("id", "")).strip()
            if not agent_id:
                raise ValueError("Agent entry missing required field: id")

            if agent_id in seen:
                raise ValueError(f"Duplicate agent id in registry: {agent_id}")
            seen.add(agent_id)

            md = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
            entrypoint = str(a.get("entrypoint") or md.get("entrypoint") or "").strip()
            if not entrypoint:
                raise ValueError(
                    f"Agent '{agent_id}' missing required field: entrypoint"
                )

            if (
                (":" not in entrypoint)
                or entrypoint.startswith(":")
                or entrypoint.endswith(":")
            ):
                raise ValueError(
                    f"Invalid entrypoint '{entrypoint}' for agent '{agent_id}'. "
                    f"Expected format: module.path:callable"
                )

            # Optional: status validation (if provided)
            status_val = a.get("status")
            if status_val is not None:
                if not isinstance(status_val, str):
                    raise ValueError(f"Invalid status type for agent '{agent_id}'")
                st = status_val.strip().lower()
                if st not in ("active", "disabled"):
                    raise ValueError(
                        f"Invalid status for agent '{agent_id}': {status_val}"
                    )

    # =========================================================
    # LOOKUP (router compatibility)
    # =========================================================
    def get_agent(self, agent_id: str) -> Optional[AgentRegistryEntry]:
        if not agent_id:
            return None
        with self._lock:
            a = self._agents.get(agent_id)
            if not a:
                return None

            md = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
            enabled = a.get("status") == "active"

            return AgentRegistryEntry(
                id=str(a.get("agent_id") or agent_id),
                name=str(md.get("display_name") or a.get("agent_name") or agent_id),
                enabled=bool(enabled),
                priority=int(md.get("priority") or 0),
                entrypoint=str(md.get("entrypoint") or ""),
                keywords=list(md.get("keywords") or []),
                version=str(a.get("version") or "1"),
                capabilities=[str(c) for c in (list(a.get("capabilities") or []))],
                metadata=deepcopy(md),
            )

    def list_agents(self, *, enabled_only: bool = False) -> List[AgentRegistryEntry]:
        with self._lock:
            entries: List[AgentRegistryEntry] = []
            for agent_id, a in self._agents.items():
                md = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
                enabled = a.get("status") == "active"
                if enabled_only and not enabled:
                    continue

                entries.append(
                    AgentRegistryEntry(
                        id=str(a.get("agent_id") or agent_id),
                        name=str(
                            md.get("display_name") or a.get("agent_name") or agent_id
                        ),
                        enabled=bool(enabled),
                        priority=int(md.get("priority") or 0),
                        entrypoint=str(md.get("entrypoint") or ""),
                        keywords=list(md.get("keywords") or []),
                        version=str(a.get("version") or "1"),
                        capabilities=[
                            str(c) for c in (list(a.get("capabilities") or []))
                        ],
                        metadata=deepcopy(md),
                    )
                )

            # Deterministic order: priority desc, id asc
            entries.sort(key=lambda e: (-e.priority, e.id))
            return entries

    def get_agents_with_capability(self, capability: str) -> List[AgentRegistryEntry]:
        if not capability:
            return []
        cap = capability.strip()

        out: List[AgentRegistryEntry] = []
        with self._lock:
            for agent_id, a in self._agents.items():
                if a.get("status") != "active":
                    continue

                caps = a.get("capabilities") or []
                caps_set = set(str(c) for c in caps)

                if cap not in caps_set:
                    continue

                md = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
                out.append(
                    AgentRegistryEntry(
                        id=str(a.get("agent_id") or agent_id),
                        name=str(
                            md.get("display_name") or a.get("agent_name") or agent_id
                        ),
                        enabled=True,
                        priority=int(md.get("priority") or 0),
                        entrypoint=str(md.get("entrypoint") or ""),
                        keywords=list(md.get("keywords") or []),
                        version=str(a.get("version") or "1"),
                        capabilities=[
                            str(c) for c in (list(a.get("capabilities") or []))
                        ],
                        metadata=deepcopy(md),
                    )
                )

        out.sort(key=lambda e: (-e.priority, e.id))
        return out

    # =========================================================
    # STATUS MANAGEMENT
    # =========================================================
    def disable_agent(self, agent_id: str, reason: str) -> bool:
        if not agent_id:
            return False
        with self._lock:
            a = self._agents.get(agent_id)
            if not a:
                return False
            a["status"] = "disabled"
            md = a.get("metadata")
            if not isinstance(md, dict):
                md = {}
                a["metadata"] = md
            md["disabled_reason"] = str(reason or "")
            a["updated_at"] = datetime.utcnow().isoformat()
            return True

    def enable_agent(self, agent_id: str) -> bool:
        if not agent_id:
            return False
        with self._lock:
            a = self._agents.get(agent_id)
            if not a:
                return False
            a["status"] = "active"
            a["updated_at"] = datetime.utcnow().isoformat()
            return True

    # =========================================================
    # SNAPSHOT (READ-ONLY)
    # =========================================================
    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            # Deterministic snapshot (sort keys)
            ids = sorted(self._agents.keys())
            return {
                agent_id: {
                    "agent_id": self._agents[agent_id].get("agent_id"),
                    "capabilities": list(self._agents[agent_id].get("capabilities") or []),
                    "status": self._agents[agent_id].get("status"),
                    "version": self._agents[agent_id].get("version"),
                    "metadata": deepcopy(self._agents[agent_id].get("metadata", {})),
                    "read_only": True,
                }
                for agent_id in ids
            }


# =========================================================
# SINGLETON ACCESS (for router/bootstrap)
# =========================================================

_registry_singleton: Optional[AgentRegistryService] = None
_registry_lock = Lock()


def get_agent_registry_service() -> AgentRegistryService:
    """
    Global singleton accessor (avoids import cycles).
    Bootstrapping može pozvati .load_from_agents_json(...) eksplicitno.
    Router može samo pozvati snapshot/list_agents/get_agent.
    """
    global _registry_singleton
    with _registry_lock:
        if _registry_singleton is None:
            _registry_singleton = AgentRegistryService()
        return _registry_singleton

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

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime
from threading import Lock
from copy import deepcopy
from pathlib import Path
import json


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
# SERVICE
# =========================================================


class AgentRegistryService:
    def __init__(self):
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

        now = datetime.utcnow().isoformat()

        agent = {
            "agent_name": agent_name,
            "agent_id": agent_id,
            "capabilities": set(capabilities),
            "version": str(version or "1"),
            "status": status,
            "registered_at": self._agents.get(agent_id, {}).get("registered_at", now),
            "updated_at": now,
            "metadata": metadata or {},
        }

        with self._lock:
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
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"agents.json not found at: {p}")

        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)

        self._validate_agents_json(data)

        if clear:
            with self._lock:
                self._agents = {}

        file_version = str(data.get("version", "1"))
        agents = data.get("agents", [])

        for a in agents:
            agent_id = str(a.get("id", "")).strip()
            if not agent_id:
                continue

            display_name = str(a.get("name") or agent_id).strip() or agent_id

            # Resolve entrypoint/priority/keywords from legacy or metadata.*
            md = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
            entrypoint = str(a.get("entrypoint") or md.get("entrypoint") or "").strip()
            priority = a.get("priority", md.get("priority", 0))
            try:
                priority_int = int(priority)
            except Exception:
                priority_int = 0

            kw_raw = a.get("keywords")
            if kw_raw is None:
                kw_raw = md.get("keywords")
            if not isinstance(kw_raw, list):
                kw_raw = []
            keywords = [str(k).strip().lower() for k in kw_raw if str(k).strip()]

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

            self.register_agent(
                agent_name=agent_id,  # stabilan ključ
                agent_id=agent_id,
                capabilities=capabilities,
                version=agent_version,
                status=status,
                metadata=merged_meta,
            )

        return {"loaded": len(agents), "path": str(p), "version": file_version}

    def _validate_agents_json(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise ValueError("agents.json must be a JSON object")

        agents = data.get("agents")
        if not isinstance(agents, list):
            raise ValueError("agents.json must contain 'agents' as a list")

        if len(agents) < 2:
            raise ValueError("agents.json must register at least 2 agents")

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
                raise ValueError("Agent entry missing required field: entrypoint")

            if (
                ":" not in entrypoint
                or entrypoint.startswith(":")
                or entrypoint.endswith(":")
            ):
                raise ValueError(
                    f"Invalid entrypoint '{entrypoint}'. Expected format: module.path:callable"
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
        with self._lock:
            out: List[AgentRegistryEntry] = []
            for agent_id, a in self._agents.items():
                if a.get("status") != "active":
                    continue
                caps = a.get("capabilities", set())
                if isinstance(caps, set):
                    has = cap in caps
                else:
                    try:
                        has = cap in set(caps)
                    except Exception:
                        has = False
                if not has:
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
            a.setdefault("metadata", {})["disabled_reason"] = reason
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
            return {
                agent_id: {
                    "agent_id": a.get("agent_id"),
                    "capabilities": list(a.get("capabilities") or []),
                    "status": a.get("status"),
                    "version": a.get("version"),
                    "metadata": deepcopy(a.get("metadata", {})),
                    "read_only": True,
                }
                for agent_id, a in self._agents.items()
            }

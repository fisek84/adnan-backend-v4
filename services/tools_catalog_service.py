from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_tools_json_path(path: str) -> Path:
    env_override = (os.getenv("TOOLS_JSON_PATH") or "").strip()
    if env_override:
        p = Path(env_override).expanduser()
        if p.is_file():
            return p
        raise FileNotFoundError(f"TOOLS_JSON_PATH points to missing file: {p}")

    raw = (path or "config/tools.json").strip()
    p0 = Path(raw).expanduser()

    if p0.is_absolute():
        if p0.is_file():
            return p0
        raise FileNotFoundError(f"tools.json not found at absolute path: {p0}")

    cwd_candidate = Path.cwd() / p0
    if cwd_candidate.is_file():
        return cwd_candidate

    root_candidate = _repo_root() / p0
    if root_candidate.is_file():
        return root_candidate

    raise FileNotFoundError(
        f"tools.json not found. Tried: {cwd_candidate} and {root_candidate}"
    )


_ALLOWED_STATUSES = {"mvp_executable", "planned"}


@dataclass(frozen=True)
class ToolCatalogEntry:
    id: str
    description: str
    risk_level: str
    approval_required: bool
    runtime_action: Optional[str]
    status: str


class ToolsCatalogService:
    """SSOT loader + schema validator for config/tools.json."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._loaded: bool = False
        self._path: Optional[str] = None
        self._version: str = ""
        self._tools_by_id: Dict[str, ToolCatalogEntry] = {}

    def load_from_tools_json(self, path: str = "config/tools.json", *, clear: bool = True) -> Dict[str, Any]:
        p = _resolve_tools_json_path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        tools_by_id, version = self._validate_and_normalize(data)

        with self._lock:
            if clear:
                self._tools_by_id = {}
            self._tools_by_id.update(tools_by_id)
            self._version = version
            self._path = str(p)
            self._loaded = True

        return {"loaded": len(tools_by_id), "path": str(p), "version": version}

    def is_loaded(self) -> bool:
        with self._lock:
            return bool(self._loaded)

    def get(self, tool_id: str) -> Optional[ToolCatalogEntry]:
        tid = str(tool_id or "").strip()
        if not tid:
            return None
        with self._lock:
            return self._tools_by_id.get(tid)

    def list_all(self) -> List[ToolCatalogEntry]:
        with self._lock:
            return [self._tools_by_id[k] for k in sorted(self._tools_by_id.keys())]

    def is_executable(self, tool_id: str) -> bool:
        t = self.get(tool_id)
        return bool(t and t.status == "mvp_executable" and (t.runtime_action or "").strip())

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "loaded": self._loaded,
                "path": self._path,
                "version": self._version,
                "tools": {k: self._tools_by_id[k].__dict__ for k in sorted(self._tools_by_id.keys())},
            }

    def _validate_and_normalize(self, data: Any) -> tuple[Dict[str, ToolCatalogEntry], str]:
        if not isinstance(data, dict):
            raise ValueError("tools.json must be a JSON object")

        version = str(data.get("version") or "").strip() or "1"
        tools = data.get("tools")
        if not isinstance(tools, list) or not tools:
            raise ValueError("tools.json must contain non-empty 'tools' list")

        seen: set[str] = set()
        out: Dict[str, ToolCatalogEntry] = {}

        for idx, t in enumerate(tools):
            if not isinstance(t, dict):
                raise ValueError(f"tools.json tools[{idx}] must be an object")

            tool_id = str(t.get("id") or "").strip()
            if not tool_id:
                raise ValueError(f"tools.json tools[{idx}] missing required field: id")
            if tool_id in seen:
                raise ValueError(f"Duplicate tool id in tools.json: {tool_id}")
            seen.add(tool_id)

            status = str(t.get("status") or "").strip()
            if status not in _ALLOWED_STATUSES:
                raise ValueError(
                    f"Invalid status for tool '{tool_id}': {status!r} (allowed: {sorted(_ALLOWED_STATUSES)})"
                )

            runtime_action_raw = t.get("runtime_action")
            runtime_action = None
            if runtime_action_raw is not None:
                runtime_action = str(runtime_action_raw or "").strip() or None

            if status == "mvp_executable":
                if not runtime_action:
                    raise ValueError(
                        f"Tool '{tool_id}' is mvp_executable but runtime_action is missing"
                    )
                # Canon: MVP runtime action must match SSOT tool id.
                if runtime_action != tool_id:
                    raise ValueError(
                        f"Tool '{tool_id}' runtime_action must equal id (got {runtime_action!r})"
                    )
            else:
                # planned
                if runtime_action:
                    raise ValueError(
                        f"Tool '{tool_id}' is planned but runtime_action must be null/empty"
                    )

            approval_required = bool(t.get("approval_required") is True)

            out[tool_id] = ToolCatalogEntry(
                id=tool_id,
                description=str(t.get("description") or "").strip(),
                risk_level=str(t.get("risk_level") or "").strip() or "unknown",
                approval_required=approval_required,
                runtime_action=runtime_action,
                status=status,
            )

        return out, version


# =========================================================
# SINGLETON ACCESS (for bootstrap/orchestrator)
# =========================================================

_tools_catalog_singleton: Optional[ToolsCatalogService] = None
_tools_catalog_lock = Lock()


def get_tools_catalog_service() -> ToolsCatalogService:
    global _tools_catalog_singleton
    with _tools_catalog_lock:
        if _tools_catalog_singleton is None:
            _tools_catalog_singleton = ToolsCatalogService()
        return _tools_catalog_singleton

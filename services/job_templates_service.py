from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from services.tools_catalog_service import ToolsCatalogService


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_job_templates_json_path(path: str) -> Path:
    env_override = (os.getenv("JOB_TEMPLATES_JSON_PATH") or "").strip()
    if env_override:
        p = Path(env_override).expanduser()
        if p.is_file():
            return p
        raise FileNotFoundError(f"JOB_TEMPLATES_JSON_PATH points to missing file: {p}")

    raw = (path or "config/job_templates.json").strip()
    p0 = Path(raw).expanduser()

    if p0.is_absolute():
        if p0.is_file():
            return p0
        raise FileNotFoundError(f"job_templates.json not found at absolute path: {p0}")

    cwd_candidate = Path.cwd() / p0
    if cwd_candidate.is_file():
        return cwd_candidate

    root_candidate = _repo_root() / p0
    if root_candidate.is_file():
        return root_candidate

    raise FileNotFoundError(
        f"job_templates.json not found. Tried: {cwd_candidate} and {root_candidate}"
    )


@dataclass(frozen=True)
class JobTemplateStep:
    tool_action: str
    requires_approval: bool
    params_schema: Dict[str, Any]


@dataclass(frozen=True)
class JobTemplate:
    id: str
    title: str
    role: str
    steps: List[JobTemplateStep]
    expected_outputs: List[str]


class JobTemplatesService:
    """SSOT loader + schema validator for config/job_templates.json."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._loaded: bool = False
        self._path: Optional[str] = None
        self._version: str = ""
        self._templates_by_id: Dict[str, JobTemplate] = {}

    def load_from_job_templates_json(
        self,
        tools_catalog: ToolsCatalogService,
        path: str = "config/job_templates.json",
        *,
        clear: bool = True,
    ) -> Dict[str, Any]:
        if tools_catalog is None or not isinstance(tools_catalog, ToolsCatalogService):
            raise ValueError("tools_catalog is required")

        p = _resolve_job_templates_json_path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        templates_by_id, version = self._validate_and_normalize(data, tools_catalog)

        with self._lock:
            if clear:
                self._templates_by_id = {}
            self._templates_by_id.update(templates_by_id)
            self._version = version
            self._path = str(p)
            self._loaded = True

        return {"loaded": len(templates_by_id), "path": str(p), "version": version}

    def is_loaded(self) -> bool:
        with self._lock:
            return bool(self._loaded)

    def get(self, template_id: str) -> Optional[JobTemplate]:
        tid = str(template_id or "").strip()
        if not tid:
            return None
        with self._lock:
            return self._templates_by_id.get(tid)

    def list_all(self) -> List[JobTemplate]:
        with self._lock:
            return [
                self._templates_by_id[k] for k in sorted(self._templates_by_id.keys())
            ]

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "loaded": self._loaded,
                "path": self._path,
                "version": self._version,
                "job_templates": {
                    k: self._templates_by_id[k].__dict__
                    for k in sorted(self._templates_by_id.keys())
                },
            }

    def _validate_and_normalize(
        self,
        data: Any,
        tools_catalog: ToolsCatalogService,
    ) -> tuple[Dict[str, JobTemplate], str]:
        if not isinstance(data, dict):
            raise ValueError("job_templates.json must be a JSON object")

        version = str(data.get("version") or "").strip() or "1"
        templates = data.get("job_templates")
        if not isinstance(templates, list) or not templates:
            raise ValueError(
                "job_templates.json must contain non-empty 'job_templates' list"
            )

        seen: set[str] = set()
        out: Dict[str, JobTemplate] = {}

        for idx, t in enumerate(templates):
            if not isinstance(t, dict):
                raise ValueError(
                    f"job_templates.json job_templates[{idx}] must be an object"
                )

            template_id = str(t.get("id") or "").strip()
            if not template_id:
                raise ValueError(
                    f"job_templates.json job_templates[{idx}] missing required field: id"
                )
            if template_id in seen:
                raise ValueError(f"Duplicate job template id: {template_id}")
            seen.add(template_id)

            role = str(t.get("role") or "").strip()
            if not role:
                raise ValueError(
                    f"Job template '{template_id}' missing required field: role"
                )

            steps_in = t.get("steps")
            if not isinstance(steps_in, list) or not steps_in:
                raise ValueError(
                    f"Job template '{template_id}' must have non-empty steps"
                )

            steps: List[JobTemplateStep] = []
            for s_idx, s in enumerate(steps_in):
                if not isinstance(s, dict):
                    raise ValueError(
                        f"Job template '{template_id}' steps[{s_idx}] must be an object"
                    )

                tool_action = str(s.get("tool_action") or "").strip()
                if not tool_action:
                    raise ValueError(
                        f"Job template '{template_id}' steps[{s_idx}] missing required field: tool_action"
                    )

                tool = tools_catalog.get(tool_action)
                if tool is None:
                    raise ValueError(
                        f"Job template '{template_id}' steps[{s_idx}] references unknown tool_action: {tool_action}"
                    )

                if tool.status not in ("mvp_executable", "planned"):
                    raise ValueError(
                        f"Job template '{template_id}' steps[{s_idx}] tool_action '{tool_action}' has invalid status: {tool.status}"
                    )

                params_schema = s.get("params_schema")
                if params_schema is None:
                    params_schema = {}
                if not isinstance(params_schema, dict):
                    raise ValueError(
                        f"Job template '{template_id}' steps[{s_idx}] params_schema must be an object"
                    )

                steps.append(
                    JobTemplateStep(
                        tool_action=tool_action,
                        requires_approval=bool(s.get("requires_approval") is True),
                        params_schema=params_schema,
                    )
                )

            expected_outputs_raw = t.get("expected_outputs") or []
            if not isinstance(expected_outputs_raw, list):
                expected_outputs_raw = []
            expected_outputs = [
                str(x).strip() for x in expected_outputs_raw if str(x).strip()
            ]

            out[template_id] = JobTemplate(
                id=template_id,
                title=str(t.get("title") or "").strip(),
                role=role,
                steps=steps,
                expected_outputs=expected_outputs,
            )

        return out, version


# =========================================================
# SINGLETON ACCESS (for bootstrap)
# =========================================================

_job_templates_singleton: Optional[JobTemplatesService] = None
_job_templates_lock = Lock()


def get_job_templates_service() -> JobTemplatesService:
    global _job_templates_singleton
    with _job_templates_lock:
        if _job_templates_singleton is None:
            _job_templates_singleton = JobTemplatesService()
        return _job_templates_singleton

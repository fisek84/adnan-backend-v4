from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path


def _agents_json_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "agents.json"


def _load_agents() -> list[dict]:
    p = _agents_json_path()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "agents.json must be an object"
    agents = data.get("agents")
    assert isinstance(agents, list), "agents.json must contain an 'agents' list"
    assert agents, "agents.json must not be empty"
    assert all(isinstance(x, dict) for x in agents)
    return agents


def _load_entrypoint(entrypoint: str):
    assert isinstance(entrypoint, str) and ":" in entrypoint
    module_path, symbol = entrypoint.split(":", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, symbol)


def _can_accept_two_positional_args(obj: object) -> bool:
    sig = inspect.signature(obj)
    params = list(sig.parameters.values())

    # Router calls entrypoint(agent_input, ctx) positionally.
    if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
        return True

    positional = [
        p
        for p in params
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    return len(positional) >= 2


def test_agents_json_entrypoints_are_importable_and_callable() -> None:
    agents = _load_agents()

    failures: list[str] = []

    for a in agents:
        agent_id = a.get("id")
        entrypoint = a.get("entrypoint")
        if not isinstance(agent_id, str) or not agent_id.strip():
            failures.append(f"missing/invalid id: {a}")
            continue
        if not isinstance(entrypoint, str) or not entrypoint.strip():
            failures.append(f"{agent_id}: missing/invalid entrypoint")
            continue

        try:
            obj = _load_entrypoint(entrypoint)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{agent_id}: cannot import {entrypoint}: {e!r}")
            continue

        if not callable(obj):
            failures.append(f"{agent_id}: entrypoint not callable: {entrypoint}")
            continue

        try:
            if not _can_accept_two_positional_args(obj):
                failures.append(
                    f"{agent_id}: entrypoint signature must accept (agent_input, ctx): {entrypoint}"
                )
        except Exception as e:  # noqa: BLE001
            failures.append(
                f"{agent_id}: cannot inspect signature for {entrypoint}: {e!r}"
            )

    assert not failures, "\n".join(failures)

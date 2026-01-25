"""CEO Advisor grounding smoke.

Runs a few deterministic checks without starting uvicorn.
This is meant to be a quick safety net for the "no hallucinated business state"
contract when SSOT snapshot is missing.

Usage:
  python tools/smoke_ceo_grounding.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path


# Ensure repo root is on sys.path when running as a script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@dataclass
class DummyAgentInput:
    message: str
    snapshot: dict
    metadata: dict


def _run_case(*, message: str, snapshot: dict) -> dict:
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    agent_input = DummyAgentInput(
        message=message,
        snapshot=snapshot,
        metadata={"snapshot_source": "smoke"},
    )
    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={}))

    pcs = getattr(out, "proposed_commands", None)
    pcs_list = list(pcs) if isinstance(pcs, list) else []
    first_cmd = getattr(pcs_list[0], "command", None) if pcs_list else None

    return {
        "text": (out.text or ""),
        "read_only": bool(getattr(out, "read_only", False) is True),
        "first_command": first_cmd,
        "trace": getattr(out, "trace", None),
    }


def main() -> int:
    # Simulate "LLM configured" to ensure the grounding gate still blocks.
    os.environ["OPENAI_API_KEY"] = "smoke"

    # 1) Fact-sensitive: must NOT claim blocked; must propose refresh.
    r1 = _run_case(message="Da li smo blokirani?", snapshot={})
    t1 = r1["text"].lower()
    assert r1["read_only"] is True
    assert "blokir" not in t1
    assert "refresh" in t1
    assert r1["first_command"] == "refresh_snapshot"
    assert isinstance(r1["trace"], dict) and isinstance(
        r1["trace"].get("grounding_gate"), dict
    )

    # 2) Empty-state kickoff: should be helpful (not a refusal).
    r2 = _run_case(message="Imam prazno stanje, kako da pocnem?", snapshot={})
    assert r2["read_only"] is True
    assert "?" in r2["text"] or "kren" in r2["text"].lower()

    # 3) Prompt template request: should return template (offline-safe behavior).
    # Remove key to force offline deterministic path.
    os.environ.pop("OPENAI_API_KEY", None)
    r3 = _run_case(
        message=(
            "Dali mozes da mi pripremis prompt za taj cilj i potcilj "
            "koji cu poslati Notion ops agentu da upise u notion"
        ),
        snapshot={},
    )
    assert "GOAL:" in r3["text"]
    assert "POTCILJEVI" in r3["text"]

    print("OK: CEO advisor grounding smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

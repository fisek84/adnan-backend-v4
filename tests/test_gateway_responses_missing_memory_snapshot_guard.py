import asyncio
import builtins

import pytest

from gateway.gateway_server import _generate_ceo_readonly_answer


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "prompt",
    [
        "koja je tvoja uloga i kako mi pomažeš?",
        "Ko si ti?",
    ],
)
def test_responses_mode_missing_memory_snapshot_does_not_block_identity_meta(
    monkeypatch, prompt
):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")

    # Ensure required bridge inputs are present so we reach the missing_memory_snapshot guard.
    ctx = {
        "grounding_pack": {},
        "identity_json": {"payload": {"role": "ceo"}},
        "snapshot": {"payload": {}},
        "missing": [],
    }

    out = _run(
        _generate_ceo_readonly_answer(prompt=prompt, session_id="t", context=ctx)
    )
    txt = str(out.get("text") or "")

    assert "Ne mogu dati smislen odgovor" not in txt


def test_responses_mode_missing_memory_snapshot_blocks_fact_lookup(monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")

    ctx = {
        "grounding_pack": {},
        "identity_json": {"payload": {"role": "ceo"}},
        "snapshot": {"payload": {}},
        "missing": [],
    }

    out = _run(
        _generate_ceo_readonly_answer(
            prompt="Objasni mi CAP theorem?",
            session_id="t",
            context=ctx,
        )
    )
    txt = str(out.get("text") or "")

    assert "Ne mogu dati smislen odgovor" in txt


def test_gateway_except_path_does_not_block_identity_meta(monkeypatch):
    """Force the gateway guard's inner ResponseClass import to fail.

    This simulates environments where internal classifier imports fail, ensuring
    identity/meta still does not get blocked by the missing_memory_snapshot guard.
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        # Only fail the specific import used in the guard:
        # `from services.ceo_advisor_agent import ResponseClass`.
        if (
            name == "services.ceo_advisor_agent"
            and fromlist
            and "ResponseClass" in fromlist
        ):
            # Allow other imports (e.g., create_ceo_advisor_agent) to succeed.
            raise ImportError("simulated import failure for ResponseClass")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    ctx = {
        "grounding_pack": {},
        "identity_json": {"payload": {"role": "ceo"}},
        "snapshot": {"payload": {}},
        "missing": [],
    }

    out = _run(
        _generate_ceo_readonly_answer(
            prompt="Koja je tvoja uloga i kako mi pomažeš?",
            session_id="t",
            context=ctx,
        )
    )
    txt = str(out.get("text") or "")

    assert "Ne mogu dati smislen odgovor" not in txt

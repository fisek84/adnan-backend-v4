from __future__ import annotations

import pytest

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_block3_continuity_store_reuse_versioned_writes() -> None:
    from services.block3_shared_continuity_grounding import (
        ContinuityKey,
        InMemoryContinuityStore,
    )

    store = InMemoryContinuityStore()
    key = ContinuityKey(tenant_id="t1", principal_id="p1", conversation_id="c1")

    r0 = store.read(key)
    assert r0["status"] == "NOT_FOUND"
    assert r0["reason_code"] == "CONTINUITY_NOT_FOUND"

    w1 = store.write(key, expected_version=None, state_payload={"v": 1})
    assert w1["status"] == "OK"
    assert w1["reason_code"] == "CONTINUITY_OK"
    assert w1["state_version"] == 1

    r1 = store.read(key)
    assert r1["status"] == "OK"
    assert r1["state_version"] == 1

    w2 = store.write(key, expected_version=1, state_payload={"v": 2})
    assert w2["status"] == "OK"
    assert w2["state_version"] == 2


def test_block3_continuity_store_conflict_no_silent_overwrite() -> None:
    from services.block3_shared_continuity_grounding import (
        ContinuityKey,
        InMemoryContinuityStore,
    )

    store = InMemoryContinuityStore()
    key = ContinuityKey(tenant_id="t1", principal_id="p1", conversation_id="c1")

    store.write(key, expected_version=None, state_payload={"v": 1})

    w = store.write(key, expected_version=999, state_payload={"v": 2})
    assert w["status"] == "CONFLICT"
    assert w["reason_code"] == "CONTINUITY_CONFLICT"

    # Must NOT overwrite existing state on conflict.
    r = store.read(key)
    assert r["status"] == "OK"
    assert r["state_version"] == 1
    assert r["state_payload"] == {"v": 1}


@pytest.mark.parametrize(
    "case_id, prompt, turn_gate_intent_category, evidence, expected",
    [
        (
            "C01",
            "Koji su aktivni zadaci?",
            "NORMAL_QUESTION",
            {
                "provider_status": "OK",
                "authoritative_count": 1,
                "secondary_count": 0,
                "non_authoritative_count": 0,
                "fresh_count": 1,
                "stale_count": 0,
                "sources": ["SNAPSHOT"],
                "source_ids": ["snap:v1"],
            },
            {
                "question_class": "FACT_SENSITIVE",
                "decision": "ALLOW",
                "reason_code": "GROUNDING_OK",
                "constraint": "EVIDENCE_BACKED_FACTS_ONLY",
            },
        ),
        (
            "C04",
            "Koji su aktivni zadaci?",
            "NORMAL_QUESTION",
            {
                "provider_status": "OK",
                "authoritative_count": 0,
                "secondary_count": 0,
                "non_authoritative_count": 1,
                "fresh_count": 0,
                "stale_count": 0,
                "sources": ["MEMORY"],
                "source_ids": ["mem:1"],
            },
            {
                "question_class": "FACT_SENSITIVE",
                "decision": "FAIL_CLOSED",
                "reason_code": "GROUNDING_FACT_SENSITIVE_NO_EVIDENCE",
                "constraint": "REFUSE_FACT_ANSWER",
            },
        ),
        (
            "C05",
            "Koji su aktivni zadaci?",
            "NORMAL_QUESTION",
            {
                "provider_status": "OK",
                "authoritative_count": 1,
                "secondary_count": 0,
                "non_authoritative_count": 0,
                "fresh_count": 0,
                "stale_count": 1,
                "sources": ["SNAPSHOT"],
                "source_ids": ["snap:stale"],
            },
            {
                "question_class": "FACT_SENSITIVE",
                "decision": "FAIL_CLOSED",
                "reason_code": "GROUNDING_EVIDENCE_STALE",
                "constraint": "REFUSE_FACT_ANSWER",
            },
        ),
        (
            "C06",
            "Koji su aktivni zadaci?",
            "NORMAL_QUESTION",
            {
                "provider_status": "UNAVAILABLE",
                "authoritative_count": 0,
                "secondary_count": 0,
                "non_authoritative_count": 0,
                "fresh_count": 0,
                "stale_count": 0,
                "sources": [],
                "source_ids": [],
            },
            {
                "question_class": "FACT_SENSITIVE",
                "decision": "FAIL_CLOSED",
                "reason_code": "GROUNDING_PROVIDER_UNAVAILABLE",
                "constraint": "REFUSE_FACT_ANSWER",
            },
        ),
        (
            "D01",
            "Daj mi strategiju za bolji pipeline.",
            "NORMAL_QUESTION",
            {
                "provider_status": "EMPTY",
                "authoritative_count": 0,
                "secondary_count": 0,
                "non_authoritative_count": 0,
                "fresh_count": 0,
                "stale_count": 0,
                "sources": [],
                "source_ids": [],
            },
            {
                "question_class": "ADVISORY",
                "decision": "ALLOW",
                "reason_code": "GROUNDING_ADVISORY_ASSUMPTIONS_ONLY",
                "constraint": "NO_SSOT_FACT_CLAIMS",
            },
        ),
        (
            "E01",
            "Ko si ti?",
            "META_ASSISTANT",
            {
                "provider_status": "UNAVAILABLE",
                "authoritative_count": 0,
                "secondary_count": 0,
                "non_authoritative_count": 0,
                "fresh_count": 0,
                "stale_count": 0,
                "sources": [],
                "source_ids": [],
            },
            {
                "question_class": "META_SYSTEM",
                "decision": "ALLOW",
                "reason_code": "GROUNDING_META_DETERMINISTIC",
                "constraint": "META_ONLY",
            },
        ),
    ],
)
def test_block3_grounding_gate_decisions(
    case_id: str,
    prompt: str,
    turn_gate_intent_category: str,
    evidence: dict,
    expected: dict,
) -> None:
    from services.block3_shared_continuity_grounding import (
        classify_question_class,
        evaluate_grounding_gate,
    )

    question_class = classify_question_class(
        prompt=prompt, turn_gate_intent_category=turn_gate_intent_category
    )
    assert question_class == expected["question_class"], case_id

    out = evaluate_grounding_gate(
        prompt=prompt,
        question_class=question_class,
        evidence_summary=evidence,
    )

    assert out["decision"] == expected["decision"], case_id
    assert out["reason_code"] == expected["reason_code"], case_id
    assert out["downstream_constraint"] == expected["constraint"], case_id


def test_block3_trace_contract_updates_turn_gate_only_when_trace_exists() -> None:
    from services.block3_shared_continuity_grounding import apply_block3_trace

    # If trace is absent, Block 3 must NOT create it.
    content = {"text": "x"}
    apply_block3_trace(content, continuity=None, grounding=None)
    assert "trace" not in content

    # If trace exists, Block 3 may write only under trace.turn_gate.*
    content2 = {"trace": {"turn_gate": {"intent_category": "NORMAL_QUESTION"}}}
    apply_block3_trace(
        content2,
        continuity={
            "store_status": "OK",
            "reason_code": "CONTINUITY_OK",
            "state_version": 1,
        },
        grounding={
            "question_class": "ADVISORY",
            "decision": "ALLOW",
            "reason_code": "GROUNDING_ADVISORY_ASSUMPTIONS_ONLY",
            "evidence_summary": {
                "authoritative_count": 0,
                "secondary_count": 0,
                "non_authoritative_count": 0,
                "fresh_count": 0,
                "stale_count": 0,
                "sources": [],
                "source_ids": [],
            },
        },
    )

    tr = content2["trace"]
    assert set(tr.keys()) == {"turn_gate"}
    tg = tr["turn_gate"]
    assert "continuity" in tg
    assert "grounding" in tg


def test_block3_no_continuity_minted_trace_drift(monkeypatch) -> None:
    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Koji su aktivni zadaci?",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    tr = body.get("trace")
    assert isinstance(tr, dict), "trace missing"
    tg = tr.get("turn_gate")
    assert isinstance(tg, dict), "trace.turn_gate missing"

    # Regression lock: Block 3 must not invent new continuity enum-like values.
    dumped = str(tg)
    assert "MINTED" not in dumped
    assert "CONTINUITY_MINTED" not in dumped

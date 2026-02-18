from __future__ import annotations

from models.canon import PROPOSAL_WRAPPER_INTENT


def test_kreiraj_task_blocks_force_batch_request_only_create_task_ops_and_strict_fields():
    from gateway.gateway_server import _unwrap_proposal_wrapper_or_raise

    goal_title = "Baza Blok 1 – Adaptacija na trčanje (18.02–02.03)"

    # 8 strict blocks, deterministic keys only.
    blocks = []
    for i in range(1, 9):
        blocks.append(
            "\n".join(
                [
                    "Kreiraj Task:",
                    f"Name: Task {i} – Title",
                    f"Goal: {goal_title}",
                    f"Due Date: 2026-02-{10+i:02d}",
                    "Priority: high" if i % 2 else "Priority: medium",
                    f"Description: Opis taska {i}",
                ]
            )
        )

    prompt = "\n\n".join(blocks)

    cmd = _unwrap_proposal_wrapper_or_raise(
        command=PROPOSAL_WRAPPER_INTENT,
        intent=PROPOSAL_WRAPPER_INTENT,
        params={"prompt": prompt},
        initiator="ceo",
        read_only=False,
        metadata={},
    )

    assert cmd.intent == "batch_request"
    assert cmd.command == "notion_write"

    ops = cmd.params.get("operations")
    assert isinstance(ops, list)

    create_task_ops = [o for o in ops if isinstance(o, dict) and o.get("intent") == "create_task"]
    create_goal_ops = [o for o in ops if isinstance(o, dict) and o.get("intent") == "create_goal"]

    assert len(create_task_ops) == 8
    assert len(create_goal_ops) == 0

    # Strict parsing guarantees: title is clean, description is block-local.
    for i, op in enumerate(create_task_ops, start=1):
        payload = op.get("payload") or {}
        assert payload.get("title") == f"Task {i} – Title"

        desc = payload.get("description")
        assert isinstance(desc, str)
        assert desc == f"Opis taska {i}"
        assert "Kreiraj Task:" not in desc
        assert "Goal:" not in payload.get("title", "")
        assert "Due Date:" not in payload.get("title", "")


def test_kreiraj_task_inline_kv_does_not_leak_into_title():
    from gateway.gateway_server import _unwrap_proposal_wrapper_or_raise

    # Inline KV is forbidden; parser should truncate Name safely.
    prompt = (
        "Kreiraj Task:\n"
        "Name: Trebevic hiking Goal: SOME GOAL Due Date: 2026-02-19\n"
        "Goal: X\n"
        "Due Date: 2026-02-19\n"
        "Priority: high\n"
        "Description: Opis\n"
    )

    cmd = _unwrap_proposal_wrapper_or_raise(
        command=PROPOSAL_WRAPPER_INTENT,
        intent=PROPOSAL_WRAPPER_INTENT,
        params={"prompt": prompt},
        initiator="ceo",
        read_only=False,
        metadata={},
    )

    assert cmd.intent == "batch_request"

    ops = cmd.params.get("operations")
    assert isinstance(ops, list)
    assert len(ops) == 1

    op0 = ops[0]
    assert op0.get("intent") == "create_task"
    payload = op0.get("payload") or {}
    assert payload.get("title") == "Trebevic hiking"

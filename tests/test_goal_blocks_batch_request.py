from __future__ import annotations

from models.canon import PROPOSAL_WRAPPER_INTENT


def test_multi_kreiraj_cilj_blocks_force_batch_request_and_clean_fields() -> None:
    from gateway.gateway_server import _unwrap_proposal_wrapper_or_raise

    prompt = """
Kreiraj Cilj: "Prvi cilj",
Status: "In Progress",
Priority: "High";
Type: "Business",
Assigned To: "Ad Fisek"; "Snezana",
Deadline: "2026-02-20",
Description: Ovo je opis prvog cilja.

Kreiraj Cilj: Drugi cilj
Status: "Not Started"
Priority: "Medium"
Deadline: 2026-03-01
Description: Drugi opis.

Kreiraj Cilj: Treći cilj
Parent Goal: "Prvi cilj"
Status: "In Progress"
Priority: "Low"
Deadline: 2026-03-15
Description: Treći opis.
""".strip()

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
    assert len(ops) == 3

    d0 = ops[0]["payload"].get("description")
    assert isinstance(d0, str)
    assert "Kreiraj Cilj:" not in d0

    assert ops[0]["payload"]["title"] == "Prvi cilj"
    assert not ops[0]["payload"]["title"].endswith(",")

    assert ops[0]["payload"]["priority"] == "High"
    assert ops[0]["payload"]["status"] == "In Progress"

    ps0 = ops[0]["payload"].get("property_specs")
    assert isinstance(ps0, dict)
    assert ps0["Type"]["name"] == "Business"
    assert ps0["Assigned To"]["names"] == ["Ad Fisek", "Snezana"]

    assert ops[2]["payload"].get("parent_goal_id") == "$goal_1"

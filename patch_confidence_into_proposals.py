from pathlib import Path

path = Path("gateway/gateway_server.py")
src = path.read_text(encoding="utf-8")

anchor = '    result["trace"] = tr2\n'

if anchor not in src:
    raise SystemExit("ANCHOR NOT FOUND — STOP")

patch = (
    anchor
    + """
    # === CANON PATCH: propagate confidence/risk into proposal payloads ===
    cr = tr2.get("confidence_risk")
    if isinstance(cr, dict):
        for pc in result.get("proposed_commands", []):
            if not isinstance(pc, dict):
                continue

            ps = pc.get("payload_summary")
            if not isinstance(ps, dict):
                ps = {}
                pc["payload_summary"] = ps

            ps.setdefault("confidence_score", cr.get("confidence_score"))
            ps.setdefault("assumption_count", cr.get("assumption_count", 0))
            ps.setdefault("recommendation_type", "OPERATIONAL")

            rl = cr.get("risk_level")
            if isinstance(rl, str):
                pc.setdefault(
                    "risk",
                    {"low": "LOW", "medium": "MED", "high": "HIGH"}.get(rl, "LOW"),
                )
    # === END CANON PATCH ===

"""
)

path.write_text(src.replace(anchor, patch), encoding="utf-8")
print("OK — PATCH APPLIED")

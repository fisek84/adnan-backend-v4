from pathlib import Path

path = Path("gateway/gateway_server.py")
src = path.read_text(encoding="utf-8")

anchor = """    return {
        "command": cmd,
        "intent": intent,
        "params": params if isinstance(params, dict) else {},
    }
"""

if anchor not in src:
    raise SystemExit("ANCHOR NOT FOUND in _safe_command_summary")

patch = """    summary = {
        "command": cmd,
        "intent": intent,
        "params": params if isinstance(params, dict) else {},
    }

    md = getattr(ai_command, "metadata", None)
    if isinstance(md, dict) and isinstance(md.get("confidence_risk"), dict):
        summary["confidence_risk"] = md.get("confidence_risk")

    return summary
"""

path.write_text(src.replace(anchor, patch), encoding="utf-8")
print("OK — confidence_risk added to _safe_command_summary")

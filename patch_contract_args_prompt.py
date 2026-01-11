from pathlib import Path

path = Path("gateway/gateway_server.py")
src = path.read_text(encoding="utf-8")

anchor = "# === END CANON PATCH ==="

if anchor not in src:
    raise SystemExit("ANCHOR NOT FOUND")

patch = (
    anchor
    + """

    # === CANON STABILITY PATCH: ensure args.prompt exists ===
    for pc in result.get("proposed_commands", []):
        if not isinstance(pc, dict):
            continue

        if pc.get("command") == "ceo.command.propose":
            args = pc.get("args")
            if not isinstance(args, dict):
                args = {}
                pc["args"] = args

            if "prompt" not in args or not isinstance(args.get("prompt"), str):
                args["prompt"] = cleaned_text.strip()
    # === END CANON STABILITY PATCH ===
"""
)

path.write_text(src.replace(anchor, patch), encoding="utf-8")
print("OK — enforced args.prompt for ceo.command.propose")

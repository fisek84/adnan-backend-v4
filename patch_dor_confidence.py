from pathlib import Path

path = Path("gateway/gateway_server.py")
src = path.read_text(encoding="utf-8")

anchor = """    if isinstance(meta_in, dict):
        merged_md.update(meta_in)
"""

if anchor not in src:
    raise SystemExit("ANCHOR NOT FOUND")

patch = (
    anchor
    + """    if isinstance(meta_in, dict):
        merged_md.update(meta_in)

    # === CANON: propagate confidence_risk into metadata for DOR ===
    cr = None
    if isinstance(proposal_meta, dict):
        cr = proposal_meta.get("confidence_risk")
    if cr is None and isinstance(meta_in, dict):
        cr = meta_in.get("confidence_risk")

    if isinstance(cr, dict):
        merged_md["confidence_risk"] = cr
    # === END CANON ===
"""
)

path.write_text(src.replace(anchor, patch), encoding="utf-8")
print("OK — confidence_risk propagated into merged_md")

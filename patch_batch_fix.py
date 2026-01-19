from __future__ import annotations
from pathlib import Path

def patch_file(path: Path, find: str, repl: str) -> None:
    s = path.read_text(encoding="utf-8")
    if repl in s:
        print(f"[SKIP] already patched: {path}")
        return
    if find not in s:
        raise SystemExit(f"[FAIL] anchor not found in {path}: {find!r}")
    path.write_text(s.replace(find, repl, 1), encoding="utf-8")
    print(f"[OK] patched: {path}")

# A) notion_keyword_mapper.py
nk = Path("services/notion_keyword_mapper.py")
find_a = 'return cls.detect_intent(text) == "batch_request"'
repl_a = '''t = (text or "").lower()

        # Heuristika: ako u istom inputu ima i (goal/cilj) i (task/zadatak), to je GROUP/BATCH.
        if (("task" in t) or ("zad" in t)) and (("goal" in t) or ("cilj" in t)):
            return True

        return cls.detect_intent(text) == "batch_request"'''
patch_file(nk, find_a, repl_a)

# B) gateway_server.py (prije fast-path-a)
gw = Path("gateway/gateway_server.py")
anchor_b = "    # Create intents with explicit/detected hint: build minimal executable without LLM translation.\n"
insert_b = '''    # If this looks like a batch/branch request, force batch_request so we do NOT enter create_goal/create_task fast-path.
    try:
        from services.notion_keyword_mapper import NotionKeywordMapper  # noqa: PLC0415
        if NotionKeywordMapper.is_batch_request(prompt.strip()):
            hint_intent = "batch_request"
    except Exception:
        pass

'''
repl_b = insert_b + anchor_b
patch_file(gw, anchor_b, repl_b)

print("[DONE] Now re-run preview with a Goal+Task prompt; it should come back as intent=batch_request with per-op preview rows.")

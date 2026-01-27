from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _leaf_paths(obj: Any, *, prefix: str = "", max_paths: int = 10_000) -> List[str]:
    out_paths: List[str] = []
    stack: List[Tuple[str, Any, int]] = [(prefix, obj, 0)]

    while stack and len(out_paths) < max_paths:
        pfx, cur, depth = stack.pop()

        if isinstance(cur, dict) and depth < 32:
            for k in sorted(cur.keys(), reverse=True):
                if not isinstance(k, str):
                    continue
                v = cur.get(k)
                p2 = f"{pfx}.{k}" if pfx else k
                stack.append((p2, v, depth + 1))
            continue

        if isinstance(cur, list) and depth < 16:
            # Treat lists as leaf nodes to avoid path explosion.
            out_paths.append(pfx or prefix or "<list>")
            continue

        if pfx:
            out_paths.append(pfx)

    return sorted(set([x for x in out_paths if isinstance(x, str) and x.strip()]))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only identity usage audit: runs one /api/chat call with include_debug=true, "
            "then reports what identity.json fields were used and % coverage."
        )
    )
    parser.add_argument(
        "--message",
        default="Koja je naša operativna filozofija?",
        help="User message to send to /api/chat.",
    )
    parser.add_argument(
        "--identity-json",
        default=str(Path("identity") / "identity.json"),
        help="Path to identity.json (workspace-relative).",
    )
    parser.add_argument(
        "--no-notion",
        action="store_true",
        help="Disable Notion targeted reads for this run (prevents outbound Notion calls).",
    )

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    identity_path = (repo_root / args.identity_json).resolve()
    if not identity_path.exists():
        raise SystemExit(f"identity.json not found: {identity_path}")

    identity_obj = json.loads(identity_path.read_text(encoding="utf-8-sig"))
    all_fields = _leaf_paths(identity_obj, prefix="identity")

    # Keep this read-only and deterministic: use in-process TestClient.
    if args.no_notion:
        os.environ["CEO_NOTION_TARGETED_READS_ENABLED"] = "false"

    os.environ.setdefault("CEO_GROUNDING_PACK_ENABLED", "true")

    from fastapi.testclient import TestClient  # lazy import

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": args.message,
            "identity_pack": {"user_id": "audit"},
            "snapshot": {},
            "metadata": {"include_debug": True, "initiator": "identity_audit"},
        },
    )
    if r.status_code != 200:
        raise SystemExit(f"/api/chat failed: {r.status_code} {r.text}")

    body: Dict[str, Any] = r.json()
    tr = body.get("trace") if isinstance(body.get("trace"), dict) else {}

    identity_used = (
        tr.get("identity_used") if isinstance(tr.get("identity_used"), dict) else None
    )
    if not isinstance(identity_used, dict):
        raise SystemExit(
            "trace.identity_used missing. Ensure your build includes debug-observability and request include_debug=true."
        )

    used_fields0 = identity_used.get("fields_used")
    used_fields = (
        [x for x in used_fields0 if isinstance(x, str) and x.strip()]
        if isinstance(used_fields0, list)
        else []
    )

    used_set: Set[str] = set(used_fields)
    all_set: Set[str] = set(all_fields)

    inter = sorted(all_set.intersection(used_set))

    denom = max(1, len(all_fields))
    pct = 100.0 * float(len(inter)) / float(denom)

    files_loaded0 = identity_used.get("files_loaded")
    files_loaded = (
        [x for x in files_loaded0 if isinstance(x, str) and x.strip()]
        if isinstance(files_loaded0, list)
        else []
    )

    print("IDENTITY USAGE AUDIT (read-only)")
    print(f"identity.json: {identity_path}")
    print(f"fields_total: {len(all_fields)}")
    print(f"fields_used:  {len(inter)}")
    print(f"coverage_pct: {pct:.2f}")
    print(f"files_loaded: {files_loaded or '[]'}")

    # Keep output compact by default.
    unused = sorted(all_set.difference(used_set))
    print(f"unused_fields_count: {len(unused)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

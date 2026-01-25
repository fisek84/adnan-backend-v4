from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
OFF = ROOT / "artifacts" / "extra_routers" / "routes_dump_off.json"
ON = ROOT / "artifacts" / "extra_routers" / "routes_dump_on.json"
OUT = ROOT / "ROUTE_DIFF.md"


@dataclass(frozen=True)
class RouteKey:
    method: str
    path: str


def load_routes(p: Path) -> List[Dict[str, object]]:
    data = json.loads(p.read_text(encoding="utf-8"))
    routes = data.get("routes")
    return routes if isinstance(routes, list) else []


HandlerSig = Tuple[str, str, str]


def handler_sig(route: Dict[str, object]) -> HandlerSig:
    module = route.get("module")
    endpoint = route.get("endpoint")
    name = route.get("name")
    return (
        str(module) if module is not None else "",
        str(endpoint) if endpoint is not None else "",
        str(name) if name is not None else "",
    )


def expand_keys(routes: Iterable[Dict[str, object]]) -> Dict[RouteKey, Set[HandlerSig]]:
    out: Dict[RouteKey, Set[HandlerSig]] = {}
    for r in routes:
        path = r.get("path")
        methods = r.get("methods")
        if not isinstance(path, str) or not path:
            continue
        if not isinstance(methods, list):
            continue
        sig = handler_sig(r)
        for m in methods:
            if not isinstance(m, str) or not m:
                continue
            key = RouteKey(method=m.upper(), path=path)
            out.setdefault(key, set()).add(sig)
    return out


def main() -> int:
    off_routes = load_routes(OFF)
    on_routes = load_routes(ON)

    off_map = expand_keys(off_routes)
    on_map = expand_keys(on_routes)

    off_keys: Set[RouteKey] = set(off_map.keys())
    on_keys: Set[RouteKey] = set(on_map.keys())

    new_keys = sorted(on_keys - off_keys, key=lambda k: (k.path, k.method))
    shared_keys = sorted(on_keys & off_keys, key=lambda k: (k.path, k.method))

    # Enterprise collision definition:
    # if the same METHOD+PATH exists in OFF and ON but resolves to a different handler.
    handler_mismatch = [
        k for k in shared_keys if (off_map.get(k) or set()) != (on_map.get(k) or set())
    ]

    md: List[str] = []
    md.append("# ROUTE diff (ENABLE_EXTRA_ROUTERS off vs on)\n")
    md.append(f"- OFF dump: `{OFF.as_posix()}`")
    md.append(f"- ON dump: `{ON.as_posix()}`\n")

    md.append("## Summary\n")
    md.append(f"- OFF routes (METHOD+PATH): {len(off_keys)}")
    md.append(f"- ON routes (METHOD+PATH): {len(on_keys)}")
    md.append(f"- NEW routes when ON: {len(new_keys)}")
    md.append(
        f"- METHOD+PATH handler mismatches (OFF vs ON): {len(handler_mismatch)}\n"
    )

    md.append("## New routes when ENABLE_EXTRA_ROUTERS=true\n")
    md.append("| Method | Path | Handler module | Handler name |")
    md.append("|---|---|---|---|")
    for k in new_keys:
        sigs = sorted(on_map.get(k) or set())
        if not sigs:
            md.append(f"| {k.method} | {k.path} |  |  |")
            continue
        # In practice, each key should map to a single handler.
        for idx, (mod, endpoint, _name) in enumerate(sigs):
            md.append(
                "| "
                + " | ".join(
                    [
                        k.method if idx == 0 else "",
                        k.path if idx == 0 else "",
                        mod,
                        endpoint,
                    ]
                )
                + " |"
            )

    md.append("\n## Collision check\n")
    if not handler_mismatch:
        md.append(
            "- OK: 0 collisions (no shared METHOD+PATH changes handler between OFF and ON)."
        )
    else:
        md.append("- FAIL: shared METHOD+PATH changed handler between OFF and ON.")
        md.append("\n| Method | Path | OFF handlers | ON handlers |")
        md.append("|---|---|---|---|")
        for k in handler_mismatch:
            off_handlers = sorted(off_map.get(k) or set())
            on_handlers = sorted(on_map.get(k) or set())
            off_str = "; ".join(
                [f"{m}.{e}" if m or e else "" for (m, e, _n) in off_handlers]
            )
            on_str = "; ".join(
                [f"{m}.{e}" if m or e else "" for (m, e, _n) in on_handlers]
            )
            md.append(f"| {k.method} | {k.path} | {off_str} | {on_str} |")

    OUT.write_text("\n".join(md) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest


PATTERNS = [
    "notion.pages.create",
    "notion.pages.update",
    "notion.blocks.children.append",
]

# Only these modules are allowed to contain direct Notion-client writes.
# (This is intentionally strict; expected to fail until offenders are removed.)
ALLOWED_PATH_SUFFIXES = {
    str(Path("services") / "notion_ops_agent.py"),
    str(Path("services") / "notion_service.py"),
}


@dataclass(frozen=True)
class Hit:
    rel_path: str
    line_no: int
    line_text: str
    pattern: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _iter_py_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*.py"):
        rp = p.relative_to(root).as_posix()
        # Skip common junk / vendored dirs if any.
        if rp.startswith(".venv/") or rp.startswith("venv/") or rp.startswith("node_modules/"):
            continue
        # Skip tests to avoid self-matching on pattern literals.
        if rp.startswith("tests/"):
            continue
        out.append(p)
    return out


def test_direct_notion_client_writes_forbidden_outside_notion_ops() -> None:
    """Operational requirement: Notion writes ONLY via notion_ops.

    Implemented as a static scan for direct notion client calls:
    - notion.pages.create
    - notion.pages.update
    - notion.blocks.children.append

    This MUST FAIL on current repo because offenders exist (ext/notion/*).
    Failure message must include file:line evidence.
    """

    root = _repo_root()
    hits: list[Hit] = []

    for f in _iter_py_files(root):
        rel = f.relative_to(root).as_posix()
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue

        for i, line in enumerate(lines, start=1):
            for pat in PATTERNS:
                if pat in line:
                    allowed = any(rel.endswith(suf.replace("\\", "/")) for suf in ALLOWED_PATH_SUFFIXES)
                    if not allowed:
                        hits.append(Hit(rel_path=rel, line_no=i, line_text=line.strip(), pattern=pat))

    if hits:
        # Keep the failure message compact but evidence-rich.
        evidence = "\n".join(
            f"- {h.rel_path}:{h.line_no}: {h.pattern} :: {h.line_text}" for h in hits[:25]
        )
        raise AssertionError(
            "Direct Notion client writes are forbidden outside notion_ops. Offenders:\n" + evidence
        )

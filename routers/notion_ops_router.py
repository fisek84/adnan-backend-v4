# routers/notion_ops_router.py
#
# CANONICAL PATCH (FAZA 4 / CANON WRITE GUARD)
# - bulk/create i bulk/update su WRITE-surface i MORAJU biti guarded
# - bulk/query je READ-only i može ostati bez write-guard
#
# Kompatibilnost:
# - zadržava minimalni shape koji testovi očekuju:
#   - /bulk/create: 200 + {"created":[...]} za validne tipove, 400 za invalid type
#   - /bulk/update: 200 + {"updated": payload.updates}
#   - /bulk/query: 200 + {"results": []} kad je prazno
#
# Canon:
# - writes blokirani kad je OPS_SAFE_MODE=true
# - optional CEO token enforcement kad je CEO_TOKEN_ENFORCEMENT=true

from __future__ import annotations

import os
import logging
from uuid import uuid4
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notion-ops", tags=["Notion Bulk Ops"])


# ------------------------------------------------------------
# CANONICAL WRITE GUARDS (same semantics as ai_ops_router)
# ------------------------------------------------------------
def _env_true(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() == "true"


def _ops_safe_mode_enabled() -> bool:
    return _env_true("OPS_SAFE_MODE", "false")


def _ceo_token_enforcement_enabled() -> bool:
    return _env_true("CEO_TOKEN_ENFORCEMENT", "false")


def _require_ceo_token_if_enforced(request: Request) -> None:
    if not _ceo_token_enforcement_enabled():
        return

    expected = os.getenv("CEO_APPROVAL_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="CEO token enforcement enabled but CEO_APPROVAL_TOKEN is not set",
        )

    provided = (request.headers.get("X-CEO-Token") or "").strip()
    if provided != expected:
        raise HTTPException(status_code=403, detail="CEO token required")


def _guard_write(request: Request) -> None:
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )
    _require_ceo_token_if_enforced(request)


# -------------------------------
# MODELS
# -------------------------------
class BulkCreateItem(BaseModel):
    type: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    goal_id: Optional[str] = None


class BulkCreatePayload(BaseModel):
    items: List[BulkCreateItem]


class BulkUpdatePayload(BaseModel):
    updates: List[Dict[str, Any]] = Field(default_factory=list)


class BulkQueryPayload(BaseModel):
    queries: List[Dict[str, Any]] = Field(default_factory=list)


# -------------------------------
# ROUTES
# -------------------------------
@router.post("/bulk/create")
async def bulk_create(request: Request, payload: BulkCreatePayload) -> Dict[str, Any]:
    """
    Minimalna implementacija da zadovolji test_bulk_ops:
    - 200 + {"created": [...]} za validne tipove ("goal", "task")
    - 400 za nepoznat type

    CANON:
    - write surface => guarded
    """
    _guard_write(request)

    if not payload.items:
        return {"created": []}

    created: List[Dict[str, Any]] = []

    for item in payload.items:
        if item.type not in {"goal", "task"}:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported type: {item.type}",
            )

        created.append(
            {
                "id": str(uuid4()),
                "type": item.type,
                "title": item.title,
                "goal_id": item.goal_id,
            }
        )

    return {"created": created}


@router.post("/bulk/update")
async def bulk_update(request: Request, payload: BulkUpdatePayload) -> Dict[str, Any]:
    """
    Test očekuje:
    - 200
    - {"updated": []} kad je payload.updates == []

    CANON:
    - write surface => guarded
    """
    _guard_write(request)
    return {"updated": payload.updates}


@router.post("/bulk/query")
async def bulk_query(payload: BulkQueryPayload) -> Dict[str, Any]:
    """
    READ-only endpoint.

    Test očekuje:
    - 200
    - {"results": []} kad je payload.queries == []
    """
    if not payload.queries:
        return {"results": []}

    # Placeholder; real query bi morao biti read-only ili kroz governance ako radi side-effect.
    return {"results": [{} for _ in payload.queries]}

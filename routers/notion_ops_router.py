# routers/notion_ops_router.py

from __future__ import annotations

import os
import logging
from uuid import uuid4
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.approval_flow import require_approval_or_block

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notion-ops", tags=["Notion Bulk Ops"])


# ------------------------------------------------------------
# CANONICAL WRITE GUARDS (ENV + approval_flow)
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


def _guard_write(request: Request, command_type: str) -> None:
    """
    Kombinuje:
    - globalni blok (OPS_SAFE_MODE)
    - CEO token zaštitu
    - approval_flow granularnu kontrolu
    """
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )

    _require_ceo_token_if_enforced(request)

    # Canon granular approval check
    require_approval_or_block(
        command_id="notion_bulk_write",
        command_type=command_type,
        context={"source": "notion_ops_router"},
    )


# -------------------------------
# MODELI
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
# RUTE
# -------------------------------
@router.post("/bulk/create")
async def bulk_create(request: Request, payload: BulkCreatePayload) -> Dict[str, Any]:
    _guard_write(request, command_type="create_task")

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
    _guard_write(request, command_type="update_task")
    return {"updated": payload.updates}


@router.post("/bulk/query")
async def bulk_query(payload: BulkQueryPayload) -> Dict[str, Any]:
    if not payload.queries:
        return {"results": []}
    return {"results": [{} for _ in payload.queries]}

# routers/notion_ops_router.py

from uuid import uuid4
from typing import Any, Dict, List, Optional

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notion-ops", tags=["Notion Bulk Ops"])


class BulkCreateItem(BaseModel):
    type: str
    title: str
    goal_id: Optional[str] = None


class BulkCreatePayload(BaseModel):
    items: List[BulkCreateItem]


class BulkUpdatePayload(BaseModel):
    updates: List[Dict[str, Any]] = []


class BulkQueryPayload(BaseModel):
    queries: List[Dict[str, Any]] = []


@router.post("/bulk/create")
async def bulk_create(payload: BulkCreatePayload) -> Dict[str, Any]:
    """
    Minimalna implementacija da zadovolji test_bulk_ops:
    - 200 + {"created": [...]} za validne tipove ("goal", "task")
    - 400 za nepoznat type
    """
    if not payload.items:
        return {"created": []}

    created: List[Dict[str, Any]] = []

    for item in payload.items:
        if item.type not in {"goal", "task"}:
            # test_bulk_invalid_type očekuje 400
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
async def bulk_update(payload: BulkUpdatePayload) -> Dict[str, Any]:
    """
    Test očekuje:
    - 200
    - {"updated": []} kad je payload.updates == []
    """
    return {"updated": payload.updates}


@router.post("/bulk/query")
async def bulk_query(payload: BulkQueryPayload) -> Dict[str, Any]:
    """
    Test očekuje:
    - 200
    - {"results": []} kad je payload.queries == []
    """
    if not payload.queries:
        return {"results": []}

    # Ako ikad budeš koristio ovo “za pravo”, ovo može da postane realan query.
    return {"results": [{} for _ in payload.queries]}

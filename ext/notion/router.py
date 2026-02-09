# ext/notion/router.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ext.notion.writer import create_page, delete_page
from ext.notion.linker import link_to_relation

router = APIRouter()


# --------------------- CREATE PAGE ---------------------
@router.post("/notion/page")
async def create_page_endpoint(data: dict):
    try:
        res = await create_page(
            db_key=data.get("db_key"),
            property_specs=data.get("property_specs") or {},
            wrapper_patch=data.get("wrapper_patch") or {},
            approval_id=data.get("approval_id"),
            execution_id=data.get("execution_id"),
            initiator=data.get("initiator") or "unknown",
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating page: {str(e)}")


# --------------------- WRITE TO PAGE ---------------------
class WriteBody(BaseModel):
    page_id: str
    content: str


@router.post("/notion/write")
async def write_to_page_endpoint(body: WriteBody):
    try:
        raise RuntimeError(
            "DISABLED: /notion/write performed direct block appends; use governed notion_ops flow"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error appending text: {str(e)}")


# --------------------- DELETE PAGE ---------------------
@router.post("/notion/delete")
async def delete_page_endpoint(data: dict):
    page_id = data.get("page_id")
    if page_id:
        # Use await for async calls to delete page
        res = await delete_page(
            page_id=page_id,
            approval_id=data.get("approval_id"),
            execution_id=data.get("execution_id"),
            initiator=data.get("initiator") or "unknown",
        )
        return res
    else:
        return {"status": "failed", "message": "No page_id provided"}


# --------------------- LINK PAGES ---------------------
@router.post("/notion/link")
async def link_page_endpoint(data: dict):
    res = await link_to_relation(
        data["page_id"],
        data["relation"],
        data["target_id"],
        db_key=data.get("db_key"),
        approval_id=data.get("approval_id"),
        execution_id=data.get("execution_id"),
        initiator=data.get("initiator") or "unknown",
    )
    return res

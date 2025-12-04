# ext/notion/router.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ext.notion.writer import create_page, append_text, delete_page  # Dodali smo delete_page
from ext.notion.linker import link_to_relation

router = APIRouter()

# --------------------- CREATE PAGE ---------------------
@router.post("/notion/page")
async def create_page_endpoint(data: dict):
    try:
        page = create_page(data["title"], data["parent_db"])
        return {"page_id": page["id"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating page: {str(e)}")

# --------------------- WRITE TO PAGE ---------------------
class WriteBody(BaseModel):
    page_id: str
    content: str

@router.post("/notion/write")
async def write_to_page_endpoint(body: WriteBody):
    try:
        append_text(body.page_id, body.content)  # Ensure this is async if necessary
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error appending text: {str(e)}")

# --------------------- DELETE PAGE ---------------------
@router.post("/notion/delete")
async def delete_page_endpoint(data: dict):
    page_id = data.get("page_id")
    if page_id:
        # Use await for async calls to delete page
        res = await delete_page(page_id)  # Ensure 'await' for async function
        if res["ok"]:
            return {"status": "deleted"}
        else:
            return {"status": "failed", "message": res["error"]}
    else:
        return {"status": "failed", "message": "No page_id provided"}

# --------------------- LINK PAGES ---------------------
@router.post("/notion/link")
async def link_page_endpoint(data: dict):
    link_to_relation(
        data["page_id"],
        data["relation"],
        data["target_id"]
    )
    return {"status": "linked"}

print("🔥 LOADED EXT NOTION ROUTER:", __file__)

from fastapi import APIRouter
from pydantic import BaseModel

from ext.notion.writer import create_page, append_text
from ext.notion.linker import link_to_relation

router = APIRouter()


# --------------------- CREATE PAGE ---------------------
@router.post("/notion/page")
async def create_page_endpoint(data: dict):
    page = create_page(data["title"], data["parent_db"])
    return {"page_id": page["id"]}


# --------------------- WRITE TO PAGE ---------------------
class WriteBody(BaseModel):
    page_id: str
    content: str

@router.post("/notion/write")
async def write_to_page_endpoint(body: WriteBody):
    print("🔥 WRITE ENDPOINT HIT")
    append_text(body.page_id, body.content)
    return {"status": "ok"}

# --------------------- LINK PAGES ---------------------
@router.post("/notion/link")
async def link_page_endpoint(data: dict):
    link_to_relation(
        data["page_id"],
        data["relation"],
        data["target_id"]
    )
    return {"status": "linked"}
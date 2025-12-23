# ext/notion/writer.py

import time
import logging
from ext.notion.client import notion
from ext.notion.chunker import chunk_text

logger = logging.getLogger(__name__)


def normalize_id(id: str) -> str:
    return id.replace("-", "")


# -------------------------------------------------
#  CREATE PAGE IN DATABASE
# -------------------------------------------------
def create_page(title: str, parent_db_id: str):
    print("CREATE_PAGE DEBUG → parent_db_id =", parent_db_id)

    return notion.pages.create(
        parent={"database_id": parent_db_id},
        properties={"Name": {"title": [{"text": {"content": title}}]}},
    )


# -------------------------------------------------
#  GET OR CREATE ROOT BLOCK INSIDE PAGE
# -------------------------------------------------
def get_or_create_root_block(page_id: str) -> str:
    print("🔍 Checking for existing blocks in page:", page_id)

    children = notion.blocks.children.list(page_id)

    if children and children.get("results"):
        block_id = children["results"][0]["id"]
        print("➡ Found existing block:", block_id)
        return block_id

    print("⚠ Page has NO blocks → creating initial paragraph block...")

    res = notion.blocks.children.append(
        block_id=page_id,
        children=[
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": []}}
        ],
    )

    block_id = res["results"][0]["id"]
    print("✅ Created initial block:", block_id)
    return block_id


# -------------------------------------------------
#  APPEND TEXT
# -------------------------------------------------
def append_text(page_id: str, text: str):
    print("\n=========================")
    print("📌 APPEND_TEXT CALLED")
    print("Original page_id:", page_id)

    page_id = normalize_id(page_id)
    print("Normalized page_id:", page_id)
    print("=========================\n")

    chunks = chunk_text(text)

    root_block_id = get_or_create_root_block(page_id)

    print("🧱 Using block for append:", root_block_id)

    for index, chunk in enumerate(chunks):
        print(f"\n➡ Sending chunk #{index + 1}")
        print("Chunk preview:", chunk[:60], "...")

        try:
            res = notion.blocks.children.append(
                block_id=root_block_id,
                children=[
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": chunk}}]
                        },
                    }
                ],
            )

            print("✅ NOTION RESPONSE:", res)

        except Exception as e:
            print("❌ NOTION API ERROR:", str(e))
            if hasattr(e, "response"):
                print("🔍 RAW RESPONSE:", e.response)
            raise e

        # Reduce sleep time if the content size is smaller, for faster performance
        time.sleep(0.3)  # You can adjust this value for optimization


# -------------------------------------------------
#  DELETE PAGE FROM NOTION
# -------------------------------------------------
async def delete_page(page_id: str):
    """
    Funkcija za brisanje stranice u Notion-u.
    """
    try:
        logger.info(f"Brisanje stranice sa Notion ID: {page_id}")

        # Poziv za brisanje stranice
        res = await notion.delete_page(page_id)

        if res.get("ok"):
            logger.info(f"Stranica sa ID: {page_id} uspješno obrisana.")
        else:
            logger.error(f"Greška pri brisanju stranice sa Notion ID: {page_id}.")
            return {"ok": False, "error": res.get("error")}

        return {"ok": True, "message": f"Page {page_id} deleted successfully"}

    except Exception as e:
        logger.error(f"Greška prilikom brisanja stranice {page_id}: {str(e)}")
        return {"ok": False, "error": str(e)}

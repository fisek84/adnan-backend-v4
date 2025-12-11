import os
from dotenv import load_dotenv
from notion_client import Client

# --- LOAD .env ---
load_dotenv()

# --- READ KEY ---
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
print("NOTION_API_KEY LOADED:", NOTION_API_KEY)

# --- INIT NOTION CLIENT ---
notion = Client(auth=NOTION_API_KEY)

def delete_page(page_id: str):
    """
    Funkcija za brisanje stranice (zadataka) iz Notion-a.
    """
    try:
        notion.pages.delete(page_id)
        print(f"✅ Page with ID {page_id} deleted successfully")
    except Exception as e:
        print("❌ Error deleting page:", str(e))
        if hasattr(e, "response"):
            print("🔍 Raw response:", e.response)
        raise e

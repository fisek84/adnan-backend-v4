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

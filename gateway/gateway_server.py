print("LOADED NEW GATEWAY VERSION")

import os
import logging
import json

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from notion_client import Client
from services.adnan_ai_decision_service import AdnanAIDecisionService

# NEW: voice router
from routers.voice_router import router as voice_router

print("CURRENT FILE LOADED FROM:", os.path.abspath(__file__))

# Load .env
load_dotenv("C:/adnan-backend-v4/.env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

NOTION_KEY = os.getenv("NOTION_API_KEY")
notion = Client(auth=NOTION_KEY)

# Global engine instance
decision_engine = AdnanAIDecisionService()


class CommandRequest(BaseModel):
    command: str
    payload: dict


# =====================================================================
# REGISTER ROUTERS
# =====================================================================
app.include_router(voice_router)


# =====================================================================
# /ops/execute
# CEO → Decision Engine → Notion
# =====================================================================
@app.post("/ops/execute")
async def execute_notion_command(req: CommandRequest):
    try:
        logger.info(">> Incoming /ops/execute")
        logger.info(">> Command: %s", req.command)
        logger.info(">> Payload: %s", json.dumps(req.payload, ensure_ascii=False))

        # ==============================================================
        # 1. CEO MODE → USE DECISION ENGINE
        # ==============================================================
        if req.command == "from_ceo":
            ceo_text = req.payload.get("text", "")
            logger.info(">> Processing CEO instruction through Decision Engine")

            decision = decision_engine.process_ceo_instruction(ceo_text)

            logger.info(">> DECISION OUTPUT:")
            logger.info(json.dumps(decision, indent=2, ensure_ascii=False))

            # Stop execution on critical errors
            err = decision.get("error_engine", {})
            if err and err.get("errors"):
                return {
                    "success": False,
                    "blocked": True,
                    "reason": "Critical Decision Engine error — execution aborted.",
                    "engine_output": decision,
                }

            # Extract final Notion command directly from decision
            notion_command = decision.get("command")
            notion_payload = decision.get("payload")

            if not notion_command or not notion_payload:
                raise HTTPException(500, "Decision Engine did not produce a valid command/payload")

            # Override incoming request
            req.command = notion_command
            req.payload = notion_payload

        # =================================================================
        # 2. EXECUTE NOTION COMMAND
        # =================================================================
        command = req.command
        payload = req.payload

        logger.info(">> EXECUTING NOTION COMMAND: %s", command)

        # -------------------------------------------------------------
        # CREATE DATABASE ENTRY
        # -------------------------------------------------------------
        if command == "create_database_entry":
            db = payload.get("database_id")
            entry = payload.get("entry", {})

            properties = {}

            for key, value in entry.items():
                if key.lower() == "name":
                    properties["Name"] = {
                        "title": [{"text": {"content": value}}]
                    }
                elif key in ["Status", "Priority"]:
                    properties[key] = {"select": {"name": value}}
                else:
                    properties[key] = {
                        "rich_text": [{"text": {"content": str(value)}}]
                    }

            created = notion.pages.create(
                parent={"database_id": db},
                properties=properties,
            )

            logger.info(">> Created: %s", created.get("id"))

            return {
                "success": True,
                "id": created.get("id"),
                "url": created.get("url"),
            }

        # -------------------------------------------------------------
        # UPDATE DATABASE ENTRY
        # -------------------------------------------------------------
        elif command == "update_database_entry":
            page_id = payload.get("page_id")
            entry = payload.get("entry", {})

            properties = {}
            for key, value in entry.items():
                if key.lower() == "name":
                    properties["Name"] = {
                        "title": [{"text": {"content": value}}]
                    }
                elif key in ["Status", "Priority"]:
                    properties[key] = {"select": {"name": value}}
                else:
                    properties[key] = {
                        "rich_text": [{"text": {"content": str(value)}}]
                    }

            updated = notion.pages.update(page_id=page_id, properties=properties)

            logger.info(">> Updated: %s", updated.get("id"))

            return {
                "success": True,
                "updated_id": updated.get("id"),
                "url": updated.get("url"),
            }

        # -------------------------------------------------------------
        # QUERY DATABASE
        # -------------------------------------------------------------
        elif command == "query_database":
            db = payload.get("database_id")
            results = notion.databases.query(database_id=db)

            logger.info(">> Query returned %d rows", len(results.get("results", [])))

            return {
                "success": True,
                "results": results.get("results", []),
            }

        # -------------------------------------------------------------
        # CREATE PAGE
        # -------------------------------------------------------------
        elif command == "create_page":
            parent_id = payload.get("parent_page_id")
            title = payload.get("title", "Untitled Page")
            children = payload.get("children", [])

            created = notion.pages.create(
                parent={"page_id": parent_id},
                properties={"title": [{"text": {"content": title}}]},
                children=children,
            )

            return {
                "success": True,
                "page_id": created.get("id"),
                "url": created.get("url"),
            }

        # -------------------------------------------------------------
        # RETRIEVE PAGE CONTENT
        # -------------------------------------------------------------
        elif command == "retrieve_page_content":
            page_id = payload.get("page_id")
            blocks = notion.blocks.children.list(block_id=page_id)

            return {
                "success": True,
                "blocks": blocks.get("results", []),
            }

        # -------------------------------------------------------------
        # UNKNOWN COMMAND
        # -------------------------------------------------------------
        else:
            return {"error": f"Unknown command: {command}"}

    except Exception as e:
        logger.exception(">> ERROR in /ops/execute")
        raise HTTPException(500, str(e))


# =====================================================================
# /ops/test_ceo
# =====================================================================
@app.post("/ops/test_ceo")
async def test_ceo(req: dict):
    try:
        text = req.get("text")
        if not text:
            raise HTTPException(400, "Missing field: text")

        print("\n======================")
        print(" DECISION ENGINE TEST ")
        print("======================")
        print("INPUT:", text)

        result = decision_engine.process_ceo_instruction(text)

        print("\n--- DECISION OUTPUT ---")
        print(json.dumps(result, indent=2, ensure_ascii=False))

        return {
            "success": True,
            "engine_output": result,
        }

    except Exception as e:
        logger.exception(">> ERROR in /ops/test_ceo")
        raise HTTPException(500, str(e))

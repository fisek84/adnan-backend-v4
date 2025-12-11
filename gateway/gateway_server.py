print("LOADED NEW GATEWAY VERSION")

import os
import logging
import json

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

from notion_client import Client

# FINAL HYBRID DECISION ENGINE
from services.adnan_ai_decision_service import AdnanAIDecisionService

# FINAL PERSONALITY ENGINE (shared reference)
from services.decision_engine.personality_engine import PersonalityEngine

# NEW — CONTEXT ORCHESTRATION IMPORTS
from services.decision_engine.context_orchestrator import ContextOrchestrator

# FIXED — correct import
from services.identity_loader import load_adnan_identity
from services.adnan_mode_service import load_mode
from services.adnan_state_service import load_state

# voice router
from routers.voice_router import router as voice_router

print("CURRENT FILE LOADED FROM:", os.path.abspath(__file__))

# Load .env
load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")

app = FastAPI()

# ============================
# HEALTH CHECK
# ============================
@app.get("/health")
async def health():
    return {"status": "ok"}


# ============================
# CORS
# ============================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================
# GLOBALS
# ============================
NOTION_KEY = os.getenv("NOTION_API_KEY")
notion = Client(auth=NOTION_KEY)

decision_engine = AdnanAIDecisionService()
personality_engine = PersonalityEngine()  # shared personality

# FIXED — LOAD IDENTITY / MODE / STATE
identity = load_adnan_identity()
mode = load_mode()
state = load_state()

# NEW — INIT ORCHESTRATOR
orchestrator = ContextOrchestrator(identity, mode, state)


class CommandRequest(BaseModel):
    command: str
    payload: dict


# REGISTER ROUTERS
app.include_router(voice_router)


# =====================================================================
# PERSONALITY ROUTES
# =====================================================================
@app.get("/ops/get_personality")
async def get_personality():
    try:
        return {
            "success": True,
            "personality": personality_engine.get_personality()
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/ops/reset_personality")
async def reset_personality():
    try:
        personality_engine.reset()
        return {
            "success": True,
            "message": "Personality fully reset."
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/ops/teach_personality")
async def teach_personality(req: dict):
    try:
        text = req.get("text")
        category = req.get("category", "values")

        if not text:
            raise HTTPException(400, "Missing field: text")

        personality_engine.add_trait(category, text)

        return {
            "success": True,
            "taught": text,
            "category": category,
            "message": "Personality updated successfully."
        }

    except Exception as e:
        raise HTTPException(500, str(e))


# =====================================================================
# /ops/execute   (CEO → Hybrid Engine → Business / Chat / Personality)
# =====================================================================
@app.post("/ops/execute")
async def execute_notion_command(req: CommandRequest):
    try:
        logger.info(">> Incoming /ops/execute")
        logger.info(">> Command: %s", req.command)
        logger.info(">> Payload: %s", json.dumps(req.payload, ensure_ascii=False))

        # ============================================================
        # ORCHESTRATOR — PRVI SLOJ (context + identity reasoning)
        # ============================================================
        user_text = None

        if req.command == "from_ceo":
            user_text = req.payload.get("text", "")
        else:
            user_text = req.payload.get("text") or req.payload.get("query") or ""

        if user_text:
            orch = orchestrator.run(user_text)
            context_type = orch.get("context_type")

            if context_type in ["identity", "memory", "agent", "sop", "notion", "meta"]:
                return {
                    "success": True,
                    "final_answer": orch["final_output"]["final_answer"],
                    "engine_output": orch
                }

        # ============================================================
        # CEO MODE — klasik
        # ============================================================
        if req.command == "from_ceo":
            ceo_text = req.payload.get("text", "")
            logger.info(">> Processing CEO instruction through Hybrid Decision Engine")

            decision = decision_engine.process_ceo_instruction(ceo_text)
            logger.info(json.dumps(decision, indent=2, ensure_ascii=False))

            if decision.get("local_only"):
                return {
                    "success": True,
                    "final_answer": decision.get("system_response"),
                    "engine_output": decision
                }

            err = decision.get("error_engine", {})
            if err and err.get("errors"):
                return {
                    "success": False,
                    "blocked": True,
                    "reason": "Critical Decision Engine error — execution aborted.",
                    "engine_output": decision,
                }

            notion_command = decision.get("command")
            notion_payload = decision.get("payload")

            if not notion_command:
                return {
                    "success": True,
                    "final_answer": decision.get("system_response"),
                    "engine_output": decision
                }

            req.command = notion_command
            req.payload = notion_payload

        # ============================================================
        # EXECUTE NOTION COMMANDS
        # ============================================================
        command = req.command
        payload = req.payload

        logger.info(">> EXECUTING NOTION COMMAND: %s", command)

        # CREATE ENTRY
        if command == "create_database_entry":
            db = payload.get("database_id")
            entry = payload.get("entry", {})

            properties = {}
            for key, value in entry.items():
                if key.lower() == "name":
                    properties["Name"] = {"title": [{"text": {"content": value}}]}
                elif key in ["Status", "Priority"]:
                    properties[key] = {"select": {"name": value}}
                else:
                    properties[key] = {"rich_text": [{"text": {"content": str(value)}}]}

            created = notion.pages.create(
                parent={"database_id": db},
                properties=properties,
            )
            return {
                "success": True,
                "final_answer": "Novi zapis je kreiran.",
                "id": created.get("id"),
                "url": created.get("url"),
            }

        # UPDATE ENTRY
        elif command == "update_database_entry":
            page_id = payload.get("page_id")
            entry = payload.get("entry", {})

            properties = {}
            for key, value in entry.items():
                if key.lower() == "name":
                    properties["Name"] = {"title": [{"text": {"content": value}}]}
                elif key in ["Status", "Priority"]:
                    properties[key] = {"select": {"name": value}}
                else:
                    properties[key] = {"rich_text": [{"text": {"content": str(value)}}]}

            updated = notion.pages.update(page_id=page_id, properties=properties)
            return {
                "success": True,
                "final_answer": "Zapis je ažuriran.",
                "updated_id": updated.get("id"),
                "url": updated.get("url"),
            }

        # QUERY DATABASE
        elif command == "query_database":
            db = payload.get("database_id")
            results = notion.databases.query(database_id=db)
            return {
                "success": True,
                "final_answer": "Evo rezultata iz baze.",
                "results": results.get("results", []),
            }

        # CREATE PAGE
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
                "final_answer": "Nova stranica je kreirana.",
                "page_id": created.get("id"),
                "url": created.get("url"),
            }

        # RETRIEVE PAGE CONTENT
        elif command == "retrieve_page_content":
            page_id = payload.get("page_id")
            blocks = notion.blocks.children.list(block_id=page_id)
            return {
                "success": True,
                "final_answer": "Evo sadržaja stranice.",
                "blocks": blocks.get("results", []),
            }

        # DELETE PAGE
        elif command == "delete_page":
            name = payload.get("name")
            if not name:
                return {"error": "Missing name for delete_page"}

            databases = [
                "2ac5873bd84a801f956fc30327b8ef94",  # goals
                "2ad5873bd84a80e8b4dac703018212fe",  # tasks
                "2ac5873bd84a8004aac0ea9c53025bfc",  # projects
            ]

            page_to_delete = None

            for db in databases:
                res = notion.databases.query(database_id=db)
                for row in res.get("results", []):
                    try:
                        title = row["properties"]["Name"]["title"][0]["plain_text"].lower()
                        if name.lower() in title:
                            page_to_delete = row["id"]
                            break
                    except:
                        continue
                if page_to_delete:
                    break

            if not page_to_delete:
                return {"error": f"No page found matching: {name}"}

            notion.pages.update(page_id=page_to_delete, archived=True)
            return {
                "success": True,
                "final_answer": "Stranica je obrisana.",
                "deleted_id": page_to_delete,
            }

        # UNKNOWN COMMAND
        else:
            return {
                "error": f"Unknown command: {command}",
                "final_answer": "Ne poznajem ovu operaciju."
            }

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

        result = decision_engine.process_ceo_instruction(text)

        return {
            "success": True,
            "final_answer": result.get("system_response"),
            "engine_output": result
        }

    except Exception as e:
        logger.exception(">> ERROR in /ops/test_ceo")
        raise HTTPException(500, str(e))


# =====================================================================
# NEW — DIRECT CONTEXT ORCHESTRATION ENDPOINT
# =====================================================================
@app.post("/ai/context")
async def ai_context(req: dict):
    try:
        user_input = req.get("text")
        if not user_input:
            raise HTTPException(400, "Missing field: text")

        result = orchestrator

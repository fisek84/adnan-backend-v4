from typing import Dict, Optional
import os
import asyncio

from openai import OpenAI


class AgentRouter:
    """
    AgentRouter — KANONSKI AGENT CALLER

    - capability-based routing
    - deterministički agent registry
    - OpenAI Assistants API execution
    - backend = orchestrator, ne executor
    """

    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # -------------------------------------------------
        # AGENT REGISTRY (KANON)
        # -------------------------------------------------
        self.agent_registry: Dict[str, Dict] = {
            "notion_ops": {
                "type": "executor",
                "capabilities": {
                    "create_database_entry",
                    "update_database_entry",
                    "query_database",
                    "create_page",
                    "retrieve_page_content",
                    "delete_page",
                },
                # ⚠️ TAČAN Assistant ID iz OpenAI
                "assistant_id": os.getenv("NOTION_OPS_ASSISTANT_ID"),
                # Executor mora biti determinističan
                "response_format": "json_object",
                "temperature": 0,
            }
        }

    # -------------------------------------------------
    # ROUTING (BY CAPABILITY)
    # -------------------------------------------------
    def route(self, command: dict) -> Dict[str, Optional[str]]:
        cmd_name = command.get("command")
        if not cmd_name:
            return {"agent": None, "assistant_id": None}

        for agent_name, agent in self.agent_registry.items():
            if cmd_name in agent["capabilities"]:
                return {
                    "agent": agent_name,
                    "assistant_id": agent["assistant_id"],
                }

        return {"agent": None, "assistant_id": None}

    # -------------------------------------------------
    # EXECUTION (OPENAI AGENT)
    # -------------------------------------------------
    async def execute(self, command: dict) -> dict:
        route = self.route(command)

        if not route.get("assistant_id"):
            return {
                "success": False,
                "reason": "no_matching_agent",
                "command": command,
            }

        assistant_id = route["assistant_id"]

        try:
            # 1. Create thread
            thread = self.client.beta.threads.create()

            # 2. Send message (delegation contract)
            self.client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=command,
            )

            # 3. Run assistant
            run = self.client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=assistant_id,
                temperature=0,
                response_format={"type": "json_object"},
            )

            # 4. Poll run (simple, safe)
            while True:
                run = self.client.beta.threads.runs.retrieve(
                    thread_id=thread.id,
                    run_id=run.id,
                )

                if run.status in {"completed", "failed", "cancelled"}:
                    break

                await asyncio.sleep(0.3)

            if run.status != "completed":
                return {
                    "success": False,
                    "reason": "agent_run_failed",
                    "status": run.status,
                }

            # 5. Fetch last message
            messages = self.client.beta.threads.messages.list(
                thread_id=thread.id,
                limit=1,
            )

            message = messages.data[0]

            if not message.content:
                return {
                    "success": False,
                    "reason": "empty_agent_response",
                }

            content = message.content[0]

            if content["type"] != "output_json":
                return {
                    "success": False,
                    "reason": "invalid_response_format",
                    "raw": content,
                }

            return {
                "success": True,
                "agent": route["agent"],
                "agent_response": content["json"],
            }

        except Exception as e:
            return {
                "success": False,
                "reason": "agent_exception",
                "error": str(e),
            }

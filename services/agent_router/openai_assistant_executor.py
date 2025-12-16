from typing import Dict, Any
import asyncio
import os
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)


class OpenAIAssistantExecutor:
    """
    OPENAI ASSISTANT EXECUTION ADAPTER — CANONICAL

    Uloga:
    - JEDINA veza backend → OpenAI agent
    - ne sadrži biznis logiku
    - ne donosi odluke
    - samo izvršava task nad asst_id
    """

    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.assistant_id = os.getenv("NOTION_OPS_ASSISTANT_ID")

        if not self.assistant_id:
            raise RuntimeError("NOTION_OPS_ASSISTANT_ID is missing")

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        task = {
            "command": str,
            "payload": dict
        }
        """

        # -------------------------------------------------
        # 1. CREATE THREAD
        # -------------------------------------------------
        thread = self.client.beta.threads.create()

        # -------------------------------------------------
        # 2. SEND TASK TO AGENT
        # -------------------------------------------------
        self.client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=[
                {
                    "type": "text",
                    "text": {
                        "command": task.get("command"),
                        "payload": task.get("payload", {}),
                    },
                }
            ],
        )

        # -------------------------------------------------
        # 3. RUN ASSISTANT
        # -------------------------------------------------
        run = self.client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=self.assistant_id,
        )

        # -------------------------------------------------
        # 4. WAIT FOR COMPLETION (ASYNC SAFE)
        # -------------------------------------------------
        while True:
            run_status = self.client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id,
            )

            if run_status.status in {"completed", "failed", "cancelled"}:
                break

            await asyncio.sleep(0.5)

        # -------------------------------------------------
        # 5. HANDLE FAILURE
        # -------------------------------------------------
        if run_status.status != "completed":
            return {
                "success": False,
                "agent": self.assistant_id,
                "status": run_status.status,
            }

        # -------------------------------------------------
        # 6. READ FINAL ASSISTANT MESSAGE (SAFE)
        # -------------------------------------------------
        messages = self.client.beta.threads.messages.list(
            thread_id=thread.id
        )

        assistant_messages = [
            m for m in messages.data if m.role == "assistant"
        ]

        if not assistant_messages:
            return {
                "success": False,
                "agent": self.assistant_id,
                "status": "no_assistant_response",
            }

        final_message = assistant_messages[0].content[0].text.value

        return {
            "success": True,
            "agent": self.assistant_id,
            "result": final_message,
        }

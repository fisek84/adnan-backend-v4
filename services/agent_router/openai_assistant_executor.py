from typing import Dict, Any
import asyncio
import os
import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)


class OpenAIAssistantExecutor:
    """
    OPENAI ASSISTANT EXECUTION ADAPTER — KANONSKI

    Pravila:
    - jedina veza backend → OpenAI agent
    - NEMA biznis logike
    - agent je GLUP izvršilac
    - backend šalje JEDNOZNAČAN execution kontrakt
    """

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        self.assistant_id = os.getenv("NOTION_OPS_ASSISTANT_ID")

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing")

        if not self.assistant_id:
            raise RuntimeError("NOTION_OPS_ASSISTANT_ID is missing")

        self.client = OpenAI(api_key=api_key)

    # ============================================================
    # EXECUTE AGENT TASK
    # ============================================================
    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        task = {
            "command": str,
            "payload": dict
        }
        """

        if not isinstance(task, dict):
            raise ValueError("Agent task must be a dict")

        command = task.get("command")
        payload = task.get("payload")

        if not command or not isinstance(payload, dict):
            raise ValueError("Agent task requires 'command' and 'payload'")

        # -------------------------------------------------
        # 1. CREATE THREAD
        # -------------------------------------------------
        thread = self.client.beta.threads.create()

        # -------------------------------------------------
        # 2. SEND EXECUTION CONTRACT (STRICT JSON)
        # -------------------------------------------------
        execution_contract = {
            "type": "agent_execution",
            "command": command,
            "payload": payload,
        }

        self.client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=json.dumps(execution_contract, ensure_ascii=False),
        )

        # -------------------------------------------------
        # 3. RUN ASSISTANT
        # -------------------------------------------------
        run = self.client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=self.assistant_id,
        )

        # -------------------------------------------------
        # 4. WAIT FOR COMPLETION
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
        # 5. FAILURE HANDLING
        # -------------------------------------------------
        if run_status.status != "completed":
            return {
                "success": False,
                "agent": self.assistant_id,
                "status": run_status.status,
            }

        # -------------------------------------------------
        # 6. READ FINAL ASSISTANT MESSAGE (LAST ONE)
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

        final_text = assistant_messages[-1].content[0].text.value

        # -------------------------------------------------
        # 7. PARSE AGENT RESPONSE (JSON SAFE)
        # -------------------------------------------------
        try:
            parsed = json.loads(final_text)
        except Exception:
            parsed = {
                "raw": final_text,
            }

        return {
            "success": True,
            "agent": self.assistant_id,
            "result": parsed,
        }

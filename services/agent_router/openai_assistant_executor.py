from typing import Dict, Any
import asyncio
import os
import json
import logging
from openai import OpenAI

from ext.notion.client import perform_notion_action

logger = logging.getLogger(__name__)


class OpenAIAssistantExecutor:
    """
    OPENAI ASSISTANT EXECUTION ADAPTER — KANONSKI

    - agent NIKAD ne vraća failure dict
    - agent ili izvrši ili baci exception
    """

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        self.assistant_id = os.getenv("NOTION_OPS_ASSISTANT_ID")

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing")

        if not self.assistant_id:
            raise RuntimeError("NOTION_OPS_ASSISTANT_ID is missing")

        self.client = OpenAI(api_key=api_key)

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(task, dict):
            raise ValueError("Agent task must be a dict")

        command = task.get("command")
        payload = task.get("payload")

        if not command or not isinstance(payload, dict):
            raise ValueError("Agent task requires 'command' and 'payload'")

        thread = self.client.beta.threads.create()

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

        run = self.client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=self.assistant_id,
        )

        while True:
            run_status = self.client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id,
            )

            if run_status.status == "requires_action":
                tool_calls = run_status.required_action.submit_tool_outputs.tool_calls

                tool_outputs = []

                for call in tool_calls:
                    if call.function.name != "perform_notion_action":
                        raise RuntimeError(
                            f"Unsupported tool call: {call.function.name}"
                        )

                    args = json.loads(call.function.arguments)
                    result = perform_notion_action(**args)

                    tool_outputs.append(
                        {
                            "tool_call_id": call.id,
                            "output": json.dumps(result, ensure_ascii=False),
                        }
                    )

                self.client.beta.threads.runs.submit_tool_outputs(
                    thread_id=thread.id,
                    run_id=run.id,
                    tool_outputs=tool_outputs,
                )

            elif run_status.status in {"completed"}:
                break

            elif run_status.status in {"failed", "cancelled"}:
                raise RuntimeError(
                    f"Assistant run failed with status: {run_status.status}"
                )

            await asyncio.sleep(0.5)

        messages = self.client.beta.threads.messages.list(thread_id=thread.id)

        assistant_messages = [m for m in messages.data if m.role == "assistant"]

        if not assistant_messages:
            raise RuntimeError("Assistant produced no response")

        final_text = assistant_messages[-1].content[0].text.value

        try:
            parsed = json.loads(final_text)
        except Exception:
            parsed = {"raw": final_text}

        return {
            "agent": self.assistant_id,
            "result": parsed,
        }

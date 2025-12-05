import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from openai import OpenAI

from services.adnan_ai_decision_service import AdnanAIDecisionService

router = APIRouter(prefix="/adnan-ai", tags=["AdnanAI Query"])

BASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "adnan_ai")


class QueryRequest(BaseModel):
    text: str


def load_json(name: str):
    path = os.path.join(BASE_PATH, name)
    if not os.path.exists(path):
        raise HTTPException(500, f"{name} not found")

    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read().strip()
        if not content:
            return {}
        return json.loads(content)


@router.post("/query")
async def adnan_ai_query(request: QueryRequest):

    OPENAI_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENAI_KEY:
        raise HTTPException(500, "OPENAI_API_KEY missing")

    client = OpenAI(api_key=OPENAI_KEY)

    decision_service = AdnanAIDecisionService()
    decision_context = decision_service.align(request.text)
    decision_process = decision_service.process(request.text)

    # --------------------------------------------------
    # FIX: REFRESH MEMORY CONTEXT AFTER decision.process()
    # --------------------------------------------------
    memory_context = decision_service.get_memory_context()
    # --------------------------------------------------

    try:
        identity = load_json("identity.json")
        kernel = load_json("kernel.json")
        mode = load_json("mode.json")
        state = load_json("state.json")
        decision_engine = load_json("decision_engine.json")
    except Exception as e:
        raise HTTPException(500, f"Failed to load identity files: {e}")

    system_prompt = (
        "Ti si Adnan.AI — digitalni Co-CEO i sistemski arhitekta Evolia ekosistema.\n\n"
        f"IDENTITY:\n{json.dumps(identity, ensure_ascii=False)}\n\n"
        f"KERNEL:\n{json.dumps(kernel, ensure_ascii=False)}\n\n"
        f"MODE:\n{json.dumps(mode, ensure_ascii=False)}\n\n"
        f"STATE:\n{json.dumps(state, ensure_ascii=False)}\n\n"
        f"DECISION_ENGINE:\n{json.dumps(decision_engine, ensure_ascii=False)}\n\n"
        f"DECISION_SNAPSHOT:\n{json.dumps(decision_process, ensure_ascii=False)}\n\n"
        f"MEMORY_CONTEXT:\n{json.dumps(memory_context, ensure_ascii=False)}\n\n"
        "BEHAVIOR_GUIDELINES:\n"
        "- Razmišljaj kao sistemski arhitekta i Co-CEO.\n"
        "- Strukturirano. Precizno. Odluke.\n"
        "- Poštuj current_mode i state.\n"
    )

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.text},
        ],
    )

    answer = response.choices[0].message.content

    final_answer = decision_service.assemble_output(answer, decision_process)

    return {
        "ok": True,
        "response": final_answer,
        "decision_context": decision_context,
        "decision_process": decision_process,
        "memory_context": memory_context
    }

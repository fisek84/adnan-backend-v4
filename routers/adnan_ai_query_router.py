import os
import json
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from openai import OpenAI

from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.conversation_state_service import ConversationStateService

router = APIRouter(prefix="/adnan-ai", tags=["AdnanAI Query"])

BASE_PATH = os.path.join(os.path.dirname(__file__), "..", "services", "adnan_ai")
BASE_PATH = os.path.abspath(BASE_PATH)

conversation_state = ConversationStateService()


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
async def adnan_ai_query(
    request: QueryRequest, x_conversation_id: str = Header(default="default")
):
    OPENAI_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENAI_KEY:
        raise HTTPException(500, "OPENAI_API_KEY missing")

    client = OpenAI(api_key=OPENAI_KEY)

    # =====================================================
    # CSI READ (READ-ONLY)
    # =====================================================
    csi_snapshot = conversation_state.get_state(x_conversation_id)

    # =====================================================
    # DECISION ENGINE
    # =====================================================
    decision_service = AdnanAIDecisionService()

    decision_context = decision_service.align(request.text, csi_snapshot=csi_snapshot)

    decision_process = decision_service.process(request.text, csi_snapshot=csi_snapshot)

    memory_context = decision_service.get_memory_context()

    # =====================================================
    # LOAD IDENTITY
    # =====================================================
    try:
        identity = load_json("identity.json")
        kernel = load_json("kernel.json")
        mode = load_json("mode.json")
        state = load_json("state.json")
        decision_engine = load_json("decision_engine.json")
    except Exception as e:
        raise HTTPException(500, f"Failed to load identity files: {e}")

    # =====================================================
    # SYSTEM PROMPT
    # =====================================================
    system_prompt = (
        "Ti si Adnan.AI — digitalni Co-CEO i sistemski arhitekta Evolia ekosistema.\n\n"
        f"IDENTITY:\n{json.dumps(identity, ensure_ascii=False)}\n\n"
        f"KERNEL:\n{json.dumps(kernel, ensure_ascii=False)}\n\n"
        f"MODE:\n{json.dumps(mode, ensure_ascii=False)}\n\n"
        f"STATE:\n{json.dumps(state, ensure_ascii=False)}\n\n"
        f"DECISION_ENGINE:\n{json.dumps(decision_engine, ensure_ascii=False)}\n\n"
        f"CSI_STATE:\n{json.dumps(csi_snapshot, ensure_ascii=False)}\n\n"
        f"DECISION_SNAPSHOT:\n{json.dumps(decision_process, ensure_ascii=False)}\n\n"
        f"MEMORY_CONTEXT:\n{json.dumps(memory_context, ensure_ascii=False)}\n\n"
        "BEHAVIOR_GUIDELINES:\n"
        "- Razmišljaj kao CEO sa short-term working memory.\n"
        "- Brojevi, potvrde i reference se odnose na CSI_STATE.\n"
        "- Ne pitaj ponovo ako CSI ima odgovor.\n"
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
        "memory_context": memory_context,
        "csi_state": csi_snapshot,
    }

import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from openai import OpenAI

from services.adnan_ai_decision_service import AdnanAIDecisionService  # ← (7.3)

# Router
router = APIRouter(prefix="/adnan-ai", tags=["AdnanAI Query"])

# Base directory for identity files
BASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "adnan_ai")


# -------------------------------
# MODELS
# -------------------------------
class QueryRequest(BaseModel):
    text: str


# -------------------------------
# HELPERS
# -------------------------------
def load_json(name: str):
    path = os.path.join(BASE_PATH, name)
    if not os.path.exists(path):
        raise HTTPException(500, f"{name} not found")

    # FIX: Windows JSON BOM problem → use utf-8-sig
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read().strip()
        if not content:
            return {}
        return json.loads(content)


# -------------------------------
# MAIN ENDPOINT
# -------------------------------
@router.post("/query")
async def adnan_ai_query(request: QueryRequest):
    """
    Centralni mozak Adnan.AI klona.
    """
    OPENAI_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENAI_KEY:
        raise HTTPException(500, "OPENAI_API_KEY missing")

    client = OpenAI(api_key=OPENAI_KEY)

    # ---------------------------------
    # Decision Layer (7.3 + 7.5)
    # ---------------------------------
    decision_service = AdnanAIDecisionService()
    decision_context = decision_service.align(request.text)
    decision_process = decision_service.process(request.text)

    # ---------------------------------
    # 7.12 — MEMORY CONTEXT EXTRACTION
    # ---------------------------------
    memory_context = decision_service.get_memory_context()
    # ---------------------------------

    try:
        identity = load_json("identity.json")
        kernel = load_json("kernel.json")
        mode = load_json("mode.json")
        state = load_json("state.json")
        decision_engine = load_json("decision_engine.json")
    except Exception as e:
        raise HTTPException(500, f"Failed to load identity files: {e}")

    # ---------------------------------
    # 7.6 + 7.7 + 7.12 — prošireni system_prompt
    # ---------------------------------
    system_prompt = (
        "Ti si Adnan.AI — digitalni Co-CEO i sistemski arhitekta Evolia ekosistema.\n\n"
        "Ovo je tvoj identitet i konfiguracija:\n"
        f"IDENTITY:\n{json.dumps(identity, ensure_ascii=False)}\n\n"
        f"KERNEL:\n{json.dumps(kernel, ensure_ascii=False)}\n\n"
        f"MODE:\n{json.dumps(mode, ensure_ascii=False)}\n\n"
        f"STATE:\n{json.dumps(state, ensure_ascii=False)}\n\n"
        f"DECISION_ENGINE:\n{json.dumps(decision_engine, ensure_ascii=False)}\n\n"
        f"DECISION_SNAPSHOT:\n{json.dumps(decision_process, ensure_ascii=False)}\n\n"
        f"MEMORY_CONTEXT:\n{json.dumps(memory_context, ensure_ascii=False)}\n\n"
        "BEHAVIOR_GUIDELINES:\n"
        "- Razmišljaj kao sistemski arhitekta i Co-CEO.\n"
        "- Odgovori moraju biti strukturirani, precizni i orijentisani na odluke.\n"
        "- Poštuj current_mode i prilagodi stil:\n"
        "  * operational → konkretno, kratko, naredbodavno\n"
        "  * strategic → vizionarski, sistemski, prioriteti\n"
        "  * diagnostic → uzrok → analiza → korekcija\n"
        "  * deep_clarity → maksimalna jasnoća i duboka analiza\n"
        "- Poštuj state (focus, deep_work, planning, execution).\n"
        "- Ne koristi emocije. Ne izmišljaj sisteme van JSON konfiguracija.\n"
        "- CEO ton i preciznost.\n"
    )
    # ---------------------------------

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.text},
        ],
    )

    answer = response.choices[0].message.content

    # ---------------------------------
    # 7.8 — Execution Alignment Layer
    # ---------------------------------
    final_answer = decision_service.enforce(answer, decision_process)

    # ---------------------------------
    # 7.9 — Refinement & Stability Layer
    # ---------------------------------
    refined_answer = decision_service.refine(final_answer, decision_process)

    # ---------------------------------
    # 7.14 — Strategic Compression Layer
    # ---------------------------------
    compressed_answer = decision_service.compress(refined_answer)

    # ---------------------------------
    # 7.15 — Executive Consistency Layer
    # ---------------------------------
    consistent_answer = decision_service.executive_consistency(compressed_answer, decision_process)

    # ---------------------------------

    return {
        "ok": True,
        "response": consistent_answer,
        "decision_context": decision_context,
        "decision_process": decision_process,
        "memory_context": memory_context
    }

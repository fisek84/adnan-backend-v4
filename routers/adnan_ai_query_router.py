# routers/adnan_ai_query_router.py
#
# CANONICAL PATCH — READ/PROPOSE ONLY (FAZA 4)
# - Ovo je "query" endpoint; mora ostati READ-ONLY (nema execution / side-effect).
# - Uklanja direktnu OpenAI chat.completions upotrebu iz routera (prevelika coupling + ne-audit).
# - Standardizuje response shape i dodaje read_only=True + trace.
# - Zadržava postojeću "decision engine" logiku i CSI snapshot.
#
# Napomena:
# - Ako želiš zadržati LLM odgovor u ovom endpointu, to treba ići kroz kanonski executor sloj
#   (npr. OpenAIAssistantExecutor) koji već ima guard-ove. Ovdje ostavljamo deterministički fallback.

from __future__ import annotations

import os
import json
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field

from services.adnan_ai_decision_service import AdnanAIDecisionService
from services.conversation_state_service import ConversationStateService

router = APIRouter(prefix="/adnan-ai", tags=["AdnanAI Query"])

BASE_PATH = os.path.join(os.path.dirname(__file__), "..", "services", "adnan_ai")
BASE_PATH = os.path.abspath(BASE_PATH)

conversation_state = ConversationStateService()


class QueryRequest(BaseModel):
    text: str = Field(..., min_length=1)


def _load_json(name: str) -> Dict[str, Any]:
    path = os.path.join(BASE_PATH, name)
    if not os.path.exists(path):
        raise HTTPException(500, f"{name} not found")

    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read().strip()
        if not content:
            return {}
        return json.loads(content)


async def _llm_readonly_advice(prompt: str, user_text: str) -> str:
    """
    READ-ONLY advisory helper.
    Prefer canonical executor if available; otherwise deterministic fallback.

    Hard rule:
    - No tool calls / no actions here.
    """
    # 1) Prefer canonical executor if present
    try:
        from services.agent_router.openai_assistant_executor import (  # type: ignore
            OpenAIAssistantExecutor,
        )

        execr = OpenAIAssistantExecutor()
        if hasattr(execr, "chat_readonly"):
            out = await execr.chat_readonly(text=user_text, system_prompt=prompt)  # type: ignore[misc]
            if isinstance(out, str) and out.strip():
                return out.strip()
        if hasattr(execr, "ceo_command"):
            # reuse ceo_command in strictly read-only mode
            result = await execr.ceo_command(
                text=user_text, context={"canon": {"read_only": True}}
            )  # type: ignore[misc]
            if isinstance(result, dict):
                summary = result.get("summary")
                if isinstance(summary, str) and summary.strip():
                    return summary.strip()
    except Exception:
        pass

    # 2) Deterministic fallback (no OpenAI dependency in router)
    # Keep it predictable: echo intent and ask for minimal constraints.
    return (
        "READ-ONLY odgovor (fallback): Primio sam upit i mogu dati analizu i prijedlog koraka, "
        "ali u ovom modu nema izvršenja niti write operacija.\n\n"
        f"Upit: {user_text}"
    )


@router.post("/query")
async def adnan_ai_query(
    request: QueryRequest, x_conversation_id: str = Header(default="default")
) -> Dict[str, Any]:
    # =====================================================
    # CSI READ (READ-ONLY)
    # =====================================================
    csi_snapshot = conversation_state.get_state(x_conversation_id)

    # =====================================================
    # DECISION ENGINE (READ-ONLY)
    # =====================================================
    decision_service = AdnanAIDecisionService()

    decision_context = decision_service.align(request.text, csi_snapshot=csi_snapshot)
    decision_process = decision_service.process(request.text, csi_snapshot=csi_snapshot)
    memory_context = decision_service.get_memory_context()

    # =====================================================
    # LOAD IDENTITY (READ-ONLY local files)
    # =====================================================
    try:
        identity = _load_json("identity.json")
        kernel = _load_json("kernel.json")
        mode = _load_json("mode.json")
        state = _load_json("state.json")
        decision_engine = _load_json("decision_engine.json")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Failed to load identity files: {e}") from e

    # =====================================================
    # SYSTEM PROMPT (READ-ONLY)
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
        "- READ-ONLY: nema toolova, nema akcija, nema write.\n"
        "- Razmišljaj kao CEO sa short-term working memory.\n"
        "- Brojevi, potvrde i reference se odnose na CSI_STATE.\n"
        "- Ne pitaj ponovo ako CSI ima odgovor.\n"
    )

    # =====================================================
    # READ-ONLY ADVICE (no direct OpenAI in router)
    # =====================================================
    answer = await _llm_readonly_advice(system_prompt, request.text)

    final_answer = decision_service.assemble_output(answer, decision_process)

    return {
        "ok": True,
        "read_only": True,
        "response": final_answer,
        "decision_context": decision_context,
        "decision_process": decision_process,
        "memory_context": memory_context,
        "csi_state": csi_snapshot,
        "trace": {
            "endpoint": "/adnan-ai/query",
            "canon": "read_propose_only",
            "conversation_id": x_conversation_id,
            "llm_path": "canonical_executor_or_fallback",
        },
    }

from __future__ import annotations

from typing import Any, Dict

import httpx
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from starlette.responses import JSONResponse

from integrations.voice_service import VoiceService

router = APIRouter(prefix="/voice", tags=["Voice Input"])

# Instances
voice_service = VoiceService()


async def _forward_to_canonical_chat(
    request: Request,
    *,
    message: str,
    extra_payload: Dict[str, Any] | None = None,
) -> httpx.Response:
    """Forward to canonical /api/chat using an in-process ASGI transport.

    This guarantees we hit the exact same canonical path (governance, sanitizers,
    session/identity propagation rules) without calling AgentRouter.execute or
    AdnanAIDecisionService in the voice runtime path.
    """

    payload: Dict[str, Any] = {"message": message}
    if isinstance(extra_payload, dict) and extra_payload:
        payload.update(extra_payload)

    transport = httpx.ASGITransport(app=request.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=30.0,
    ) as client:
        return await client.post("/api/chat", json=payload)


class VoiceText(BaseModel):
    text: str


@router.post("/exec_text")
async def voice_exec_text(payload: VoiceText, request: Request):
    # Voice is a pure input adapter; canonical processing happens in /api/chat.
    resp = await _forward_to_canonical_chat(request, message=payload.text)

    try:
        content = resp.json()
    except Exception:
        content = {"error": "canonical_chat_non_json_response", "raw": resp.text}

    if isinstance(content, dict) and "transcribed_text" not in content:
        content["transcribed_text"] = payload.text

    return JSONResponse(status_code=resp.status_code, content=content)


@router.post("/exec")
async def voice_exec(request: Request, audio: UploadFile = File(...)):
    """CEO govori → Whisper → canonical /api/chat.

    Voice layer is STT-only; it never executes or bypasses approvals.
    """
    if not audio:
        raise HTTPException(400, "Missing audio file")

    try:
        # 1. Transcribe voice → text
        text = await voice_service.transcribe(audio)

        # 2. Forward to canonical /api/chat (in-process, no network).
        resp = await _forward_to_canonical_chat(request, message=text)

        try:
            content = resp.json()
        except Exception:
            content = {"error": "canonical_chat_non_json_response", "raw": resp.text}

        if isinstance(content, dict) and "transcribed_text" not in content:
            content["transcribed_text"] = text

        return JSONResponse(status_code=resp.status_code, content=content)

    except Exception as e:
        raise HTTPException(500, f"Voice execution failed: {e}")

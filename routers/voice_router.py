from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from integrations.voice_service import VoiceService

router = APIRouter(prefix="/voice", tags=["Voice Input"])

# Instances
voice_service = VoiceService()


_ALLOWED_CHAT_FORWARD_HEADERS = {
    # Session continuity
    "x-session-id",
    # Request correlation / traceability
    "x-request-id",
    # Debug toggles used by /api/chat
    "x-debug",
    # Auth / CEO enforcement (gateway uses these)
    "authorization",
    "x-ceo-token",
    # Initiator is used by gateway CEO detection heuristics
    "x-initiator",
}


_ALLOWED_CHAT_FORWARD_PAYLOAD_KEYS = {
    # Session + conversation continuity
    "session_id",
    "sessionId",
    "conversation_id",
    # Identity/context propagation
    "identity_pack",
    "preferred_agent_id",
    "context_hint",
    # Metadata (sanitized)
    "metadata",
}


_ALLOWED_FORWARD_METADATA_KEYS = {
    "session_id",
    "sessionId",
    "initiator",
    "source",
    "channel",
}


def _parse_optional_json_dict(
    value: Optional[str], *, field_name: str
) -> Dict[str, Any]:
    if value is None:
        return {}
    raw = value.strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid JSON for '{field_name}': {exc}"
        )
    if not isinstance(obj, dict):
        raise HTTPException(
            status_code=400, detail=f"'{field_name}' must be a JSON object"
        )
    return obj


def _sanitize_metadata(md: Any) -> Dict[str, Any]:
    md0 = md if isinstance(md, dict) else {}
    out: Dict[str, Any] = {}
    for k, v in md0.items():
        if not isinstance(k, str):
            continue
        if k not in _ALLOWED_FORWARD_METADATA_KEYS:
            continue
        out[k] = v

    # Stable voice tracing (additive; do not override caller-provided values).
    out.setdefault("source", "voice")
    out.setdefault("channel", "voice")
    out.setdefault("initiator", "voice")
    return out


def _forward_headers(request: Request) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        for k, v in request.headers.items():
            if isinstance(k, str) and k.lower() in _ALLOWED_CHAT_FORWARD_HEADERS:
                out[k] = v
    except Exception:
        return {}
    return out


def _build_forward_payload(
    *,
    message: str,
    incoming_payload: Dict[str, Any] | None,
    incoming_headers: Dict[str, str],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"message": message}

    src = incoming_payload if isinstance(incoming_payload, dict) else {}

    # Allowlist only known canonical keys.
    for k in _ALLOWED_CHAT_FORWARD_PAYLOAD_KEYS:
        if k in src:
            payload[k] = src.get(k)

    # Normalize session_id from header into payload when caller didn't provide it.
    # This makes voice parity closer to text flow and avoids relying solely on headers.
    has_sid = (
        isinstance(payload.get("session_id"), str) and payload.get("session_id").strip()
    )
    if not has_sid:
        hdr_sid = (
            incoming_headers.get("X-Session-Id")
            or incoming_headers.get("x-session-id")
            or ""
        ).strip()
        if hdr_sid:
            payload["session_id"] = hdr_sid

    # Sanitize metadata strictly; also inject stable voice markers.
    payload["metadata"] = _sanitize_metadata(payload.get("metadata"))

    return payload


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

    headers = _forward_headers(request)
    payload = _build_forward_payload(
        message=message,
        incoming_payload=extra_payload,
        incoming_headers=headers,
    )

    transport = httpx.ASGITransport(app=request.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=30.0,
    ) as client:
        return await client.post("/api/chat", json=payload, headers=headers)


class VoiceText(BaseModel):
    text: str
    # Optional canonical context (additive; aligns voice with text flow)
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    identity_pack: Dict[str, Any] = Field(default_factory=dict)
    preferred_agent_id: Optional[str] = None
    context_hint: Any = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


@router.post("/exec_text")
async def voice_exec_text(payload: VoiceText, request: Request):
    # Voice is a pure input adapter; canonical processing happens in /api/chat.
    extra: Dict[str, Any] = {
        "session_id": payload.session_id,
        "conversation_id": payload.conversation_id,
        "identity_pack": payload.identity_pack,
        "preferred_agent_id": payload.preferred_agent_id,
        "context_hint": payload.context_hint,
        "metadata": payload.metadata,
    }
    resp = await _forward_to_canonical_chat(
        request, message=payload.text, extra_payload=extra
    )

    try:
        content = resp.json()
    except Exception:
        content = {"error": "canonical_chat_non_json_response", "raw": resp.text}

    if isinstance(content, dict) and "transcribed_text" not in content:
        content["transcribed_text"] = payload.text

    return JSONResponse(status_code=resp.status_code, content=content)


@router.post("/exec")
async def voice_exec(
    request: Request,
    audio: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    conversation_id: Optional[str] = Form(None),
    preferred_agent_id: Optional[str] = Form(None),
    identity_pack: Optional[str] = Form(None),
    context_hint: Optional[str] = Form(None),
    metadata: Optional[str] = Form(None),
):
    """CEO govori → Whisper → canonical /api/chat.

    Voice layer is STT-only; it never executes or bypasses approvals.
    """
    if not audio:
        raise HTTPException(400, "Missing audio file")

    try:
        # 1. Transcribe voice → text
        text = await voice_service.transcribe(audio)

        # Optional context (form fields). These are additive and allow callers
        # to keep session/conversation/identity continuity across channels.
        identity_pack_obj = _parse_optional_json_dict(
            identity_pack,
            field_name="identity_pack",
        )
        context_hint_obj = _parse_optional_json_dict(
            context_hint,
            field_name="context_hint",
        )
        metadata_obj = _parse_optional_json_dict(
            metadata,
            field_name="metadata",
        )

        # 2. Forward to canonical /api/chat (in-process, no network).
        extra2: Dict[str, Any] = {
            "session_id": session_id,
            "conversation_id": conversation_id,
            "identity_pack": identity_pack_obj,
            "preferred_agent_id": preferred_agent_id,
            "context_hint": context_hint_obj,
            "metadata": metadata_obj,
        }
        resp = await _forward_to_canonical_chat(
            request, message=text, extra_payload=extra2
        )

        try:
            content = resp.json()
        except Exception:
            content = {"error": "canonical_chat_non_json_response", "raw": resp.text}

        if isinstance(content, dict) and "transcribed_text" not in content:
            content["transcribed_text"] = text

        return JSONResponse(status_code=resp.status_code, content=content)

    except Exception as e:
        raise HTTPException(500, f"Voice execution failed: {e}")

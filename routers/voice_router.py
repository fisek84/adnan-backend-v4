from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, WebSocket
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, Response

from integrations.voice_service import VoiceService
from services.spoken_text import build_spoken_text
from services.voice_tts_service import VoiceTTSService, tts_enabled
from services.voice_profiles import (
    SUPPORTED_VOICE_LANGS,
    catalog_for_ui,
    list_agents_for_voice_ui,
    resolve_voice_profile,
)

router = APIRouter(prefix="/voice", tags=["Voice Input"])

# Instances
voice_service = VoiceService()

# Ephemeral store for large TTS payloads.
# When audio is too large to inline as base64 in JSON, we store it briefly and
# return a fetchable URL. This keeps backend voice primary without bloating JSON.
_VOICE_OUTPUT_STORE_LOCK = threading.Lock()
_VOICE_OUTPUT_STORE: Dict[str, Tuple[float, bytes, str]] = {}


def _voice_output_audio_url_ttl_sec() -> int:
    raw = (os.getenv("VOICE_TTS_AUDIO_URL_TTL_SEC") or "").strip()
    if not raw:
        return 300
    try:
        return max(0, int(raw))
    except ValueError:
        return 300


def _voice_output_audio_url_max_items() -> int:
    raw = (os.getenv("VOICE_TTS_AUDIO_URL_MAX_ITEMS") or "").strip()
    if not raw:
        return 64
    try:
        return max(0, int(raw))
    except ValueError:
        return 64


def _store_voice_output_bytes(*, audio_bytes: bytes, content_type: str) -> str:
    now = time.time()
    ttl = _voice_output_audio_url_ttl_sec()
    max_items = _voice_output_audio_url_max_items()

    with _VOICE_OUTPUT_STORE_LOCK:
        if ttl:
            expired = [
                k for k, (ts, _b, _ct) in _VOICE_OUTPUT_STORE.items() if now - ts > ttl
            ]
            for k in expired:
                _VOICE_OUTPUT_STORE.pop(k, None)

        if max_items:
            while len(_VOICE_OUTPUT_STORE) >= max_items:
                oldest_key = next(iter(_VOICE_OUTPUT_STORE), None)
                if not oldest_key:
                    break
                _VOICE_OUTPUT_STORE.pop(oldest_key, None)

        key = uuid.uuid4().hex
        _VOICE_OUTPUT_STORE[key] = (now, audio_bytes, content_type)
        return key


def _get_voice_output_bytes(key: str) -> Optional[Tuple[bytes, str]]:
    now = time.time()
    ttl = _voice_output_audio_url_ttl_sec()
    with _VOICE_OUTPUT_STORE_LOCK:
        item = _VOICE_OUTPUT_STORE.get(key)
        if item is None:
            return None
        ts, audio_bytes, content_type = item
        if ttl and now - ts > ttl:
            _VOICE_OUTPUT_STORE.pop(key, None)
            return None
        return audio_bytes, content_type


@router.get("/output/{key}")
async def voice_output_get(key: str):
    item = _get_voice_output_bytes(key)
    if item is None:
        raise HTTPException(status_code=404, detail="voice_output_not_found")

    audio_bytes, content_type = item
    ttl = _voice_output_audio_url_ttl_sec()
    headers = {
        "Cache-Control": f"private, max-age={int(ttl) if ttl else 0}",
    }
    return Response(content=audio_bytes, media_type=content_type, headers=headers)


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
    # Output language preference (safe)
    "output_lang",
}


_ALLOWED_FORWARD_METADATA_KEYS = {
    "session_id",
    "sessionId",
    "initiator",
    "source",
    "channel",
    # Language preferences (safe)
    "ui_output_lang",
    "output_lang",
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


def _extract_voice_profiles_from_metadata(md: Any) -> Dict[str, Any]:
    """Best-effort extraction of per-agent voice profile overrides.

    This is intentionally NOT forwarded to canonical /api/chat.
    """

    md0 = md if isinstance(md, dict) else {}
    vp = md0.get("voice_profiles")
    if not isinstance(vp, dict):
        return {}

    # Clamp size/shape for production safety.
    out: Dict[str, Any] = {}
    for agent_id, prof in list(vp.items())[:32]:
        if not isinstance(agent_id, str) or not agent_id.strip():
            continue
        if not isinstance(prof, dict):
            continue
        safe_prof: Dict[str, Any] = {}
        for k in ("language", "gender", "preset_id", "preset", "model", "format"):
            if k in prof:
                safe_prof[k] = prof.get(k)
        if safe_prof:
            out[agent_id.strip()] = safe_prof

    # Allow wildcard default via "*".
    wildcard = vp.get("*")
    if isinstance(wildcard, dict):
        safe_wc: Dict[str, Any] = {}
        for k in ("language", "gender", "preset_id", "preset", "model", "format"):
            if k in wildcard:
                safe_wc[k] = wildcard.get(k)
        if safe_wc:
            out["*"] = safe_wc

    return out


def _resolve_output_lang_from_request(
    *, output_lang: Optional[str], metadata: Any, context_hint: Any
) -> Optional[str]:
    if isinstance(output_lang, str) and output_lang.strip():
        return output_lang.strip()
    md = metadata if isinstance(metadata, dict) else {}
    cand = md.get("ui_output_lang") or md.get("output_lang")
    if isinstance(cand, str) and cand.strip():
        return cand.strip()
    ch = context_hint if isinstance(context_hint, dict) else {}
    cand2 = ch.get("ui_output_lang") or ch.get("output_lang")
    if isinstance(cand2, str) and cand2.strip():
        return cand2.strip()
    return None


def _truthy(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _env_true(name: str, default: str = "false") -> bool:
    raw = (os.getenv(name) or default or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _voice_realtime_ws_enabled() -> bool:
    return _env_true("VOICE_REALTIME_WS_ENABLED", "false")


def _voice_realtime_ws_idle_timeout_sec() -> float:
    # Keep conservative defaults; WS is opt-in.
    v = _env_int("VOICE_REALTIME_WS_IDLE_TIMEOUT_SEC", 60)
    return float(max(5, min(v, 600)))


def _voice_realtime_ws_turn_timeout_sec() -> float:
    v = _env_int("VOICE_REALTIME_WS_TURN_TIMEOUT_SEC", 120)
    return float(max(5, min(v, 600)))


def _iso_utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _chunk_text(text: str, *, max_chars: int = 240) -> list[str]:
    t = text or ""
    if not t:
        return []
    if max_chars <= 0:
        return [t]
    out: list[str] = []
    i = 0
    n = len(t)
    while i < n:
        j = min(n, i + max_chars)
        if j < n:
            k = t.rfind(" ", i, j)
            if k > i + int(max_chars * 0.6):
                j = k + 1
        out.append(t[i:j])
        i = j
    return out


def _ceo_token_enforcement_enabled() -> bool:
    # Mirrors gateway behaviour but kept local to avoid import cycles.
    return _env_true("CEO_TOKEN_ENFORCEMENT", "false")


def _extract_bearer_token(authorization: str) -> str:
    auth = (authorization or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _require_ceo_token_if_enforced_ws(websocket: WebSocket) -> str:
    """Return token if enforced; else return empty string.

    NOTE: Browsers cannot set arbitrary headers for WebSocket.
    For v1 we accept token via query string when enforcement is enabled.
    """

    if not _ceo_token_enforcement_enabled():
        return ""

    expected = (os.getenv("CEO_APPROVAL_TOKEN") or "").strip()
    if not expected:
        raise RuntimeError(
            "CEO token enforcement enabled but CEO_APPROVAL_TOKEN is not set"
        )

    qp = websocket.query_params
    provided = (qp.get("ceo_token") or qp.get("token") or "").strip()
    if not provided:
        # Allow subprotocol-like fallback via query param only.
        # (WebSocket API can't send headers from browsers.)
        provided = ""

    if provided != expected:
        raise PermissionError("ceo_token_required")

    return provided


async def _call_canonical_chat_via_asgi(
    *,
    app: Any,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout_sec: float,
) -> Dict[str, Any]:
    """Call canonical /api/chat in-process via ASGI transport and return decoded JSON."""

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=timeout_sec,
    ) as client:
        res = await client.post("/api/chat", json=payload, headers=headers)
        try:
            body = res.json()
        except Exception:
            body = {"error": "canonical_chat_non_json_response", "raw": res.text}
        if not isinstance(body, dict):
            body = {"error": "canonical_chat_non_object_response", "raw": body}
        body.setdefault("_http_status", res.status_code)
        return body


def _voice_output_max_audio_bytes() -> int:
    raw = (os.getenv("VOICE_TTS_MAX_AUDIO_BYTES") or "").strip()
    if not raw:
        return 512 * 1024
    try:
        return max(0, int(raw))
    except ValueError:
        return 512 * 1024


def _voice_output_max_text_chars() -> int:
    raw = (os.getenv("VOICE_TTS_MAX_TEXT_CHARS") or "").strip()
    if not raw:
        return 2000
    try:
        return max(0, int(raw))
    except ValueError:
        return 2000


def _maybe_build_voice_output(
    *,
    text: str,
    want_voice_output: bool,
    agent_id: Optional[str] = None,
    output_lang: Optional[str] = None,
    request_voice_profiles: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if not want_voice_output:
        return None

    if not tts_enabled():
        return {"available": False, "reason": "tts_disabled"}

    max_text_chars = _voice_output_max_text_chars()
    spoken = build_spoken_text(
        text=text, output_lang=output_lang, max_chars=max_text_chars
    )
    spoken_text = spoken.spoken_text
    if not spoken_text.strip():
        return {"available": False, "reason": "empty_spoken_text"}

    service = VoiceTTSService()
    if not service.is_configured():
        return {"available": False, "reason": "tts_not_configured"}

    prof = resolve_voice_profile(
        agent_id=agent_id,
        output_lang=output_lang,
        request_voice_profiles=request_voice_profiles,
    )

    try:
        audio_bytes, content_type = service.synthesize(
            text=spoken_text,
            voice=prof.vendor_voice,
            model=prof.model,
            audio_format=prof.audio_format,
        )
    except Exception as exc:
        return {"available": False, "reason": "tts_failed", "error": str(exc)}

    max_audio_bytes = _voice_output_max_audio_bytes()
    if max_audio_bytes and len(audio_bytes) > max_audio_bytes:
        key = _store_voice_output_bytes(
            audio_bytes=audio_bytes, content_type=content_type
        )
        return {
            "available": True,
            "reason": "delivered_via_url",
            "delivery": "url",
            "content_type": content_type,
            "audio_url": f"/api/voice/output/{key}",
            "inline_max_audio_bytes": max_audio_bytes,
            "audio_bytes": len(audio_bytes),
            "spoken_text": {
                "full_text_chars": spoken.full_text_chars,
                "spoken_text_chars": spoken.spoken_text_chars,
                "changed": spoken.changed,
                "shortened": spoken.shortened,
                "normalized": spoken.normalized,
                "strategy": spoken.strategy,
                "max_text_chars": max_text_chars,
            },
            "voice_profile": {
                "agent_id": prof.agent_id,
                "language": prof.language,
                "gender": prof.gender,
                "preset_id": prof.preset_id,
                "voice": prof.vendor_voice,
                "model": prof.model,
                "format": prof.audio_format,
                "source": prof.source,
            },
        }

    return {
        "available": True,
        "delivery": "inline",
        "content_type": content_type,
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "audio_bytes": len(audio_bytes),
        "spoken_text": {
            "full_text_chars": spoken.full_text_chars,
            "spoken_text_chars": spoken.spoken_text_chars,
            "changed": spoken.changed,
            "shortened": spoken.shortened,
            "normalized": spoken.normalized,
            "strategy": spoken.strategy,
            "max_text_chars": max_text_chars,
        },
        "voice_profile": {
            "agent_id": prof.agent_id,
            "language": prof.language,
            "gender": prof.gender,
            "preset_id": prof.preset_id,
            "voice": prof.vendor_voice,
            "model": prof.model,
            "format": prof.audio_format,
            "source": prof.source,
        },
    }


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
    output_lang: Optional[str] = None
    context_hint: Any = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    want_voice_output: Optional[bool] = None


@router.post("/exec_text")
async def voice_exec_text(payload: VoiceText, request: Request):
    voice_profiles = _extract_voice_profiles_from_metadata(payload.metadata)
    out_lang = _resolve_output_lang_from_request(
        output_lang=payload.output_lang,
        metadata=payload.metadata,
        context_hint=payload.context_hint,
    )

    # Voice is a pure input adapter; canonical processing happens in /api/chat.
    extra: Dict[str, Any] = {
        "session_id": payload.session_id,
        "conversation_id": payload.conversation_id,
        "identity_pack": payload.identity_pack,
        "preferred_agent_id": payload.preferred_agent_id,
        "output_lang": payload.output_lang,
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

    if isinstance(content, dict):
        voice_output = _maybe_build_voice_output(
            text=str(content.get("text") or ""),
            want_voice_output=_truthy(payload.want_voice_output),
            agent_id=str(content.get("agent_id") or "").strip() or None,
            output_lang=out_lang,
            request_voice_profiles=voice_profiles,
        )
        if voice_output is not None:
            content["voice_output"] = voice_output

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
    want_voice_output: Optional[str] = Form(None),
    output_lang: Optional[str] = Form(None),
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

        voice_profiles = _extract_voice_profiles_from_metadata(metadata_obj)
        out_lang = _resolve_output_lang_from_request(
            output_lang=output_lang,
            metadata=metadata_obj,
            context_hint=context_hint_obj,
        )

        # 2. Forward to canonical /api/chat (in-process, no network).
        extra2: Dict[str, Any] = {
            "session_id": session_id,
            "conversation_id": conversation_id,
            "identity_pack": identity_pack_obj,
            "preferred_agent_id": preferred_agent_id,
            "context_hint": context_hint_obj,
            "metadata": metadata_obj,
            "output_lang": output_lang,
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

        if isinstance(content, dict):
            voice_output = _maybe_build_voice_output(
                text=str(content.get("text") or ""),
                want_voice_output=_truthy(want_voice_output),
                agent_id=str(content.get("agent_id") or "").strip() or None,
                output_lang=out_lang,
                request_voice_profiles=voice_profiles,
            )
            if voice_output is not None:
                content["voice_output"] = voice_output

        return JSONResponse(status_code=resp.status_code, content=content)

    except Exception as e:
        raise HTTPException(500, f"Voice execution failed: {e}")


@router.websocket("/realtime/ws")
async def voice_realtime_ws(websocket: WebSocket):
    """WebSocket realtime adapter v1 (text-only input/final + cancel).

    This is transport/session only. It bridges to canonical /api/chat (brain) via
    in-process ASGI HTTP and emits a stream-like event contract.
    """

    # Always accept first, then close with a deterministic code.
    await websocket.accept()

    if not _voice_realtime_ws_enabled():
        await websocket.close(code=4404, reason="voice_realtime_disabled")
        return

    try:
        ceo_token = _require_ceo_token_if_enforced_ws(websocket)
    except PermissionError:
        await websocket.close(code=4403, reason="ceo_token_required")
        return
    except Exception:
        await websocket.close(code=1011, reason="server_misconfigured")
        return

    send_lock = asyncio.Lock()
    seq = 0

    session_id: Optional[str] = None
    conversation_id: Optional[str] = None

    active_turn_task: Optional[asyncio.Task] = None
    active_turn_id: Optional[str] = None
    active_request_id: Optional[str] = None
    active_cancelled = False

    idle_timeout = _voice_realtime_ws_idle_timeout_sec()
    turn_timeout = _voice_realtime_ws_turn_timeout_sec()

    async def _send_event(
        evt_type: str,
        data: Dict[str, Any],
        *,
        request_id: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> None:
        nonlocal seq

        rid = request_id if request_id is not None else active_request_id
        evt = {
            "v": 1,
            "type": evt_type,
            "seq": seq,
            "ts": _iso_utc_now(),
            "request_id": rid,
            "session_id": session_id,
            "conversation_id": conversation_id,
            "data": {**(data or {}), **({"turn_id": turn_id} if turn_id else {})},
        }
        seq += 1
        raw = json.dumps(evt, ensure_ascii=False)
        async with send_lock:
            await websocket.send_text(raw)

    async def _cancel_active_turn(*, reason: str) -> None:
        nonlocal active_turn_task, active_turn_id, active_request_id, active_cancelled
        if active_turn_task is None:
            return
        active_cancelled = True
        try:
            current = asyncio.current_task()
            if active_turn_task is not current:
                active_turn_task.cancel()
        except Exception:
            pass
        try:
            await _send_event(
                "done",
                {"ok": False, "reason": reason},
                request_id=active_request_id,
                turn_id=active_turn_id,
            )
        except Exception:
            pass
        active_turn_task = None
        active_turn_id = None
        active_request_id = None

    def _normalize_incoming_event(obj: Any) -> Dict[str, Any]:
        return obj if isinstance(obj, dict) else {}

    async def _recv_event() -> Dict[str, Any]:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=idle_timeout)
        try:
            return _normalize_incoming_event(json.loads(raw))
        except Exception:
            return {"type": "_invalid_json", "data": {"raw": raw}}

    # Require session.start as the first meaningful event.
    try:
        first = await _recv_event()
    except asyncio.TimeoutError:
        await websocket.close(code=4408, reason="idle_timeout")
        return
    except Exception:
        await websocket.close(code=1011, reason="receive_failed")
        return

    if str(first.get("type") or "") != "session.start":
        await _send_event(
            "error",
            {
                "code": "bad_request",
                "message": "Expected session.start",
                "retryable": False,
                "http_status": 400,
            },
            request_id=uuid.uuid4().hex,
        )
        await websocket.close(code=4400, reason="expected_session_start")
        return

    data0 = first.get("data") if isinstance(first.get("data"), dict) else {}
    session_id = (
        str(data0.get("session_id") or "").strip() or f"ws_session_{uuid.uuid4().hex}"
    )
    conversation_id = str(data0.get("conversation_id") or "").strip() or session_id

    await _send_event(
        "session.started",
        {
            "session_id": session_id,
            "conversation_id": conversation_id,
            "capabilities": {
                "text_streaming": True,
                "final_response": True,
                "cancel": True,
            },
        },
        request_id=uuid.uuid4().hex,
    )

    async def _process_turn(
        *,
        text: str,
        preferred_agent_id: Optional[str],
        output_lang: Optional[str],
        want_voice_output: bool,
        metadata: Dict[str, Any],
        context_hint: Any,
        identity_pack: Dict[str, Any],
        request_id: str,
        turn_id: str,
    ) -> None:
        nonlocal active_turn_task, active_turn_id, active_request_id

        await _send_event(
            "meta",
            {
                "source_endpoint": "/api/voice/realtime/ws",
                "bridge": {
                    "brain": "/api/chat",
                    "streaming_semantics": "/api/chat/stream",
                },
                "capabilities": {"text_streaming": True, "final_response": True},
            },
            request_id=request_id,
            turn_id=turn_id,
        )
        await _send_event(
            "turn.started",
            {"turn_id": turn_id, "request_id": request_id},
            request_id=request_id,
            turn_id=turn_id,
        )

        # Build canonical chat payload (do NOT invent a new brain contract).
        chat_payload: Dict[str, Any] = {
            "message": text,
            "text": text,
            "input_text": text,
            "initiator": "ceo_chat",
            "session_id": session_id,
            "conversation_id": conversation_id,
        }
        if preferred_agent_id:
            chat_payload["preferred_agent_id"] = preferred_agent_id
        if output_lang:
            chat_payload["output_lang"] = output_lang

        # Keep metadata additive; allowlist only a minimal set.
        md_out: Dict[str, Any] = {}
        md_in = metadata if isinstance(metadata, dict) else {}
        for k in ("session_id", "initiator", "source", "channel", "ui_output_lang"):
            if k in md_in:
                md_out[k] = md_in.get(k)
        md_out.setdefault("session_id", session_id)
        md_out.setdefault("initiator", "ceo_chat")
        md_out.setdefault("source", "voice")
        md_out.setdefault("channel", "voice")
        chat_payload["metadata"] = md_out

        if isinstance(context_hint, dict):
            chat_payload["context_hint"] = context_hint
        if isinstance(identity_pack, dict) and identity_pack:
            chat_payload["identity_pack"] = identity_pack

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-Initiator": "ceo_chat",
            "X-Session-Id": session_id,
            "X-Request-Id": request_id,
        }
        if ceo_token:
            headers["X-CEO-Token"] = ceo_token

        body_obj = await asyncio.wait_for(
            _call_canonical_chat_via_asgi(
                app=websocket.app,
                payload=chat_payload,
                headers=headers,
                timeout_sec=turn_timeout,
            ),
            timeout=turn_timeout,
        )

        text_out = str(body_obj.get("text") or "")

        # Additive: include backend-generated voice_output only when explicitly requested.
        # This does NOT change canonical /api/chat; it only enriches the WS adapter response.
        if want_voice_output:
            try:
                voice_profiles = _extract_voice_profiles_from_metadata(metadata)
                voice_output = _maybe_build_voice_output(
                    text=text_out,
                    want_voice_output=True,
                    agent_id=str(body_obj.get("agent_id") or "").strip() or None,
                    output_lang=output_lang,
                    request_voice_profiles=voice_profiles,
                )
                if voice_output is not None:
                    body_obj["voice_output"] = voice_output
            except Exception:
                # Fail-soft: text response should still complete.
                pass
        for part in _chunk_text(text_out):
            if active_cancelled:
                return
            if part:
                await _send_event(
                    "assistant.delta",
                    {"delta_text": part},
                    request_id=request_id,
                    turn_id=turn_id,
                )

        await _send_event(
            "assistant.final",
            {"text": text_out, "response": body_obj},
            request_id=request_id,
            turn_id=turn_id,
        )
        await _send_event(
            "done",
            {"ok": True, "reason": "completed"},
            request_id=request_id,
            turn_id=turn_id,
        )
        active_turn_task = None
        active_turn_id = None
        active_request_id = None

    async def _run_turn_task(
        *,
        request_id: str,
        turn_id: str,
        text: str,
        preferred_agent_id: Optional[str],
        output_lang: Optional[str],
        want_voice_output: bool,
        metadata: Dict[str, Any],
        context_hint: Any,
        identity_pack: Dict[str, Any],
    ) -> None:
        try:
            await asyncio.wait_for(
                _process_turn(
                    text=text,
                    preferred_agent_id=preferred_agent_id,
                    output_lang=output_lang,
                    want_voice_output=want_voice_output,
                    metadata=metadata,
                    context_hint=context_hint,
                    identity_pack=identity_pack,
                    request_id=request_id,
                    turn_id=turn_id,
                ),
                timeout=turn_timeout,
            )
        except asyncio.CancelledError:
            # Cancelled by control.cancel or disconnect.
            raise
        except asyncio.TimeoutError:
            try:
                await _send_event(
                    "error",
                    {
                        "code": "turn_timeout",
                        "message": "Turn timed out",
                        "retryable": False,
                        "http_status": 504,
                    },
                    request_id=request_id,
                    turn_id=turn_id,
                )
            finally:
                await _cancel_active_turn(reason="turn_timeout")
        except Exception as exc:
            try:
                await _send_event(
                    "error",
                    {
                        "code": "internal_error",
                        "message": str(exc),
                        "retryable": False,
                        "http_status": 500,
                    },
                    request_id=request_id,
                    turn_id=turn_id,
                )
            finally:
                await _cancel_active_turn(reason="error")

    try:
        while True:
            try:
                evt = await _recv_event()
            except asyncio.TimeoutError:
                await _cancel_active_turn(reason="idle_timeout")
                await websocket.close(code=4408, reason="idle_timeout")
                return

            evt_type = str(evt.get("type") or "")
            data = evt.get("data") if isinstance(evt.get("data"), dict) else {}

            if evt_type == "session.end":
                await _cancel_active_turn(reason="session_end")
                await websocket.close(code=1000, reason="session_end")
                return

            if evt_type == "control.cancel":
                await _cancel_active_turn(reason="cancelled")
                continue

            if evt_type == "input.final":
                if active_turn_task is not None:
                    await _send_event(
                        "error",
                        {
                            "code": "turn_in_progress",
                            "message": "Turn already in progress",
                            "retryable": False,
                            "http_status": 409,
                        },
                        request_id=uuid.uuid4().hex,
                    )
                    continue

                text_in = str(data.get("text") or "").strip()
                if not text_in:
                    await _send_event(
                        "error",
                        {
                            "code": "bad_request",
                            "message": "Missing text",
                            "retryable": False,
                            "http_status": 400,
                        },
                        request_id=uuid.uuid4().hex,
                    )
                    continue

                active_cancelled = False
                active_request_id = uuid.uuid4().hex
                active_turn_id = (
                    str(data.get("turn_id") or "").strip() or uuid.uuid4().hex
                )

                preferred_agent_id = (
                    str(data.get("preferred_agent_id") or "").strip() or None
                )
                output_lang = str(data.get("output_lang") or "").strip() or None
                want_voice_output = _truthy(data.get("want_voice_output"))
                context_hint = data.get("context_hint")
                identity_pack = (
                    data.get("identity_pack")
                    if isinstance(data.get("identity_pack"), dict)
                    else {}
                )
                metadata = (
                    data.get("metadata")
                    if isinstance(data.get("metadata"), dict)
                    else {}
                )

                active_turn_task = asyncio.create_task(
                    _run_turn_task(
                        request_id=active_request_id,
                        turn_id=active_turn_id,
                        text=text_in,
                        preferred_agent_id=preferred_agent_id,
                        output_lang=output_lang,
                        want_voice_output=want_voice_output,
                        metadata=metadata,
                        context_hint=context_hint,
                        identity_pack=identity_pack,
                    )
                )
                continue

            # Ignore other event types for forward-compat.

    except Exception:
        # Best-effort cleanup.
        try:
            await _cancel_active_turn(reason="error")
        except Exception:
            pass
        try:
            await websocket.close(code=1011, reason="internal_error")
        except Exception:
            pass


@router.get("/profiles")
async def voice_profiles_get():
    """Canonical voice profile catalog for the frontend.

    This endpoint intentionally exposes only stable, UI-safe data.
    """

    return {
        "provider": {
            "type": "openai_tts",
            "configured": bool(VoiceTTSService().is_configured()),
            "enabled": bool(tts_enabled()),
        },
        "catalog": catalog_for_ui(),
        "agents": list_agents_for_voice_ui(),
        "supported_voice_langs": list(SUPPORTED_VOICE_LANGS),
    }

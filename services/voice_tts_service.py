from __future__ import annotations

import os
from typing import Optional, Tuple


def _env_true(name: str, default: str = "false") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class VoiceTTSService:
    """Minimal TTS adapter (turn-based).

    NOTE:
    - API contract is vendor-agnostic; this is only an internal implementation.
    - Uses existing `openai` dependency already present in this repo.
    - Designed to fail safe: callers should treat errors as "no audio available".
    """

    def __init__(self) -> None:
        self._api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None

        # Keep defaults minimal and overridable.
        self._model = (os.getenv("VOICE_TTS_MODEL") or "tts-1").strip() or "tts-1"
        self._voice = (os.getenv("VOICE_TTS_VOICE") or "alloy").strip() or "alloy"
        self._format = (os.getenv("VOICE_TTS_FORMAT") or "mp3").strip().lower() or "mp3"

    def is_configured(self) -> bool:
        if not self._api_key:
            return False
        if not self._model:
            return False
        return True

    def synthesize(self, *, text: str) -> Tuple[bytes, str]:
        """Return (audio_bytes, content_type). Raises on error."""

        if not self.is_configured():
            raise RuntimeError("tts_not_configured")

        # Import inside method to avoid import-time side effects.
        audio_bytes: Optional[bytes] = None

        # Preferred client style (OpenAI SDK v1).
        try:
            from openai import OpenAI  # type: ignore

            client = OpenAI(api_key=self._api_key)
            resp = client.audio.speech.create(
                model=self._model,
                voice=self._voice,
                input=text,
                format=self._format,
            )

            # SDK response shapes vary; handle defensively.
            if hasattr(resp, "content"):
                c = getattr(resp, "content")
                if isinstance(c, (bytes, bytearray)):
                    audio_bytes = bytes(c)
            if audio_bytes is None and hasattr(resp, "read"):
                r = resp.read()
                if isinstance(r, (bytes, bytearray)):
                    audio_bytes = bytes(r)
        except Exception:
            audio_bytes = None

        # Fallback to legacy module-level API (also used by VoiceService for STT).
        if audio_bytes is None:
            try:
                import openai  # type: ignore

                openai.api_key = self._api_key
                resp2 = openai.audio.speech.create(
                    model=self._model,
                    voice=self._voice,
                    input=text,
                    format=self._format,
                )
                if hasattr(resp2, "content"):
                    c2 = getattr(resp2, "content")
                    if isinstance(c2, (bytes, bytearray)):
                        audio_bytes = bytes(c2)
                if audio_bytes is None and hasattr(resp2, "read"):
                    r2 = resp2.read()
                    if isinstance(r2, (bytes, bytearray)):
                        audio_bytes = bytes(r2)
            except Exception as exc:
                raise RuntimeError(f"tts_failed: {exc}") from exc

        if audio_bytes is None:
            raise RuntimeError("tts_failed: empty_audio")

        content_type = (
            "audio/mpeg" if self._format == "mp3" else "application/octet-stream"
        )
        return audio_bytes, content_type


def tts_enabled() -> bool:
    """Server-side feature flag. OFF by default."""

    return _env_true("VOICE_TTS_ENABLED", "false")

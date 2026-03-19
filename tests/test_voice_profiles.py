from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from routers import voice_router
from services.voice_profiles import resolve_voice_profile


def test_resolve_voice_profile_uses_agent_default_from_registry() -> None:
    prof = resolve_voice_profile(agent_id="ceo_advisor", output_lang="en")
    assert prof.vendor_voice == "onyx"
    assert prof.preset_id in {"onyx", "default"}


def test_resolve_voice_profile_request_override_wins() -> None:
    prof = resolve_voice_profile(
        agent_id="ceo_advisor",
        output_lang="en",
        request_voice_profiles={
            "ceo_advisor": {"preset_id": "nova", "gender": "female", "language": "en"}
        },
    )
    assert prof.vendor_voice == "nova"
    assert prof.gender == "female"
    assert prof.language == "en"


def test_voice_output_uses_resolved_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_TTS_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    calls: Dict[str, Any] = {}

    def fake_is_configured(self: Any) -> bool:
        return True

    def fake_synthesize(
        self: Any,
        *,
        text: str,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        audio_format: Optional[str] = None,
    ):
        calls["voice"] = voice
        calls["model"] = model
        calls["format"] = audio_format
        return (b"abc", "audio/mpeg")

    monkeypatch.setattr(
        voice_router.VoiceTTSService, "is_configured", fake_is_configured
    )
    monkeypatch.setattr(voice_router.VoiceTTSService, "synthesize", fake_synthesize)

    vo = voice_router._maybe_build_voice_output(
        text="Hello",
        want_voice_output=True,
        agent_id="ceo_advisor",
        output_lang="en",
        request_voice_profiles={"ceo_advisor": {"preset_id": "nova"}},
    )

    assert vo and vo.get("available") is True
    assert calls.get("voice") == "nova"
    vp = vo.get("voice_profile")
    assert isinstance(vp, dict)
    assert vp.get("voice") == "nova"
    assert vp.get("agent_id") == "ceo_advisor"

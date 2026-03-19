from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from services.agent_registry_service import AgentRegistryService


SUPPORTED_VOICE_LANGS: Tuple[str, ...] = ("bs", "hr", "sr", "en", "de")
SUPPORTED_GENDERS: Tuple[str, ...] = ("male", "female", "neutral")


@dataclass(frozen=True)
class VoicePreset:
    preset_id: str
    vendor_voice: str
    label: str
    gender: str  # male | female | neutral
    languages: Tuple[str, ...] = SUPPORTED_VOICE_LANGS


@dataclass(frozen=True)
class ResolvedVoiceProfile:
    agent_id: str
    language: str
    gender: str
    preset_id: str
    vendor_voice: str
    model: str
    audio_format: str
    source: str  # request_override | agent_default | global_default


# Canonical catalog for the current OpenAI TTS adapter.
# IMPORTANT: keep the vendor voice names centralized here.
VOICE_PRESETS: Dict[str, VoicePreset] = {
    "alloy": VoicePreset(
        preset_id="alloy",
        vendor_voice="alloy",
        label="Alloy",
        gender="neutral",
    ),
    "onyx": VoicePreset(
        preset_id="onyx",
        vendor_voice="onyx",
        label="Onyx",
        gender="male",
    ),
    "echo": VoicePreset(
        preset_id="echo",
        vendor_voice="echo",
        label="Echo",
        gender="male",
    ),
    "nova": VoicePreset(
        preset_id="nova",
        vendor_voice="nova",
        label="Nova",
        gender="female",
    ),
    "shimmer": VoicePreset(
        preset_id="shimmer",
        vendor_voice="shimmer",
        label="Shimmer",
        gender="female",
    ),
    "fable": VoicePreset(
        preset_id="fable",
        vendor_voice="fable",
        label="Fable",
        gender="neutral",
    ),
}


def _norm_lang(value: Optional[str]) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    # Accept both BCP-47 (en-US) and short tags (en)
    base = raw.split("-", 1)[0].split("_", 1)[0]
    if base in SUPPORTED_VOICE_LANGS:
        return base
    # Treat sh as BCS
    if base == "sh":
        return "bs"
    return ""


def _norm_gender(value: Optional[str]) -> str:
    raw = (value or "").strip().lower()
    if raw in SUPPORTED_GENDERS:
        return raw
    return ""


def _env_default_model() -> str:
    return (os.getenv("VOICE_TTS_MODEL") or "tts-1").strip() or "tts-1"


def _env_default_voice() -> str:
    return (os.getenv("VOICE_TTS_VOICE") or "alloy").strip() or "alloy"


def _env_default_format() -> str:
    return (os.getenv("VOICE_TTS_FORMAT") or "mp3").strip().lower() or "mp3"


_AGENT_REGISTRY: Optional[AgentRegistryService] = None
_AGENT_DEFAULTS_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def _load_agent_defaults() -> Dict[str, Dict[str, Any]]:
    global _AGENT_REGISTRY, _AGENT_DEFAULTS_CACHE
    if _AGENT_DEFAULTS_CACHE is not None:
        return _AGENT_DEFAULTS_CACHE

    reg = AgentRegistryService()
    try:
        reg.load_from_agents_json("config/agents.json", clear=True)
    except Exception:
        _AGENT_DEFAULTS_CACHE = {}
        _AGENT_REGISTRY = reg
        return _AGENT_DEFAULTS_CACHE

    out: Dict[str, Dict[str, Any]] = {}
    try:
        for entry in reg.list_agents(enabled_only=False):
            md = entry.metadata if isinstance(entry.metadata, dict) else {}
            vp = (
                md.get("voice_profile")
                if isinstance(md.get("voice_profile"), dict)
                else {}
            )
            if isinstance(vp, dict) and vp:
                out[str(entry.id)] = vp
    except Exception:
        out = {}

    _AGENT_REGISTRY = reg
    _AGENT_DEFAULTS_CACHE = out
    return out


def list_agents_for_voice_ui() -> List[Dict[str, Any]]:
    reg = AgentRegistryService()
    try:
        reg.load_from_agents_json("config/agents.json", clear=True)
    except Exception:
        return []

    agents: List[Dict[str, Any]] = []
    for entry in reg.list_agents(enabled_only=True):
        agents.append({"agent_id": entry.id, "name": entry.name})
    return agents


def catalog_for_ui() -> Dict[str, Any]:
    return {
        "supported_languages": list(SUPPORTED_VOICE_LANGS),
        "supported_genders": list(SUPPORTED_GENDERS),
        "presets": [
            {
                "preset_id": p.preset_id,
                "label": p.label,
                "vendor_voice": p.vendor_voice,
                "gender": p.gender,
                "languages": list(p.languages),
            }
            for p in VOICE_PRESETS.values()
        ],
    }


def resolve_voice_profile(
    *,
    agent_id: Optional[str],
    output_lang: Optional[str],
    request_voice_profiles: Optional[Dict[str, Any]] = None,
) -> ResolvedVoiceProfile:
    agent = (agent_id or "").strip() or "unknown"

    request_map = (
        request_voice_profiles if isinstance(request_voice_profiles, dict) else {}
    )
    request_for_agent = (
        request_map.get(agent)
        if isinstance(request_map.get(agent), dict)
        else request_map.get("*")
        if isinstance(request_map.get("*"), dict)
        else {}
    )
    request_for_agent = request_for_agent if isinstance(request_for_agent, dict) else {}

    defaults = _load_agent_defaults()
    agent_default = defaults.get(agent) if isinstance(defaults.get(agent), dict) else {}

    lang = _norm_lang(
        str(request_for_agent.get("language"))
        if request_for_agent.get("language") is not None
        else None
    )
    if not lang:
        lang = _norm_lang(
            str(agent_default.get("language"))
            if agent_default.get("language") is not None
            else None
        )
    if not lang:
        lang = _norm_lang(output_lang)
    if not lang:
        lang = "bs"

    gender = _norm_gender(
        str(request_for_agent.get("gender"))
        if request_for_agent.get("gender") is not None
        else None
    )
    if not gender:
        gender = _norm_gender(
            str(agent_default.get("gender"))
            if agent_default.get("gender") is not None
            else None
        )
    if not gender:
        gender = "neutral"

    preset_id = str(
        request_for_agent.get("preset_id") or request_for_agent.get("preset") or ""
    ).strip()
    if not preset_id:
        preset_id = str(
            agent_default.get("preset_id") or agent_default.get("preset") or ""
        ).strip()

    source = "global_default"
    if preset_id and preset_id in VOICE_PRESETS:
        preset = VOICE_PRESETS[preset_id]
        source = (
            "request_override"
            if request_for_agent
            else "agent_default"
            if agent_default
            else "global_default"
        )
        vendor_voice = preset.vendor_voice
    else:
        # If no preset specified (or unknown), fall back to global env voice.
        preset_id = "default"
        vendor_voice = _env_default_voice()
        source = (
            "request_override"
            if request_for_agent
            else "agent_default"
            if agent_default
            else "global_default"
        )

    # Optional model/format overrides (kept production-safe: only accept strings).
    model = (
        str(request_for_agent.get("model")).strip()
        if isinstance(request_for_agent.get("model"), str)
        else str(agent_default.get("model")).strip()
        if isinstance(agent_default.get("model"), str)
        else _env_default_model()
    )
    audio_format = (
        str(request_for_agent.get("format")).strip().lower()
        if isinstance(request_for_agent.get("format"), str)
        else str(agent_default.get("format")).strip().lower()
        if isinstance(agent_default.get("format"), str)
        else _env_default_format()
    )

    return ResolvedVoiceProfile(
        agent_id=agent,
        language=lang,
        gender=gender,
        preset_id=preset_id,
        vendor_voice=vendor_voice,
        model=model,
        audio_format=audio_format,
        source=source,
    )

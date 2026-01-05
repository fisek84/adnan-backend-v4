# models/agent_contract.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _extra_allow_config_dict():
    # Pydantic v2: ConfigDict exists; v1: doesn't.
    try:
        from pydantic import ConfigDict  # type: ignore

        return ConfigDict(extra="allow")
    except Exception:
        return None


def _is_pydantic_v2() -> bool:
    return hasattr(BaseModel, "model_validate")


class _AllowExtraBaseModel(BaseModel):
    """
    Pydantic v1/v2 compatible "extra=allow".
    """

    _cfg = _extra_allow_config_dict()
    if _cfg is not None:
        model_config = _cfg  # type: ignore
    else:

        class Config:
            extra = "allow"


class ProposedCommand(_AllowExtraBaseModel):
    """
    "Proposal-only" komanda: chat endpoint je nikad ne izvršava.

    FAZA 5 canon:
      - stable fields:
          command, args(params alias), dry_run, requires_approval, risk, reason
      - optional:
          scope, payload_summary
    """

    command: str = Field(..., description="Kanonski naziv komande/operacije.")

    # Canon: args is the SSOT payload. Input may provide `params` as alias.
    args: Dict[str, Any] = Field(default_factory=dict, description="Argumenti komande.")

    reason: Optional[str] = Field(
        default=None, description="Zašto se predlaže ova komanda."
    )

    dry_run: bool = Field(default=True, description="Uvijek True za /api/chat.")

    requires_approval: bool = Field(
        default=True, description="Da li bi u write toku tražilo approval."
    )

    risk: str = Field(default="LOW", description="LOW/MED/HIGH - heuristika.")

    # Optional canon fields (FAZA 5)
    scope: Optional[str] = Field(
        default=None,
        description="Opcionalni scope (npr. notion/tasks, api_execute_raw).",
    )
    payload_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Opcionalni sažetak payload-a (siguran za log/UX).",
    )

    # ---- normalization guards ----
    if _is_pydantic_v2():
        from pydantic import field_validator, model_validator  # type: ignore

        @model_validator(mode="before")
        @classmethod
        def _normalize_params_alias(cls, data: Any):
            """
            Accept input shape where payload is provided as `params` instead of `args`.
            Canon output uses `args` as SSOT.

            Rules:
              - if args missing/None and params is dict -> args = params
              - if args empty dict and params dict provided -> merge (args wins)
            """
            if not isinstance(data, dict):
                return data

            args = data.get("args")
            params = data.get("params")

            args_dict = args if isinstance(args, dict) else {}
            params_dict = params if isinstance(params, dict) else {}

            if not isinstance(args, dict) and params_dict:
                data["args"] = params_dict
                return data

            if isinstance(args, dict) and not args_dict and params_dict:
                merged = dict(params_dict)
                merged.update(args_dict)  # args wins (though args_dict is empty here)
                data["args"] = merged
                return data

            if args is None:
                data["args"] = {}
            return data

        @field_validator("command", mode="before")
        @classmethod
        def _command_strip_nonempty(cls, v):
            s = "" if v is None else str(v)
            s = s.strip()
            if not s:
                raise ValueError("command must be a non-empty string")
            return s

        @field_validator("args", mode="before")
        @classmethod
        def _args_none_to_dict(cls, v):
            return v or {}

        @field_validator("payload_summary", mode="before")
        @classmethod
        def _payload_summary_none_to_dict_or_none(cls, v):
            if v is None:
                return None
            return v if isinstance(v, dict) else None

        @field_validator("risk", mode="before")
        @classmethod
        def _risk_upper(cls, v):
            if v is None:
                return "LOW"
            return str(v).strip().upper() or "LOW"

        @field_validator("dry_run", mode="before")
        @classmethod
        def _dry_run_hard_true(cls, v):
            return True
    else:
        from pydantic import root_validator, validator  # type: ignore

        @root_validator(pre=True)
        def _normalize_params_alias(cls, values):
            if not isinstance(values, dict):
                return values

            args = values.get("args")
            params = values.get("params")

            args_dict = args if isinstance(args, dict) else {}
            params_dict = params if isinstance(params, dict) else {}

            if not isinstance(args, dict) and params_dict:
                values["args"] = params_dict
                return values

            if isinstance(args, dict) and not args_dict and params_dict:
                merged = dict(params_dict)
                merged.update(args_dict)  # args wins (though args_dict is empty here)
                values["args"] = merged
                return values

            if args is None:
                values["args"] = {}
            return values

        @validator("command", pre=True, always=True)
        def _command_strip_nonempty(cls, v):
            s = "" if v is None else str(v)
            s = s.strip()
            if not s:
                raise ValueError("command must be a non-empty string")
            return s

        @validator("args", pre=True, always=True)
        def _args_none_to_dict(cls, v):
            return v or {}

        @validator("payload_summary", pre=True, always=True)
        def _payload_summary_none_to_dict_or_none(cls, v):
            if v is None:
                return None
            return v if isinstance(v, dict) else None

        @validator("risk", pre=True, always=True)
        def _risk_upper(cls, v):
            if v is None:
                return "LOW"
            return str(v).strip().upper() or "LOW"

        @validator("dry_run", pre=True, always=True)
        def _dry_run_hard_true(cls, v):
            return True


class AgentInput(_AllowExtraBaseModel):
    """
    Minimalni input za agent layer.
    identity_pack + snapshot dolaze iz CANON-a; ovdje ih tretiramo kao opaque dict.
    """

    message: str = Field(..., description="User poruka.")
    identity_pack: Dict[str, Any] = Field(default_factory=dict)
    snapshot: Dict[str, Any] = Field(default_factory=dict)

    conversation_id: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = None

    preferred_agent_id: Optional[str] = Field(
        default=None, description="Opcionalno: klijent može eksplicitno tražiti agenta."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Normalize incoming nulls from clients
    if _is_pydantic_v2():
        from pydantic import field_validator  # type: ignore

        @field_validator("message", mode="before")
        @classmethod
        def _message_any_to_str(cls, v):
            # Allow null/number/object from clients; normalize deterministically.
            if v is None:
                return ""
            if isinstance(v, str):
                return v
            return str(v)

        @field_validator("identity_pack", mode="before")
        @classmethod
        def _idpack_none_to_dict(cls, v):
            return v or {}

        @field_validator("snapshot", mode="before")
        @classmethod
        def _snapshot_none_to_dict(cls, v):
            return v or {}

        @field_validator("metadata", mode="before")
        @classmethod
        def _metadata_none_to_dict(cls, v):
            return v or {}
    else:
        from pydantic import validator  # type: ignore

        @validator("message", pre=True, always=True)
        def _message_any_to_str(cls, v):
            if v is None:
                return ""
            if isinstance(v, str):
                return v
            return str(v)

        @validator("identity_pack", pre=True, always=True)
        def _idpack_none_to_dict(cls, v):
            return v or {}

        @validator("snapshot", pre=True, always=True)
        def _snapshot_none_to_dict(cls, v):
            return v or {}

        @validator("metadata", pre=True, always=True)
        def _metadata_none_to_dict(cls, v):
            return v or {}


class AgentOutput(_AllowExtraBaseModel):
    """
    Standardni izlaz svih agenata.
    """

    text: str = Field(..., description="Primarni text odgovor.")
    proposed_commands: List[ProposedCommand] = Field(default_factory=list)

    agent_id: str = Field(..., description="ID agenta iz registry-ja.")
    read_only: bool = Field(default=True, description="Za /api/chat uvijek True.")
    trace: Dict[str, Any] = Field(
        default_factory=dict, description="Trace metadata (routing, scoring, itd.)."
    )

    # Defense-in-depth: read_only must never be false in this contract.
    if _is_pydantic_v2():
        from pydantic import field_validator  # type: ignore

        @field_validator("read_only", mode="before")
        @classmethod
        def _read_only_hard_true(cls, v):
            return True

        @field_validator("trace", mode="before")
        @classmethod
        def _trace_none_to_dict(cls, v):
            return v or {}

        @field_validator("proposed_commands", mode="before")
        @classmethod
        def _pcs_none_to_list(cls, v):
            return v or []
    else:
        from pydantic import validator  # type: ignore

        @validator("read_only", pre=True, always=True)
        def _read_only_hard_true(cls, v):
            return True

        @validator("trace", pre=True, always=True)
        def _trace_none_to_dict(cls, v):
            return v or {}

        @validator("proposed_commands", pre=True, always=True)
        def _pcs_none_to_list(cls, v):
            return v or []

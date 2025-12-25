# services/rbac_service.py
# FULL FILE — zamijeni cijeli services/rbac_service.py ovim.

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class RBACService:
    """
    CANONICAL RBAC SERVICE (SSOT for role resolution + basic allow rules)

    Required by PolicyService (observed calls):
    - get_role_for_initiator(...)
    - is_allowed(...)

    Goals:
    - deterministic defaults
    - config override via config/rbac.json or RBAC_CONFIG_JSON env
    - tolerant signatures to avoid brittle coupling
    """

    DEFAULT_ROLE = "user"

    # Minimal canonical allow policy.
    # system/ceo/admin -> allow all
    # user -> allow read-only + a small safe set (customize via config if needed)
    # guest -> deny
    _ALLOW_ALL_ROLES = {"system", "ceo", "admin"}
    _DEFAULT_USER_ALLOW = {
        # keep conservative but enough to run your flow (approval gate still blocks writes first)
        "goal_task_workflow",
        "notion_write",
        "sync_knowledge_snapshot",
        "notion_read",
        "health",
    }

    def __init__(self) -> None:
        self._map: Dict[str, str] = {}
        self._role_actions: Dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------
    # ROLE RESOLUTION
    # ------------------------------------------------------------

    def get_role_for_initiator(self, initiator: str) -> str:
        key = (initiator or "").strip().lower()
        if not key:
            return "guest"

        role = self._map.get(key)
        if isinstance(role, str) and role.strip():
            return role.strip().lower()

        # canonical fallbacks
        if key in ("system",):
            return "system"
        if key in ("ceo", "owner", "founder"):
            return "ceo"
        if key in ("admin", "administrator", "ops"):
            return "admin"

        return self.DEFAULT_ROLE

    # Backward-compatible aliases
    def get_role(self, initiator: str) -> str:
        return self.get_role_for_initiator(initiator)

    def resolve_role(self, initiator: str) -> str:
        return self.get_role_for_initiator(initiator)

    # ------------------------------------------------------------
    # AUTHZ (EXPECTED BY PolicyService)
    # ------------------------------------------------------------

    def is_allowed(self, *args: Any, **kwargs: Any) -> bool:
        """
        Flexible signature to match different calling styles:

        Common patterns:
        - is_allowed(initiator, action)
        - is_allowed(role, action)
        - is_allowed(initiator=..., action=...)
        - is_allowed(role=..., directive=...)

        Returns True/False.
        """
        initiator = kwargs.get("initiator")
        role = kwargs.get("role")
        action = (
            kwargs.get("action") or kwargs.get("directive") or kwargs.get("command")
        )

        # positional fallback
        if len(args) >= 2 and not action:
            # args[1] is action, args[0] is initiator or role
            action = args[1]
            if not role and not initiator:
                first = args[0]
                if isinstance(first, str):
                    # if first looks like a known role -> role, else initiator
                    if first.strip().lower() in {
                        "system",
                        "ceo",
                        "admin",
                        "user",
                        "guest",
                    }:
                        role = first
                    else:
                        initiator = first

        if not isinstance(action, str) or not action.strip():
            # if caller didn't specify action, be safe and deny
            return False

        action_norm = action.strip()

        if isinstance(role, str) and role.strip():
            role_norm = role.strip().lower()
        else:
            role_norm = self.get_role_for_initiator(str(initiator or ""))

        # Allow-all roles
        if role_norm in self._ALLOW_ALL_ROLES:
            return True

        if role_norm == "guest":
            return False

        # If config provides role_actions, honor it
        if self._role_actions:
            return self._is_allowed_by_role_actions(role_norm, action_norm)

        # Default user policy (conservative baseline)
        if role_norm == "user":
            # allow safe actions; approval gate still enforces writes via governance
            return action_norm in self._DEFAULT_USER_ALLOW

        return False

    def is_allowed_for_role(self, role: str, action: str) -> bool:
        return self.is_allowed(role=role, action=action)

    # Optional compat (some codebases call can_request on rbac)
    def can_request(self, initiator: str) -> bool:
        # By default: anything except empty/guest
        role = self.get_role_for_initiator(initiator)
        return role != "guest"

    # ------------------------------------------------------------
    # INTERNAL: CONFIG
    # ------------------------------------------------------------

    def _load(self) -> None:
        """
        Load from:
        1) env RBAC_CONFIG_JSON
        2) config/rbac.json

        Supported JSON shapes:
        A) Simple initiator->role map:
           { "ceo": "ceo", "adnan": "admin" }

        B) Extended:
           {
             "initiators": { "ceo": "ceo", "adnan": "admin" },
             "role_actions": {
               "user": ["notion_write", "goal_task_workflow"],
               "guest": []
             }
           }
        """
        env_json = os.getenv("RBAC_CONFIG_JSON")
        if env_json:
            parsed = self._safe_parse_json(env_json)
            if isinstance(parsed, dict):
                self._apply_config(parsed)
                logger.info("RBACService loaded config from RBAC_CONFIG_JSON env")
                return

        cfg_path = Path("config") / "rbac.json"
        try:
            if cfg_path.exists():
                raw = cfg_path.read_text(encoding="utf-8")
                parsed = self._safe_parse_json(raw)
                if isinstance(parsed, dict):
                    self._apply_config(parsed)
                    logger.info("RBACService loaded config from %s", str(cfg_path))
                    return
        except Exception as e:
            logger.warning("RBACService failed reading config/rbac.json: %s", str(e))

        # defaults
        self._map = {}
        self._role_actions = {}
        logger.info("RBACService using default role resolution/authz (no config found)")

    def _apply_config(self, cfg: Dict[str, Any]) -> None:
        # extended format
        initiators = cfg.get("initiators")
        role_actions = cfg.get("role_actions")

        if isinstance(initiators, dict):
            self._map = self._normalize_map(initiators)
        else:
            # simple format
            self._map = self._normalize_map(cfg)

        if isinstance(role_actions, dict):
            self._role_actions = role_actions
        else:
            self._role_actions = {}

    def _is_allowed_by_role_actions(self, role: str, action: str) -> bool:
        rules = self._role_actions.get(role)

        # If role not found in config, fallback to default behavior
        if rules is None:
            if role == "user":
                return action in self._DEFAULT_USER_ALLOW
            return role in self._ALLOW_ALL_ROLES

        # role_actions can be:
        # - "*" meaning allow all
        # - list of allowed actions
        if rules == "*":
            return True

        if isinstance(rules, list):
            return action in {str(x) for x in rules}

        return False

    @staticmethod
    def _safe_parse_json(text: str) -> Optional[Any]:
        try:
            return json.loads(text)
        except Exception:
            return None

    @staticmethod
    def _normalize_map(obj: Dict[str, Any]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for k, v in obj.items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            kk = k.strip().lower()
            vv = v.strip().lower()
            if kk and vv:
                out[kk] = vv
        return out

# routers/notion_ops_router.py
from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from services.approval_flow import require_approval_or_block
from services.auth.dependencies import require_principal, require_role
from services.auth.principal import Principal

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/notion-ops",
    tags=["Notion Bulk Ops"],
    dependencies=[Depends(require_principal)],
)

NOTION_API_URL = (
    os.getenv("NOTION_API_URL", "https://api.notion.com/v1") or ""
).strip()
NOTION_VERSION = (os.getenv("NOTION_VERSION", "2022-06-28") or "").strip()


# ------------------------------------------------------------
# CANONICAL WRITE GUARDS (ENV + approval_flow)
# ------------------------------------------------------------
def _env_true(name: str, default: str = "false") -> bool:
    return (os.getenv(name, default) or "").strip().lower() == "true"


def _is_test_mode() -> bool:
    return (os.getenv("TESTING") or "").strip() == "1" or (
        "PYTEST_CURRENT_TEST" in os.environ
    )


def _ops_safe_mode_enabled() -> bool:
    if _is_test_mode() and not _env_true("OPS_SAFE_MODE_TESTS", "false"):
        return False
    return _env_true("OPS_SAFE_MODE", "false")


def _ceo_token_enforcement_enabled() -> bool:
    if _is_test_mode() and not _env_true("CEO_TOKEN_ENFORCEMENT_TESTS", "false"):
        return False
    return _env_true("CEO_TOKEN_ENFORCEMENT", "false")


def _is_ceo_request(request: Request) -> bool:
    """
    Check if the request is from a CEO user.
    CEO users are identified by:
    1. Valid X-CEO-Token header (if CEO_TOKEN_ENFORCEMENT is enabled)
    2. metadata.initiator == "ceo_chat" or similar CEO indicators
    """
    # If enforcement is enabled, check for valid token
    if _ceo_token_enforcement_enabled():
        expected = (os.getenv("CEO_APPROVAL_TOKEN", "") or "").strip()
        provided = (request.headers.get("X-CEO-Token") or "").strip()
        if expected and provided == expected:
            return True

    # Check for CEO indicators in request (for non-enforced mode)
    # Headers that indicate CEO context
    initiator = (request.headers.get("X-Initiator") or "").strip().lower()
    if initiator in ("ceo_chat", "ceo_dashboard", "ceo"):
        return True

    return False


def _require_ceo_token_if_enforced(request: Request) -> None:
    """
    Require CEO token if enforcement is enabled.
    This function now returns successfully for CEO requests.
    """
    if not _ceo_token_enforcement_enabled():
        return

    expected = (os.getenv("CEO_APPROVAL_TOKEN", "") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="CEO token enforcement enabled but CEO_APPROVAL_TOKEN is not set",
        )

    provided = (request.headers.get("X-CEO-Token") or "").strip()
    if provided != expected:
        raise HTTPException(status_code=403, detail="CEO token required")


def _guard_write(request: Request, command_type: str) -> None:
    """
    Kombinuje:
    - globalni blok (OPS_SAFE_MODE) - bypassed for CEO users
    - CEO token zaštitu - validated for CEO users
    - approval_flow granularnu kontrolu

    CEO users bypass OPS_SAFE_MODE and approval_flow checks.
    """
    # CEO users bypass all restrictions
    if _is_ceo_request(request):
        # Still validate token if enforcement is enabled
        _require_ceo_token_if_enforced(request)
        return

    # Non-CEO users must pass all checks
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )

    _require_ceo_token_if_enforced(request)

    require_approval_or_block(
        command_id="notion_bulk_write",
        command_type=command_type,
        context={"source": "notion_ops_router"},
    )


# ------------------------------------------------------------
# NOTION HELPERS
# ------------------------------------------------------------
def _notion_token() -> str:
    tok = (os.getenv("NOTION_TOKEN", "") or "").strip()
    if not tok:
        raise HTTPException(status_code=500, detail="NOTION_TOKEN is missing")
    return tok


def _notion_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_notion_token()}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _normalize_db_key(db_key: str) -> str:
    return (db_key or "").strip().lower()


def _env_db_id_for_key(db_key: str) -> Optional[str]:
    """
    db_key -> database_id kroz .env konvencije:
      - NOTION_<KEY>_DATABASE_ID
      - NOTION_<KEY>_DB_ID
    Primjer: db_key="tasks" -> NOTION_TASKS_DATABASE_ID ili NOTION_TASKS_DB_ID
    """
    k = _normalize_db_key(db_key)
    if not k:
        return None

    env1 = f"NOTION_{k.upper()}_DATABASE_ID"
    env2 = f"NOTION_{k.upper()}_DB_ID"

    v = (os.getenv(env1, "") or "").strip()
    if v:
        return v

    v = (os.getenv(env2, "") or "").strip()
    if v:
        return v

    return None


def _discover_all_db_keys_from_env() -> Dict[str, str]:
    """
    Izvuci sve NOTION_*_(DB_ID|DATABASE_ID) varijable kao mapu db_key -> database_id
    Npr: NOTION_TASKS_DB_ID => "tasks": "<id>"

    Opcionalno podržava:
      NOTION_EXTRA_DATABASES_JSON='{"my_db":"<id>","other":"<id>"}'
    """
    out: Dict[str, str] = {}

    for name, value in os.environ.items():
        if not name.startswith("NOTION_"):
            continue
        if not value or not value.strip():
            continue

        if name.endswith("_DATABASE_ID"):
            key = name[len("NOTION_") : -len("_DATABASE_ID")].lower()
            out[key] = value.strip()
        elif name.endswith("_DB_ID"):
            key = name[len("NOTION_") : -len("_DB_ID")].lower()
            # ne pregazi DATABASE_ID ako već postoji
            out.setdefault(key, value.strip())

    extra_json = (os.getenv("NOTION_EXTRA_DATABASES_JSON", "") or "").strip()
    if extra_json:
        try:
            extra = json.loads(extra_json)
            if isinstance(extra, dict):
                for k, v in extra.items():
                    if isinstance(k, str) and isinstance(v, str) and v.strip():
                        out[_normalize_db_key(k)] = v.strip()
        except Exception:
            # ne ruši server ako je env loš
            logger.warning("Invalid NOTION_EXTRA_DATABASES_JSON (ignored).")

    return out


async def _notion_db_query(database_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{NOTION_API_URL}/databases/{database_id}/query"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, headers=_notion_headers(), json=body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Notion request failed: {type(exc).__name__}: {exc}",
        )

    if r.status_code >= 400:
        try:
            j = r.json()
        except Exception:
            j = {"error": r.text}
        raise HTTPException(
            status_code=502,
            detail={"notion_status": r.status_code, "notion_error": j},
        )

    return r.json()


def _pyd_parse(model_cls: Any, obj: Any) -> Any:
    """
    Pydantic v1/v2 kompatibilno parsiranje.
    """
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(obj)
    return model_cls.parse_obj(obj)


# -------------------------------
# MODELI
# -------------------------------
class BulkCreateItem(BaseModel):
    type: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    goal_id: Optional[str] = None


class BulkCreatePayload(BaseModel):
    items: List[BulkCreateItem]


class BulkUpdatePayload(BaseModel):
    updates: List[Dict[str, Any]] = Field(default_factory=list)


class NotionQuerySpec(BaseModel):
    # jedan od ova 2 je potreban
    db_key: Optional[str] = None
    database_id: Optional[str] = None

    # Notion query shape
    filter: Optional[Dict[str, Any]] = None
    sorts: Optional[List[Dict[str, Any]]] = None
    start_cursor: Optional[str] = None
    page_size: Optional[int] = 50


class BulkQueryPayload(BaseModel):
    queries: List[NotionQuerySpec] = Field(default_factory=list)


class NotionOpsTogglePayload(BaseModel):
    """Payload for toggling Notion Ops armed state."""

    # BE-301: retained for backward compatibility, but NOT used for keying.
    session_id: Optional[str] = None
    armed: bool


# -------------------------------
# RUTE
# -------------------------------
@router.post("/toggle")
async def toggle_notion_ops(
    request: Request,
    payload: NotionOpsTogglePayload,
    principal: Principal = Depends(require_role("admin", "ceo")),
) -> Dict[str, Any]:
    """
    Toggle Notion Ops ARMED/DISARMED state for the authenticated principal.

    BE-301:
    - Requires authenticated principal.
    - Requires role admin OR ceo.
    - State is keyed by principal.sub (principal-based), not session_id.
    """
    from services import notion_armed_store

    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def _now_iso() -> str:
        return _utcnow().isoformat()

    def _arm_ttl_seconds() -> int:
        raw = (os.getenv("NOTION_OPS_ARM_TTL_SECONDS", "3600") or "").strip()
        try:
            v = int(raw)
        except Exception:
            v = 3600
        return v if v > 0 else 3600

    # Enterprise safety (optional): when arming, validate Notion is configured and reachable.
    # Default is OFF to preserve local/dev ergonomics and existing tests.
    # Enable by setting NOTION_OPS_PREFLIGHT_REQUIRED=true.
    if bool(payload.armed) is True and _env_true(
        "NOTION_OPS_PREFLIGHT_REQUIRED", "false"
    ):
        from services.notion_service import get_or_init_notion_service

        notion = get_or_init_notion_service()
        if notion is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot ARM Notion Ops: Notion is not configured. "
                    "Set NOTION_API_KEY (or NOTION_TOKEN) and NOTION_GOALS_DB_ID, "
                    "NOTION_TASKS_DB_ID, NOTION_PROJECTS_DB_ID."
                ),
            )

        pre = await notion.preflight_can_write()
        if not isinstance(pre, dict) or not pre.get("ok"):
            raise HTTPException(
                status_code=503,
                detail=f"Cannot ARM Notion Ops: Notion preflight failed: {pre}",
            )

    # Toggle the state
    principal_sub = principal.sub.strip()
    armed = bool(payload.armed)

    now_iso = _now_iso()
    ttl_seconds = _arm_ttl_seconds()
    expires_at = (
        (_utcnow() + timedelta(seconds=ttl_seconds)).isoformat() if armed else None
    )

    state: Dict[str, Any] = {
        "principal_sub": principal_sub,
        "armed": armed,
        "armed_at": now_iso if armed else None,
        "expires_at": expires_at,
        "armed_by_sub": principal_sub,
        "status": "armed" if armed else "disarmed",
        "revoked_at": None if armed else now_iso,
        "last_toggled_at": now_iso,
        "last_prompt": f"Notion ops toggle via API (principal={principal_sub}): {armed}",
    }

    try:
        result = notion_armed_store.set(principal_sub, state)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"notion_armed_store_unavailable:{type(exc).__name__}",
        )

    return {
        "ok": True,
        "principal_sub": principal_sub,
        "armed": result.get("armed"),
        "armed_at": result.get("armed_at"),
        "expires_at": result.get("expires_at"),
        "last_toggled_at": result.get("last_toggled_at"),
    }


@router.get("/databases")
def list_databases() -> Dict[str, Any]:
    """
    Frontend može ovo pozvati da dobije listu dostupnih baza (iz .env),
    da ne hardkodiramo tasks/goals itd.
    """
    dbs = _discover_all_db_keys_from_env()
    return {"ok": True, "read_only": True, "databases": dbs}


@router.post("/bulk/create")
async def bulk_create(
    request: Request,
    payload: BulkCreatePayload,
    principal: Principal = Depends(require_principal),
) -> Dict[str, Any]:
    from services import notion_armed_store

    try:
        st = notion_armed_store.get(principal.sub)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"notion_armed_store_unavailable:{type(exc).__name__}",
        )

    if st.get("armed") is not True:
        raise HTTPException(status_code=403, detail="notion_ops_disarmed")

    _guard_write(request, command_type="create_task")

    if not payload.items:
        return {"created": []}

    created: List[Dict[str, Any]] = []
    for item in payload.items:
        if item.type not in {"goal", "task"}:
            raise HTTPException(
                status_code=400, detail=f"Unsupported type: {item.type}"
            )

        # Stub (ako želiš, kasnije ga spojimo na Notion write)
        created.append(
            {
                "id": str(uuid4()),
                "type": item.type,
                "title": item.title,
                "goal_id": item.goal_id,
            }
        )

    return {"created": created}


@router.post("/bulk/update")
async def bulk_update(
    request: Request,
    payload: BulkUpdatePayload,
    principal: Principal = Depends(require_principal),
) -> Dict[str, Any]:
    from services import notion_armed_store

    try:
        st = notion_armed_store.get(principal.sub)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"notion_armed_store_unavailable:{type(exc).__name__}",
        )

    if st.get("armed") is not True:
        raise HTTPException(status_code=403, detail="notion_ops_disarmed")

    _guard_write(request, command_type="update_task")
    # Stub (ako želiš, kasnije spajamo na Notion update)
    return {"updated": payload.updates}


@router.post("/bulk/query")
async def bulk_query(payload: Any = Body(None)) -> Dict[str, Any]:
    """
    REAL query prema Notionu.

    Podržava dva inputa:

    1) Bulk shape:
      {
        "queries": [
          {"db_key":"tasks", "filter": {...}, "page_size": 5}
        ]
      }

    2) Flat shape (single query):
      {"db_key":"tasks", "filter": {...}, "page_size": 5}

    (Ovo je bitno jer frontend radi "flat retry" kad je tačno 1 query.)
    """
    if payload is None:
        return {"results": []}

    # --- Normalize input to List[NotionQuerySpec] ---
    queries: List[NotionQuerySpec] = []

    if isinstance(payload, dict) and isinstance(payload.get("queries"), list):
        # canonical bulk
        parsed = _pyd_parse(BulkQueryPayload, payload)
        queries = list(parsed.queries or [])
    elif isinstance(payload, dict):
        # flat single query
        q = _pyd_parse(NotionQuerySpec, payload)
        queries = [q]
    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid payload. Expected object or {queries:[...]}",
        )

    if not queries:
        return {"results": []}

    env_map = _discover_all_db_keys_from_env()

    results: List[Dict[str, Any]] = []
    for q in queries:
        db_id = (q.database_id or "").strip() if q.database_id else ""
        db_key_norm = _normalize_db_key(q.db_key or "")

        if not db_id:
            db_id = env_map.get(db_key_norm) or _env_db_id_for_key(db_key_norm) or ""

        if not db_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unknown db_key/database_id. "
                    f"Provided db_key={q.db_key!r}. "
                    f"Add NOTION_{(q.db_key or '').strip().upper()}_DB_ID or _DATABASE_ID to .env, "
                    "or pass database_id."
                ),
            )

        body: Dict[str, Any] = {"page_size": int(q.page_size or 50)}
        if q.filter is not None:
            body["filter"] = q.filter
        if q.sorts is not None:
            body["sorts"] = q.sorts
        if q.start_cursor is not None:
            body["start_cursor"] = q.start_cursor

        notion_resp = await _notion_db_query(db_id, body)

        results.append(
            {
                "db_key": db_key_norm or None,
                "database_id": db_id,
                "notion": notion_resp,
            }
        )

    return {"results": results}

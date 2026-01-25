from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# =========================
# Notion-aligned UI options
# (based on your screenshots)
# =========================

# Goals DB / Weekly Dashboard (Status column options)
GOAL_STATUS_OPTIONS: List[str] = [
    "completed",
    "in_progress",
    "pending",
    "To Do",
    "Not Started",
    "In Progress",
    "Active",
    "Aktivan",
    "Planned",
]

# Tasks DB (Status column options)
TASK_STATUS_OPTIONS: List[str] = [
    "Completed",
    "in_progress",
    "pending",
    "To Do",
    "active",
    "Not Started",
    "In Progress",
]

# Projects DB (Status column options)
PROJECT_STATUS_OPTIONS: List[str] = [
    "Completed",
    "Blocked",
    "Review",
    "In Progress",
    "Planning",
    "Not Started",
]

# KPI weekly (Status column options)
KPI_STATUS_OPTIONS: List[str] = [
    "Planned",
    "Completed",
    "In progress",
]

# Agent Exchange DB (Status column options)
AGENT_EXCHANGE_STATUS_OPTIONS: List[str] = [
    "Needs Review",
    "Error",
    "Completed",
    "In Progress",
    "Waiting",
    "New",
]

# Agent Project DB (Status column options)
AGENT_PROJECT_STATUS_OPTIONS: List[str] = [
    "Not started",
    "Waiting",
    "In progress",
    "Completed",
]

# Priority (you didn't show the dropdown, so keep standard + allow free typing in UI if needed)
PRIORITY_OPTIONS: List[str] = ["High", "Medium", "Low"]


# =========================
# Intent detection helpers
# =========================


def _t(prompt: str) -> str:
    return (prompt or "").strip().lower()


def _is_create_intent(t: str) -> bool:
    return any(k in t for k in ["create", "kreiraj", "napravi", "dodaj", "new"])


def _is_goal_intent(t: str) -> bool:
    return ("goal" in t) or ("cilj" in t)


def _is_task_intent(t: str) -> bool:
    return ("task" in t) or ("zadatak" in t)


def _is_project_intent(t: str) -> bool:
    return (
        ("project" in t) or ("projekat" in t) or ("projekat" in t) or ("projekti" in t)
    )


def _is_kpi_intent(t: str) -> bool:
    return "kpi" in t


def _is_agent_exchange_intent(t: str) -> bool:
    return ("agent exchange" in t) or ("exchange" in t and "agent" in t)


def _is_agent_project_intent(t: str) -> bool:
    return (
        ("agent project" in t)
        or ("agent projekat" in t)
        or ("agent" in t and "project" in t)
    )


def _has_any_token(t: str, tokens: List[str]) -> bool:
    tl = t.lower()
    for tok in tokens:
        if not tok:
            continue
        if tok.lower() in tl:
            return True
    return False


def _has_priority(t: str) -> bool:
    # deterministic: either explicit key word, or a known priority value
    if ("priority" in t) or ("prioritet" in t):
        return True
    return _has_any_token(t, PRIORITY_OPTIONS + ["visok", "srednji", "nizak"])


def _status_options_for(intent_type: str) -> List[str]:
    if intent_type == "goal_create":
        return list(GOAL_STATUS_OPTIONS)
    if intent_type == "task_create":
        return list(TASK_STATUS_OPTIONS)
    if intent_type == "project_create":
        return list(PROJECT_STATUS_OPTIONS)
    if intent_type == "kpi_create":
        return list(KPI_STATUS_OPTIONS)
    if intent_type == "agent_exchange_create":
        return list(AGENT_EXCHANGE_STATUS_OPTIONS)
    if intent_type == "agent_project_create":
        return list(AGENT_PROJECT_STATUS_OPTIONS)
    return []


def _has_status(t: str, intent_type: str) -> bool:
    # deterministic: either explicit key word, or a known status value from that DB
    if "status" in t:
        return True
    opts = _status_options_for(intent_type)
    return _has_any_token(t, opts)


# =========================
# Main contract builder
# =========================


def detect_write_create_review_contract(
    prompt: str,
) -> Tuple[bool, str, List[str], Dict[str, Any]]:
    """
    Deterministic UI review contract builder (NO trace, NO LLM, NO Notion calls).

    Returns:
      (is_supported, intent_type, missing_fields, fields_schema)

    intent_type values:
      - goal_create
      - task_create
      - project_create
      - kpi_create
      - agent_exchange_create
      - agent_project_create

    Contract rule:
      - If is_supported=True, fields_schema MUST be non-empty (modal never blank).
      - missing_fields must be keys that exist in fields_schema.
    """
    t = _t(prompt)
    if not t:
        return (False, "", [], {})

    if not _is_create_intent(t):
        return (False, "", [], {})

    # Determine best intent_type
    if _is_goal_intent(t):
        intent_type = "goal_create"
    elif _is_task_intent(t):
        intent_type = "task_create"
    elif _is_project_intent(t):
        intent_type = "project_create"
    elif _is_kpi_intent(t):
        intent_type = "kpi_create"
    elif _is_agent_exchange_intent(t):
        intent_type = "agent_exchange_create"
    elif _is_agent_project_intent(t):
        intent_type = "agent_project_create"
    else:
        # generic create in Notion (unknown DB from prompt)
        intent_type = "generic_create"

    # Build schema (MUST be non-empty if supported)
    if intent_type == "generic_create":
        # Fallback: always provide editable fields so UI never blank
        fields_schema: Dict[str, Any] = {
            "Status": {
                "type": "text",
                "required": False,
                "placeholder": "Unesi status (npr. Not Started / In Progress / Completed)",
            },
            "Priority": {
                "type": "text",
                "required": False,
                "placeholder": "Unesi prioritet (npr. High/Medium/Low)",
            },
        }
        return (True, intent_type, [], fields_schema)

    status_options = _status_options_for(intent_type)

    fields_schema = {
        "Status": {"type": "select", "required": True, "options": list(status_options)},
        "Priority": {
            "type": "select",
            "required": True,
            "options": list(PRIORITY_OPTIONS),
        },
    }

    # Extra fields per DB (for "Show all fields" in UI)
    if intent_type == "task_create":
        fields_schema.update(
            {
                "Due Date": {
                    "type": "text",
                    "required": False,
                    "placeholder": "YYYY-MM-DD",
                },
                "Goal": {
                    "type": "text",
                    "required": False,
                    "placeholder": "Naziv cilja / link",
                },
                "Assigned To": {
                    "type": "text",
                    "required": False,
                    "placeholder": "npr. Adnan",
                },
                "AI Agent": {
                    "type": "text",
                    "required": False,
                    "placeholder": "npr. CEO / Ops / Sales",
                },
                "Agent Notes": {
                    "type": "text",
                    "required": False,
                    "placeholder": "kratka napomena",
                },
            }
        )
    elif intent_type == "goal_create":
        fields_schema.update(
            {
                "Deadline": {
                    "type": "text",
                    "required": False,
                    "placeholder": "YYYY-MM-DD",
                },
                "Assigned To": {
                    "type": "text",
                    "required": False,
                    "placeholder": "npr. Adnan",
                },
                "Level": {
                    "type": "text",
                    "required": False,
                    "placeholder": "npr. 30-Day / 90-Day",
                },
                "Parent Goal": {
                    "type": "text",
                    "required": False,
                    "placeholder": "Naziv parent goal",
                },
                "Outcome": {
                    "type": "text",
                    "required": False,
                    "placeholder": "Očekivani rezultat",
                },
                "Description": {
                    "type": "text",
                    "required": False,
                    "placeholder": "kratki opis",
                },
            }
        )
    elif intent_type == "project_create":
        fields_schema.update(
            {
                "Category": {
                    "type": "text",
                    "required": False,
                    "placeholder": "npr. Product / Ops / Sales",
                },
                "Start Date": {
                    "type": "text",
                    "required": False,
                    "placeholder": "YYYY-MM-DD",
                },
                "Target Deadline": {
                    "type": "text",
                    "required": False,
                    "placeholder": "YYYY-MM-DD",
                },
                "Progress": {
                    "type": "text",
                    "required": False,
                    "placeholder": "npr. 0-100",
                },
                "CEO Notes": {
                    "type": "text",
                    "required": False,
                    "placeholder": "kratka napomena",
                },
            }
        )
    elif intent_type == "kpi_create":
        fields_schema.update(
            {
                "KPI Type": {
                    "type": "text",
                    "required": False,
                    "placeholder": "npr. LeadInflow / RevenueMomentum",
                },
                "Review": {
                    "type": "text",
                    "required": False,
                    "placeholder": "kratki review",
                },
            }
        )
    elif intent_type == "agent_exchange_create":
        fields_schema.update(
            {
                "Sender": {
                    "type": "text",
                    "required": False,
                    "placeholder": "npr. CFO Agent",
                },
                "Recipient": {
                    "type": "text",
                    "required": False,
                    "placeholder": "npr. CEO Agent",
                },
                "Project": {
                    "type": "text",
                    "required": False,
                    "placeholder": "npr. Adnan.ai",
                },
                "Department Stage": {
                    "type": "text",
                    "required": False,
                    "placeholder": "npr. Ops / Sales",
                },
                "Content": {
                    "type": "text",
                    "required": False,
                    "placeholder": "kratki sadržaj",
                },
            }
        )
    elif intent_type == "agent_project_create":
        fields_schema.update(
            {
                "Start Date": {
                    "type": "text",
                    "required": False,
                    "placeholder": "YYYY-MM-DD",
                },
                "Due Date": {
                    "type": "text",
                    "required": False,
                    "placeholder": "YYYY-MM-DD",
                },
                "Pipeline Flow": {
                    "type": "text",
                    "required": False,
                    "placeholder": "npr. Discovery → Build → Ship",
                },
            }
        )

    # Missing fields (deterministic)
    missing: List[str] = []
    if not _has_status(t, intent_type):
        missing.append("Status")
    if not _has_priority(t):
        missing.append("Priority")

    return (True, intent_type, missing, fields_schema)


def detect_goal_create_missing_fields(
    prompt: str,
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """
    Backwards-compatible wrapper:
      (is_goal_create_intent, missing_fields, fields_schema)
    """
    ok, intent_type, missing, schema = detect_write_create_review_contract(prompt)
    if not ok or intent_type != "goal_create":
        return (False, [], {})
    return (True, missing, schema)


# PHASE 1: Batch Plan Canon
def build_batch_plan_review_v1(
    *,
    prompt_text: str,
    review_fields_schema: Any,
    review_missing_fields: Any,
) -> Optional[Dict[str, Any]]:
    """
    PHASE 1 (CANON only):
    - Prepoznaje samo batch test-case: "Kreiraj 1 cilj + 5 taskova: X"
    - Vraća {"plan": {"operations":[...]} , "mode": "fill_missing"/"approve"}
    - Ne radi Notion write, ne oslanja se na LLM, ne mijenja postojeći flow.
    """

    text = (prompt_text or "").strip()
    if not text:
        return None

    t = text.lower()

    # Minimalna heuristika (dozvoljeno u fazi 1)
    looks_like_batch = ("1 cilj" in t or "jedan cilj" in t) and (
        "5 task" in t or "5 zadat" in t or "pet task" in t or "pet zadat" in t
    )
    if not looks_like_batch:
        return None

    topic = text.split(":", 1)[1].strip() if ":" in text else text
    if not topic:
        topic = text

    # Uskladi task schema sa postojećim gateway review contract patternom:
    # baseline pokazuje required: Status, Priority (camelcase nije dozvoljen).
    fs = review_fields_schema if isinstance(review_fields_schema, dict) else {}
    task_fields_schema = (
        fs
        if fs
        else {
            "Status": {
                "type": "select",
                "required": True,
                "options": ["To Do", "In Progress", "Completed"],
            },
            "Priority": {
                "type": "select",
                "required": True,
                "options": ["High", "Medium", "Low"],
            },
        }
    )

    # Batch plan: 1 goal + 5 tasks
    goal_op_id = "op_goal_1"
    operations: List[Dict[str, Any]] = []

    # Goal op (minimal payload: title)
    goal_fields_schema = {
        "Title": {"type": "text", "required": True, "placeholder": "Naziv cilja"}
    }
    goal_payload = {"Title": topic}
    goal_missing: List[str] = []
    if (
        not isinstance(goal_payload.get("Title"), str)
        or not goal_payload["Title"].strip()
    ):
        goal_missing.append("Title")

    operations.append(
        {
            "op_id": goal_op_id,
            "intent": "create",
            "target": "goal",
            "payload": goal_payload,
            "fields_schema": goal_fields_schema,
            "missing_fields": goal_missing,
            "defaults_applied": {},
        }
    )

    # Task ops: zadržavamo fill_missing (Status/Priority nisu u payload),
    # ali eksplicitno prikazujemo šta bi sistem default-ovao kroz defaults_applied.
    for i in range(1, 6):
        defaults_applied = {
            "Status": "To Do",
            "Priority": "Medium",
        }

        payload = {
            "Title": f"Task {i}: {topic}",
            "Parent Goal": topic,  # veza (tekstualna) bez Notion linkova u fazi 1
        }

        missing: List[str] = []
        if not isinstance(payload.get("Title"), str) or not payload["Title"].strip():
            missing.append("Title")

        # Required po kanonu za task: Status + Priority (iz postojeće review šeme)
        required_from_schema: List[str] = []
        for k, v in task_fields_schema.items():
            if isinstance(k, str) and isinstance(v, dict) and v.get("required") is True:
                required_from_schema.append(k)

        for req_key in required_from_schema:
            if req_key not in payload:
                missing.append(req_key)

        operations.append(
            {
                "op_id": f"op_task_{i}",
                "intent": "create",
                "target": "task",
                "payload": payload,
                "fields_schema": task_fields_schema,
                "missing_fields": missing,
                "defaults_applied": defaults_applied,
            }
        )

    mode = (
        "fill_missing"
        if any(
            isinstance(op.get("missing_fields"), list) and len(op["missing_fields"]) > 0
            for op in operations
        )
        else "approve"
    )

    return {
        "plan": {"operations": operations},
        "mode": mode,
    }


# PHASE 2: Batch Plan Parser V2
def build_batch_plan_review_v2(
    *,
    prompt_text: str,
    review_fields_schema: Any,
    review_missing_fields: Any,
) -> Optional[Dict[str, Any]]:
    """
    PHASE 2:
    - Deterministički, rule-based parser za format:
      goal '...' + status/prioritet/rok + taskova: 'T1' (...), 'T2' (...)
    - Vraća {"plan":{"operations":[...]}, "mode":"fill_missing"/"approve"} ili None ako nije V2 format.
    """
    import re
    from datetime import datetime, timedelta

    text = (prompt_text or "").strip()
    if not text:
        return None

    # --- helpers (deterministički) ---
    def _norm(s: str) -> str:
        return (s or "").strip()

    def _pick_first_quoted(s: str) -> Optional[str]:
        m = re.search(r"['\"]([^'\"]+)['\"]", s)
        return _norm(m.group(1)) if m else None

    def _parse_status(raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        r = raw.strip().lower()
        if r in ["to do", "todo", "not started", "pending", "planirano", "planned"]:
            return "To Do"
        if r in [
            "in progress",
            "inprogress",
            "u toku",
            "progress",
            "aktivno",
            "active",
            "aktivan",
        ]:
            return "In Progress"
        if r in [
            "done",
            "completed",
            "završeno",
            "zavrseno",
            "gotovo",
            "finish",
            "finished",
        ]:
            return "Completed"
        return raw.strip()

    def _parse_priority(raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        r = raw.strip().lower()
        if r in ["high", "visok"]:
            return "High"
        if r in ["medium", "srednji"]:
            return "Medium"
        if r in ["low", "nizak"]:
            return "Low"
        return raw.strip()

    def _parse_deadline(raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        r = raw.strip().lower()

        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", raw)
        if m:
            return m.group(1)

        m2 = re.search(r"\brok\s+(\d{1,4})\s+dana\b", r)
        if m2:
            days = int(m2.group(1))
            return (datetime.utcnow().date() + timedelta(days=days)).strftime(
                "%Y-%m-%d"
            )

        return None

    def _required_keys_from_schema(fs: Dict[str, Any]) -> List[str]:
        req: List[str] = []
        for k, v in fs.items():
            if isinstance(k, str) and isinstance(v, dict) and v.get("required") is True:
                req.append(k)
        return req

    # ✅ FIX: bez \b oko taskova:/zadataka:/tasks:
    split_pat = r"(\d+\s+)?(taskova:|zadataka:|tasks:)"

    split_m = re.search(split_pat, text, flags=re.IGNORECASE)
    if not split_m:
        return None

    pre_tasks = text[: split_m.start()]
    if not re.search(r"['\"][^'\"]+['\"]", pre_tasks):
        return None

    goal_part = text[: split_m.start()]
    tasks_part = text[split_m.end(0) :]  # cijeli match (npr "5 taskova:")

    goal_title = _pick_first_quoted(goal_part)
    if not goal_title:
        return None

    # goal-level fields
    goal_status = None
    goal_priority = None
    goal_deadline = None

    mgs = re.search(
        r"statusom?\s+([A-Za-z\s]+?)(?:,|\s+i\s+|\.|$)", goal_part, flags=re.IGNORECASE
    )
    if mgs:
        goal_status = _parse_status(mgs.group(1))

    mgp = re.search(
        r"prioritetom?\s+([A-Za-z\s]+?)(?:,|\s+i\s+|\.|$)",
        goal_part,
        flags=re.IGNORECASE,
    )
    if mgp:
        goal_priority = _parse_priority(mgp.group(1))

    mgd = re.search(
        r"(rokom?\s+([^\.]+)|do\s+(\d{4}-\d{2}-\d{2})|rok\s+\d{1,4}\s+dana)",
        goal_part,
        flags=re.IGNORECASE,
    )
    if mgd:
        goal_deadline = _parse_deadline(mgd.group(0))

    # tasks parse
    task_items: List[Dict[str, Any]] = []
    for m in re.finditer(r"['\"]([^'\"]+)['\"]\s*(\(([^)]*)\))?", tasks_part):
        t_title = _norm(m.group(1))
        meta = m.group(3) or ""
        if not t_title:
            continue

        t_status = None
        t_priority = None
        t_deadline = None

        ms = re.search(r"status\s+([A-Za-z\s]+?)(?:,|$)", meta, flags=re.IGNORECASE)
        if ms:
            t_status = _parse_status(ms.group(1))

        mp = re.search(r"prioritet\s+([A-Za-z\s]+?)(?:,|$)", meta, flags=re.IGNORECASE)
        if mp:
            t_priority = _parse_priority(mp.group(1))

        md = re.search(
            r"(do\s+\d{4}-\d{2}-\d{2}|rok\s+\d{1,4}\s+dana|\b\d{4}-\d{2}-\d{2}\b)",
            meta,
            flags=re.IGNORECASE,
        )
        if md:
            t_deadline = _parse_deadline(md.group(0))

        task_items.append(
            {
                "Title": t_title,
                "Status": t_status,
                "Priority": t_priority,
                "Deadline": t_deadline,
            }
        )

    # debug
    if isinstance(review_fields_schema, dict):
        review_fields_schema.setdefault("__debug", {})
        if isinstance(review_fields_schema.get("__debug"), dict):
            review_fields_schema["__debug"]["v2_task_items_count"] = len(task_items)
            review_fields_schema["__debug"]["v2_tasks_part_preview"] = tasks_part[:200]

    if len(task_items) == 0:
        return None

    fs = review_fields_schema if isinstance(review_fields_schema, dict) else {}

    goal_fields_schema: Dict[str, Any] = {
        "Title": {"type": "text", "required": True, "placeholder": "Naziv cilja"}
    }
    for k in ["Status", "Priority", "Deadline"]:
        if k in fs and isinstance(fs.get(k), dict):
            goal_fields_schema[k] = fs[k]

    task_fields_schema = (
        fs
        if fs
        else {
            "Status": {
                "type": "select",
                "required": True,
                "options": ["To Do", "In Progress", "Completed"],
            },
            "Priority": {
                "type": "select",
                "required": True,
                "options": ["High", "Medium", "Low"],
            },
        }
    )

    operations: List[Dict[str, Any]] = []

    goal_payload: Dict[str, Any] = {"Title": goal_title}
    if goal_status:
        goal_payload["Status"] = goal_status
    if goal_priority:
        goal_payload["Priority"] = goal_priority
    if goal_deadline:
        goal_payload["Deadline"] = goal_deadline

    goal_missing: List[str] = []
    if (
        not isinstance(goal_payload.get("Title"), str)
        or not goal_payload["Title"].strip()
    ):
        goal_missing.append("Title")
    for req_key in _required_keys_from_schema(goal_fields_schema):
        if req_key not in goal_payload:
            goal_missing.append(req_key)

    operations.append(
        {
            "op_id": "op_goal_1",
            "intent": "create",
            "target": "goal",
            "payload": goal_payload,
            "fields_schema": goal_fields_schema,
            "missing_fields": goal_missing,
            "defaults_applied": {},
        }
    )

    req_task_keys = _required_keys_from_schema(task_fields_schema)
    for idx, ti in enumerate(task_items, start=1):
        payload: Dict[str, Any] = {"Title": ti["Title"], "Parent Goal": goal_title}
        if ti.get("Status"):
            payload["Status"] = ti["Status"]
        if ti.get("Priority"):
            payload["Priority"] = ti["Priority"]
        if ti.get("Deadline"):
            payload["Deadline"] = ti["Deadline"]

        missing: List[str] = []
        if not isinstance(payload.get("Title"), str) or not payload["Title"].strip():
            missing.append("Title")
        for req_key in req_task_keys:
            if req_key not in payload:
                missing.append(req_key)

        operations.append(
            {
                "op_id": f"op_task_{idx}",
                "intent": "create",
                "target": "task",
                "payload": payload,
                "fields_schema": task_fields_schema,
                "missing_fields": missing,
                "defaults_applied": {},
            }
        )

    mode = (
        "fill_missing"
        if any(
            isinstance(op.get("missing_fields"), list) and len(op["missing_fields"]) > 0
            for op in operations
        )
        else "approve"
    )

    return {"plan": {"operations": operations}, "mode": mode}

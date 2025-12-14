from typing import Dict, Any, List
import asyncio
import time
import uuid
from datetime import datetime

from services.agent_router.agent_router import AgentRouter


class ActionExecutionService:
    """
    Execution Engine (FAZA 11 → 19)

    KANONSKI REŽIM:
    - Backend NE izvršava akcije
    - Backend radi: RBAC, policy, approval, audit
    - Izvršenje ide ISKLJUČIVO preko agenata
    """

    def __init__(self):
        self.agent_router = AgentRouter()

    # ============================================================
    # FAZA 19 — RBAC
    # ============================================================
    def _rbac_check(self, directive: str, params: Dict[str, Any]) -> Dict[str, Any]:
        role = params.get("role", "user")

        ROLE_MATRIX = {
            "user": {
                "allowed": {
                    "create_page",
                    "query_database",
                }
            },
            "manager": {
                "allowed": {
                    "create_page",
                    "query_database",
                    "update_database_entry",
                }
            },
            "admin": {
                "allowed": "*",
            },
        }

        role_policy = ROLE_MATRIX.get(role)

        if not role_policy:
            return {"allowed": False, "reason": "unknown_role"}

        allowed = role_policy["allowed"]

        if allowed == "*" or directive in allowed:
            return {"allowed": True}

        return {"allowed": False, "reason": "role_not_permitted"}

    # ============================================================
    # FAZA 16 — POLICY ENGINE
    # ============================================================
    def _policy_check(self, directive: str) -> Dict[str, Any]:
        MULTI_LEVEL_POLICIES = {
            "delete_page": ["owner", "admin"],
            "update_database_entry": ["manager", "admin"],
        }

        if directive in MULTI_LEVEL_POLICIES:
            return {
                "allowed": False,
                "requires_approval": True,
                "approval_levels": MULTI_LEVEL_POLICIES[directive],
            }

        return {"allowed": True}

    # ============================================================
    # FAZA 18 — MULTI LEVEL APPROVAL CHECK
    # ============================================================
    def _approval_check(
        self, policy: Dict[str, Any], params: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not policy.get("requires_approval"):
            return {"approved": True}

        approval_id = params.get("approval_id") or str(uuid.uuid4())
        approved_levels: List[str] = params.get("approved_levels", [])
        required_levels: List[str] = policy.get("approval_levels", [])

        if approved_levels != required_levels:
            next_level = required_levels[len(approved_levels)]
            return {
                "approved": False,
                "requires_approval": True,
                "approval_id": approval_id,
                "next_level": next_level,
                "approved_levels": approved_levels,
                "required_levels": required_levels,
            }

        return {
            "approved": True,
            "approval_id": approval_id,
            "approved_levels": approved_levels,
        }

    # ============================================================
    # FAZA 15 — AUDIT
    # ============================================================
    def _record_audit(self, record: Dict[str, Any]) -> None:
        try:
            from services.memory_service import MemoryService

            mem = MemoryService()
            mem.store_decision_outcome(
                decision_type="audit",
                context_type="execution",
                target=record.get("directive"),
                success=record.get("executed", False),
                metadata=record,
            )
        except Exception:
            pass

    # ============================================================
    # PUBLIC EXECUTION (AGENT ONLY)
    # ============================================================
    def execute(self, directive: str, params: Dict[str, Any]) -> Dict[str, Any]:
        trace_id = str(uuid.uuid4())
        started_at = datetime.utcnow().isoformat()
        start_ts = time.time()

        base_trace = {
            "trace_id": trace_id,
            "started_at": started_at,
        }

        params = params or {}

        # -------------------------------
        # 1. VALIDACIJA
        # -------------------------------
        if not directive:
            result = {
                "executed": False,
                "confirmed": False,
                "error": "missing_directive",
                "trace": base_trace,
            }
            self._record_audit(result)
            return result

        # -------------------------------
        # 2. RBAC CHECK
        # -------------------------------
        rbac = self._rbac_check(directive, params)

        if not rbac.get("allowed"):
            result = {
                "executed": False,
                "confirmed": False,
                "execution_type": "blocked",
                "directive": directive,
                "error": rbac.get("reason"),
                "trace": {
                    **base_trace,
                    "finished_at": datetime.utcnow().isoformat(),
                    "latency_ms": int((time.time() - start_ts) * 1000),
                    "outcome": "blocked",
                },
            }
            self._record_audit(result)
            return result

        # -------------------------------
        # 3. POLICY + APPROVAL
        # -------------------------------
        policy = self._policy_check(directive)

        if not policy.get("allowed"):
            approval = self._approval_check(policy, params)

            if not approval.get("approved"):
                result = {
                    "executed": False,
                    "confirmed": False,
                    "execution_type": "blocked",
                    "directive": directive,
                    "requires_approval": True,
                    "approval_id": approval["approval_id"],
                    "next_approval_level": approval["next_level"],
                    "approved_levels": approval["approved_levels"],
                    "required_levels": approval["required_levels"],
                    "trace": {
                        **base_trace,
                        "finished_at": datetime.utcnow().isoformat(),
                        "latency_ms": int((time.time() - start_ts) * 1000),
                        "outcome": "blocked",
                    },
                }
                self._record_audit(result)
                return result

        # -------------------------------
        # 4. AGENT ROUTE + EXECUTION
        # -------------------------------
        route = self.agent_router.route({"command": directive})

        if not route.get("endpoint"):
            result = {
                "executed": False,
                "confirmed": False,
                "execution_type": "agent",
                "directive": directive,
                "error": "no_matching_agent",
                "trace": {
                    **base_trace,
                    "finished_at": datetime.utcnow().isoformat(),
                    "latency_ms": int((time.time() - start_ts) * 1000),
                    "outcome": "failed",
                },
            }
            self._record_audit(result)
            return result

        agent_name = route.get("agent")

        try:
            agent_result = asyncio.run(
                self.agent_router.execute({"command": directive, **params})
            )
        except RuntimeError:
            agent_result = asyncio.get_event_loop().run_until_complete(
                self.agent_router.execute({"command": directive, **params})
            )

        if not agent_result.get("success"):
            result = {
                "executed": False,
                "confirmed": False,
                "execution_type": "agent",
                "directive": directive,
                "error": "agent_execution_failed",
                "agent_result": agent_result,
                "trace": {
                    **base_trace,
                    "agent": agent_name,
                    "finished_at": datetime.utcnow().isoformat(),
                    "latency_ms": int((time.time() - start_ts) * 1000),
                    "outcome": "failed",
                },
            }
            self._record_audit(result)
            return result

        # -------------------------------
        # 5. SUCCESS
        # -------------------------------
        result = {
            "executed": True,
            "confirmed": True,
            "execution_type": "agent",
            "directive": directive,
            "params": params,
            "agent_result": agent_result,
            "trace": {
                **base_trace,
                "agent": agent_name,
                "finished_at": datetime.utcnow().isoformat(),
                "latency_ms": int((time.time() - start_ts) * 1000),
                "outcome": "success",
            },
        }

        self._record_audit(result)
        return result

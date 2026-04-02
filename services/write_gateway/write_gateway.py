from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Literal

from services.execution_governance_service import ExecutionGovernanceService
from services.memory_service import MemoryService
from services.audit_log_service import AuditEvent, get_audit_log_service
from services.approval_state_service import get_approval_state


WriteStatus = Literal[
    "accepted",  # request_write ok (token izdan)
    "requires_approval",  # governance traži approval
    "rejected",  # governance deny
    "applied",  # commit_write izvršen
    "replayed",  # idempotency replay
    "failed",  # commit_write failed
    "invalid_token",  # commit token ne postoji/istekao
]


@dataclass(frozen=True)
class PolicyDecision:
    decision: Literal["allow", "deny", "requires_approval"]
    reason: str = ""
    approval_payload: Optional[Dict[str, Any]] = None
    approval_id: Optional[str] = None


@dataclass
class WriteEnvelope:
    command: str
    actor_id: str
    resource: str
    payload: Dict[str, Any]

    task_id: Optional[str] = None
    execution_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    scope: Optional[Dict[str, str]] = None  # npr {"type":"execution","id":"..."}
    metadata: Optional[Dict[str, Any]] = None
    approval_id: Optional[str] = None

    write_id: Optional[str] = None
    created_at_unix: Optional[float] = None


@dataclass
class WriteResult:
    success: bool
    status: WriteStatus
    write_id: str
    reason: Optional[str] = None

    idempotency_key: Optional[str] = None
    task_id: Optional[str] = None
    execution_id: Optional[str] = None

    audit_id: Optional[str] = None
    approval_id: Optional[str] = None

    data: Optional[Dict[str, Any]] = None


@dataclass
class _IdempotencyRecord:
    status: Literal["processing", "succeeded", "failed"]
    result: Optional[WriteResult]
    updated_at_unix: float


class InMemoryIdempotencyStore:
    """
    Level 1 idempotency: in-memory. Determinističan replay.
    """

    def __init__(self) -> None:
        self._records: Dict[str, _IdempotencyRecord] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[_IdempotencyRecord]:
        async with self._lock:
            return self._records.get(key)

    async def set_processing(self, key: str) -> None:
        async with self._lock:
            self._records[key] = _IdempotencyRecord(
                status="processing",
                result=None,
                updated_at_unix=time.time(),
            )

    async def set_result(self, key: str, result: WriteResult, succeeded: bool) -> None:
        async with self._lock:
            self._records[key] = _IdempotencyRecord(
                status="succeeded" if succeeded else "failed",
                result=result,
                updated_at_unix=time.time(),
            )


HandlerFn = Callable[[WriteEnvelope], Awaitable[Dict[str, Any]]]


async def _default_approval_creator(env: WriteEnvelope, payload: Dict[str, Any]) -> str:
    if not isinstance(getattr(env, "execution_id", None), str) or not env.execution_id:
        raise ValueError("execution_id is required for approval creation")

    payload_summary = payload if isinstance(payload, dict) else {}
    scope = "write_gateway"
    if isinstance(env.scope, dict):
        t = env.scope.get("type")
        if isinstance(t, str) and t.strip():
            scope = t.strip()
    risk_level = "standard"
    rl = payload_summary.get("risk_level") if isinstance(payload_summary, dict) else None
    if isinstance(rl, str) and rl.strip():
        risk_level = rl.strip()

    approval = get_approval_state().create(
        command=env.command,
        payload_summary=payload_summary,
        scope=scope,
        risk_level=risk_level,
        execution_id=env.execution_id,
    )
    approval_id = approval.get("approval_id") if isinstance(approval, dict) else None
    if not isinstance(approval_id, str) or not approval_id.strip():
        raise RuntimeError("approval_creator returned empty approval_id")
    return approval_id.strip()


class WriteGateway:
    """
    SSOT write execution layer (KANON-FIX-003).

    request_write: governance gate + token issuance (no side effects)
    commit_write: side-effect execution + audit + idempotency
    write: convenience = request_write + commit_write (only if accepted)
    """

    def __init__(
        self,
        *,
        idempotency_store: Optional[InMemoryIdempotencyStore] = None,
        token_ttl_seconds: int = 300,
        policy_evaluator: Optional[
            Callable[[WriteEnvelope], Awaitable[PolicyDecision]]
        ] = None,
        audit_emitter: Optional[
            Callable[[str, WriteEnvelope, Dict[str, Any]], Awaitable[Optional[str]]]
        ] = None,
        approval_creator: Callable[[WriteEnvelope, Dict[str, Any]], Awaitable[str]] = _default_approval_creator,
        governance_service: Optional[ExecutionGovernanceService] = None,
        memory_service: Optional[MemoryService] = None,
    ) -> None:
        self._idempotency = idempotency_store or InMemoryIdempotencyStore()
        self._token_ttl = int(token_ttl_seconds)

        self._policy_evaluator = policy_evaluator
        self._audit_emitter = audit_emitter
        if approval_creator is None:
            raise ValueError("approval_creator is required")
        self._approval_creator = approval_creator

        self._governance = governance_service or ExecutionGovernanceService()
        self._memory = memory_service or MemoryService()

        self._handlers: Dict[str, HandlerFn] = {}
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._pending_lock = asyncio.Lock()
        self._audit_lock = asyncio.Lock()

        # Default handler (da demo radi)
        self.register_handler("demo_write", self._demo_handler)

    def register_handler(self, command: str, handler: HandlerFn) -> None:
        self._handlers[command] = handler

    async def request_write(self, command: Dict[str, Any]) -> Dict[str, Any]:
        env = self._normalize_envelope(command)
        env.write_id = env.write_id or str(uuid.uuid4())
        env.created_at_unix = env.created_at_unix or time.time()

        def _audit_request_id() -> str:
            try:
                md = env.metadata if isinstance(env.metadata, dict) else {}
                rid = md.get("request_id") if isinstance(md, dict) else None
                rid = rid.strip() if isinstance(rid, str) and rid.strip() else None
                return rid or str(uuid.uuid4())
            except Exception:
                return str(uuid.uuid4())

        def _audit_roles() -> list[str]:
            try:
                md = env.metadata if isinstance(env.metadata, dict) else {}
                roles = md.get("principal_roles") if isinstance(md, dict) else None
                if isinstance(roles, list):
                    return [str(r).strip() for r in roles if str(r).strip()]
            except Exception:
                pass
            return []

        # KANON: execution_id required
        if not env.execution_id:
            audit_id = await self._emit_audit(
                "WRITE_RECEIVED", env, {"status": "received"}
            )
            await self._emit_audit(
                "WRITE_REJECTED", env, {"reason": "missing_execution_id"}
            )

            # PLAT-502: central audit write blocked.
            try:
                get_audit_log_service().emit(
                    AuditEvent(
                        event_type="write_blocked",
                        request_id=_audit_request_id(),
                        principal_sub=env.actor_id or None,
                        principal_roles=sorted(set(_audit_roles())),
                        route="write_gateway.request_write",
                        result="rejected",
                        approval_id=None,
                        execution_id=None,
                        data={"reason": "missing_execution_id", "command": env.command},
                    )
                )
            except Exception:
                pass
            return WriteResult(
                success=False,
                status="rejected",
                write_id=env.write_id,
                reason="missing_execution_id",
                idempotency_key=env.idempotency_key,
                task_id=env.task_id,
                execution_id=env.execution_id,
                audit_id=audit_id,
            ).__dict__

        # Default idempotency key (ako nije data)
        env.idempotency_key = env.idempotency_key or self._derive_idempotency_key(env)

        # Audit: received
        audit_id = await self._emit_audit("WRITE_RECEIVED", env, {"status": "received"})

        # Policy/governance
        decision = await self._evaluate_policy(env)
        await self._emit_audit(
            "WRITE_POLICY_EVAL",
            env,
            {
                "decision": decision.decision,
                "reason": decision.reason,
                "approval_id": decision.approval_id,
            },
        )

        if decision.decision == "deny":
            await self._emit_audit("WRITE_REJECTED", env, {"reason": decision.reason})

            # PLAT-502: central audit write blocked.
            try:
                get_audit_log_service().emit(
                    AuditEvent(
                        event_type="write_blocked",
                        request_id=_audit_request_id(),
                        principal_sub=env.actor_id or None,
                        principal_roles=sorted(set(_audit_roles())),
                        route="write_gateway.request_write",
                        result="rejected",
                        approval_id=None,
                        execution_id=env.execution_id,
                        data={
                            "reason": decision.reason or "policy_denied",
                            "command": env.command,
                            "resource": env.resource,
                        },
                    )
                )
            except Exception:
                pass
            return WriteResult(
                success=False,
                status="rejected",
                write_id=env.write_id,
                reason=decision.reason or "policy_denied",
                idempotency_key=env.idempotency_key,
                task_id=env.task_id,
                execution_id=env.execution_id,
                audit_id=audit_id,
            ).__dict__

        if decision.decision == "requires_approval":
            approval_id = decision.approval_id or env.approval_id
            if approval_id is None:
                try:
                    approval_id = await self._approval_creator(
                        env, decision.approval_payload or {}
                    )
                except Exception as e:
                    await self._emit_audit(
                        "WRITE_APPROVAL_REQUIRED",
                        env,
                        {
                            "reason": decision.reason,
                            "approval_id": None,
                            "error": f"approval_create_failed:{type(e).__name__}:{str(e)}",
                        },
                    )
                    return WriteResult(
                        success=False,
                        status="failed",
                        write_id=env.write_id,
                        reason="approval_create_failed",
                        idempotency_key=env.idempotency_key,
                        task_id=env.task_id,
                        execution_id=env.execution_id,
                        audit_id=audit_id,
                        approval_id=None,
                    ).__dict__

            if not isinstance(approval_id, str) or not approval_id.strip():
                await self._emit_audit(
                    "WRITE_APPROVAL_REQUIRED",
                    env,
                    {
                        "reason": decision.reason,
                        "approval_id": None,
                        "error": "approval_id_missing_after_create",
                    },
                )
                return WriteResult(
                    success=False,
                    status="failed",
                    write_id=env.write_id,
                    reason="approval_id_missing",
                    idempotency_key=env.idempotency_key,
                    task_id=env.task_id,
                    execution_id=env.execution_id,
                    audit_id=audit_id,
                    approval_id=None,
                ).__dict__

            approval_id = approval_id.strip()
            env.approval_id = approval_id
            await self._emit_audit(
                "WRITE_APPROVAL_REQUIRED",
                env,
                {"reason": decision.reason, "approval_id": approval_id},
            )

            # PLAT-502: central audit write blocked.
            try:
                get_audit_log_service().emit(
                    AuditEvent(
                        event_type="write_blocked",
                        request_id=_audit_request_id(),
                        principal_sub=env.actor_id or None,
                        principal_roles=sorted(set(_audit_roles())),
                        route="write_gateway.request_write",
                        result="requires_approval",
                        approval_id=str(approval_id) if approval_id else None,
                        execution_id=env.execution_id,
                        data={
                            "reason": decision.reason or "approval_required",
                            "command": env.command,
                            "resource": env.resource,
                        },
                    )
                )
            except Exception:
                pass
            return WriteResult(
                success=False,
                status="requires_approval",
                write_id=env.write_id,
                reason=decision.reason or "approval_required",
                idempotency_key=env.idempotency_key,
                task_id=env.task_id,
                execution_id=env.execution_id,
                audit_id=audit_id,
                approval_id=approval_id,
            ).__dict__

        # Allow: issue token
        token = str(uuid.uuid4())
        exp = time.time() + self._token_ttl
        async with self._pending_lock:
            self._pending[token] = {"envelope": env, "exp": exp}

        return {
            "success": True,
            "status": "accepted",
            "write_id": env.write_id,
            "write_token": token,
            "idempotency_key": env.idempotency_key,
            "task_id": env.task_id,
            "execution_id": env.execution_id,
            "audit_id": audit_id,
        }

    async def commit_write(self, write_token: str) -> Dict[str, Any]:
        env = await self._take_token(write_token)
        if env is None:
            return WriteResult(
                success=False,
                status="invalid_token",
                write_id="",
                reason="write_token_not_found_or_expired",
            ).__dict__

        assert env.write_id is not None
        assert env.execution_id is not None
        assert env.idempotency_key is not None

        # BE-402: approval state must be APPROVED before any side-effect dispatch.
        if isinstance(env.approval_id, str) and env.approval_id.strip():
            from services.approval_flow import ApprovalStatus, check_approval

            st = check_approval(
                command_id=env.execution_id,
                command_type=env.command,
                context={"approval_id": env.approval_id},
            )

            if st == ApprovalStatus.APPROVED:
                pass
            elif st == ApprovalStatus.PENDING:
                return WriteResult(
                    success=False,
                    status="requires_approval",
                    write_id=env.write_id,
                    reason="approval_pending",
                    idempotency_key=env.idempotency_key,
                    task_id=env.task_id,
                    execution_id=env.execution_id,
                    approval_id=env.approval_id,
                ).__dict__
            elif st in (ApprovalStatus.REJECTED, ApprovalStatus.INVALID):
                return WriteResult(
                    success=False,
                    status="rejected",
                    write_id=env.write_id,
                    reason=f"approval_not_approved:{st.value}",
                    idempotency_key=env.idempotency_key,
                    task_id=env.task_id,
                    execution_id=env.execution_id,
                    approval_id=env.approval_id,
                ).__dict__
            else:
                return WriteResult(
                    success=False,
                    status="rejected",
                    write_id=env.write_id,
                    reason="approval_not_approved",
                    idempotency_key=env.idempotency_key,
                    task_id=env.task_id,
                    execution_id=env.execution_id,
                    approval_id=env.approval_id,
                ).__dict__

        # Idempotency check
        existing = await self._idempotency.get(env.idempotency_key)
        if existing and existing.status == "succeeded" and existing.result is not None:
            await self._emit_audit("WRITE_IDEMPOTENT_REPLAY", env, {"replayed": True})
            stored = existing.result
            replay = WriteResult(
                success=True,
                status="replayed",
                write_id=stored.write_id,
                reason=stored.reason,
                idempotency_key=stored.idempotency_key,
                task_id=stored.task_id,
                execution_id=stored.execution_id,
                audit_id=stored.audit_id,
                approval_id=stored.approval_id,
                data=stored.data,
            )
            return replay.__dict__

        if existing and existing.status == "processing":
            # deterministički odgovor (MAX: ne pravimo side-effect)
            return WriteResult(
                success=False,
                status="failed",
                write_id=env.write_id,
                reason="idempotency_in_progress",
                idempotency_key=env.idempotency_key,
                task_id=env.task_id,
                execution_id=env.execution_id,
            ).__dict__

        await self._idempotency.set_processing(env.idempotency_key)

        try:
            handler = self._handlers.get(env.command)
            if handler is None:
                raise RuntimeError(f"no_handler_registered_for_command:{env.command}")

            result_payload = await handler(env)

            res = WriteResult(
                success=True,
                status="applied",
                write_id=env.write_id,
                idempotency_key=env.idempotency_key,
                task_id=env.task_id,
                execution_id=env.execution_id,
                approval_id=env.approval_id,
                data=result_payload,
            )
            await self._idempotency.set_result(env.idempotency_key, res, succeeded=True)
            await self._emit_audit("WRITE_APPLIED", env, {"success": True})
            return res.__dict__

        except Exception as e:
            res = WriteResult(
                success=False,
                status="failed",
                write_id=env.write_id,
                reason=f"write_failed:{type(e).__name__}:{str(e)}",
                idempotency_key=env.idempotency_key,
                task_id=env.task_id,
                execution_id=env.execution_id,
                approval_id=env.approval_id,
            )
            await self._idempotency.set_result(
                env.idempotency_key, res, succeeded=False
            )
            await self._emit_audit(
                "WRITE_FAILED", env, {"success": False, "error": str(e)}
            )
            return res.__dict__

    async def write(self, command: Dict[str, Any]) -> Dict[str, Any]:
        req = await self.request_write(command)
        if not req.get("success", False):
            return req

        token = req.get("write_token")
        if not token:
            # should not happen; defensive
            return WriteResult(
                success=False,
                status="failed",
                write_id=req.get("write_id", ""),
                reason="missing_write_token",
            ).__dict__

        return await self.commit_write(token)

    # ---------- internals ----------

    def _normalize_envelope(self, command: Dict[str, Any]) -> WriteEnvelope:
        metadata = command.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else None

        approval_id = command.get("approval_id")
        if approval_id is None and metadata:
            approval_id = metadata.get("approval_id")

        scope = command.get("scope")
        scope = scope if isinstance(scope, dict) else None

        return WriteEnvelope(
            command=str(command.get("command", "")).strip(),
            actor_id=str(command.get("actor_id", "")).strip(),
            resource=str(command.get("resource", "")).strip(),
            payload=dict(command.get("payload", {}) or {}),
            task_id=command.get("task_id"),
            execution_id=command.get("execution_id"),
            idempotency_key=command.get("idempotency_key"),
            scope=scope,
            metadata=metadata,
            approval_id=str(approval_id).strip() if approval_id else None,
        )

    def _derive_idempotency_key(self, env: WriteEnvelope) -> str:
        base = f"{env.task_id or 'NO_TASK'}::{env.execution_id or 'NO_EXEC'}::{env.command}::{env.resource}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, base))

    async def _evaluate_policy(self, env: WriteEnvelope) -> PolicyDecision:
        if self._policy_evaluator is not None:
            return await self._policy_evaluator(env)

        context_type = self._derive_context_type(env)

        resp = self._governance.evaluate(
            initiator=env.actor_id,
            context_type=context_type,
            directive=env.command,
            params=env.payload if isinstance(env.payload, dict) else {},
            execution_id=env.execution_id or "",
            approval_id=env.approval_id,
        )

        if resp.get("allowed") is True:
            return PolicyDecision(
                decision="allow",
                reason="governance_allowed",
                approval_id=resp.get("approval_id"),
            )

        appr = resp.get("approval_id")
        if appr:
            return PolicyDecision(
                decision="requires_approval",
                reason=resp.get("reason", "approval_required"),
                approval_id=appr,
            )

        return PolicyDecision(
            decision="deny", reason=resp.get("reason", "policy_denied")
        )

    def _derive_context_type(self, env: WriteEnvelope) -> str:
        if env.scope and isinstance(env.scope, dict):
            t = env.scope.get("type")
            if isinstance(t, str) and t.strip():
                return t.strip()
        if env.metadata and isinstance(env.metadata, dict):
            ct = env.metadata.get("context_type")
            if isinstance(ct, str) and ct.strip():
                return ct.strip()
        return "system"

    async def _emit_audit(
        self, event_type: str, env: WriteEnvelope, data: Dict[str, Any]
    ) -> Optional[str]:
        audit_id = str(uuid.uuid4())
        record = {
            "audit_id": audit_id,
            "event_type": event_type,
            "timestamp_unix": time.time(),
            "write_id": env.write_id,
            "task_id": env.task_id,
            "execution_id": env.execution_id,
            "idempotency_key": env.idempotency_key,
            "actor_id": env.actor_id,
            "command": env.command,
            "resource": env.resource,
            "data": data or {},
        }

        async with self._audit_lock:
            mem = getattr(self._memory, "memory", None)
            if isinstance(mem, dict):
                mem.setdefault("write_audit_events", []).append(record)

        if self._audit_emitter is None:
            return audit_id

        try:
            await self._audit_emitter(event_type, env, data)
            return audit_id
        except Exception:
            return audit_id

    async def _take_token(self, token: str) -> Optional[WriteEnvelope]:
        now = time.time()
        async with self._pending_lock:
            entry = self._pending.pop(token, None)
        if not entry:
            return None
        if entry["exp"] < now:
            return None
        return entry["envelope"]

    async def _demo_handler(self, env: WriteEnvelope) -> Dict[str, Any]:
        return {
            "noop": True,
            "command": env.command,
            "resource": env.resource,
            "actor_id": env.actor_id,
        }

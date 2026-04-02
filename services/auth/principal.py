from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _normalize_str_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, set, tuple)):
        items = list(value)
    else:
        items = [value]

    normalized: set[str] = set()
    for item in items:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            normalized.add(text)
    return normalized


def _normalize_scopes(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        parts = [p.strip() for p in value.split()]
        return {p for p in parts if p}
    return _normalize_str_set(value)


@dataclass(frozen=True, slots=True)
class Principal:
    sub: str
    roles: set[str] = field(default_factory=set)
    tenant: str | None = None
    scopes: set[str] = field(default_factory=set)
    raw_claims: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_claims(cls, claims: Mapping[str, Any]) -> "Principal":
        if claims is None:
            raise ValueError("claims must not be None")
        if not isinstance(claims, Mapping):
            raise ValueError("claims must be a mapping")

        sub_value = claims.get("sub")
        if sub_value is None:
            raise ValueError("sub claim is required")
        sub = str(sub_value).strip()
        if not sub:
            raise ValueError("sub claim must be a non-empty string")

        roles_value = claims.get("roles", claims.get("role"))
        roles = _normalize_str_set(roles_value)

        scopes_value = claims.get("scope", claims.get("scp"))
        scopes = _normalize_scopes(scopes_value)

        tenant_value = claims.get("tenant", claims.get("tid"))
        tenant = None
        if tenant_value is not None:
            tenant_text = str(tenant_value).strip()
            tenant = tenant_text if tenant_text else None

        raw_claims = dict(claims)
        return cls(
            sub=sub, roles=roles, tenant=tenant, scopes=scopes, raw_claims=raw_claims
        )

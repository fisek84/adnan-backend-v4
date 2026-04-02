from __future__ import annotations

from typing import Callable

from fastapi import Depends, Header, HTTPException, status

from services.auth.jwt import JWTVerificationError, verify_jwt
from services.auth.principal import Principal


def require_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Principal:
    """Require an authenticated principal.

    - Missing or invalid Authorization header -> 401
    - Any JWT verification or claims-to-principal failure -> 401
    """

    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_authorization"
        )

    value = authorization.strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_authorization"
        )

    if not value.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_authorization_scheme",
        )

    token = value[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_bearer_token"
        )

    try:
        claims = verify_jwt(token)
        principal = Principal.from_claims(claims)
    except (JWTVerificationError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials"
        )

    return principal


def require_role(*roles: str) -> Callable[[Principal], Principal]:
    """Require that the authenticated principal has at least one of the given roles.

    If called with no roles, this dependency denies access (403) to avoid implicit allow.
    """

    required_roles = {r.strip() for r in roles if isinstance(r, str) and r.strip()}

    def _dependency(principal: Principal = Depends(require_principal)) -> Principal:
        if not required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        if principal.roles.intersection(required_roles):
            return principal
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    return _dependency


def require_scope(*scopes: str) -> Callable[[Principal], Principal]:
    """Require that the authenticated principal has all given scopes.

    If called with no scopes, this dependency denies access (403) to avoid implicit allow.
    """

    required_scopes = {s.strip() for s in scopes if isinstance(s, str) and s.strip()}

    def _dependency(principal: Principal = Depends(require_principal)) -> Principal:
        if not required_scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        if required_scopes.issubset(principal.scopes):
            return principal
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    return _dependency

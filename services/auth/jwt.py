from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


class JWTVerificationError(Exception):
    """Base class for JWT verification failures."""


class JWTConfigError(JWTVerificationError):
    """Raised when required verification configuration is missing."""


class JWTInvalidTokenError(JWTVerificationError):
    """Raised when token is malformed or claims/header are invalid."""


class JWTUnsupportedAlgorithmError(JWTVerificationError):
    """Raised when token uses an unsupported or disallowed algorithm."""


class JWTInvalidSignatureError(JWTVerificationError):
    """Raised when signature verification fails."""


class JWTExpiredError(JWTVerificationError):
    """Raised when token is expired."""


class JWTNotYetValidError(JWTVerificationError):
    """Raised when token is not yet valid (nbf in the future)."""


class JWTInvalidIssuerError(JWTVerificationError):
    """Raised when issuer does not match required issuer."""


class JWTInvalidAudienceError(JWTVerificationError):
    """Raised when audience does not match required audience."""


def _b64url_decode(segment: str) -> bytes:
    if not isinstance(segment, str) or not segment:
        raise JWTInvalidTokenError("invalid_base64url_segment")
    padded = segment + "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as exc:  # pragma: no cover
        raise JWTInvalidTokenError("invalid_base64url_encoding") from exc


def _load_json_object(raw: bytes, kind: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise JWTInvalidTokenError(f"invalid_{kind}_json") from exc
    if not isinstance(parsed, dict):
        raise JWTInvalidTokenError(f"invalid_{kind}_type")
    return parsed


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise JWTConfigError(f"missing_config:{name}")
    value = value.strip()
    if not value:
        raise JWTConfigError(f"missing_config:{name}")
    return value


def _aud_matches(aud_claim: Any, required_audience: str) -> bool:
    if aud_claim is None:
        return False
    if isinstance(aud_claim, str):
        return aud_claim == required_audience
    if isinstance(aud_claim, (list, tuple, set)):
        return required_audience in {str(x) for x in aud_claim if x is not None}
    return False


def _verify_hs256(signing_input: bytes, signature: bytes, secret: str) -> None:
    mac = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, signature):
        raise JWTInvalidSignatureError("invalid_signature")


def _verify_rs256(signing_input: bytes, signature: bytes, public_key_pem: str) -> None:
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
    except Exception as exc:  # pragma: no cover
        raise JWTUnsupportedAlgorithmError("rs256_requires_cryptography") from exc

    try:
        public_key = load_pem_public_key(public_key_pem.encode("utf-8"))
        public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except JWTVerificationError:
        raise
    except Exception as exc:
        raise JWTInvalidSignatureError("invalid_signature") from exc


def verify_jwt(token: str) -> dict[str, Any]:
    """Verify a JWT and return verified claims.

    Verification is strict and fail-closed:
    - signature is verified (HS256; RS256 requires cryptography)
    - issuer, audience, exp are required and validated
    - nbf is validated when present

    Required configuration (environment variables):
    - AUTH_JWT_ISSUER
    - AUTH_JWT_AUDIENCE
    - AUTH_JWT_ALLOWED_ALGS (comma-separated, e.g. "HS256,RS256")
    - AUTH_JWT_SECRET (required when HS256 is allowed/used)
    - AUTH_JWT_PUBLIC_KEY_PEM (required when RS256 is allowed/used)
    """

    if not isinstance(token, str):
        raise JWTInvalidTokenError("token_must_be_string")
    token = token.strip()
    if not token:
        raise JWTInvalidTokenError("empty_token")

    parts = token.split(".")
    if len(parts) != 3:
        raise JWTInvalidTokenError("token_must_have_3_parts")
    header_b64, payload_b64, signature_b64 = parts

    header = _load_json_object(_b64url_decode(header_b64), "header")
    claims = _load_json_object(_b64url_decode(payload_b64), "claims")
    signature = _b64url_decode(signature_b64)

    alg = header.get("alg")
    if not isinstance(alg, str) or not alg.strip():
        raise JWTInvalidTokenError("missing_alg")
    alg = alg.strip()
    if alg.lower() == "none":
        raise JWTUnsupportedAlgorithmError("alg_none_not_allowed")

    allowed_algs_raw = _get_required_env("AUTH_JWT_ALLOWED_ALGS")
    allowed_algs = {a.strip() for a in allowed_algs_raw.split(",") if a.strip()}
    if alg not in allowed_algs:
        raise JWTUnsupportedAlgorithmError("alg_not_allowed")

    required_issuer = _get_required_env("AUTH_JWT_ISSUER")
    required_audience = _get_required_env("AUTH_JWT_AUDIENCE")

    iss = claims.get("iss")
    if not isinstance(iss, str) or iss != required_issuer:
        raise JWTInvalidIssuerError("invalid_issuer")

    aud = claims.get("aud")
    if not _aud_matches(aud, required_audience):
        raise JWTInvalidAudienceError("invalid_audience")

    now = int(time.time())

    exp = claims.get("exp")
    if exp is None:
        raise JWTInvalidTokenError("missing_exp")
    try:
        exp_i = int(exp)
    except Exception as exc:
        raise JWTInvalidTokenError("invalid_exp") from exc
    if exp_i < now:
        raise JWTExpiredError("token_expired")

    nbf = claims.get("nbf")
    if nbf is not None:
        try:
            nbf_i = int(nbf)
        except Exception as exc:
            raise JWTInvalidTokenError("invalid_nbf") from exc
        if nbf_i > now:
            raise JWTNotYetValidError("token_not_yet_valid")

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    if alg == "HS256":
        secret = _get_required_env("AUTH_JWT_SECRET")
        _verify_hs256(signing_input, signature, secret)
    elif alg == "RS256":
        public_key_pem = _get_required_env("AUTH_JWT_PUBLIC_KEY_PEM")
        _verify_rs256(signing_input, signature, public_key_pem)
    else:
        raise JWTUnsupportedAlgorithmError("unsupported_alg")

    return claims

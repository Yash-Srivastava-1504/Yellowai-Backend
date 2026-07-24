"""
Manah Backend — Auth Middleware
FastAPI Depends() factories for JWT and Supabase JWT verification.
"""
import base64
import json
import time
from typing import Annotated, Optional

import httpx
from fastapi import Cookie, Depends, Header, HTTPException, status
from jose import ExpiredSignatureError, JWTError, jwt

from auth.service import decode_access_token
from config import get_settings

settings = get_settings()

# ── JWKS cache (per URL, TTL = 5 minutes) ────────────────────────────────────
_jwks_cache: dict[str, tuple[dict, float]] = {}  # url -> (jwks_json, fetched_at)
_JWKS_TTL = 300  # seconds


async def _fetch_jwks(url: str) -> dict:
    """Return JWKS from cache or fetch fresh. Never hits Supabase more than once per 5 min."""
    cached = _jwks_cache.get(url)
    if cached and (time.monotonic() - cached[1]) < _JWKS_TTL:
        return cached[0]
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=8.0)
        resp.raise_for_status()
        jwks = resp.json()
    _jwks_cache[url] = (jwks, time.monotonic())
    return jwks


# ── Internal JWT (legacy SQLite auth) ─────────────────────────────────────────

class CurrentUser:
    def __init__(self, id: int, email: str):
        self.id = id
        self.email = email


async def get_current_user(
    authorization: Annotated[Optional[str], Header()] = None,
    accessToken: Annotated[Optional[str], Cookie()] = None,
) -> CurrentUser:
    """
    Verifies JWT from `Authorization: Bearer <token>` header or `accessToken` cookie.
    Raises HTTP 401 on failure. Attaches user.id and user.email.
    """
    token: Optional[str] = None

    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
    elif accessToken:
        token = accessToken

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    try:
        payload = decode_access_token(token)
        return CurrentUser(id=payload["id"], email=payload["email"])
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"X-Error-Code": "TOKEN_EXPIRED"},
        )
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ── Supabase JWT (RS256/HS256) ─────────────────────────────────────────────────

class SupabaseUser:
    def __init__(self, id: str, email: Optional[str]):
        self.id = id
        self.email = email


def _parse_jwt_header(token: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        padding = "=" * (-len(parts[0]) % 4)
        return json.loads(base64.urlsafe_b64decode(parts[0] + padding))
    except Exception:
        return None


def _parse_jwt_payload(token: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        padding = "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(parts[1] + padding))
    except Exception:
        return None


async def _verify_supabase_token(token: str) -> dict:
    header = _parse_jwt_header(token)
    if not header:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")

    alg = header.get("alg", "")

    if alg == "HS256":
        secret = settings.SUPABASE_JWT_SECRET
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server missing Supabase JWT configuration",
            )
        try:
            return jwt.decode(token, secret, algorithms=["HS256"])
        except ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"X-Error-Code": "TOKEN_EXPIRED"},
            )
        except JWTError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if alg in ("RS256", "ES256", "EdDSA"):
        payload = _parse_jwt_payload(token)
        iss = (payload or {}).get("iss", "")
        if not isinstance(iss, str) or "supabase" not in iss:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid issuer")

        # Prefer explicit SUPABASE_JWKS_URL from env, fall back to deriving from iss
        jwks_url = settings.SUPABASE_JWKS_URL or (iss.rstrip("/") + "/.well-known/jwks.json")
        jwks = await _fetch_jwks(jwks_url)

        # Find matching key by kid
        kid = header.get("kid")
        keys = jwks.get("keys", [])
        key = next((k for k in keys if k.get("kid") == kid), keys[0] if keys else None)
        if not key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No matching JWKS key")

        try:
            from jose.backends import RSAKey
            return jwt.decode(token, key, algorithms=[alg], options={"verify_aud": False})
        except ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"X-Error-Code": "TOKEN_EXPIRED"},
            )
        except JWTError as e:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Unsupported JWT algorithm: {alg}")


async def get_supabase_user(
    authorization: Annotated[Optional[str], Header()] = None,
) -> SupabaseUser:
    """
    Verifies Supabase Auth JWT (HS256 or RS256/ES256 via JWKS).
    Sets supabase_user.id (uuid str) and supabase_user.email.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization Bearer token required",
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization Bearer token required",
        )

    payload = await _verify_supabase_token(token)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    return SupabaseUser(id=str(sub), email=payload.get("email"))

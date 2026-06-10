"""
Authentication — Google OAuth 2.0 (production) with HS256 JWT fallback (dev).

Production mode (GOOGLE_OAUTH_CLIENT_ID set):
  - UI sends Google Sign-In id_token
  - POST /auth/google  →  server verifies with Google's public keys
  - Returns our own short-lived JWT so every downstream request stays uniform
  - /auth/token is disabled (returns 403)

Dev/fallback mode (no GOOGLE_OAUTH_CLIENT_ID):
  - POST /auth/token  →  any non-empty client_secret issues a HS256 JWT
  - Identical to the previous behaviour — no change needed in tests

Both modes produce the same JWT shape for verify_token, so /chat /workflow
/a2a /properties all work unchanged.
"""
from __future__ import annotations
import os
import time
import logging
from typing import Any
import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_SECRET         = os.getenv("JWT_SECRET", "lettingcopilot-dev-secret-change-in-prod")
_ALGORITHM      = "HS256"
_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", "86400"))   # 24h
_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")        # set this for prod

_bearer = HTTPBearer(auto_error=False)


# ── Token creation ────────────────────────────────────────────────────────────

def create_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    """Issue a signed HS256 JWT. Used by both dev (/auth/token) and OAuth flow."""
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + _EXPIRE_SECONDS,
        "iss": "lettingcopilot",
        **(extra or {}),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


# ── Token verification ────────────────────────────────────────────────────────

def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> dict[str, Any]:
    """FastAPI dependency — validates Bearer JWT, returns claims."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    try:
        claims = jwt.decode(
            credentials.credentials,
            _SECRET,
            algorithms=[_ALGORITHM],
            options={"verify_exp": True},
        )
        return claims
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired — please sign in again")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


# ── Google OAuth 2.0 id_token verification ────────────────────────────────────

def verify_google_id_token(id_token: str) -> dict[str, Any]:
    """
    Verify a Google Sign-In id_token using Google's tokeninfo endpoint.
    Returns the token claims (sub, email, name, picture).
    Raises HTTPException 401 on any failure.

    Uses google-auth library when available (preferred — uses local public keys).
    Falls back to HTTPS tokeninfo endpoint if library not installed.
    """
    if not _OAUTH_CLIENT_ID:
        raise HTTPException(
            status_code=501,
            detail="Google OAuth not configured. Set GOOGLE_OAUTH_CLIENT_ID env var.",
        )

    # Try google-auth library first (no network round-trip, uses cached certs)
    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests

        idinfo = google_id_token.verify_oauth2_token(
            id_token,
            google_requests.Request(),
            _OAUTH_CLIENT_ID,
        )
        logger.info("[auth] Google id_token verified sub=%s email=%s", idinfo.get("sub"), idinfo.get("email"))
        return idinfo

    except ImportError:
        pass  # fall through to HTTP endpoint
    except Exception as e:
        logger.warning("[auth] google-auth verification failed: %s", e)
        raise HTTPException(status_code=401, detail=f"Google token verification failed: {e}")

    # HTTP fallback — calls Google's tokeninfo endpoint
    import httpx
    try:
        resp = httpx.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": id_token},
            timeout=10,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Google token rejected")
        info = resp.json()
        if info.get("aud") != _OAUTH_CLIENT_ID:
            raise HTTPException(status_code=401, detail="Token audience mismatch")
        return info
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Could not reach Google auth servers: {e}")


def is_oauth_enabled() -> bool:
    return bool(_OAUTH_CLIENT_ID)

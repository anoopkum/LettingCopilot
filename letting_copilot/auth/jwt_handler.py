"""
JWT authentication — HS256 signed tokens.
For POC: shared secret via JWT_SECRET env var.
For prod: replace with Google Cloud KMS or Firebase Auth.
"""
import os
import time
import logging
from typing import Any
import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

_SECRET = os.getenv("JWT_SECRET", "lettingcopilot-dev-secret-change-in-prod")
_ALGORITHM = "HS256"
_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", "86400"))  # 24h

_bearer = HTTPBearer(auto_error=False)


def create_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    """Issue a signed JWT for a given subject (user_id or agent_id)."""
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + _EXPIRE_SECONDS,
        "iss": "lettingcopilot",
        **(extra or {}),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


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
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


class JWTBearer(HTTPBearer):
    """Reusable FastAPI dependency class for JWT auth."""
    async def __call__(self, *args, **kwargs) -> dict:
        return verify_token(await super().__call__(*args, **kwargs))

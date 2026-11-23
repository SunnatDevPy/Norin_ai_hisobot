"""JWT, OTP hashing and in-memory rate limiting helpers for norin-api."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, Optional
from collections import defaultdict, deque

import jwt

from config import get_settings


JWT_ALG = "HS256"


def _secret() -> str:
    """Return JWT secret from .env, falling back to a key derived from BOT_TOKEN."""
    s = get_settings()
    if s.API_JWT_SECRET.strip():
        return s.API_JWT_SECRET.strip()
    return hashlib.sha256(f"norin-api::{s.BOT_TOKEN}".encode()).hexdigest()


def hash_secret(value: str) -> str:
    """HMAC-SHA256 a code/refresh token so only hashes are stored in the database."""
    return hmac.new(_secret().encode(), value.encode(), hashlib.sha256).hexdigest()


def verify_hash(value: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_secret(value), hashed)


def make_otp() -> str:
    """Generate a cryptographically secure 6-digit code."""
    return f"{secrets.randbelow(1_000_000):06d}"


def make_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def create_access_token(
    telegram_id: int, role: str, tenant_id: int, session_id: int
) -> tuple[str, int]:
    """Create a short-lived access JWT; returns (token, expires_in_seconds)."""
    ttl = max(1, int(get_settings().API_ACCESS_TTL_MIN)) * 60
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": str(telegram_id),
        "role": role,
        "tid": int(tenant_id),
        "sid": int(session_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALG), ttl


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, _secret(), algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None


class RateLimiter:
    """Simple sliding-window limiter (per process) for login endpoints."""

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_sec: int) -> bool:
        """Record a hit and return True when still within the limit."""
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > window_sec:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


rate_limiter = RateLimiter()

"""Password hashing (bcrypt) and JWT issuance/verification (HS256)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import bcrypt
import jwt

from aegis.config import get_settings


class Role(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


# Higher rank includes the permissions of lower ranks.
ROLE_RANK = {Role.VIEWER: 0, Role.ANALYST: 1, Role.ADMIN: 2}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: str, tenant_id: str, role: str, email: str) -> tuple[str, int]:
    s = get_settings()
    ttl = s.jwt_ttl_minutes * 60
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": user_id,
        "tid": tenant_id,
        "role": role,
        "email": email,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "iss": "aegis",
    }
    return jwt.encode(claims, s.jwt_secret, algorithm=s.jwt_algorithm), ttl


def decode_access_token(token: str) -> dict[str, Any]:
    s = get_settings()
    return jwt.decode(
        token,
        s.jwt_secret,
        algorithms=[s.jwt_algorithm],
        issuer="aegis",
        options={"require": ["sub", "tid", "role", "exp"]},
    )

"""Authentication service."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy import Engine

from aegis.repositories import investigations as repo
from aegis.security import create_access_token, hash_password, verify_password


@lru_cache
def _dummy_hash() -> str:
    """Verify against a real bcrypt hash even for unknown users so timing doesn't reveal which emails exist."""
    return hash_password("timing-equaliser")


class InvalidCredentials(Exception):
    pass


def login(engine: Engine, email: str, password: str) -> dict[str, Any]:
    with engine.connect() as conn:
        user = repo.get_user_by_email(conn, email)
    ok = verify_password(password, user["password_hash"] if user else _dummy_hash())
    if not user or not ok or not user["is_active"]:
        # Recorded in its own transaction so the audit row survives the failed login.
        with engine.begin() as conn:
            repo.audit(
                conn,
                user["tenant_id"] if user else None,
                None,
                "login_failed",
                "user",
                None,
                {"email": email.lower()[:254]},
            )
        raise InvalidCredentials()
    token, ttl = create_access_token(str(user["user_id"]), user["tenant_id"], user["role"], user["email"])
    with engine.begin() as conn:
        repo.audit(conn, user["tenant_id"], user["user_id"], "login", "user", str(user["user_id"]))
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": ttl,
        "user": {
            "user_id": str(user["user_id"]),
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            "tenant_id": user["tenant_id"],
        },
    }

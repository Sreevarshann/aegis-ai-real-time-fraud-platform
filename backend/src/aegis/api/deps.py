"""FastAPI dependencies: database engine, authenticated principal and role checks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine

from aegis.config import Settings, get_settings
from aegis.db.engine import get_engine
from aegis.security import ROLE_RANK, Role, decode_access_token

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    tenant_id: str
    role: Role
    email: str


def db_engine() -> Engine:
    return get_engine()


def settings() -> Settings:
    return get_settings()


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_access_token(creds.credentials)
        return Principal(UUID(claims["sub"]), str(claims["tid"]), Role(claims["role"]), str(claims.get("email", "")))
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}
        ) from exc


def require_role(minimum: Role) -> Callable[[Principal], Principal]:
    def check(user: Principal = Depends(current_user)) -> Principal:
        if ROLE_RANK[user.role] < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role '{minimum.value}' or higher")
        return user

    return check

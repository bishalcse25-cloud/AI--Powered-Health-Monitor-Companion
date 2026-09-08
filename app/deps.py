"""
Shared FastAPI dependencies.

Authentication is ENFORCED. Every dependency that yields a `User` requires a
valid `Authorization: Bearer <token>` issued by POST /api/v1/auth/login.
There is no implicit demo user anymore - an unauthenticated request to a
protected route gets 401.
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Device, User
from app.security import decode_access_token

# tokenUrl lets the Swagger UI "Authorize" button drive the password flow.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
# Same flow, but a missing Authorization header yields None instead of a 401.
# Used by endpoints that accept an alternative credential (e.g. a device token).
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolve the caller from their bearer token.

    Raises 401 if the header is missing, the token is malformed / expired /
    wrong-type, or the user id it carries no longer exists.
    """
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        raise _CREDENTIALS_ERROR

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise _CREDENTIALS_ERROR
    return user


def get_optional_current_user(
    token: str | None = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> User | None:
    """
    Like :func:`get_current_user`, but returns ``None`` when no bearer token is
    supplied instead of raising 401. A token that IS supplied must still be
    valid - a malformed / expired / unknown-user token is a 401, not anonymous.
    """
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        raise _CREDENTIALS_ERROR

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise _CREDENTIALS_ERROR
    return user


# Back-compat alias. `get_current_user` used to return a shared demo user and
# `get_current_auth_user` was the "real" one; they are the same thing now.
# Kept so existing router imports don't break - prefer `get_current_user`.
get_current_auth_user = get_current_user


def authenticate_device(db: Session, device_token: str) -> Device:
    """Look up an active device by its secret token (device-to-server auth)."""
    device = (
        db.query(Device)
        .filter(Device.secret_token == device_token, Device.is_active.is_(True))
        .first()
    )
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive device token",
        )
    return device

"""
Shared FastAPI dependencies.

get_current_user() is a placeholder for real authentication, which is a
later phase. For now every request acts as a single demo user so the four
pillars (IoT / ML / LLM / frontend) can all be exercised end-to-end. Once
Phase 2 (auth) exists, this function is the only place that needs to change.
"""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Device, User
from app.security import decode_access_token

settings = get_settings()

# Points at the login route so FastAPI's docs "Authorize" button works.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_or_create_demo_user(db: Session) -> User:
    user = db.query(User).filter(User.email == settings.demo_user_email).first()
    if user is None:
        user = User(email=settings.demo_user_email, full_name="Demo User")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_current_user(db: Session = Depends(get_db)) -> User:
    return get_or_create_demo_user(db)


def get_current_auth_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Real JWT authentication: requires a valid `Authorization: Bearer <token>`
    header (token issued by POST /api/v1/auth/login). Used to protect routes
    that must not run as the shared demo user.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        raise credentials_error

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_error
    return user


def authenticate_device(db: Session, device_token: str) -> Device:
    device = db.query(Device).filter(Device.secret_token == device_token, Device.is_active.is_(True)).first()
    if device is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive device token")
    return device

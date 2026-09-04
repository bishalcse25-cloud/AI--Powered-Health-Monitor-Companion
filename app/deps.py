"""
Shared FastAPI dependencies.

get_current_user() is a placeholder for real authentication, which is a
later phase. For now every request acts as a single demo user so the four
pillars (IoT / ML / LLM / frontend) can all be exercised end-to-end. Once
Phase 2 (auth) exists, this function is the only place that needs to change.
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Device, User

settings = get_settings()


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


def authenticate_device(db: Session, device_token: str) -> Device:
    device = db.query(Device).filter(Device.secret_token == device_token, Device.is_active.is_(True)).first()
    if device is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive device token")
    return device

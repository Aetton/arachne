"""FastAPI auth dependencies. Token lives in an httponly cookie so HTMX
requests carry it automatically without any JS."""
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database import SessionLocal, User
from auth.security import verify_token

COOKIE_NAME = "portal_session"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _user_from_request(request: Request, db: Session) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    username = verify_token(token)
    if not username:
        return None
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
        return None
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Hard dependency: 401 (API) — callers that render HTML catch this and redirect."""
    user = _user_from_request(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    return _user_from_request(request, db)


def require_role(*allowed: str):
    """Guard factory. Admin always passes."""
    def _check(user: User = Depends(get_current_user)) -> User:
        roles = set(user.roles or [])
        if "admin" in roles or roles.intersection(allowed):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return _check

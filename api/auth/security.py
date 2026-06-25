"""Password hashing (bcrypt direct) + JWT issuing/verification."""
import os
from datetime import timedelta

import bcrypt
import jwt

from database import utcnow

PROD_ENV_VALUES = {"prod", "production"}
BAD_JWT_SECRETS = {"", "dev-secret-change-me", "change-me-in-prod"}


def is_prod_env() -> bool:
    return (os.getenv("ENV", "").lower() in PROD_ENV_VALUES
            or os.getenv("APP_ENV", "").lower() in PROD_ENV_VALUES)


def _env_value(name: str, default: str, forbidden_in_prod: set[str]) -> str:
    value = os.getenv(name, default)
    if is_prod_env() and value in forbidden_in_prod:
        raise RuntimeError(f"{name} must be set to a safe non-default value in prod")
    return value


JWT_SECRET = _env_value("JWT_SECRET", "dev-secret-change-me", BAD_JWT_SECRETS)
JWT_ALGO = "HS256"
TOKEN_TTL_DAYS = int(os.getenv("TOKEN_TTL_DAYS", "7"))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def create_token(username: str) -> str:
    now = utcnow()
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(days=TOKEN_TTL_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None

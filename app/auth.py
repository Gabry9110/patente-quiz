from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.models import User

SESSION_COOKIE = "patente_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="patente-session")


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")
    if len(pw) > 72:
        pw = pw[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    pw = plain.encode("utf-8")
    if len(pw) > 72:
        pw = pw[:72]
    try:
        return bcrypt.checkpw(pw, hashed.encode("utf-8"))
    except ValueError:
        return False


def create_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def decode_session_token(token: str) -> dict | None:
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def set_session_cookie(response, user_id: int) -> None:
    token = create_session_token(user_id)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # behind Cloudflare Tunnel terminates TLS upstream; set True if tunnel does HTTPS to origin
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    data = decode_session_token(token)
    if not data or "uid" not in data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user = session.get(User, data["uid"])
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


def require_user_redirect(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> User | RedirectResponse:
    """Like get_current_user but returns a RedirectResponse for browser flows."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return RedirectResponse("/login", status_code=303)
    data = decode_session_token(token)
    if not data or "uid" not in data:
        return RedirectResponse("/login", status_code=303)
    user = session.get(User, data["uid"])
    if not user:
        return RedirectResponse("/login", status_code=303)
    return user


def needs_initial_setup(session: Session) -> bool:
    """True when no user exists yet -> first-run password setup flow."""
    return session.exec(select(User)).first() is None
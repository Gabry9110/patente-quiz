from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.auth import (
    clear_session_cookie,
    hash_password,
    needs_initial_setup,
    set_session_cookie,
    verify_password,
)
from app.config import settings
from app.db import get_session
from app.models import User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login")
async def login_page(
    request: Request,
    session: Session = Depends(get_session),
):
    setup = needs_initial_setup(session)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "setup": setup, "username": settings.initial_username, "error": None, "topbar": False, "user": None},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    if needs_initial_setup(session):
        return RedirectResponse("/login", status_code=303)
    user = session.exec(select(User).where(User.username == username)).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "setup": False, "username": username, "error": "Credenziali non valide.", "topbar": False, "user": None},
            status_code=401,
        )
    resp = RedirectResponse("/", status_code=303)
    set_session_cookie(resp, user.id)
    return resp


@router.get("/setup")
async def setup_page(
    request: Request,
    session: Session = Depends(get_session),
):
    if not needs_initial_setup(session):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "setup": True, "username": settings.initial_username, "error": None, "topbar": False, "user": None},
    )


@router.post("/setup")
async def setup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    session: Session = Depends(get_session),
):
    if not needs_initial_setup(session):
        return RedirectResponse("/login", status_code=303)
    if len(password) < 8:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "setup": True, "username": username, "error": "La password deve avere almeno 8 caratteri.", "topbar": False, "user": None},
            status_code=400,
        )
    if password != password2:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "setup": True, "username": username, "error": "Le password non coincidono.", "topbar": False, "user": None},
            status_code=400,
        )
    user = User(username=username, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    resp = RedirectResponse("/", status_code=303)
    set_session_cookie(resp, user.id)
    return resp


@router.post("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    clear_session_cookie(resp)
    return resp
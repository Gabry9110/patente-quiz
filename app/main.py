import logging

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import init_db
from app.routes import auth as auth_routes
from app.routes import dashboard as dashboard_routes
from app.routes import questions as question_routes
from app.routes import quiz as quiz_routes
from app.routes import review as review_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("patente-quiz")

app = FastAPI(title="Patente Quiz", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
async def _startup() -> None:
    log.info("Initialising database...")
    init_db()
    log.info("Ready on %s:%s", settings.app_host, settings.app_port)


app.include_router(auth_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(quiz_routes.router)
app.include_router(question_routes.router)
app.include_router(review_routes.router)


@app.exception_handler(401)
async def _unauth(request: Request, exc):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(404)
async def _notfound(request: Request, exc):
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "topbar": False, "user": None, "code": "404", "message": "Pagina non trovata."},
        status_code=404,
    )
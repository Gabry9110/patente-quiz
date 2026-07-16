from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, func, select

from app.auth import get_current_user, require_user_redirect
from app.db import get_session
from app.llm import generate_questions, reference_for_category, self_check
from app.models import Category, Option, Question, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/questions")
async def list_questions(
    request: Request,
    category: str = Query(...),
    session: Session = Depends(get_session),
):
    user = require_user_redirect(request, session)
    if isinstance(user, RedirectResponse):
        return user
    cat = session.exec(select(Category).where(Category.slug == category)).first()
    if not cat:
        raise HTTPException(404)
    questions = session.exec(
        select(Question).where(Question.category_id == cat.id).order_by(Question.created_at.desc())
    ).all()
    for q in questions:
        q.options = sorted(q.options, key=lambda o: o.position)
    return templates.TemplateResponse(
        "questions_list.html",
        {"request": request, "user": user, "topbar": True, "category": cat, "questions": questions},
    )


@router.post("/questions/generate")
async def generate_on_demand(
    request: Request,
    category: str = Query(...),
    n: int = Query(1, ge=1, le=5),
    session: Session = Depends(get_session),
):
    # Auth: HTMX partial — return 401 text if not logged in
    try:
        user = get_current_user(request, session)
    except HTTPException:
        return HTMLResponse("Devi essere autenticato.", status_code=401)

    cat = session.exec(select(Category).where(Category.slug == category)).first()
    if not cat:
        return HTMLResponse("Categoria non trovata.", status_code=404)

    ref = reference_for_category(cat.slug)
    try:
        generated = generate_questions(cat.title, cat.description, ref, n=n)
    except Exception as e:
        return HTMLResponse(f"Errore generazione: {e}", status_code=502)

    added = 0
    notes: list[str] = []
    for qd in generated:
        q = Question(
            category_id=cat.id,
            text=qd["question"],
            explanation=qd.get("explanation", ""),
            source="ondemand",
        )
        try:
            res = self_check(qd, ref)
            q.verified = res["verified"]
            q.verification_note = res["note"]
        except Exception as e:
            q.verified = False
            q.verification_note = f"self-check error: {e}"
        session.add(q)
        session.flush()
        for pos, od in enumerate(qd["options"]):
            session.add(Option(
                question_id=q.id,
                text=od["text"],
                is_correct=od["is_correct"],
                position=pos,
            ))
        added += 1
        if not q.verified:
            notes.append(f"⚠️ Domanda '{qd['question'][:40]}…' non verificata: {q.verification_note}")
    session.commit()

    if added == 0:
        return HTMLResponse("Nessuna domanda valida generata. Riprova.", status_code=502)
    out = f"✓ Aggiunta {added} nuova domanda al banco globale."
    if notes:
        out += "<br>" + "<br>".join(notes)
    return HTMLResponse(out)
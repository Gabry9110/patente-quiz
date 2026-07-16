from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, func, select

from app.auth import needs_initial_setup, require_user_redirect
from app.db import get_session
from app.models import Answer, Category, Question, QuizSession

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def dashboard(request: Request, session: Session = Depends(get_session)):
    # First-run: redirect to setup
    if needs_initial_setup(session):
        return RedirectResponse("/setup", status_code=303)

    user = require_user_redirect(request, session)
    if isinstance(user, RedirectResponse):
        return user

    categories = session.exec(select(Category).order_by(Category.order)).all()
    counts: dict[str, int] = {}
    for c in categories:
        counts[c.slug] = session.exec(
            select(func.count(Question.id)).where(Question.category_id == c.id)
        ).one()
    total_questions = sum(counts.values())

    # wrong count for badge
    wrong_ids = set(session.exec(
        select(Answer.question_id).join(QuizSession)
        .where(QuizSession.user_id == user.id, Answer.is_correct == False)  # noqa: E712
    ).all())
    correct_ids = set(session.exec(
        select(Answer.question_id).join(QuizSession)
        .where(QuizSession.user_id == user.id, Answer.is_correct == True)  # noqa: E712
    ).all())
    wrong_count = len([qid for qid in wrong_ids if qid not in correct_ids])

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request, "user": user, "topbar": True,
            "categories": categories, "counts": counts,
            "total_questions": total_questions, "wrong_count": wrong_count,
        },
    )
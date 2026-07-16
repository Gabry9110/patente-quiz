from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Integer, func as sa_func, cast
from sqlmodel import Session, select

from app.auth import require_user_redirect
from app.db import get_session
from app.models import Answer, Category, Question, QuizSession

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/review")
async def review(request: Request, session: Session = Depends(get_session)):
    user = require_user_redirect(request, session)
    if isinstance(user, RedirectResponse):
        return user

    # questions answered wrong at least once and never answered correctly
    wrong_ids = session.exec(
        select(Answer.question_id)
        .join(QuizSession)
        .where(QuizSession.user_id == user.id, Answer.is_correct == False)  # noqa: E712
    ).all()
    correct_ids = set(
        session.exec(
            select(Answer.question_id)
            .join(QuizSession)
            .where(QuizSession.user_id == user.id, Answer.is_correct == True)  # noqa: E712
        ).all()
    )
    candidate_ids = [qid for qid in set(wrong_ids) if qid not in correct_ids]
    questions = []
    if candidate_ids:
        questions = session.exec(
            select(Question).where(Question.id.in_(candidate_ids))
        ).all()
        for q in questions:
            q.options = sorted(q.options, key=lambda o: o.position)
            q.category = session.get(Category, q.category_id)

    return templates.TemplateResponse(
        "review.html",
        {"request": request, "user": user, "topbar": True, "questions": questions},
    )


@router.get("/stats")
async def stats(request: Request, session: Session = Depends(get_session)):
    user = require_user_redirect(request, session)
    if isinstance(user, RedirectResponse):
        return user

    sessions = session.exec(
        select(QuizSession).where(QuizSession.user_id == user.id, QuizSession.ended_at.is_not(None))
    ).all()
    answered = session.exec(
        select(sa_func.count(Answer.id))
        .join(QuizSession)
        .where(QuizSession.user_id == user.id)
    ).one()
    correct = session.exec(
        select(sa_func.count(Answer.id))
        .join(QuizSession)
        .where(QuizSession.user_id == user.id, Answer.is_correct == True)  # noqa: E712
    ).one()
    overall_pct = int(correct * 100 / answered) if answered else 0

    # per category: count answers joined to question -> category
    rows = session.exec(
        select(
            Category.title,
            sa_func.count(Answer.id).label("answered"),
            sa_func.sum(cast(Answer.is_correct, Integer)).label("correct"),
        )
        .join(Question, Question.id == Answer.question_id)
        .join(Category, Category.id == Question.category_id)
        .join(QuizSession, QuizSession.id == Answer.session_id)
        .where(QuizSession.user_id == user.id)
        .group_by(Category.title)
    ).all()
    per_category = [
        {"title": r[0], "answered": r[1], "correct": int(r[2] or 0), "pct": int((r[2] or 0) * 100 / r[1]) if r[1] else 0}
        for r in rows
    ]
    per_category.sort(key=lambda x: x["pct"])

    recent = sessions[-10:][::-1]
    mode_labels = {"category": "Categoria", "mixed": "Misto", "wrong": "Ripasso"}
    for s in recent:
        s.mode_label = mode_labels.get(s.mode, s.mode)

    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request, "user": user, "topbar": True,
            "overall": {
                "sessions": len(sessions),
                "answered": answered,
                "correct": correct,
                "pct": overall_pct,
            },
            "per_category": per_category,
            "recent_sessions": recent,
        },
    )
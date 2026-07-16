from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, func, select

from app.auth import require_user_redirect
from app.db import get_session
from app.models import Answer, Category, Option, Question, QuizSession, User

router = APIRouter(prefix="/quiz")
templates = Jinja2Templates(directory="app/templates")

QUESTIONS_PER_QUIZ = 10


def _pick_questions(session: Session, mode: str, slug: str | None, n: int, user_id: int) -> list[Question]:
    if mode == "category":
        if not slug:
            raise HTTPException(400, "slug required for category mode")
        stmt = select(Question).join(Category).where(Category.slug == slug).order_by(func.random())
    elif mode == "mixed":
        stmt = select(Question).order_by(func.random())
    elif mode == "wrong":
        # questions answered wrong at least once, not yet answered correctly
        wrong_ids = session.exec(
            select(Answer.question_id)
            .join(QuizSession)
            .where(QuizSession.user_id == user_id, Answer.is_correct == False)  # noqa: E712
        ).all()
        correct_ids = set(
            session.exec(
                select(Answer.question_id)
                .join(QuizSession)
                .where(QuizSession.user_id == user_id, Answer.is_correct == True)  # noqa: E712
            ).all()
        )
        candidate_ids = [qid for qid in wrong_ids if qid not in correct_ids]
        if not candidate_ids:
            return []
        stmt = select(Question).where(Question.id.in_(candidate_ids)).order_by(func.random())
    else:
        raise HTTPException(400, "invalid mode")
    return list(session.exec(stmt.limit(n)).all())


def _mode_label(mode: str, scope: str | None, session: Session) -> str:
    if mode == "category" and scope:
        c = session.exec(select(Category).where(Category.slug == scope)).first()
        return c.title if c else scope
    if mode == "mixed":
        return "Quiz misto"
    if mode == "wrong":
        return "Ripasso sbagliate"
    return mode


@router.get("/start")
async def quiz_start(
    request: Request,
    mode: str = Query("mixed"),
    slug: str | None = Query(None),
    session: Session = Depends(get_session),
):
    user = require_user_redirect(request, session)
    if isinstance(user, RedirectResponse):
        return user

    questions = _pick_questions(session, mode, slug, QUESTIONS_PER_QUIZ, user.id)
    if not questions:
        return RedirectResponse("/review?empty=1", status_code=303)

    qs = QuizSession(user_id=user.id, mode=mode, scope=slug, total=len(questions))
    session.add(qs)
    session.commit()
    session.refresh(qs)

    # stash the ordered question ids in server-side memory? We'll re-randomize on next.
    # Simpler: store the first question and pass index 0.
    return _render_question(request, session, qs.id, 0, questions, _mode_label(mode, slug, session), user=user)


def _render_question(request: Request, session: Session, sid: int, index: int, questions: list[Question], title: str, user=None):
    q = questions[index]
    # eager-load options sorted by position
    opts = sorted(q.options, key=lambda o: o.position)
    q.options = opts
    return templates.TemplateResponse(
        "quiz_play.html",
        {
            "request": request,
            "user": user,
            "topbar": True,
            "title": title,
            "session_id": sid,
            "question": q,
            "index": index,
            "total": len(questions),
        },
    )


@router.post("/answer")
async def quiz_answer(
    request: Request,
    session_id: int = Form(...),
    question_id: int = Form(...),
    index: int = Form(...),
    total: int = Form(...),
    option_ids: list[int] = Form(default=[]),
    session: Session = Depends(get_session),
):
    # Auth check via cookie (no redirect for HTMX partial)
    from app.auth import get_current_user
    user = get_current_user(request, session)

    qs = session.get(QuizSession, session_id)
    if not qs or qs.user_id != user.id:
        raise HTTPException(404)

    q = session.get(Question, question_id)
    if not q:
        raise HTTPException(404)
    opts = sorted(q.options, key=lambda o: o.position)
    q.options = opts
    correct_ids = {o.id for o in opts if o.is_correct}
    selected = set(option_ids)
    is_correct = selected == correct_ids

    ans = Answer(
        session_id=session_id,
        question_id=question_id,
        selected_option_ids=list(selected),
        is_correct=is_correct,
    )
    session.add(ans)
    if is_correct:
        qs.score += 1
    session.add(qs)
    session.commit()

    label = _mode_label(qs.mode, qs.scope, session)
    return templates.TemplateResponse(
        "partials/quiz_feedback.html",
        {
            "request": request,
            "session_id": session_id,
            "question": q,
            "correct_ids": correct_ids,
            "selected_ids": selected,
            "is_correct": is_correct,
            "next_index": index + 1,
            "total": total,
        },
    )


@router.get("/next")
async def quiz_next(
    request: Request,
    session_id: int = Query(...),
    index: int = Query(...),
    session: Session = Depends(get_session),
):
    from app.auth import get_current_user
    user = get_current_user(request, session)

    qs = session.get(QuizSession, session_id)
    if not qs or qs.user_id != user.id:
        raise HTTPException(404)

    answered_ids = [a.question_id for a in session.exec(
        select(Answer).where(Answer.session_id == session_id)
    ).all()]
    # pick a new question not yet answered in this session
    stmt = select(Question)
    if qs.mode == "category" and qs.scope:
        stmt = stmt.join(Category).where(Category.slug == qs.scope)
    elif qs.mode == "wrong":
        wrong_ids = session.exec(
            select(Answer.question_id).join(QuizSession)
            .where(QuizSession.user_id == user.id, Answer.is_correct == False)  # noqa: E712
        ).all()
        correct_ids = set(session.exec(
            select(Answer.question_id).join(QuizSession)
            .where(QuizSession.user_id == user.id, Answer.is_correct == True)  # noqa: E712
        ).all())
        candidate = [qid for qid in wrong_ids if qid not in correct_ids]
        if not candidate:
            return RedirectResponse(f"/quiz/end?session_id={session_id}", status_code=303)
        stmt = stmt.where(Question.id.in_(candidate))
    if answered_ids:
        stmt = stmt.where(Question.id.notin_(answered_ids))
    stmt = stmt.order_by(func.random()).limit(1)
    q = session.exec(stmt).first()
    if not q:
        return RedirectResponse(f"/quiz/end?session_id={session_id}", status_code=303)

    title = _mode_label(qs.mode, qs.scope, session)
    # render a fresh quiz_play with index advanced
    opts = sorted(q.options, key=lambda o: o.position)
    q.options = opts
    return templates.TemplateResponse(
        "quiz_play.html",
        {
            "request": request,
            "user": user,
            "topbar": True,
            "title": title,
            "session_id": session_id,
            "question": q,
            "index": index,
            "total": qs.total,
        },
    )


@router.get("/end")
async def quiz_end(
    request: Request,
    session_id: int = Query(...),
    session: Session = Depends(get_session),
):
    from app.auth import get_current_user
    user = get_current_user(request, session)

    qs = session.get(QuizSession, session_id)
    if not qs or qs.user_id != user.id:
        raise HTTPException(404)
    if qs.ended_at is None:
        from datetime import datetime, timezone
        qs.ended_at = datetime.now(timezone.utc)
        session.add(qs)
        session.commit()
        session.refresh(qs)

    answers = session.exec(
        select(Answer).where(Answer.session_id == session_id)
    ).all()
    wrong = []
    for a in answers:
        if not a.is_correct:
            q = session.get(Question, a.question_id)
            if q:
                q.options = sorted(q.options, key=lambda o: o.position)
                wrong.append({"question": q, "selected_ids": a.selected_option_ids})

    label = _mode_label(qs.mode, qs.scope, session)
    return templates.TemplateResponse(
        "quiz_end.html",
        {
            "request": request,
            "user": user,
            "topbar": True,
            "session": qs,
            "mode_label": label,
            "score": qs.score,
            "total": qs.total,
            "wrong_answers": wrong,
        },
    )
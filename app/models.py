from datetime import datetime, timezone

from sqlmodel import Field, SQLModel, Relationship, Column, ARRAY, Integer
from sqlalchemy import JSON


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=50)
    password_hash: str
    created_at: datetime = Field(default_factory=_utcnow)

    sessions: list["QuizSession"] = Relationship(back_populates="user")


class Category(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True, max_length=80)
    title: str = Field(max_length=200)
    description: str = ""
    order: int = 0
    # Whether the riassunto-video.md contains material useful for this category.
    has_reference: bool = False

    questions: list["Question"] = Relationship(back_populates="category")


class Question(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="category.id", index=True)
    text: str
    explanation: str = ""
    source: str = Field(default="seed", max_length=20)  # seed | ondemand
    verified: bool = False
    verification_note: str = ""
    created_at: datetime = Field(default_factory=_utcnow, index=True)

    category: Category | None = Relationship(back_populates="questions")
    options: list["Option"] = Relationship(back_populates="question")


class Option(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="question.id", index=True)
    text: str
    is_correct: bool = False
    position: int = 0

    question: Question | None = Relationship(back_populates="options")


class QuizSession(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    mode: str = Field(max_length=20)  # category | mixed | wrong
    scope: str | None = None  # category slug when mode=category
    score: int = 0
    total: int = 0
    started_at: datetime = Field(default_factory=_utcnow, index=True)
    ended_at: datetime | None = None

    user: User | None = Relationship(back_populates="sessions")
    answers: list["Answer"] = Relationship(back_populates="session")


class Answer(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="quizsession.id", index=True)
    question_id: int = Field(foreign_key="question.id", index=True)
    # Store the selected option ids as JSON array.
    selected_option_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    is_correct: bool = False

    session: QuizSession | None = Relationship(back_populates="answers")
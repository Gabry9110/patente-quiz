from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

engine = create_engine(
    settings.sqlalchemy_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)


def init_db() -> None:
    """Create all tables. Called on application startup."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
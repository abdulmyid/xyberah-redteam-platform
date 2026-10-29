from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

engine = create_engine(get_settings().db_url, connect_args={"check_same_thread": False})


def init_db() -> None:
    from . import models  # noqa: F401  (registers tables)

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session

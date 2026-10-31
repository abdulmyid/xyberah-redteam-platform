from collections.abc import Iterator

from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

engine = create_engine(get_settings().db_url, connect_args={"check_same_thread": False})


def init_db() -> None:
    from . import models  # noqa: F401  (registers tables)

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Lightweight SQLite migration: add any model column missing from an existing
    table. create_all() only creates missing tables, not missing columns, so new
    fields on existing tables (e.g. Finding.status) are added here. Safe to re-run."""
    insp = inspect(engine)
    for table in SQLModel.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            coltype = col.type.compile(engine.dialect)
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'
            default = getattr(getattr(col, "default", None), "arg", None)
            if isinstance(default, bool):
                ddl += f" DEFAULT {1 if default else 0}"
            elif isinstance(default, (int, float)):
                ddl += f" DEFAULT {default}"
            elif isinstance(default, str):
                ddl += " DEFAULT '" + default.replace("'", "''") + "'"
            elif not col.nullable:
                ddl += " DEFAULT ''"  # keep NOT NULL add valid on populated tables
            try:
                with engine.begin() as conn:
                    conn.exec_driver_sql(ddl)
            except Exception:  # column race / unsupported add — leave table as-is
                pass


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session

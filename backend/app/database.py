import os
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def create_database(state_dir: Path):
    state_dir.mkdir(parents=True, exist_ok=True)
    url = os.getenv("ALIGNFAIL_DATABASE_URL", f"sqlite:///{(state_dir / 'studio.db').as_posix()}")
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def sqlite_config(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=10000")

    Base.metadata.create_all(engine)
    if "pattern_type" not in {c["name"] for c in inspect(engine).get_columns("pairs")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE pairs ADD COLUMN pattern_type VARCHAR(10) NOT NULL DEFAULT 'unknown'"))
    columns = {c["name"] for c in inspect(engine).get_columns("pairs")}
    additions = {
        "class_label": "VARCHAR(200) NOT NULL DEFAULT ''",
        "modality": "VARCHAR(10) NOT NULL DEFAULT ''",
        "match_result": "VARCHAR(10) NOT NULL DEFAULT 'unknown'",
    }
    for name, definition in additions.items():
        if name not in columns:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE pairs ADD COLUMN {name} {definition}"))
    return engine, sessionmaker(engine, expire_on_commit=False)


def session_dependency(factory):
    """FastAPI dependency yielding one ORM session per request."""

    def session():
        with factory() as db:
            yield db

    return session

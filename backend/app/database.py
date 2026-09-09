import os
from pathlib import Path

from sqlalchemy import create_engine, event
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
    return engine, sessionmaker(engine, expire_on_commit=False)

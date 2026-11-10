from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _engine():
    url_text = get_settings().database_url
    parsed_url = make_url(url_text)
    kwargs = {"connect_args": {"check_same_thread": False}} if parsed_url.drivername.startswith("sqlite") else {}

    if parsed_url.drivername.startswith("sqlite") and parsed_url.database not in (None, "", ":memory:"):
        database_path = Path(parsed_url.database).expanduser()
        database_path.parent.mkdir(parents=True, exist_ok=True)

    return create_engine(url_text, future=True, pool_pre_ping=True, **kwargs)


engine = _engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

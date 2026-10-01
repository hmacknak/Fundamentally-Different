"""Engine/session construction. SQLite by default; swap DATABASE_URL for
PostgreSQL in production without touching the models (see docs/DATA_ARCHITECTURE.md)."""
from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def get_engine(database_url: str) -> Engine:
    # A bare "postgresql://" URL leaves the DBAPI driver to SQLAlchemy's
    # default resolution, which has changed versions-to-version (SQLAlchemy
    # 2.1 started preferring psycopg (v3) over psycopg2, while this project
    # only installs psycopg2-binary -- caught when a routine `pip install`
    # picked up a newer SQLAlchemy and the scheduled report run started
    # failing with `ModuleNotFoundError: No module named 'psycopg'`).
    # Pinning the driver in the URL itself makes this independent of
    # whatever SQLAlchemy version happens to be installed.
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def init_db(database_url: str) -> Engine:
    """Create all tables if they don't already exist. Idempotent."""
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    return engine


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)

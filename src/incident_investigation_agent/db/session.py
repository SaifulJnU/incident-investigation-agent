"""Database engine and sessions."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


def session_factory_from_url(url: str) -> sessionmaker[Session]:
    engine = create_engine(url, pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False)


def database_ready(factory: sessionmaker[Session]) -> bool:
    try:
        with factory() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

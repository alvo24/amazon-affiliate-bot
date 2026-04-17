"""Database engine and session helpers."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


def _make_engine():
    url = get_settings().database_url
    if url.startswith("sqlite"):
        # Ensure parent directory exists for file-backed SQLite.
        path_part = url.split("sqlite:///", 1)[-1]
        if path_part and path_part != ":memory:":
            Path(os.path.dirname(path_part) or ".").mkdir(parents=True, exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url)


engine = _make_engine()


def init_db() -> None:
    """Create all tables. Safe to call repeatedly."""
    # Ensure models are imported so SQLModel.metadata knows about them.
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session

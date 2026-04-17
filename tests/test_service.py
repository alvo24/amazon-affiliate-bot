"""End-to-end test of the service in dry-run mode (no external calls)."""

from __future__ import annotations

import pytest
from sqlmodel import Session, select

from app.config import Settings
from app.db import init_db
from app.models import Post, Product, RunLog
from app.service import run_once


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    # Rebuild the engine with the patched URL.
    from app import db as db_module

    new_engine = db_module.create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr(db_module, "engine", new_engine)

    import app.service as service_module

    monkeypatch.setattr(service_module, "engine", new_engine)

    from sqlmodel import SQLModel

    SQLModel.metadata.create_all(new_engine)
    yield


@pytest.mark.asyncio
async def test_run_once_in_dry_run_records_products_and_skipped_posts():
    settings = Settings(
        dry_run=True,
        amazon_partner_tag="mytag-20",
        amazon_max_items=2,
        enabled_platforms="facebook,instagram,pinterest",
    )

    summary = await run_once(settings)

    assert summary["products_fetched"] == 2
    # 2 products * 3 platforms = 6 attempts, all skipped in dry-run
    assert summary["posts_attempted"] == 6
    assert summary["posts_skipped"] == 6
    assert summary["posts_succeeded"] == 0
    assert summary["posts_failed"] == 0

    from app.db import engine as current_engine

    with Session(current_engine) as session:
        products = session.exec(select(Product)).all()
        posts = session.exec(select(Post)).all()
        runs = session.exec(select(RunLog)).all()

    assert len(products) == 2
    assert len(posts) == 6
    assert all(p.status == "skipped" for p in posts)
    assert len(runs) == 1 and runs[0].finished_at is not None


# Ensure init_db is exercised (does not raise).
def test_init_db_idempotent():
    init_db()
    init_db()

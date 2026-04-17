"""Database models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class Product(SQLModel, table=True):
    """A product fetched from Amazon PA-API."""

    asin: str = Field(primary_key=True)
    title: str
    price: str | None = None
    image_url: str | None = None
    detail_url: str
    affiliate_url: str
    features: str | None = None  # newline-separated bullet features
    browse_node: str | None = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class Post(SQLModel, table=True):
    """Record of a single social media post attempt."""

    id: int | None = Field(default=None, primary_key=True)
    asin: str = Field(foreign_key="product.asin", index=True)
    platform: str  # facebook | instagram | pinterest
    status: str  # success | failed | skipped
    remote_id: str | None = None  # ID of the post on the remote platform
    message: str | None = None  # error message or response snippet
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class RunLog(SQLModel, table=True):
    """Record of a scheduler run."""

    id: int | None = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    finished_at: datetime | None = None
    products_fetched: int = 0
    posts_attempted: int = 0
    posts_succeeded: int = 0
    posts_failed: int = 0
    error: str | None = None


class SettingOverride(SQLModel, table=True):
    """Runtime-editable override for a value that's otherwise env-driven.

    Values stored here take precedence over the corresponding env var so the
    user can paste credentials through the in-app Settings page without needing
    shell access or a redeploy.
    """

    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)

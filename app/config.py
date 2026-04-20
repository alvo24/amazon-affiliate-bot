"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from a .env file or process environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_secret: str = "change-me"
    app_admin_password: str = "change-me"
    database_url: str = "sqlite:///./data/app.db"
    log_level: str = "INFO"
    dry_run: bool = True

    # Amazon PA-API
    amazon_access_key: str = ""
    amazon_secret_key: str = ""
    amazon_partner_tag: str = ""
    amazon_host: str = "www.amazon.com"
    amazon_region: str = "us-east-1"
    amazon_browse_nodes: str = ""
    amazon_max_items: int = 10

    # Facebook
    facebook_page_id: str = ""
    facebook_page_access_token: str = ""

    # Instagram
    instagram_business_account_id: str = ""
    instagram_access_token: str = ""

    # Pinterest
    pinterest_access_token: str = ""
    pinterest_board_id: str = ""

    # Twitter / X (OAuth 1.0a user context)
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_token_secret: str = ""

    # Scheduling
    post_schedule_cron: str = "0 9,13,18 * * *"
    timezone: str = "UTC"

    # Content generator (optional OpenAI upgrade)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Posting
    caption_template: str = (
        "🔥 {title}\n\n💰 {price}\n\n{features}\n\n"
        "👉 Shop here: {url}\n\n#amazonfinds #affiliate #shopping"
    )
    enabled_platforms: str = "facebook,instagram,pinterest,twitter"

    # ---- Derived helpers ----

    @property
    def browse_node_list(self) -> list[str]:
        return [node.strip() for node in self.amazon_browse_nodes.split(",") if node.strip()]

    @property
    def platform_list(self) -> list[str]:
        return [p.strip().lower() for p in self.enabled_platforms.split(",") if p.strip()]

    def amazon_configured(self) -> bool:
        return bool(self.amazon_access_key and self.amazon_secret_key and self.amazon_partner_tag)

    def facebook_configured(self) -> bool:
        return bool(self.facebook_page_id and self.facebook_page_access_token)

    def instagram_configured(self) -> bool:
        return bool(self.instagram_business_account_id and self.instagram_access_token)

    def pinterest_configured(self) -> bool:
        return bool(self.pinterest_access_token and self.pinterest_board_id)

    def twitter_configured(self) -> bool:
        return bool(
            self.twitter_api_key
            and self.twitter_api_secret
            and self.twitter_access_token
            and self.twitter_access_token_secret
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings singleton (env only, no DB overrides)."""
    return Settings()


# Keys writable from the in-app Settings page. Booleans are stored as "true"/"false".
OVERRIDABLE_KEYS: tuple[str, ...] = (
    "dry_run",
    "app_admin_password",
    "amazon_access_key",
    "amazon_secret_key",
    "amazon_partner_tag",
    "amazon_host",
    "amazon_browse_nodes",
    "facebook_page_id",
    "facebook_page_access_token",
    "instagram_business_account_id",
    "instagram_access_token",
    "pinterest_access_token",
    "pinterest_board_id",
    "twitter_api_key",
    "twitter_api_secret",
    "twitter_access_token",
    "twitter_access_token_secret",
    "post_schedule_cron",
    "timezone",
    "caption_template",
    "enabled_platforms",
    "openai_api_key",
    "openai_model",
)

SECRET_KEYS: frozenset[str] = frozenset({
    "app_admin_password",
    "amazon_secret_key",
    "facebook_page_access_token",
    "instagram_access_token",
    "pinterest_access_token",
    "twitter_api_secret",
    "twitter_access_token_secret",
    "openai_api_key",
})


def _coerce(key: str, value: str):
    """Coerce a stored string value to the type expected by the Settings model."""
    if key == "dry_run":
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return value


def load_overrides() -> dict[str, object]:
    """Read all persisted overrides from the DB as a {key: coerced_value} dict."""
    # Imported lazily to avoid a config<->db import cycle.
    from sqlmodel import Session, select

    from app.db import engine
    from app.models import SettingOverride

    with Session(engine) as session:
        rows = session.exec(select(SettingOverride)).all()
    return {
        row.key: _coerce(row.key, row.value)
        for row in rows
        if row.key in OVERRIDABLE_KEYS
    }


def get_effective_settings() -> Settings:
    """Return a Settings instance with DB overrides layered on top of env."""
    base = get_settings()
    overrides = load_overrides()
    if not overrides:
        return base
    return base.model_copy(update=overrides)

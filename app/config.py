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

    # Scheduling
    post_schedule_cron: str = "0 9,13,18 * * *"
    timezone: str = "UTC"

    # Posting
    caption_template: str = (
        "🔥 {title}\n\n💰 {price}\n\n{features}\n\n"
        "👉 Shop here: {url}\n\n#amazonfinds #affiliate #shopping"
    )
    enabled_platforms: str = "facebook,instagram,pinterest"

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings singleton."""
    return Settings()

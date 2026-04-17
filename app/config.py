"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Literal strings that ship in `.env.example` / the README. If an operator leaves
# them unchanged we fail startup rather than expose session forgery or a known
# admin password to the public internet.
INSECURE_DEFAULT_SECRET = "change-me"  # noqa: S105  # sentinel, not a secret
INSECURE_DEFAULT_PASSWORD = "change-me"  # noqa: S105  # sentinel, not a secret
INSECURE_DEFAULT_LEGACY = "change-me-to-a-long-random-string"  # noqa: S105


class Settings(BaseSettings):
    """Settings loaded from a .env file or process environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_secret: str = INSECURE_DEFAULT_SECRET
    app_admin_password: str = INSECURE_DEFAULT_PASSWORD
    database_url: str = "sqlite:///./data/app.db"
    log_level: str = "INFO"
    dry_run: bool = True
    # Mark session cookies Secure. Defaults to ``True`` in production;
    # override via env if you intentionally run over plain HTTP locally.
    cookie_secure: bool = True
    # Lifetime of the admin session cookie, in seconds (default: 14 days).
    session_max_age: int = 14 * 24 * 60 * 60

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
    """Return cached Settings singleton (env only, no DB overrides)."""
    return Settings()


# Secret values that are considered "operator forgot to change this" and must
# be replaced before the app is allowed to serve traffic.
_INSECURE_SECRET_SENTINELS: frozenset[str] = frozenset({
    INSECURE_DEFAULT_SECRET,
    INSECURE_DEFAULT_LEGACY,
    "",
})
_INSECURE_PASSWORD_SENTINELS: frozenset[str] = frozenset({
    INSECURE_DEFAULT_PASSWORD,
    "",
})


class InsecureConfigurationError(RuntimeError):
    """Raised when Settings still contain one of the ``.env.example`` placeholders."""


def validate_production_settings(settings: Settings) -> None:
    """Fail fast when the app is about to serve traffic with unsafe defaults.

    We block startup on two conditions:

    * ``app_secret`` is empty or still set to a known placeholder. Serving
      traffic with a known signing key lets anyone forge an admin session.
    * ``app_admin_password`` is empty or still the known placeholder. An
      attacker who can reach the login page can trivially log in.

    Errors are raised synchronously so platform health checks fail loudly
    instead of silently running with a trivially bypassable admin.
    """
    problems: list[str] = []
    if settings.app_secret in _INSECURE_SECRET_SENTINELS:
        problems.append(
            "APP_SECRET is empty or still set to the `.env.example` placeholder. "
            "Set it to a long random string (e.g. `python -c 'import secrets; "
            "print(secrets.token_urlsafe(64))'`)."
        )
    if settings.app_admin_password in _INSECURE_PASSWORD_SENTINELS:
        problems.append(
            "APP_ADMIN_PASSWORD is empty or still `change-me`. Choose a strong "
            "password before exposing the dashboard."
        )
    if problems:
        raise InsecureConfigurationError(
            "Refusing to start with unsafe defaults:\n - " + "\n - ".join(problems)
        )


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
    "post_schedule_cron",
    "timezone",
    "caption_template",
    "enabled_platforms",
)

SECRET_KEYS: frozenset[str] = frozenset({
    "app_admin_password",
    "amazon_secret_key",
    "facebook_page_access_token",
    "instagram_access_token",
    "pinterest_access_token",
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

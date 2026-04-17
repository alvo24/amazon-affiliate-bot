"""Base publisher interface."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.amazon import ProductInfo
from app.config import Settings

# Hard cap we apply to any upstream error body we persist in `Post.message`
# before it's rendered back on the dashboard. 500+ chars was enough room for
# Meta/Pinterest responses to occasionally echo the query string (including
# the bearer token) back at us.
_ERROR_BODY_MAX = 200

_ACCESS_TOKEN_RE = re.compile(
    r"""(["']?(?:access_token|access-token|token|bearer)["']?\s*[:=]\s*["']?)[^"'&\s]+""",
    re.IGNORECASE,
)


def sanitize_error_body(body: str | None) -> str | None:
    """Redact anything that looks like an access token before persisting/rendering."""
    if not body:
        return body
    scrubbed = _ACCESS_TOKEN_RE.sub(r"\1[REDACTED]", body)
    return scrubbed[:_ERROR_BODY_MAX]


@dataclass
class PostResult:
    """Outcome of a single publish attempt."""

    status: str  # success | failed | skipped
    remote_id: str | None = None
    message: str | None = None


class Publisher:
    """Base class every social media publisher inherits from."""

    name: str = "base"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        raise NotImplementedError

    def render_caption(self, product: ProductInfo) -> str:
        if product.caption_override:
            return product.caption_override
        features_block = "\n".join(f"• {f}" for f in product.features[:3])
        template = self.settings.caption_template.replace("\\n", "\n")
        return template.format(
            title=product.title,
            price=product.price or "See price on Amazon",
            url=product.affiliate_url,
            features=features_block,
        )

    async def publish(self, product: ProductInfo) -> PostResult:
        raise NotImplementedError

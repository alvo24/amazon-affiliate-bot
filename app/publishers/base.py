"""Base publisher interface."""

from __future__ import annotations

from dataclasses import dataclass

from app.amazon import ProductInfo
from app.config import Settings


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

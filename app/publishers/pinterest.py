"""Pinterest publisher using Pinterest API v5."""

from __future__ import annotations

import logging

import httpx

from app.amazon import ProductInfo
from app.publishers.base import PostResult, Publisher, sanitize_error_body

logger = logging.getLogger(__name__)

PINTEREST_API = "https://api.pinterest.com/v5"


class PinterestPublisher(Publisher):
    name = "pinterest"

    def is_configured(self) -> bool:
        return self.settings.pinterest_configured()

    async def publish(self, product: ProductInfo) -> PostResult:
        if self.settings.dry_run:
            logger.info("[DRY_RUN] Would post to Pinterest: %s", product.title)
            return PostResult(status="skipped", message="dry_run")
        if not self.is_configured():
            return PostResult(status="skipped", message="pinterest not configured")
        if not product.image_url:
            return PostResult(status="skipped", message="pinterest requires an image_url")

        caption = self.render_caption(product)
        # Pinterest truncates titles at ~100 chars; keep it short.
        title = product.title[:97] + "..." if len(product.title) > 100 else product.title

        body = {
            "board_id": self.settings.pinterest_board_id,
            "title": title,
            "description": caption[:800],
            "link": product.affiliate_url,
            "media_source": {
                "source_type": "image_url",
                "url": product.image_url,
            },
        }
        headers = {
            "Authorization": f"Bearer {self.settings.pinterest_access_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(f"{PINTEREST_API}/pins", json=body, headers=headers)
            if resp.status_code >= 400:
                return PostResult(status="failed", message=sanitize_error_body(resp.text))
            remote_id = resp.json().get("id")
            return PostResult(status="success", remote_id=remote_id)
        except httpx.HTTPError as exc:
            logger.exception("Pinterest post failed")
            return PostResult(status="failed", message=str(exc))

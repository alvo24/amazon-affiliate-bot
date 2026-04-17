"""Facebook Page publisher using Meta Graph API."""

from __future__ import annotations

import logging

import httpx

from app.amazon import ProductInfo
from app.publishers.base import PostResult, Publisher, sanitize_error_body

logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v20.0"


class FacebookPublisher(Publisher):
    name = "facebook"

    def is_configured(self) -> bool:
        return self.settings.facebook_configured()

    async def publish(self, product: ProductInfo) -> PostResult:
        if self.settings.dry_run:
            logger.info("[DRY_RUN] Would post to Facebook: %s", product.title)
            return PostResult(status="skipped", message="dry_run")
        if not self.is_configured():
            return PostResult(status="skipped", message="facebook not configured")

        caption = self.render_caption(product)
        url = f"{GRAPH_API}/{self.settings.facebook_page_id}/photos"
        data = {
            "url": product.image_url or "",
            "caption": caption,
            "access_token": self.settings.facebook_page_access_token,
        }

        # If no image, fall back to a link post.
        if not product.image_url:
            url = f"{GRAPH_API}/{self.settings.facebook_page_id}/feed"
            data = {
                "message": caption,
                "link": product.affiliate_url,
                "access_token": self.settings.facebook_page_access_token,
            }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, data=data)
            if resp.status_code >= 400:
                return PostResult(status="failed", message=sanitize_error_body(resp.text))
            payload = resp.json()
            remote_id = payload.get("post_id") or payload.get("id")
            return PostResult(status="success", remote_id=remote_id)
        except httpx.HTTPError as exc:
            logger.exception("Facebook post failed")
            return PostResult(status="failed", message=str(exc))

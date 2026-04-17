"""Instagram Business publisher (requires an IG Business account via the Graph API)."""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.amazon import ProductInfo
from app.publishers.base import PostResult, Publisher

logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v20.0"


class InstagramPublisher(Publisher):
    name = "instagram"

    def is_configured(self) -> bool:
        return self.settings.instagram_configured()

    async def publish(self, product: ProductInfo) -> PostResult:
        if self.settings.dry_run:
            logger.info("[DRY_RUN] Would post to Instagram: %s", product.title)
            return PostResult(status="skipped", message="dry_run")
        if not self.is_configured():
            return PostResult(status="skipped", message="instagram not configured")
        if not product.image_url:
            return PostResult(status="skipped", message="instagram requires an image_url")

        caption = self.render_caption(product)
        account = self.settings.instagram_business_account_id
        token = self.settings.instagram_access_token

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                # 1. Create media container
                create = await client.post(
                    f"{GRAPH_API}/{account}/media",
                    data={
                        "image_url": product.image_url,
                        "caption": caption,
                        "access_token": token,
                    },
                )
                if create.status_code >= 400:
                    return PostResult(status="failed", message=create.text[:500])
                creation_id = create.json().get("id")
                if not creation_id:
                    return PostResult(status="failed", message="no creation id returned")

                # 2. Poll for container to be ready
                for _ in range(10):
                    await asyncio.sleep(3)
                    status_resp = await client.get(
                        f"{GRAPH_API}/{creation_id}",
                        params={"fields": "status_code", "access_token": token},
                    )
                    if status_resp.status_code >= 400:
                        return PostResult(status="failed", message=status_resp.text[:500])
                    if status_resp.json().get("status_code") == "FINISHED":
                        break

                # 3. Publish container
                publish = await client.post(
                    f"{GRAPH_API}/{account}/media_publish",
                    data={"creation_id": creation_id, "access_token": token},
                )
                if publish.status_code >= 400:
                    return PostResult(status="failed", message=publish.text[:500])
                remote_id = publish.json().get("id")
                return PostResult(status="success", remote_id=remote_id)
        except httpx.HTTPError as exc:
            logger.exception("Instagram post failed")
            return PostResult(status="failed", message=str(exc))

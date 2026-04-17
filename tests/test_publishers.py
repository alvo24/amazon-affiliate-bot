"""Tests for publisher behaviour."""

from __future__ import annotations

import pytest

from app.amazon import ProductInfo
from app.config import Settings
from app.publishers import FacebookPublisher, InstagramPublisher, PinterestPublisher


def _product() -> ProductInfo:
    return ProductInfo(
        asin="B0TEST",
        title="Cool Gadget",
        price="$19.99",
        image_url="https://example.com/image.jpg",
        detail_url="https://www.amazon.com/dp/B0TEST",
        affiliate_url="https://www.amazon.com/dp/B0TEST?tag=mytag-20",
        features=["Feature 1", "Feature 2", "Feature 3", "Feature 4"],
    )


def test_render_caption_uses_template_and_first_three_features():
    settings = Settings(caption_template="{title} | {price} | {features} | {url}")
    pub = FacebookPublisher(settings)
    caption = pub.render_caption(_product())

    assert "Cool Gadget" in caption
    assert "$19.99" in caption
    assert "Feature 1" in caption
    assert "Feature 3" in caption
    # Only first three features should be rendered.
    assert "Feature 4" not in caption
    assert "tag=mytag-20" in caption


def test_render_caption_handles_literal_newlines_in_template():
    settings = Settings(caption_template="{title}\\n\\n{url}")
    pub = FacebookPublisher(settings)
    caption = pub.render_caption(_product())
    assert "Cool Gadget\n\n" in caption


@pytest.mark.asyncio
async def test_publishers_dry_run_returns_skipped():
    settings = Settings(dry_run=True)
    product = _product()
    for pub_cls in (FacebookPublisher, InstagramPublisher, PinterestPublisher):
        result = await pub_cls(settings).publish(product)
        assert result.status == "skipped"
        assert result.message == "dry_run"


@pytest.mark.asyncio
async def test_publishers_skip_when_not_configured():
    settings = Settings(dry_run=False)  # no tokens
    product = _product()
    for pub_cls in (FacebookPublisher, InstagramPublisher, PinterestPublisher):
        result = await pub_cls(settings).publish(product)
        assert result.status == "skipped"
        assert "not configured" in (result.message or "")

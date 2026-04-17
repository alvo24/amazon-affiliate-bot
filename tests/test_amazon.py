"""Tests for the Amazon client (mock mode) and affiliate-link helper."""

from __future__ import annotations

from app.amazon import AmazonClient, build_affiliate_url
from app.config import Settings


def test_build_affiliate_url_appends_tag():
    url = build_affiliate_url("https://www.amazon.com/dp/B0TEST", "myTag-20")
    assert url == "https://www.amazon.com/dp/B0TEST?tag=myTag-20"


def test_build_affiliate_url_preserves_existing_query():
    url = build_affiliate_url("https://www.amazon.com/dp/B0TEST?ref=sr_1", "myTag-20")
    assert url == "https://www.amazon.com/dp/B0TEST?ref=sr_1&tag=myTag-20"


def test_build_affiliate_url_no_tag_returns_original():
    original = "https://www.amazon.com/dp/B0TEST"
    assert build_affiliate_url(original, "") == original


def test_fetch_bestsellers_returns_mock_products_when_not_configured():
    settings = Settings(dry_run=True, amazon_partner_tag="mytag-20", amazon_max_items=3)
    client = AmazonClient(settings)

    assert client.is_live() is False
    products = client.fetch_bestsellers()

    assert len(products) == 3
    for p in products:
        assert p.asin
        assert p.title
        assert p.affiliate_url.endswith("tag=mytag-20")


def test_amazon_client_requires_both_keys_and_disabled_dry_run_to_go_live():
    live_settings = Settings(
        dry_run=False,
        amazon_access_key="k",
        amazon_secret_key="s",
        amazon_partner_tag="t-20",
    )
    assert AmazonClient(live_settings).is_live() is True

    # Missing credentials -> not live even with DRY_RUN=false
    partial = Settings(dry_run=False, amazon_access_key="k")
    assert AmazonClient(partial).is_live() is False

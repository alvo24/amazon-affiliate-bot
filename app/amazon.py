"""Amazon Product Advertising API (PA-API 5.0) client.

Uses the official ``paapi5-python-sdk`` when credentials are configured, and falls
back to a deterministic mock dataset when ``DRY_RUN`` is enabled or credentials
are missing. This lets the rest of the bot be developed and tested before the
user is approved for PA-API access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class ProductInfo:
    """Normalized product data used across the app."""

    asin: str
    title: str
    price: str | None
    image_url: str | None
    detail_url: str
    affiliate_url: str
    features: list[str]
    browse_node: str | None = None
    caption_override: str | None = None  # when set, publishers skip the template


def build_affiliate_url(detail_url: str, partner_tag: str) -> str:
    """Append the Amazon Associates ``tag`` query parameter to a product URL."""
    if not partner_tag:
        return detail_url
    sep = "&" if "?" in detail_url else "?"
    return f"{detail_url}{sep}tag={quote_plus(partner_tag)}"


# --------------------------------------------------------------------------- #
# Mock data
# --------------------------------------------------------------------------- #

_MOCK_PRODUCTS: list[dict[str, Any]] = [
    {
        "asin": "B08N5WRWNW",
        "title": "Echo Dot (4th Gen) Smart Speaker with Alexa",
        "price": "$29.99",
        "image_url": "https://m.media-amazon.com/images/I/61MZzA4tA3L._AC_SL1000_.jpg",
        "detail_url": "https://www.amazon.com/dp/B08N5WRWNW",
        "features": [
            "Meet the Echo Dot - our most popular smart speaker",
            "Voice control your entertainment",
            "Ready to help around the house",
        ],
    },
    {
        "asin": "B09B8V1LZ3",
        "title": "Apple AirPods Pro (2nd Generation) Wireless Earbuds",
        "price": "$199.00",
        "image_url": "https://m.media-amazon.com/images/I/61SUj2aKoEL._AC_SL1500_.jpg",
        "detail_url": "https://www.amazon.com/dp/B09B8V1LZ3",
        "features": [
            "Up to 2x more Active Noise Cancellation",
            "Adaptive Transparency mode",
            "Personalized Spatial Audio with dynamic head tracking",
        ],
    },
    {
        "asin": "B07FZ8S74R",
        "title": "Instant Pot Duo 7-in-1 Electric Pressure Cooker",
        "price": "$89.99",
        "image_url": "https://m.media-amazon.com/images/I/71WbdzLaXoL._AC_SL1500_.jpg",
        "detail_url": "https://www.amazon.com/dp/B07FZ8S74R",
        "features": [
            "7-in-1 functionality",
            "Stainless steel cooking pot",
            "13 customizable smart programs",
        ],
    },
    {
        "asin": "B0B5F4V4S4",
        "title": "Fire TV Stick 4K Max streaming device",
        "price": "$54.99",
        "image_url": "https://m.media-amazon.com/images/I/51c+tPZ1XmL._AC_SL1000_.jpg",
        "detail_url": "https://www.amazon.com/dp/B0B5F4V4S4",
        "features": [
            "Our most powerful streaming stick",
            "Wi-Fi 6 support",
            "Dolby Vision, HDR, HDR10+",
        ],
    },
    {
        "asin": "B07VGRJDFY",
        "title": "Anker Portable Charger 10000mAh Power Bank",
        "price": "$21.99",
        "image_url": "https://m.media-amazon.com/images/I/61bKiLRAwcL._AC_SL1500_.jpg",
        "detail_url": "https://www.amazon.com/dp/B07VGRJDFY",
        "features": [
            "Ultra-compact 10000mAh power bank",
            "PowerIQ high-speed charging",
            "MultiProtect safety system",
        ],
    },
]


def _mock_products(settings: Settings) -> list[ProductInfo]:
    tag = settings.amazon_partner_tag or "example-20"
    items: list[ProductInfo] = []
    for raw in _MOCK_PRODUCTS[: settings.amazon_max_items]:
        items.append(
            ProductInfo(
                asin=raw["asin"],
                title=raw["title"],
                price=raw["price"],
                image_url=raw["image_url"],
                detail_url=raw["detail_url"],
                affiliate_url=build_affiliate_url(raw["detail_url"], tag),
                features=list(raw["features"]),
                browse_node="mock",
            )
        )
    return items


# --------------------------------------------------------------------------- #
# Real PA-API client
# --------------------------------------------------------------------------- #


class AmazonClient:
    """Thin wrapper around the PA-API 5 SDK."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def is_live(self) -> bool:
        """Return True when real PA-API calls should be made."""
        return self.settings.amazon_configured() and not self.settings.dry_run

    def fetch_bestsellers(self) -> list[ProductInfo]:
        """Return a list of bestselling products across configured browse nodes."""
        if not self.is_live():
            logger.info("Amazon client running in mock mode (dry_run=%s)", self.settings.dry_run)
            return _mock_products(self.settings)

        return self._fetch_live()

    # ------------------------------------------------------------------ #
    # Live PA-API path
    # ------------------------------------------------------------------ #

    def _fetch_live(self) -> list[ProductInfo]:  # pragma: no cover - needs network + keys
        try:
            from amazon_paapi import AmazonApi
        except ImportError as exc:
            raise RuntimeError(
                "python-amazon-paapi is not installed; cannot run in live mode"
            ) from exc

        country = _host_to_country(self.settings.amazon_host)
        api = AmazonApi(
            self.settings.amazon_access_key,
            self.settings.amazon_secret_key,
            self.settings.amazon_partner_tag,
            country,
        )

        browse_nodes = self.settings.browse_node_list or [None]
        per_node = max(1, self.settings.amazon_max_items // max(1, len(browse_nodes)))
        products: list[ProductInfo] = []

        for node in browse_nodes:
            kwargs = {"keywords": "bestseller", "item_count": per_node}
            if node:
                kwargs["browse_node_id"] = node
                kwargs["sort_by"] = "AvgCustomerReviews"

            try:
                response = api.search_items(**kwargs)
            except Exception as exc:
                logger.exception("PA-API SearchItems failed for node %s: %s", node, exc)
                continue

            items = getattr(response, "items", None) or []
            if not items:
                logger.warning("PA-API returned no items for browse node %s", node)
                continue

            for item in items:
                try:
                    products.append(self._item_to_product(item, node))
                except Exception as exc:  # defensive: skip malformed items
                    logger.warning("Skipping malformed PA-API item: %s", exc)

        return products[: self.settings.amazon_max_items]

    def _item_to_product(self, item: Any, browse_node: str | None) -> ProductInfo:
        asin = getattr(item, "asin", None) or ""
        title = asin
        features: list[str] = []
        price: str | None = None
        image_url: str | None = None

        item_info = getattr(item, "item_info", None)
        if item_info:
            if getattr(item_info, "title", None) and getattr(item_info.title, "display_value", None):
                title = item_info.title.display_value
            features_obj = getattr(item_info, "features", None)
            if features_obj and getattr(features_obj, "display_values", None):
                features = list(features_obj.display_values)

        offers = getattr(item, "offers", None)
        listings = getattr(offers, "listings", None) if offers else None
        if listings:
            listing_price = getattr(listings[0], "price", None)
            display = getattr(listing_price, "display_amount", None) if listing_price else None
            if display:
                price = display

        images = getattr(item, "images", None)
        primary = getattr(images, "primary", None) if images else None
        large = getattr(primary, "large", None) if primary else None
        if large and getattr(large, "url", None):
            image_url = large.url

        detail_url = getattr(item, "detail_page_url", None) or f"https://{self.settings.amazon_host}/dp/{asin}"
        affiliate_url = build_affiliate_url(detail_url, self.settings.amazon_partner_tag)

        return ProductInfo(
            asin=asin,
            title=title,
            price=price,
            image_url=image_url,
            detail_url=detail_url,
            affiliate_url=affiliate_url,
            features=features,
            browse_node=browse_node or None,
        )


_HOST_TO_COUNTRY = {
    "www.amazon.com": "US",
    "www.amazon.co.uk": "UK",
    "www.amazon.de": "DE",
    "www.amazon.fr": "FR",
    "www.amazon.it": "IT",
    "www.amazon.es": "ES",
    "www.amazon.ca": "CA",
    "www.amazon.com.mx": "MX",
    "www.amazon.com.br": "BR",
    "www.amazon.com.au": "AU",
    "www.amazon.co.jp": "JP",
    "www.amazon.in": "IN",
    "www.amazon.ae": "AE",
    "www.amazon.sa": "SA",
    "www.amazon.se": "SE",
    "www.amazon.pl": "PL",
    "www.amazon.nl": "NL",
    "www.amazon.sg": "SG",
    "www.amazon.com.tr": "TR",
}


def _host_to_country(host: str) -> str:
    return _HOST_TO_COUNTRY.get(host.lower().strip(), "US")

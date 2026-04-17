"""Single-file Amazon affiliate bot — designed for Pydroid 3 on Android.

Usage:
    1. Install Pydroid 3 from the Play Store.
    2. Menu → Pip → install: python-amazon-paapi  (only needed when DRY_RUN=False)
    3. Open this file in Pydroid.
    4. Edit the CONFIG section below with your credentials.
    5. Tap ▶ to run. The bot will fetch bestsellers and post to Facebook / Instagram /
       Pinterest one time per tap. No scheduler — just tap whenever you want to post.

To schedule it to run automatically, use the Fly.io deployment in README.md instead.
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.parse
import urllib.request

# ============================================================================
# CONFIG — edit these, then tap ▶
# ============================================================================

# Set to False once all credentials are filled in.
DRY_RUN = True

# --- Amazon Associates / Product Advertising API ---
AMAZON_ACCESS_KEY = ""
AMAZON_SECRET_KEY = ""
AMAZON_PARTNER_TAG = ""          # e.g. "yourname-20"
AMAZON_COUNTRY = "US"            # "US", "UK", "DE", "IN", "CA", "AU", "JP", etc.
AMAZON_BROWSE_NODES = ["172282"] # Electronics. Find more at browsenodes.com
MAX_ITEMS = 5

# --- Facebook Page (Graph API) ---
FACEBOOK_PAGE_ID = ""
FACEBOOK_PAGE_ACCESS_TOKEN = ""

# --- Instagram Business (Graph API; must be linked to a FB Page) ---
INSTAGRAM_BUSINESS_ACCOUNT_ID = ""
INSTAGRAM_ACCESS_TOKEN = ""

# --- Pinterest (API v5) ---
PINTEREST_ACCESS_TOKEN = ""
PINTEREST_BOARD_ID = ""

CAPTION_TEMPLATE = (
    "🔥 {title}\n\n"
    "💰 {price}\n\n"
    "{features}\n\n"
    "👉 Shop here: {url}\n\n"
    "#amazonfinds #affiliate #shopping"
)

# Which platforms to post to. Remove any you don't want.
ENABLED_PLATFORMS = ("facebook", "instagram", "pinterest")

# ============================================================================
# End of config — no need to edit below this line
# ============================================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pydroid-bot")


# ----------------------------------------------------------------------------
# Mock data for dry-run
# ----------------------------------------------------------------------------

_MOCK = [
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


# ----------------------------------------------------------------------------
# Tiny HTTP helpers (std-lib only)
# ----------------------------------------------------------------------------


def _http_request(method, url, data=None, headers=None, timeout=60):
    """Return (status_code, body_str). Never raises on HTTP errors."""
    headers = dict(headers or {})
    body: bytes | None = None
    if data is not None:
        if isinstance(data, dict) and headers.get("Content-Type", "").startswith("application/json"):
            body = json.dumps(data).encode("utf-8")
        elif isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode("utf-8")
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif isinstance(data, (bytes, bytearray)):
            body = bytes(data)
        elif isinstance(data, str):
            body = data.encode("utf-8")

    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return 0, f"URLError: {exc.reason}"


def http_get(url, headers=None, params=None):
    if params:
        q = urllib.parse.urlencode(params)
        url = f"{url}?{q}" if "?" not in url else f"{url}&{q}"
    return _http_request("GET", url, headers=headers)


def http_post_form(url, data, headers=None):
    return _http_request("POST", url, data=data, headers=headers)


def http_post_json(url, data, headers=None):
    h = dict(headers or {})
    h["Content-Type"] = "application/json"
    return _http_request("POST", url, data=data, headers=h)


# ----------------------------------------------------------------------------
# Amazon product fetching
# ----------------------------------------------------------------------------


def build_affiliate_url(detail_url: str, tag: str) -> str:
    if not tag:
        return detail_url
    sep = "&" if "?" in detail_url else "?"
    return f"{detail_url}{sep}tag={urllib.parse.quote_plus(tag)}"


def fetch_mock_products():
    tag = AMAZON_PARTNER_TAG or "example-20"
    out = []
    for raw in _MOCK[:MAX_ITEMS]:
        out.append({
            **raw,
            "affiliate_url": build_affiliate_url(raw["detail_url"], tag),
        })
    return out


def fetch_live_products():
    try:
        from amazon_paapi import AmazonApi  # type: ignore
    except ImportError:
        log.error("python-amazon-paapi not installed. In Pydroid: menu → Pip → install python-amazon-paapi")
        return []

    api = AmazonApi(
        AMAZON_ACCESS_KEY, AMAZON_SECRET_KEY, AMAZON_PARTNER_TAG, AMAZON_COUNTRY
    )
    products = []
    nodes = AMAZON_BROWSE_NODES or [None]
    per_node = max(1, MAX_ITEMS // max(1, len(nodes)))

    for node in nodes:
        kwargs = {"keywords": "bestseller", "item_count": per_node}
        if node:
            kwargs["browse_node_id"] = node
            kwargs["sort_by"] = "AvgCustomerReviews"
        try:
            resp = api.search_items(**kwargs)
        except Exception as exc:
            log.error("PA-API search failed for node %s: %s", node, exc)
            continue

        items = getattr(resp, "items", None) or []
        for item in items:
            try:
                asin = getattr(item, "asin", "") or ""
                title = asin
                features: list[str] = []
                price = None
                image_url = None

                info = getattr(item, "item_info", None)
                if info:
                    t = getattr(info, "title", None)
                    if t and getattr(t, "display_value", None):
                        title = t.display_value
                    f = getattr(info, "features", None)
                    if f and getattr(f, "display_values", None):
                        features = list(f.display_values)
                offers = getattr(item, "offers", None)
                listings = getattr(offers, "listings", None) if offers else None
                if listings:
                    pr = getattr(listings[0], "price", None)
                    if pr and getattr(pr, "display_amount", None):
                        price = pr.display_amount
                images = getattr(item, "images", None)
                primary = getattr(images, "primary", None) if images else None
                large = getattr(primary, "large", None) if primary else None
                if large and getattr(large, "url", None):
                    image_url = large.url

                detail_url = (
                    getattr(item, "detail_page_url", None)
                    or f"https://www.amazon.com/dp/{asin}"
                )
                products.append({
                    "asin": asin,
                    "title": title,
                    "price": price,
                    "image_url": image_url,
                    "detail_url": detail_url,
                    "affiliate_url": build_affiliate_url(detail_url, AMAZON_PARTNER_TAG),
                    "features": features,
                })
            except Exception as exc:
                log.warning("Skipping malformed item: %s", exc)

    return products[:MAX_ITEMS]


def fetch_products():
    if DRY_RUN or not (AMAZON_ACCESS_KEY and AMAZON_SECRET_KEY and AMAZON_PARTNER_TAG):
        log.info("Using mock products (dry-run or Amazon creds missing)")
        return fetch_mock_products()
    log.info("Fetching live products from Amazon PA-API...")
    return fetch_live_products()


# ----------------------------------------------------------------------------
# Captions
# ----------------------------------------------------------------------------


def render_caption(product) -> str:
    features_block = "\n".join(f"• {f}" for f in (product.get("features") or [])[:3])
    return CAPTION_TEMPLATE.format(
        title=product["title"],
        price=product.get("price") or "See price on Amazon",
        features=features_block,
        url=product["affiliate_url"],
    )


# ----------------------------------------------------------------------------
# Publishers
# ----------------------------------------------------------------------------


def post_to_facebook(product) -> str:
    if DRY_RUN:
        log.info("[DRY_RUN] Facebook: %s", product["title"])
        return "skipped: dry_run"
    if not (FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN):
        return "skipped: not configured"

    caption = render_caption(product)
    if product.get("image_url"):
        url = f"https://graph.facebook.com/v20.0/{FACEBOOK_PAGE_ID}/photos"
        data = {
            "url": product["image_url"],
            "caption": caption,
            "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
        }
    else:
        url = f"https://graph.facebook.com/v20.0/{FACEBOOK_PAGE_ID}/feed"
        data = {
            "message": caption,
            "link": product["affiliate_url"],
            "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
        }
    status, body = http_post_form(url, data)
    if status >= 400:
        return f"failed ({status}): {body[:200]}"
    j = json.loads(body) if body else {}
    return f"success: {j.get('post_id') or j.get('id') or 'unknown_id'}"


def post_to_instagram(product) -> str:
    if DRY_RUN:
        log.info("[DRY_RUN] Instagram: %s", product["title"])
        return "skipped: dry_run"
    if not (INSTAGRAM_BUSINESS_ACCOUNT_ID and INSTAGRAM_ACCESS_TOKEN):
        return "skipped: not configured"
    if not product.get("image_url"):
        return "skipped: instagram requires an image"

    caption = render_caption(product)
    account = INSTAGRAM_BUSINESS_ACCOUNT_ID

    # 1. Create container
    status, body = http_post_form(
        f"https://graph.facebook.com/v20.0/{account}/media",
        {
            "image_url": product["image_url"],
            "caption": caption,
            "access_token": INSTAGRAM_ACCESS_TOKEN,
        },
    )
    if status >= 400:
        return f"failed on create ({status}): {body[:200]}"
    creation_id = (json.loads(body) or {}).get("id")
    if not creation_id:
        return "failed: no creation id"

    # 2. Poll container status
    import time as _time
    for _ in range(10):
        _time.sleep(3)
        s, b = http_get(
            f"https://graph.facebook.com/v20.0/{creation_id}",
            params={"fields": "status_code", "access_token": INSTAGRAM_ACCESS_TOKEN},
        )
        if s >= 400:
            return f"failed polling ({s}): {b[:200]}"
        if (json.loads(b) or {}).get("status_code") == "FINISHED":
            break

    # 3. Publish
    s, b = http_post_form(
        f"https://graph.facebook.com/v20.0/{account}/media_publish",
        {"creation_id": creation_id, "access_token": INSTAGRAM_ACCESS_TOKEN},
    )
    if s >= 400:
        return f"failed on publish ({s}): {b[:200]}"
    return f"success: {(json.loads(b) or {}).get('id', 'unknown_id')}"


def post_to_pinterest(product) -> str:
    if DRY_RUN:
        log.info("[DRY_RUN] Pinterest: %s", product["title"])
        return "skipped: dry_run"
    if not (PINTEREST_ACCESS_TOKEN and PINTEREST_BOARD_ID):
        return "skipped: not configured"
    if not product.get("image_url"):
        return "skipped: pinterest requires an image"

    caption = render_caption(product)
    title = product["title"]
    if len(title) > 100:
        title = title[:97] + "..."

    body_payload = {
        "board_id": PINTEREST_BOARD_ID,
        "title": title,
        "description": caption[:800],
        "link": product["affiliate_url"],
        "media_source": {"source_type": "image_url", "url": product["image_url"]},
    }
    status, body = http_post_json(
        "https://api.pinterest.com/v5/pins",
        body_payload,
        headers={"Authorization": f"Bearer {PINTEREST_ACCESS_TOKEN}"},
    )
    if status >= 400:
        return f"failed ({status}): {body[:200]}"
    return f"success: {(json.loads(body) or {}).get('id', 'unknown_id')}"


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------


PUBLISHERS = {
    "facebook": post_to_facebook,
    "instagram": post_to_instagram,
    "pinterest": post_to_pinterest,
}


def main():
    print("=" * 60)
    print("  Amazon Affiliate Bot — single run")
    print(f"  DRY_RUN = {DRY_RUN}    Platforms: {', '.join(ENABLED_PLATFORMS)}")
    print("=" * 60)

    products = fetch_products()
    print(f"\n📦 Fetched {len(products)} product(s):\n")
    for p in products:
        print(f"  - [{p['asin']}] {p['title']}  ({p.get('price') or '?'})")

    if not products:
        print("\nNo products fetched. Check DRY_RUN or Amazon credentials.")
        return

    print()
    ok = failed = skipped = 0
    for product in products:
        print(f"🛒 {product['title']}")
        for platform in ENABLED_PLATFORMS:
            fn = PUBLISHERS.get(platform)
            if not fn:
                print(f"   ⚠ unknown platform: {platform}")
                continue
            result = fn(product)
            prefix = "   ✅" if result.startswith("success") else (
                "   ⏭ " if result.startswith("skipped") else "   ❌"
            )
            print(f"{prefix} {platform}: {result}")
            if result.startswith("success"):
                ok += 1
            elif result.startswith("skipped"):
                skipped += 1
            else:
                failed += 1
        print()

    print("=" * 60)
    print(f"  Done. success={ok}  failed={failed}  skipped={skipped}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)

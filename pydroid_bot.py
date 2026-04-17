"""Single-file affiliate bot designed for Pydroid 3 on Android.

What it does:
- Posts an affiliate link (your choice of URL + image + caption) to Facebook Page,
  Instagram Business, and/or Pinterest in one tap — no Amazon API needed.
- Optionally fetches Amazon bestsellers via PA-API 5.0 (if you have keys).
- Saves your credentials in a local JSON file so you only enter them once.

Usage on Pydroid 3:
    1. Install Pydroid 3 from the Play Store.
    2. Download this file to your phone (Pydroid folder or Downloads).
    3. Open it in Pydroid -> tap the play button.
    4. Menu:
         1) Post an affiliate link   <- main flow (no Amazon API needed)
         2) Fetch Amazon bestsellers (needs PA-API keys + pip install python-amazon-paapi)
         3) Settings (paste your FB / IG / Pinterest tokens)
         4) Quit
    5. Credentials are saved to `pydroid_bot_config.json` next to this file.

Dry-run mode is ON by default -- no real posts are sent until you turn it off
in Settings. Start in dry-run, confirm everything works, then switch off.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ============================================================================
# Config file (auto-managed; you don't need to edit it by hand)
# ============================================================================

_SCRIPT_DIR = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
CONFIG_PATH = Path(os.environ.get("PYDROID_BOT_CONFIG", _SCRIPT_DIR / "pydroid_bot_config.json"))

DEFAULT_CONFIG: dict = {
    "dry_run": True,
    "enabled_platforms": ["facebook", "instagram", "pinterest"],
    # Amazon (only needed if you use the Amazon fetch flow)
    "amazon_access_key": "",
    "amazon_secret_key": "",
    "amazon_partner_tag": "",
    "amazon_country": "US",
    "amazon_browse_nodes": ["172282"],
    "max_items": 5,
    # Facebook Page
    "facebook_page_id": "",
    "facebook_page_access_token": "",
    # Instagram Business (linked to a FB Page)
    "instagram_business_account_id": "",
    "instagram_access_token": "",
    # Pinterest
    "pinterest_access_token": "",
    "pinterest_board_id": "",
    # Caption template used for the Amazon fetch flow
    "caption_template": (
        "{title}\n\n"
        "{price}\n\n"
        "{features}\n\n"
        "Shop here: {url}\n\n"
        "#amazonfinds #affiliate #shopping"
    ),
}


# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pydroid-bot")


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not read %s (%s). Starting with defaults.", CONFIG_PATH, exc)
            data = {}
    else:
        data = {}
    return {**DEFAULT_CONFIG, **data}


def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.error("Could not save config to %s: %s", CONFIG_PATH, exc)


# ============================================================================
# Tiny HTTP helpers (std-lib only -- works on Pydroid with zero extra installs)
# ============================================================================


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


# ============================================================================
# Publishers -- take a `post` dict and the current `cfg`
# ============================================================================


def post_to_facebook(post: dict, cfg: dict) -> str:
    if cfg["dry_run"]:
        return "skipped: dry_run"
    page_id = cfg["facebook_page_id"]
    token = cfg["facebook_page_access_token"]
    if not (page_id and token):
        return "skipped: not configured"

    caption = post["caption"]
    image_url = post.get("image_url")
    link = post["url"]

    if image_url:
        api = f"https://graph.facebook.com/v20.0/{page_id}/photos"
        data = {"url": image_url, "caption": caption, "access_token": token}
    else:
        api = f"https://graph.facebook.com/v20.0/{page_id}/feed"
        data = {"message": caption, "link": link, "access_token": token}
    status, body = http_post_form(api, data)
    if status >= 400:
        return f"failed ({status}): {body[:200]}"
    j = json.loads(body) if body else {}
    return f"success: {j.get('post_id') or j.get('id') or 'unknown_id'}"


def post_to_instagram(post: dict, cfg: dict) -> str:
    if cfg["dry_run"]:
        return "skipped: dry_run"
    account = cfg["instagram_business_account_id"]
    token = cfg["instagram_access_token"]
    if not (account and token):
        return "skipped: not configured"
    if not post.get("image_url"):
        return "skipped: instagram requires an image"

    status, body = http_post_form(
        f"https://graph.facebook.com/v20.0/{account}/media",
        {
            "image_url": post["image_url"],
            "caption": post["caption"],
            "access_token": token,
        },
    )
    if status >= 400:
        return f"failed on create ({status}): {body[:200]}"
    creation_id = (json.loads(body) or {}).get("id")
    if not creation_id:
        return "failed: no creation id"

    for _ in range(10):
        time.sleep(3)
        s, b = http_get(
            f"https://graph.facebook.com/v20.0/{creation_id}",
            params={"fields": "status_code", "access_token": token},
        )
        if s >= 400:
            return f"failed polling ({s}): {b[:200]}"
        if (json.loads(b) or {}).get("status_code") == "FINISHED":
            break

    s, b = http_post_form(
        f"https://graph.facebook.com/v20.0/{account}/media_publish",
        {"creation_id": creation_id, "access_token": token},
    )
    if s >= 400:
        return f"failed on publish ({s}): {b[:200]}"
    return f"success: {(json.loads(b) or {}).get('id', 'unknown_id')}"


def post_to_pinterest(post: dict, cfg: dict) -> str:
    if cfg["dry_run"]:
        return "skipped: dry_run"
    token = cfg["pinterest_access_token"]
    board_id = cfg["pinterest_board_id"]
    if not (token and board_id):
        return "skipped: not configured"
    if not post.get("image_url"):
        return "skipped: pinterest requires an image"

    title = post.get("title") or post["caption"].splitlines()[0][:100]
    if len(title) > 100:
        title = title[:97] + "..."

    payload = {
        "board_id": board_id,
        "title": title,
        "description": post["caption"][:800],
        "link": post["url"],
        "media_source": {"source_type": "image_url", "url": post["image_url"]},
    }
    status, body = http_post_json(
        "https://api.pinterest.com/v5/pins",
        payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    if status >= 400:
        return f"failed ({status}): {body[:200]}"
    return f"success: {(json.loads(body) or {}).get('id', 'unknown_id')}"


PUBLISHERS = {
    "facebook": post_to_facebook,
    "instagram": post_to_instagram,
    "pinterest": post_to_pinterest,
}


def _publish(post: dict, cfg: dict) -> dict:
    """Run all enabled publishers for a single post dict. Prints + returns summary."""
    results = {"ok": 0, "failed": 0, "skipped": 0, "details": []}
    for platform in cfg["enabled_platforms"]:
        fn = PUBLISHERS.get(platform)
        if not fn:
            print(f"   ! unknown platform: {platform}")
            continue
        try:
            result = fn(post, cfg)
        except Exception as exc:  # noqa: BLE001
            result = f"failed: {exc}"
        icon = "[OK]" if result.startswith("success") else ("[SKIP]" if result.startswith("skipped") else "[FAIL]")
        print(f"   {icon} {platform}: {result}")
        results["details"].append((platform, result))
        if result.startswith("success"):
            results["ok"] += 1
        elif result.startswith("skipped"):
            results["skipped"] += 1
        else:
            results["failed"] += 1
    return results


# ============================================================================
# Manual link flow -- paste URL + caption + (optional) image -> post
# ============================================================================


def prompt(label: str, default: str = "", required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            val = input(f"{label}{suffix}: ").strip()
        except EOFError:
            val = ""
        if not val:
            val = default
        if required and not val:
            print("  (required)")
            continue
        return val


def multiline_prompt(label: str) -> str:
    print(f"{label} (press Enter on a blank line to finish):")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            if lines:
                break
            continue
        lines.append(line)
    return "\n".join(lines).rstrip()


def flow_post_link(cfg: dict) -> None:
    print("\n--- Post an affiliate link ---")
    url = prompt("Affiliate URL (include your ?tag=...)", required=True)
    image_url = prompt("Image URL (optional -- needed for IG & Pinterest)")
    caption = multiline_prompt("Caption")
    if not caption:
        caption = "Check this out!"

    platforms = cfg["enabled_platforms"]
    print(f"\nAbout to post to: {', '.join(platforms)}")
    print(f"DRY_RUN = {cfg['dry_run']}")
    if prompt("Proceed? (y/n)", default="y").lower() != "y":
        print("Cancelled.")
        return

    post = {"url": url, "image_url": image_url or None, "caption": caption}
    print()
    summary = _publish(post, cfg)
    print()
    print("=" * 50)
    print(f"  success={summary['ok']}  failed={summary['failed']}  skipped={summary['skipped']}")
    print("=" * 50)


# ============================================================================
# Amazon fetch flow (optional -- only if user has PA-API keys)
# ============================================================================


_MOCK = [
    {
        "asin": "B08N5WRWNW",
        "title": "Echo Dot (4th Gen) Smart Speaker with Alexa",
        "price": "$29.99",
        "image_url": "https://m.media-amazon.com/images/I/61MZzA4tA3L._AC_SL1000_.jpg",
        "detail_url": "https://www.amazon.com/dp/B08N5WRWNW",
        "features": ["Meet the Echo Dot", "Voice control your entertainment", "Ready to help"],
    },
    {
        "asin": "B09B8V1LZ3",
        "title": "Apple AirPods Pro (2nd Gen) Wireless Earbuds",
        "price": "$199.00",
        "image_url": "https://m.media-amazon.com/images/I/61SUj2aKoEL._AC_SL1500_.jpg",
        "detail_url": "https://www.amazon.com/dp/B09B8V1LZ3",
        "features": ["Active Noise Cancellation", "Adaptive Transparency", "Spatial Audio"],
    },
]


def _build_affiliate_url(detail_url: str, tag: str) -> str:
    if not tag:
        return detail_url
    sep = "&" if "?" in detail_url else "?"
    return f"{detail_url}{sep}tag={urllib.parse.quote_plus(tag)}"


def _render_caption(product: dict, cfg: dict) -> str:
    features_block = "\n".join(f"- {f}" for f in (product.get("features") or [])[:3])
    return cfg["caption_template"].format(
        title=product["title"],
        price=product.get("price") or "See price on Amazon",
        features=features_block,
        url=product["affiliate_url"],
    )


def _fetch_live_products(cfg: dict) -> list[dict]:
    try:
        from amazon_paapi import AmazonApi  # type: ignore
    except ImportError:
        log.error(
            "python-amazon-paapi not installed. In Pydroid: menu -> Pip -> install python-amazon-paapi"
        )
        return []

    api = AmazonApi(
        cfg["amazon_access_key"],
        cfg["amazon_secret_key"],
        cfg["amazon_partner_tag"],
        cfg["amazon_country"],
    )
    products: list[dict] = []
    nodes = cfg["amazon_browse_nodes"] or [None]
    per_node = max(1, cfg["max_items"] // max(1, len(nodes)))

    for node in nodes:
        kwargs = {"keywords": "bestseller", "item_count": per_node}
        if node:
            kwargs["browse_node_id"] = node
            kwargs["sort_by"] = "AvgCustomerReviews"
        try:
            resp = api.search_items(**kwargs)
        except Exception as exc:  # noqa: BLE001
            log.error("PA-API search failed for node %s: %s", node, exc)
            continue
        for item in getattr(resp, "items", None) or []:
            try:
                asin = getattr(item, "asin", "") or ""
                title = asin
                info = getattr(item, "item_info", None)
                features: list[str] = []
                price = None
                image_url = None
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
                    "affiliate_url": _build_affiliate_url(detail_url, cfg["amazon_partner_tag"]),
                    "features": features,
                })
            except Exception as exc:  # noqa: BLE001
                log.warning("Skipping malformed item: %s", exc)
    return products[: cfg["max_items"]]


def flow_fetch_amazon(cfg: dict) -> None:
    print("\n--- Fetch Amazon bestsellers ---")
    has_creds = bool(cfg["amazon_access_key"] and cfg["amazon_secret_key"] and cfg["amazon_partner_tag"])
    if cfg["dry_run"] or not has_creds:
        log.info("Using mock products (dry-run=%s, creds=%s).", cfg["dry_run"], has_creds)
        raw = _MOCK[: cfg["max_items"]]
        products = [
            {**p, "affiliate_url": _build_affiliate_url(p["detail_url"], cfg["amazon_partner_tag"] or "example-20")}
            for p in raw
        ]
    else:
        products = _fetch_live_products(cfg)

    if not products:
        print("No products fetched.")
        return

    print(f"\nFetched {len(products)} product(s):\n")
    for p in products:
        print(f"  - [{p['asin']}] {p['title']}  ({p.get('price') or '?'})")

    if prompt("\nPost all of them now? (y/n)", default="y").lower() != "y":
        print("Cancelled.")
        return

    totals = {"ok": 0, "failed": 0, "skipped": 0}
    print()
    for product in products:
        print(product["title"])
        post = {
            "url": product["affiliate_url"],
            "image_url": product.get("image_url"),
            "caption": _render_caption(product, cfg),
            "title": product["title"],
        }
        summary = _publish(post, cfg)
        for k in totals:
            totals[k] += summary[k]
        print()

    print("=" * 50)
    print(f"  Done. success={totals['ok']}  failed={totals['failed']}  skipped={totals['skipped']}")
    print("=" * 50)


# ============================================================================
# Settings flow
# ============================================================================

_FIELDS = [
    ("dry_run", "Dry-run mode (True = don't post, False = post for real)", "bool"),
    ("enabled_platforms", "Enabled platforms (comma-separated: facebook,instagram,pinterest)", "csv"),
    ("facebook_page_id", "Facebook Page ID (numeric)", "str"),
    ("facebook_page_access_token", "Facebook Page Access Token (starts with EAA...)", "secret"),
    ("instagram_business_account_id", "Instagram Business Account ID", "str"),
    ("instagram_access_token", "Instagram Access Token", "secret"),
    ("pinterest_access_token", "Pinterest Access Token", "secret"),
    ("pinterest_board_id", "Pinterest Board ID", "str"),
    ("amazon_access_key", "Amazon PA-API Access Key (optional)", "str"),
    ("amazon_secret_key", "Amazon PA-API Secret Key (optional)", "secret"),
    ("amazon_partner_tag", "Amazon Partner Tag (e.g. yourname-20) (optional)", "str"),
    ("amazon_country", "Amazon country (US/UK/DE/...)", "str"),
]


def _mask(val: str) -> str:
    if not val:
        return ""
    if len(val) <= 6:
        return "***"
    return f"{val[:3]}...{val[-3:]}"


def flow_settings(cfg: dict) -> dict:
    print("\n--- Settings ---")
    print(f"Config file: {CONFIG_PATH}\n")

    while True:
        print("Current values (blank = not set):")
        for i, (key, label, kind) in enumerate(_FIELDS, start=1):
            raw = cfg.get(key)
            if kind == "csv":
                display = ",".join(raw or [])
            elif kind == "secret":
                display = _mask(str(raw or ""))
            else:
                display = str(raw) if raw is not None else ""
            print(f"  {i:>2}. {label}")
            print(f"       -> {display}")

        choice = prompt("\nEnter number to edit, 's' to save & exit, 'q' to cancel", default="s")
        choice = choice.strip().lower()
        if choice in {"s", ""}:
            save_config(cfg)
            print(f"Saved to {CONFIG_PATH}")
            return cfg
        if choice == "q":
            print("No changes saved.")
            return load_config()
        if not choice.isdigit():
            print("Please enter a number, 's', or 'q'.")
            continue
        idx = int(choice) - 1
        if not 0 <= idx < len(_FIELDS):
            print("Out of range.")
            continue

        key, label, kind = _FIELDS[idx]
        current = cfg.get(key)
        if kind == "bool":
            ans = prompt(f"{label} (true/false)", default=str(current).lower()).lower()
            cfg[key] = ans in {"1", "true", "yes", "on", "y"}
        elif kind == "csv":
            raw = prompt(label, default=",".join(current or []))
            cfg[key] = [x.strip() for x in raw.split(",") if x.strip()]
        else:
            shown = _mask(str(current or "")) if kind == "secret" else (current or "")
            raw = prompt(f"{label} (current: {shown}; enter to keep)")
            if raw:
                cfg[key] = raw
        print()


# ============================================================================
# Main menu
# ============================================================================


def _print_header(cfg: dict) -> None:
    print()
    print("=" * 50)
    print("  Pydroid Affiliate Bot")
    dry = "ON (safe)" if cfg["dry_run"] else "OFF (LIVE POSTS!)"
    print(f"  Dry-run: {dry}")
    print(f"  Platforms: {', '.join(cfg['enabled_platforms']) or '(none)'}")
    print(f"  Config: {CONFIG_PATH}")
    print("=" * 50)


def main() -> int:
    cfg = load_config()
    while True:
        _print_header(cfg)
        print("  1) Post an affiliate link")
        print("  2) Fetch Amazon bestsellers (needs PA-API keys)")
        print("  3) Settings (paste tokens, toggle dry-run)")
        print("  4) Quit")
        choice = prompt("Choose", default="1")
        if choice == "1":
            flow_post_link(cfg)
        elif choice == "2":
            flow_fetch_amazon(cfg)
        elif choice == "3":
            cfg = flow_settings(cfg)
        elif choice in {"4", "q", "quit", "exit"}:
            print("Bye.")
            return 0
        else:
            print("Unknown choice.")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)

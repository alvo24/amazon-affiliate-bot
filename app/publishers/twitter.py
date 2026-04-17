"""Twitter / X publisher via OAuth 1.0a (stdlib only, no extra deps)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets as pysecrets
import time
from urllib.parse import quote

import httpx

from app.amazon import ProductInfo
from app.publishers.base import PostResult, Publisher

logger = logging.getLogger(__name__)

TWEET_ENDPOINT = "https://api.twitter.com/2/tweets"
TWEET_MAX_LEN = 280


def _rfc3986(value: str) -> str:
    return quote(str(value), safe="~")


def _oauth1_header(
    method: str,
    url: str,
    api_key: str,
    api_secret: str,
    access_token: str,
    access_token_secret: str,
) -> str:
    """Build an OAuth 1.0a Authorization header for a JSON-body request.

    The POST body is JSON (per v2 /2/tweets), so only the 4 oauth_* params
    participate in the signature base string.
    """
    oauth_params = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": pysecrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }

    param_str = "&".join(
        f"{_rfc3986(k)}={_rfc3986(v)}" for k, v in sorted(oauth_params.items())
    )
    base_string = "&".join([
        method.upper(),
        _rfc3986(url),
        _rfc3986(param_str),
    ])
    signing_key = f"{_rfc3986(api_secret)}&{_rfc3986(access_token_secret)}"
    digest = hmac.new(
        signing_key.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    oauth_params["oauth_signature"] = base64.b64encode(digest).decode("utf-8")

    header = "OAuth " + ", ".join(
        f'{_rfc3986(k)}="{_rfc3986(v)}"' for k, v in sorted(oauth_params.items())
    )
    return header


def _truncate_tweet(text: str, url: str | None) -> str:
    """Fit a tweet into 280 chars while preserving the URL at the end if present."""
    if url and url not in text:
        joined = f"{text}\n{url}"
    else:
        joined = text
    if len(joined) <= TWEET_MAX_LEN:
        return joined
    if url and url in joined:
        # Keep the URL; trim the prefix text.
        allowed = TWEET_MAX_LEN - len(url) - 2  # for "… " + "\n"
        if allowed < 20:
            return joined[:TWEET_MAX_LEN]
        prefix = text[: max(allowed, 0)].rstrip()
        return f"{prefix}…\n{url}"
    return joined[: TWEET_MAX_LEN - 1] + "…"


class TwitterPublisher(Publisher):
    name = "twitter"

    def is_configured(self) -> bool:
        return self.settings.twitter_configured()

    async def publish(self, product: ProductInfo) -> PostResult:
        if self.settings.dry_run:
            logger.info("[DRY_RUN] Would tweet: %s", product.title)
            return PostResult(status="skipped", message="dry_run")
        if not self.is_configured():
            return PostResult(status="skipped", message="twitter not configured")

        caption = self.render_caption(product)
        text = _truncate_tweet(caption, product.affiliate_url)

        header = _oauth1_header(
            method="POST",
            url=TWEET_ENDPOINT,
            api_key=self.settings.twitter_api_key,
            api_secret=self.settings.twitter_api_secret,
            access_token=self.settings.twitter_access_token,
            access_token_secret=self.settings.twitter_access_token_secret,
        )
        headers = {"Authorization": header, "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(TWEET_ENDPOINT, headers=headers, json={"text": text})
            if resp.status_code >= 400:
                return PostResult(status="failed", message=resp.text[:500])
            payload = resp.json()
            remote_id = (payload.get("data") or {}).get("id")
            return PostResult(status="success", remote_id=remote_id)
        except httpx.HTTPError as exc:
            logger.exception("Twitter post failed")
            return PostResult(status="failed", message=str(exc))

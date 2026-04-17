"""High-level orchestration: fetch Amazon products → post to enabled platforms."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime

from sqlmodel import Session, select

from app.amazon import AmazonClient, ProductInfo
from app.config import Settings, get_effective_settings
from app.db import engine
from app.models import Post, Product, RunLog
from app.publishers import (
    FacebookPublisher,
    InstagramPublisher,
    PinterestPublisher,
    Publisher,
    TwitterPublisher,
)

logger = logging.getLogger(__name__)

_ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})", re.IGNORECASE)

_PUBLISHER_REGISTRY: dict[str, type[Publisher]] = {
    "facebook": FacebookPublisher,
    "instagram": InstagramPublisher,
    "pinterest": PinterestPublisher,
    "twitter": TwitterPublisher,
}


def extract_asin_from_url(url: str) -> str:
    """Pull the ASIN from an Amazon URL, or derive a stable manual ID."""
    match = _ASIN_RE.search(url)
    if match:
        return match.group(1).upper()
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest().upper()
    return f"MANUAL{digest[:10]}"


def _build_publishers(settings: Settings, platforms: list[str] | None = None) -> list[Publisher]:
    names = platforms if platforms is not None else settings.platform_list
    publishers: list[Publisher] = []
    for name in names:
        cls = _PUBLISHER_REGISTRY.get(name)
        if not cls:
            logger.warning("Unknown platform: %s", name)
            continue
        publishers.append(cls(settings))
    return publishers


def _store_product(session: Session, product: ProductInfo) -> Product:
    existing = session.get(Product, product.asin)
    if existing:
        existing.title = product.title
        existing.price = product.price
        existing.image_url = product.image_url
        existing.detail_url = product.detail_url
        existing.affiliate_url = product.affiliate_url
        existing.features = "\n".join(product.features) if product.features else None
        existing.browse_node = product.browse_node
        existing.fetched_at = datetime.utcnow()
        session.add(existing)
        return existing

    row = Product(
        asin=product.asin,
        title=product.title,
        price=product.price,
        image_url=product.image_url,
        detail_url=product.detail_url,
        affiliate_url=product.affiliate_url,
        features="\n".join(product.features) if product.features else None,
        browse_node=product.browse_node,
    )
    session.add(row)
    return row


def _already_posted(session: Session, asin: str, platform: str) -> bool:
    stmt = select(Post).where(Post.asin == asin, Post.platform == platform, Post.status == "success")
    return session.exec(stmt).first() is not None


async def run_once(settings: Settings | None = None) -> dict:
    """Fetch bestsellers and attempt to post each one to every enabled platform.

    Returns a summary dict usable by the dashboard / logs.
    """
    settings = settings or get_effective_settings()
    started = datetime.utcnow()
    summary = {
        "started_at": started.isoformat(),
        "products_fetched": 0,
        "posts_attempted": 0,
        "posts_succeeded": 0,
        "posts_failed": 0,
        "posts_skipped": 0,
        "details": [],
    }

    run_log = RunLog(started_at=started)
    with Session(engine) as session:
        session.add(run_log)
        session.commit()
        session.refresh(run_log)
        run_id = run_log.id

    try:
        client = AmazonClient(settings)
        products = client.fetch_bestsellers()
        summary["products_fetched"] = len(products)

        publishers = _build_publishers(settings)
        logger.info(
            "Posting %d products across %d platform(s): %s",
            len(products),
            len(publishers),
            [p.name for p in publishers],
        )

        with Session(engine) as session:
            for product in products:
                _store_product(session, product)
            session.commit()

        for product in products:
            for publisher in publishers:
                with Session(engine) as session:
                    if _already_posted(session, product.asin, publisher.name):
                        logger.info(
                            "Skipping %s on %s (already posted successfully)",
                            product.asin,
                            publisher.name,
                        )
                        summary["posts_skipped"] += 1
                        summary["details"].append(
                            {
                                "asin": product.asin,
                                "platform": publisher.name,
                                "status": "skipped",
                                "message": "already posted",
                            }
                        )
                        continue

                summary["posts_attempted"] += 1
                result = await publisher.publish(product)
                with Session(engine) as session:
                    session.add(
                        Post(
                            asin=product.asin,
                            platform=publisher.name,
                            status=result.status,
                            remote_id=result.remote_id,
                            message=result.message,
                        )
                    )
                    session.commit()

                if result.status == "success":
                    summary["posts_succeeded"] += 1
                elif result.status == "skipped":
                    summary["posts_skipped"] += 1
                else:
                    summary["posts_failed"] += 1

                summary["details"].append(
                    {
                        "asin": product.asin,
                        "title": product.title,
                        "platform": publisher.name,
                        "status": result.status,
                        "remote_id": result.remote_id,
                        "message": result.message,
                    }
                )
    except Exception as exc:
        logger.exception("Scheduler run failed")
        summary["error"] = str(exc)
        with Session(engine) as session:
            row = session.get(RunLog, run_id)
            if row:
                row.error = str(exc)
                row.finished_at = datetime.utcnow()
                session.add(row)
                session.commit()
        return summary

    with Session(engine) as session:
        row = session.get(RunLog, run_id)
        if row:
            row.finished_at = datetime.utcnow()
            row.products_fetched = summary["products_fetched"]
            row.posts_attempted = summary["posts_attempted"]
            row.posts_succeeded = summary["posts_succeeded"]
            row.posts_failed = summary["posts_failed"]
            session.add(row)
            session.commit()

    logger.info("Run complete: %s", json.dumps({k: v for k, v in summary.items() if k != "details"}))
    return summary


async def post_manual(
    *,
    affiliate_url: str,
    caption: str,
    image_url: str | None = None,
    title: str | None = None,
    platforms: list[str] | None = None,
    settings: Settings | None = None,
) -> dict:
    """Post a single manually-provided affiliate link to selected platforms.

    Records a RunLog plus one Post row per platform. The user's `caption` is
    used verbatim (bypassing the ENV caption template).
    """
    settings = settings or get_effective_settings()
    started = datetime.utcnow()
    summary: dict = {
        "started_at": started.isoformat(),
        "posts_attempted": 0,
        "posts_succeeded": 0,
        "posts_failed": 0,
        "posts_skipped": 0,
        "details": [],
    }

    asin = extract_asin_from_url(affiliate_url)
    display_title = (title or caption.splitlines()[0] or affiliate_url)[:200]

    product = ProductInfo(
        asin=asin,
        title=display_title,
        price=None,
        image_url=image_url or None,
        detail_url=affiliate_url,
        affiliate_url=affiliate_url,
        features=[],
        browse_node="manual",
        caption_override=caption,
    )

    run_log = RunLog(started_at=started)
    with Session(engine) as session:
        session.add(run_log)
        session.commit()
        session.refresh(run_log)
        run_id = run_log.id

    try:
        with Session(engine) as session:
            _store_product(session, product)
            session.commit()

        publishers = _build_publishers(settings, platforms=platforms)
        logger.info(
            "Manual post to %d platform(s): %s",
            len(publishers),
            [p.name for p in publishers],
        )

        for publisher in publishers:
            summary["posts_attempted"] += 1
            result = await publisher.publish(product)
            with Session(engine) as session:
                session.add(
                    Post(
                        asin=product.asin,
                        platform=publisher.name,
                        status=result.status,
                        remote_id=result.remote_id,
                        message=result.message,
                    )
                )
                session.commit()

            if result.status == "success":
                summary["posts_succeeded"] += 1
            elif result.status == "skipped":
                summary["posts_skipped"] += 1
            else:
                summary["posts_failed"] += 1

            summary["details"].append(
                {
                    "platform": publisher.name,
                    "status": result.status,
                    "remote_id": result.remote_id,
                    "message": result.message,
                }
            )
    except Exception as exc:
        logger.exception("Manual post failed")
        summary["error"] = str(exc)
        with Session(engine) as session:
            row = session.get(RunLog, run_id)
            if row:
                row.error = str(exc)
                row.finished_at = datetime.utcnow()
                session.add(row)
                session.commit()
        return summary

    with Session(engine) as session:
        row = session.get(RunLog, run_id)
        if row:
            row.finished_at = datetime.utcnow()
            row.products_fetched = 1
            row.posts_attempted = summary["posts_attempted"]
            row.posts_succeeded = summary["posts_succeeded"]
            row.posts_failed = summary["posts_failed"]
            session.add(row)
            session.commit()

    logger.info("Manual post complete: %s", json.dumps({k: v for k, v in summary.items() if k != "details"}))
    return summary

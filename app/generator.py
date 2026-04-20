"""Affiliate content-pack generator.

Given an affiliate URL (+ optional product name / image / price), produce a
full marketing pack: hooks, A/B captions, short video script, story sequence,
hard + soft CTA, hashtags, and three angles (luxury / budget / problem-solution).

Works with zero config via template heuristics. If ``openai_api_key`` is set in
the effective settings, calls OpenAI's chat completions API (via stdlib urllib,
no ``openai`` package dependency) to produce higher-quality output.
"""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_FETCH_TIMEOUT = 8


# --------------------------------------------------------------------------- #
# Data models
# --------------------------------------------------------------------------- #


@dataclass
class ProductInfo:
    """Lightweight product description extracted from a URL."""

    url: str
    title: str = ""
    description: str = ""
    image: str = ""
    price: str = ""
    brand: str = ""
    asin: str = ""
    source: str = ""  # "scraped" | "manual" | "url-only"

    @property
    def short_title(self) -> str:
        """A concise display name, trimmed of marketing fluff."""
        t = self.title.strip() or "this"
        # Amazon titles are huge. Grab the first 8 words.
        words = t.split()
        return " ".join(words[:8]).rstrip(",.-")


@dataclass
class ContentPack:
    """Full content pack, all strings ready to copy-paste."""

    product: ProductInfo
    hooks: list[str] = field(default_factory=list)
    caption_a: str = ""
    caption_b: str = ""
    video_script: str = ""
    story_sequence: list[str] = field(default_factory=list)
    hard_cta: str = ""
    soft_cta: str = ""
    hashtags: list[str] = field(default_factory=list)
    angle_luxury: str = ""
    angle_budget: str = ""
    angle_problem: str = ""
    engine: str = "templates"  # "templates" or "openai"

    def to_markdown(self) -> str:
        """Return the entire pack as a single copy-paste-friendly block."""
        lines: list[str] = []
        lines.append(f"# Affiliate content pack — {self.product.short_title}")
        lines.append(f"Source: {self.product.url}")
        if self.product.price:
            lines.append(f"Price seen: {self.product.price}")
        lines.append("")
        lines.append("## 3 Viral hooks")
        for i, h in enumerate(self.hooks, 1):
            lines.append(f"{i}. {h}")
        lines.append("")
        lines.append("## Caption A (direct)")
        lines.append(self.caption_a)
        lines.append("")
        lines.append("## Caption B (story)")
        lines.append(self.caption_b)
        lines.append("")
        lines.append("## Short viral video script (15-25s)")
        lines.append(self.video_script)
        lines.append("")
        lines.append("## Story / post sequence (5 frames)")
        for i, s in enumerate(self.story_sequence, 1):
            lines.append(f"{i}. {s}")
        lines.append("")
        lines.append("## CTAs")
        lines.append(f"- Hard sell: {self.hard_cta}")
        lines.append(f"- Soft sell: {self.soft_cta}")
        lines.append("")
        lines.append("## Hashtags")
        lines.append(" ".join(self.hashtags))
        lines.append("")
        lines.append("## Angles")
        lines.append(f"- Luxury: {self.angle_luxury}")
        lines.append(f"- Budget: {self.angle_budget}")
        lines.append(f"- Problem-solution: {self.angle_problem}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Product scraping
# --------------------------------------------------------------------------- #


class _MetaHarvester(HTMLParser):
    """Pull <title>, og:*, twitter:*, and product-y meta tags from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title: str = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower().strip()
            val = a.get("content") or ""
            if key and val and key not in self.meta:
                self.meta[key] = val
        elif tag == "link" and a.get("rel") == "canonical" and a.get("href"):
            self.meta.setdefault("canonical", a["href"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and not self.title:
            self.title = data.strip()


_ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", re.IGNORECASE)
_PRICE_RE = re.compile(
    r"(?:USD|US\$|CAD|EUR|GBP|\$|£|€)\s?\d{1,4}(?:[.,]\d{2})?|"
    r"\d{1,4}[.,]\d{2}\s?(?:USD|EUR|GBP|CAD|\$)",
    re.IGNORECASE,
)


def _extract_asin(url: str) -> str:
    m = _ASIN_RE.search(url)
    return m.group(1).upper() if m else ""


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:  # noqa: S310 - user-supplied URL
        raw = resp.read(1_500_000)  # cap to 1.5 MB
    charset = resp.headers.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def scrape_product(url: str, image_hint: str = "", title_hint: str = "") -> ProductInfo:
    """Best-effort product metadata extraction.

    Never raises — falls back to whatever we have. For Amazon (or any site that
    blocks scraping), we still at least extract the ASIN from the URL.
    """
    info = ProductInfo(url=url.strip(), asin=_extract_asin(url), source="url-only")
    if title_hint.strip():
        info.title = title_hint.strip()
        info.source = "manual"
    if image_hint.strip():
        info.image = image_hint.strip()

    try:
        body = _fetch(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.info("scrape fetch failed for %s: %s", url, exc)
        return info
    except Exception as exc:  # noqa: BLE001 - never let a scrape bring down the app
        logger.info("scrape unexpected error for %s: %s", url, exc)
        return info

    try:
        harvester = _MetaHarvester()
        harvester.feed(body)
    except Exception as exc:  # noqa: BLE001
        logger.info("html parse failed for %s: %s", url, exc)
        return info

    meta = harvester.meta
    og_title = meta.get("og:title") or meta.get("twitter:title")
    if not info.title:
        info.title = html.unescape((og_title or harvester.title or "").strip())
    if not info.image:
        info.image = html.unescape((meta.get("og:image") or meta.get("twitter:image") or "").strip())
    if not info.description:
        info.description = html.unescape(
            (meta.get("og:description") or meta.get("description") or meta.get("twitter:description") or "").strip()
        )
    if not info.brand:
        info.brand = html.unescape((meta.get("product:brand") or meta.get("og:site_name") or "").strip())
    if not info.price:
        price_meta = meta.get("product:price:amount") or meta.get("og:price:amount")
        currency = meta.get("product:price:currency") or meta.get("og:price:currency") or "USD"
        if price_meta:
            info.price = f"{currency} {price_meta}"
        else:
            m = _PRICE_RE.search(body[:200_000])
            if m:
                info.price = m.group(0).strip()
    if info.title or info.image or info.description:
        info.source = "scraped"
    return info


# --------------------------------------------------------------------------- #
# Heuristic (template) generator
# --------------------------------------------------------------------------- #


_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "for", "with", "of", "to", "in", "on",
    "by", "at", "is", "are", "was", "were", "be", "been", "this", "that",
    "it", "its", "from", "as", "but", "if", "your", "you", "our", "we",
    "my", "me", "has", "have", "will", "new", "inch", "pack", "set",
})


def _keywords(title: str, max_words: int = 4) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", title.lower())
    out: list[str] = []
    seen: set[str] = set()
    for w in words:
        if w in _STOPWORDS or w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= max_words:
            break
    return out


def _category_guess(title: str) -> str:
    t = title.lower()
    table = [
        # Audio must come before "phone" since "headphones" contains "phone".
        (("headphone", "earbud", "airpod", "speaker", "soundbar"), "audio gadget"),
        (("iphone", "samsung galaxy", "pixel phone", "smartphone", "android phone"), "phone"),
        (("laptop", "macbook", "notebook", "chromebook"), "laptop"),
        (("watch", "fitbit", "tracker"), "smart watch"),
        (("camera", "gopro", "dslr", "mirrorless"), "camera"),
        (("kitchen", "blender", "airfryer", "instant pot", "coffee"), "kitchen upgrade"),
        (("skincare", "serum", "moisturizer", "cleanser", "retinol"), "skincare find"),
        (("makeup", "lipstick", "mascara", "foundation"), "makeup drop"),
        (("shoes", "sneaker", "boot", "runner"), "footwear"),
        (("bag", "backpack", "tote", "handbag"), "carry piece"),
        (("bed", "sheet", "pillow", "mattress"), "bedroom upgrade"),
        (("chair", "desk", "monitor", "keyboard", "mouse"), "desk setup piece"),
        (("fitness", "dumbbell", "yoga", "resistance", "treadmill"), "fitness tool"),
        (("baby", "diaper", "stroller", "crib"), "baby essential"),
        (("toy", "lego", "doll", "plush"), "gift pick"),
        (("book", "novel"), "read"),
    ]
    for keys, label in table:
        if any(k in t for k in keys):
            return label
    return "find"


def _emotions(title: str) -> tuple[str, str]:
    """Return (pain_point, desire) strings tuned to the product."""
    cat = _category_guess(title)
    mapping = {
        "phone": ("the constant battery anxiety", "freedom to use your phone all day"),
        "audio gadget": ("low-quality, tinny sound", "cinema-grade audio on the go"),
        "laptop": ("laggy, unreliable work sessions", "buttery-smooth multitasking"),
        "smart watch": ("missing workouts and blaming time", "owning every minute of your day"),
        "camera": ("blurry, forgettable memories", "scroll-stopping content"),
        "kitchen upgrade": ("30-minute dinners that still taste mid", "weeknight meals that impress"),
        "skincare find": ("tired, stressed-looking skin", "the 'what's your skincare?' DMs"),
        "makeup drop": ("makeup that fades by lunch", "a look that stays all day"),
        "footwear": ("feet sore by hour three", "all-day comfort that still looks clean"),
        "carry piece": ("digging through a messy bag", "a go-bag that actually fits your life"),
        "bedroom upgrade": ("waking up stiff and groggy", "hotel-quality sleep at home"),
        "desk setup piece": ("neck pain and ugly setups", "a setup that boosts focus AND looks unreal"),
        "fitness tool": ("skipping the gym again", "a workout you'll actually stick to"),
        "baby essential": ("baby stress on rough days", "calmer routines that parents swear by"),
        "gift pick": ("gifting the boring-but-safe option", "being THE gift-giver this year"),
        "read": ("rereading the same page 4 times", "a story that grips you from page 1"),
        "find": ("settling for 'good enough'", "that small upgrade that changes your week"),
    }
    return mapping.get(cat, mapping["find"])


def _price_hint(product: ProductInfo) -> str:
    return product.price or "way less than you'd guess"


def _base_hashtags(product: ProductInfo) -> list[str]:
    kws = _keywords(product.title, max_words=3)
    cat = _category_guess(product.title).replace(" ", "")
    tags: list[str] = []
    tags.append(f"#{cat}".lower())
    for kw in kws:
        tags.append(f"#{kw}")
    tags.extend([
        "#amazonfinds",
        "#amazonmusthaves",
        "#affiliate",
        "#tiktokmademebuyit",
        "#foundonamazon",
        "#dailyfinds",
        "#shopping",
        "#musthave",
        "#reviewsmatter",
        "#linkinbio",
    ])
    # de-dupe, keep order, cap at 10
    seen: set[str] = set()
    uniq: list[str] = []
    for t in tags:
        tl = t.lower()
        if tl in seen:
            continue
        seen.add(tl)
        uniq.append(t)
        if len(uniq) >= 10:
            break
    return uniq


def generate_from_templates(product: ProductInfo) -> ContentPack:
    """Produce a full content pack purely from templates + heuristics."""
    pain, desire = _emotions(product.title or "")
    cat = _category_guess(product.title or "")
    short = product.short_title
    price = _price_hint(product)
    url = product.url

    hooks = [
        f"POV: you finally found the {cat} that fixes {pain} 🤌",
        f"I wasn't going to post this — but everyone keeps asking where I got this {cat}.",
        f"Stop scrolling. This {cat} did what 3 others couldn't — and it's {price}.",
    ]

    caption_a = (
        f"The {cat} I didn't know I needed. ✨\n\n"
        f"→ {short}\n"
        f"→ {desire.capitalize()}.\n"
        f"→ {price} (I thought it'd cost 3x more).\n\n"
        f"If you've been dealing with {pain}, try this before anything else.\n"
        f"🛒 Grab yours: {url}"
    )
    caption_b = (
        f"Okay storytime — I bought this {cat} after weeks of trying (and returning) others. "
        f"I was so over {pain}. This one actually delivered on {desire}. "
        f"Not sponsored, just obsessed. If you've been on the fence → {url} ✨"
    )

    video_script = (
        "0–2s · HOOK (on camera, no cut):\n"
        f"   \"{hooks[0]}\"\n\n"
        "2–6s · SHOW THE PROBLEM (b-roll of the pain point, quick cuts):\n"
        f"   Voiceover: \"I was SO tired of {pain}.\"\n\n"
        "6–12s · REVEAL (unbox / first use, bright clean shot):\n"
        f"   Voiceover: \"Then I tried this {cat} — and honestly?\"\n"
        f"   On-screen text: \"{short}\"\n\n"
        "12–18s · PROOF (side-by-side or before/after):\n"
        f"   Voiceover: \"It gave me {desire}. No gimmicks.\"\n\n"
        "18–23s · HARD SELL (direct to camera, urgent):\n"
        f"   \"It's {price}. Link in bio. Do not sleep on this one.\"\n\n"
        "23–25s · LOGO / brand card + URL on screen."
    )

    story_sequence = [
        f"Frame 1 — Hook slide: \"Raise your hand if {pain} has ruined your week.\"",
        "Frame 2 — Agitate: close-up of the frustration. Caption: \"Same. Until last Tuesday.\"",
        f"Frame 3 — Reveal: product shot. Caption: \"Meet the {cat} that actually works.\"",
        f"Frame 4 — Proof: quick benefit list — \"{desire}\", \"Easy setup\", \"{price}\".",
        "Frame 5 — CTA slide: \"Link in bio — swipe up 👆\" + sticker pointing to URL.",
    ]

    hard_cta = (
        f"🚨 Don't overthink this — this {cat} is selling out fast. "
        f"Tap the link and grab yours at {price} before it's gone: {url}"
    )
    soft_cta = (
        f"If you've been looking for a {cat} upgrade that actually lives up to the hype, "
        f"here's the one I trust → {url}. No pressure, just sharing what works."
    )

    hashtags = _base_hashtags(product)

    angle_luxury = (
        f"✨ The quiet-luxury {cat} upgrade no one's gatekeeping anymore.\n"
        f"Premium feel, thoughtful details, zero compromise. "
        f"If you're building a 'nice things' era — this fits right in. → {url}"
    )
    angle_budget = (
        f"💸 Under-the-radar {cat} that costs a fraction of the name brands — "
        f"and honestly? I can't tell the difference. "
        f"At {price}, it's the kind of smart buy you brag about later. → {url}"
    )
    angle_problem = (
        f"🩺 If {pain} has been dragging you down, this {cat} is a real fix — not a hack. "
        f"It gave me {desire} within days. Here's the exact one → {url}"
    )

    return ContentPack(
        product=product,
        hooks=hooks,
        caption_a=caption_a,
        caption_b=caption_b,
        video_script=video_script,
        story_sequence=story_sequence,
        hard_cta=hard_cta,
        soft_cta=soft_cta,
        hashtags=hashtags,
        angle_luxury=angle_luxury,
        angle_budget=angle_budget,
        angle_problem=angle_problem,
        engine="templates",
    )


# --------------------------------------------------------------------------- #
# Optional OpenAI backend (used only if settings.openai_api_key is set)
# --------------------------------------------------------------------------- #


_OPENAI_SYSTEM = (
    "You are a world-class affiliate marketing copywriter. "
    "Given a product, produce a full marketing pack. "
    "Tone: persuasive, modern, relatable, slightly urgent but never spammy. "
    "Never use racial, medical, or legal claims. Never invent prices — use the "
    "provided price or say 'way less than you'd guess'. "
    "Return STRICT valid JSON only. No markdown fences, no prose."
)

_OPENAI_SCHEMA_INSTR = """
Return a JSON object with exactly these keys:
{
  "hooks": [string, string, string],                // 3 viral hooks, <=140 chars each
  "caption_a": string,                              // direct, benefit-led, <=500 chars
  "caption_b": string,                              // story-led, <=500 chars
  "video_script": string,                           // 15-25s TikTok/Reels script with timestamps
  "story_sequence": [string, string, string, string, string], // 5 IG story frames
  "hard_cta": string,                               // 1 hard-selling CTA line
  "soft_cta": string,                               // 1 soft CTA line
  "hashtags": [string, ... 10 total],               // 10 hashtags, include #
  "angle_luxury": string,                           // luxury/premium angle caption
  "angle_budget": string,                           // budget/value angle caption
  "angle_problem": string                           // problem-solution angle caption
}
Every string must be safe to copy-paste. Include the product URL in captions and CTAs.
"""


def _generate_with_openai(product: ProductInfo, api_key: str, model: str = "gpt-4o-mini") -> ContentPack | None:
    """Call OpenAI Chat Completions. Returns None on any failure (we fall back)."""
    user = (
        f"Product URL: {product.url}\n"
        f"ASIN: {product.asin or '(unknown)'}\n"
        f"Title: {product.title or '(unknown)'}\n"
        f"Brand: {product.brand or '(unknown)'}\n"
        f"Price: {product.price or '(unknown)'}\n"
        f"Description: {product.description[:800] or '(unknown)'}\n\n"
        f"Target platforms: TikTok, Instagram, Facebook, WhatsApp.\n"
        + _OPENAI_SCHEMA_INSTR
    )
    payload = {
        "model": model,
        "temperature": 0.8,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _OPENAI_SYSTEM},
            {"role": "user", "content": user},
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("openai call failed: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("openai unexpected error: %s", exc)
        return None

    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("openai response parse failed: %s", exc)
        return None

    try:
        return ContentPack(
            product=product,
            hooks=list(parsed["hooks"])[:3],
            caption_a=str(parsed["caption_a"]),
            caption_b=str(parsed["caption_b"]),
            video_script=str(parsed["video_script"]),
            story_sequence=list(parsed["story_sequence"])[:5],
            hard_cta=str(parsed["hard_cta"]),
            soft_cta=str(parsed["soft_cta"]),
            hashtags=list(parsed["hashtags"])[:10],
            angle_luxury=str(parsed["angle_luxury"]),
            angle_budget=str(parsed["angle_budget"]),
            angle_problem=str(parsed["angle_problem"]),
            engine="openai",
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("openai response missing fields: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #


def build_content_pack(
    url: str,
    image_hint: str = "",
    title_hint: str = "",
    openai_api_key: str = "",
) -> ContentPack:
    """Scrape + generate. Falls back to templates if OpenAI fails or is unset."""
    product = scrape_product(url, image_hint=image_hint, title_hint=title_hint)
    if openai_api_key:
        pack = _generate_with_openai(product, openai_api_key)
        if pack is not None:
            return pack
    return generate_from_templates(product)

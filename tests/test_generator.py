"""Tests for the affiliate content-pack generator (template mode)."""

from __future__ import annotations

from app.generator import (
    ContentPack,
    ProductInfo,
    _category_guess,
    _extract_asin,
    _keywords,
    build_content_pack,
    generate_from_templates,
)


def test_extract_asin_amazon_dp() -> None:
    assert _extract_asin("https://www.amazon.com/dp/B08N5WRWNW?tag=x-20") == "B08N5WRWNW"
    assert _extract_asin("https://amazon.com/gp/product/B0ABCDEFGH/ref=x") == "B0ABCDEFGH"
    assert _extract_asin("https://example.com/product/123") == ""


def test_keywords_filters_stopwords() -> None:
    kws = _keywords("The New 2024 Wireless Noise-Cancelling Headphones for Travel")
    assert "wireless" in kws
    assert "headphones" in kws
    assert "the" not in kws
    assert len(kws) <= 4


def test_category_guess_maps_known_terms() -> None:
    assert _category_guess("Bose Wireless Headphones") == "audio gadget"
    assert _category_guess("Non-stick Kitchen Blender Set") == "kitchen upgrade"
    assert _category_guess("Random unknown thingy") == "find"


def test_template_pack_has_all_sections() -> None:
    product = ProductInfo(
        url="https://www.amazon.com/dp/B08N5WRWNW?tag=x-20",
        title="Bose QuietComfort Wireless Noise-Cancelling Headphones",
        price="$299.00",
        asin="B08N5WRWNW",
        source="scraped",
    )
    pack = generate_from_templates(product)
    assert isinstance(pack, ContentPack)
    assert len(pack.hooks) == 3
    assert all(isinstance(h, str) and h.strip() for h in pack.hooks)
    assert pack.caption_a and pack.caption_b
    assert pack.caption_a != pack.caption_b
    assert "HOOK" in pack.video_script
    assert len(pack.story_sequence) == 5
    assert pack.hard_cta and pack.soft_cta
    assert pack.hard_cta != pack.soft_cta
    assert len(pack.hashtags) == 10
    assert all(tag.startswith("#") for tag in pack.hashtags)
    assert pack.angle_luxury and pack.angle_budget and pack.angle_problem
    assert len({pack.angle_luxury, pack.angle_budget, pack.angle_problem}) == 3
    assert pack.engine == "templates"


def test_template_pack_url_is_referenced_everywhere() -> None:
    url = "https://www.amazon.com/dp/B08N5WRWNW?tag=mytag-20"
    product = ProductInfo(url=url, title="Ninja Air Fryer Pro", price="$129")
    pack = generate_from_templates(product)
    assert url in pack.caption_a
    assert url in pack.caption_b
    assert url in pack.hard_cta
    assert url in pack.soft_cta
    assert url in pack.angle_luxury
    assert url in pack.angle_budget
    assert url in pack.angle_problem


def test_build_content_pack_without_openai_falls_back_to_templates(monkeypatch) -> None:
    """If no openai key is set, must use templates without touching network."""

    def fake_scrape(url: str, image_hint: str = "", title_hint: str = "") -> ProductInfo:
        return ProductInfo(
            url=url,
            title=title_hint or "Example Skincare Serum",
            image=image_hint,
            price="$24.99",
            source="manual" if title_hint else "url-only",
        )

    monkeypatch.setattr("app.generator.scrape_product", fake_scrape)
    pack = build_content_pack(
        url="https://example.com/product",
        title_hint="Example Skincare Serum",
        openai_api_key="",
    )
    assert pack.engine == "templates"
    assert pack.product.title == "Example Skincare Serum"
    assert len(pack.hashtags) == 10


def test_to_markdown_includes_every_section() -> None:
    product = ProductInfo(url="https://example.com/x", title="Widget Pro", price="$9")
    pack = generate_from_templates(product)
    md = pack.to_markdown()
    for needle in (
        "Viral hooks",
        "Caption A",
        "Caption B",
        "video script",
        "Story / post sequence",
        "CTAs",
        "Hashtags",
        "Angles",
        "Luxury",
        "Budget",
        "Problem-solution",
    ):
        assert needle in md, f"missing section: {needle}"

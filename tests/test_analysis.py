import json
import os
from collections import Counter

from insight_agent import server as server_module
from insight_agent import settings as settings_module
from insight_agent.ingestion import agent_reach as agent_reach_module
from insight_agent.ingestion import tiktok_browser as tiktok_browser_module
from insight_agent.ingestion import youtube_ytdlp as youtube_module
from insight_agent.ingestion.agent_reach import normalize_opencli_read_items
from insight_agent.ingestion.amazon_opencli import AmazonResult, build_amazon_queries
from insight_agent.ingestion.schema import EvidenceItem, ProviderResult
from insight_agent.server import (
    amazon_review_url,
    analyze_amazon_category,
    analyze_articles,
    analyze_category,
    analyze_combined_insight,
    analyze_competitor_deep_dive,
    analyze_tiktok_category,
    analyze_youtube_category,
    build_article_search_queries,
    build_reddit_query,
    build_trend_series,
    delete_research_history_item,
    discover_article_urls,
    discover_competitors,
    list_research_history,
    save_research_history,
    verify_competitor_tiktok,
)
from insight_agent.settings import (
    build_llm_settings_response,
    build_reddit_settings_response,
    build_research_settings_response,
    build_web_search_settings_response,
    load_llm_providers,
    update_reddit_settings,
    update_research_settings,
    update_web_search_settings,
)


def test_query_expands_bra_subcategory() -> None:
    query = build_reddit_query("wireless bras for large bust")

    assert '"wireless bra"' in query
    assert '"large bust bra"' in query


def test_sample_analysis_returns_report_sections() -> None:
    result = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "sample",
            "limit": 8,
            "timeRange": "year",
            "useLlm": False,
        }
    )

    assert result["source_mode"] == "sample"
    assert result["coverage"]["posts"] == 8
    assert result["data_volume"]["requested_posts"] == 8
    assert result["data_volume"]["collected_posts"] == 8
    assert result["pain_points"]
    assert result["opportunities"]
    assert result["posts"]


def test_trend_series_fills_single_month_context() -> None:
    trend = build_trend_series(Counter({"2026-06": 5}))

    assert len(trend) == 6
    assert trend[-1] == {"month": "2026-06", "count": 5}
    assert trend[0]["count"] == 0


def test_agent_reach_analysis_uses_provider(monkeypatch) -> None:
    def fake_fetch(_query: str, _limit: int, _time_range: str) -> ProviderResult:
        return ProviderResult(
            [
                EvidenceItem(
                    source="reddit",
                    provider="agent_reach_opencli",
                    content_type="post",
                    title="Wireless bra support for large bust?",
                    text="Looking for lift, comfort, and no uniboob.",
                    url="https://www.reddit.com/r/ABraThatFits/comments/test/post/",
                    external_id="test",
                    community="ABraThatFits",
                    metrics={"score": 12, "comments": 3},
                    comments=[
                        {
                            "text": "Side support and fit are the biggest issue for me.",
                            "score": 5,
                        }
                    ],
                )
            ],
            [],
            "agent_reach",
        )

    monkeypatch.setattr("insight_agent.server.fetch_reddit_agent_reach", fake_fetch)

    result = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "agent_reach",
            "limit": 10,
            "timeRange": "year",
            "useLlm": False,
        }
    )

    assert result["source_mode"] == "agent_reach"
    assert result["coverage"]["posts"] == 1
    assert result["data_volume"]["collected_comments"] == 1
    assert result["data_volume"]["ai_comment_samples"] == 0
    assert result["posts"][0]["comment_items"]
    assert "Top comments" in result["posts"][0]["excerpt"]


def test_amazon_query_expansion_maps_large_bust_minimizer_terms() -> None:
    queries = build_amazon_queries("美国大胸显小内衣", 5)

    assert queries[0] == "美国大胸显小内衣"
    assert "minimizer bra" in queries
    assert "minimizer bras for large breasts" in queries


def test_amazon_analysis_uses_opencli_provider(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    def fake_fetch(
        _query: str,
        _limit: int,
        keyword_limit: int | None = None,
        bypass_cache: bool = False,
    ) -> AmazonResult:
        return AmazonResult(
            [
                {
                    "rank": 1,
                    "asin": "B0058LXNF0",
                    "title": "Vanity Fair Women's Beauty Back Smoothing Minimizer Bra",
                    "brand": "Vanity Fair",
                    "product_url": "https://www.amazon.com/dp/B0058LXNF0",
                    "price_text": "$29.99",
                    "price_value": 29.99,
                    "currency": "USD",
                    "rating_value": 4.3,
                    "review_count": 34856,
                    "badges": ["Overall Pick"],
                    "is_sponsored": False,
                    "bullet_points": ["Minimizes bust line up to 1.5 inches"],
                    "review_samples": [
                        {
                            "title": "Comfortable minimizer",
                            "body": "Smooths under shirts without uniboob.",
                            "rating_value": 5,
                            "verified_purchase": True,
                        }
                    ],
                }
            ],
            ["Bypassed local cache for Amazon collection."] if bypass_cache else [],
            queries=["minimizer bra", "full coverage minimizer bra"][: keyword_limit or 2],
            per_query_counts={"minimizer bra": 1, "full coverage minimizer bra": 1},
        )

    monkeypatch.setattr("insight_agent.server.fetch_amazon_opencli", fake_fetch)

    result = analyze_amazon_category(
        {
            "category": "minimizer bra",
            "limit": 10,
            "bypassCache": True,
            "useLlm": False,
        }
    )

    assert result["source_mode"] == "amazon_opencli"
    assert result["metrics"]["products"] == 1
    assert result["metrics"]["total_review_count"] == 34856
    assert result["data_volume"]["collected_review_samples"] == 1
    assert result["data_volume"]["query_count"] == 2
    assert result["data_volume"]["requested_products_per_query"] == 10
    assert result["products"][0]["asin"] == "B0058LXNF0"


def test_competitor_discovery_scores_amazon_candidates(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    def fake_fetch(
        _query: str,
        _limit: int,
        keyword_limit: int | None = None,
        bypass_cache: bool = False,
    ) -> AmazonResult:
        return AmazonResult(
            [
                {
                    "rank": 1,
                    "asin": "B0058LXNF0",
                    "title": "Wacoal Women's Visual Effects Minimizer Bra",
                    "brand": "Wacoal",
                    "product_url": "https://www.amazon.com/dp/B0058LXNF0",
                    "image_url": "https://example.com/image.jpg",
                    "price_text": "$65.00",
                    "price_value": 65.0,
                    "rating_value": 4.5,
                    "review_count": 5200,
                    "badges": ["Overall Pick"],
                    "is_sponsored": False,
                    "matched_queries": ["minimizer bra", "full coverage minimizer bra"],
                    "bullet_points": [
                        "Full coverage minimizer bra with supportive side support and smoothing back.",
                    ],
                    "review_samples": [
                        {
                            "title": "Great support",
                            "body": "Minimizes and supports my large bust under work shirts.",
                            "rating_value": 5,
                            "verified_purchase": True,
                        }
                    ],
                },
                {
                    "rank": 2,
                    "asin": "B0HSIAOWN",
                    "title": "HISA Full Coverage Minimizer Bra for Large Bust",
                    "brand": "HISA",
                    "product_url": "https://www.amazon.com/dp/B0HSIAOWN",
                    "price_text": "$59.00",
                    "price_value": 59.0,
                    "rating_value": 4.7,
                    "review_count": 900,
                    "badges": ["Popular Brand"],
                    "is_sponsored": False,
                    "bullet_points": ["Supportive smoothing minimizer bra."],
                    "review_samples": [],
                },
                {
                    "rank": 3,
                    "asin": "B0BALIMIN",
                    "title": "Bali Women's Passion for Comfort Minimizer Bra",
                    "brand": "Bali",
                    "product_url": "https://www.amazon.com/dp/B0BALIMIN",
                    "price_text": "$44.00",
                    "price_value": 44.0,
                    "rating_value": 4.2,
                    "review_count": 1500,
                    "badges": [],
                    "is_sponsored": False,
                    "bullet_points": ["Minimizer bra with full coverage support for everyday comfort."],
                    "review_samples": [],
                },
                {
                    "rank": 4,
                    "asin": "B000LOW",
                    "title": "Generic Lace Bra",
                    "brand": "Generic",
                    "product_url": "https://www.amazon.com/dp/B000LOW000",
                    "price_text": "$18.00",
                    "price_value": 18.0,
                    "rating_value": 3.8,
                    "review_count": 20,
                    "badges": [],
                    "is_sponsored": True,
                    "bullet_points": ["Lace fashion bra."],
                    "review_samples": [],
                },
            ],
            ["Bypassed local cache for Amazon collection."] if bypass_cache else [],
            queries=["minimizer bra"][: keyword_limit or 1],
            per_query_counts={"minimizer bra": 4},
        )

    monkeypatch.setattr("insight_agent.server.fetch_amazon_opencli", fake_fetch)

    result = discover_competitors(
        {
            "query": "minimizer bra",
            "limit": 10,
            "amazonKeywordLimit": 1,
            "candidateLimit": 2,
            "bypassCache": True,
        }
    )

    assert result["source"]["status"] == "ready"
    assert result["data_volume"]["excluded_products"] == 1
    assert result["summary"]["candidate_count"] == 3
    assert len(result["candidates"]) == 3
    assert result["candidates"][0]["brand"] == "Wacoal"
    assert all(candidate["brand"].lower() != "hisa" for candidate in result["candidates"])
    assert result["candidates"][0]["priority"] == "High"
    assert result["candidates"][0]["breakout_tier"] == "strong_breakout"
    assert result["candidates"][0]["score"] > result["candidates"][1]["score"]
    assert result["candidates"][0]["review_evidence"]
    assert result["score_weights"]["priceFit"] == 1.35
    assert result["score_weights"]["tiktokProof"] == 1.0
    assert result["candidates"][0]["score_breakdown"]
    low_evidence = next(candidate for candidate in result["candidates"] if candidate["asin"] == "B000LOW")
    assert low_evidence["priority"] == "Low"
    assert low_evidence["breakout_tier"] == "low_evidence"


def test_competitor_discovery_price_weight_can_change_ranking(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    def fake_fetch(
        _query: str,
        _limit: int,
        keyword_limit: int | None = None,
        bypass_cache: bool = False,
    ) -> AmazonResult:
        return AmazonResult(
            [
                {
                    "rank": 1,
                    "asin": "B0EXPENSIVE",
                    "title": "Wacoal Women's Full Coverage Minimizer Bra for Large Bust",
                    "brand": "Wacoal",
                    "product_url": "https://www.amazon.com/dp/B0EXPENSIVE",
                    "price_text": "$129.00",
                    "price_value": 129.0,
                    "rating_value": 4.8,
                    "review_count": 12000,
                    "badges": ["Overall Pick"],
                    "is_sponsored": False,
                    "matched_queries": ["minimizer bra"],
                    "bullet_points": ["Supportive full coverage minimizer bra with smoothing side support for D-G cups."],
                    "review_samples": [],
                },
                {
                    "rank": 2,
                    "asin": "B0INBAND",
                    "title": "Bali Women's Full Coverage Minimizer Bra for Large Bust",
                    "brand": "Bali",
                    "product_url": "https://www.amazon.com/dp/B0INBAND",
                    "price_text": "$59.00",
                    "price_value": 59.0,
                    "rating_value": 4.1,
                    "review_count": 150,
                    "badges": [],
                    "is_sponsored": False,
                    "matched_queries": ["minimizer bra"],
                    "bullet_points": ["Everyday smoothing minimizer bra with support for D-G cups."],
                    "review_samples": [],
                },
            ],
            ["Bypassed local cache for Amazon collection."] if bypass_cache else [],
            queries=["minimizer bra"][: keyword_limit or 1],
            per_query_counts={"minimizer bra": 2},
        )

    monkeypatch.setattr("insight_agent.server.fetch_amazon_opencli", fake_fetch)

    result = discover_competitors(
        {
            "query": "minimizer bra",
            "limit": 10,
            "amazonKeywordLimit": 1,
            "scoreWeights": {
                "briefMatch": 1,
                "priceFit": 3,
                "sizeMatch": 1,
                "marketProof": 0,
                "reviewEvidence": 1,
                "queryCoverage": 1,
            },
        }
    )

    assert result["score_weights"]["priceFit"] == 3
    assert result["candidates"][0]["asin"] == "B0INBAND"
    expensive_price = next(
        item for item in result["candidates"][1]["score_breakdown"] if item["key"] == "priceFit"
    )
    assert expensive_price["points"] < 0


def test_competitor_tiktok_validation_updates_candidate_score(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    def fake_collect_tiktok(
        category: str,
        limit: int,
        bypass_cache: bool = False,
        settings_override: dict[str, int] | None = None,
    ):
        assert "Wacoal" in category
        assert limit == 8
        return (
            [
                {
                    "id": "7350000000000000001",
                    "title": "Wacoal minimizer bra review for large bust",
                    "url": "https://www.tiktok.com/@reviewer/video/7350000000000000001",
                    "caption": "Trying the Wacoal minimizer bra under work shirts #minimizerbra",
                    "author": "@reviewer",
                    "author_url": "https://www.tiktok.com/@reviewer",
                    "cover_url": "",
                    "hashtags": ["minimizerbra"],
                    "view_count": 125000,
                    "like_count": 8000,
                    "comment_count": 240,
                    "share_count": 130,
                    "save_count": 90,
                    "published_at": "",
                    "comment_samples": [
                        {
                            "id": "c1",
                            "author": "@shopper",
                            "text": "I need this smoothing and support for button-down shirts.",
                            "like_count": 5,
                            "created_at": "",
                        }
                    ],
                    "fetched_at": "",
                }
            ],
            ["Bypassed local cache for TikTok analysis."] if bypass_cache else [],
            "tiktok_playwright",
            {"comments_per_video": (settings_override or {}).get("comments_per_video", 8), "timeout_seconds": 180},
        )

    monkeypatch.setattr(server_module, "collect_tiktok", fake_collect_tiktok)

    result = verify_competitor_tiktok(
        {
            "candidate": {
                "id": "B0058LXNF0",
                "platform": "Amazon",
                "brand": "Wacoal",
                "title": "Wacoal Women's Visual Effects Minimizer Bra",
                "price_text": "$65.00",
                "price_value": 65.0,
                "rating_value": 4.5,
                "review_count": 5200,
                "badges": ["Overall Pick"],
                "is_sponsored": False,
                "product_url": "https://www.amazon.com/dp/B0058LXNF0",
                "image_url": "",
                "asin": "B0058LXNF0",
                "matched_queries": ["minimizer bra"],
                "score": 70,
                "score_breakdown": [],
                "priority": "High",
                "breakout_tier": "strong_breakout",
                "breakout_label": "Strong breakout candidate",
                "why_worth_tracking": ["Amazon review count 5,200 is a strong public demand proxy."],
                "risks": [],
                "claim_evidence": ["Full coverage minimizer bra."],
                "review_evidence": [{"text": "Great support", "rating_value": 5, "verified_purchase": True}],
                "suggested_status": "candidate",
            },
            "scoreWeights": {
                "briefMatch": 1,
                "priceFit": 1.35,
                "sizeMatch": 1,
                "marketProof": 1,
                "reviewEvidence": 1,
                "queryCoverage": 1,
                "tiktokProof": 1,
            },
            "bypassCache": True,
        }
    )

    assert result["validation"]["status"] == "directional"
    assert result["validation"]["comment_samples"] == 1
    assert result["validation"]["video_evidence"][0]["url"].startswith("https://www.tiktok.com/")
    assert result["validation"]["video_evidence"][0]["comment_samples"][0]["text"]
    assert result["candidate"]["tiktok_validation"]["status"] == "directional"
    assert result["candidate"]["score"] > 70
    assert any(item["key"] == "tiktokProof" for item in result["candidate"]["score_breakdown"])


def test_competitor_deep_dive_collects_product_reviews_reddit_and_web(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    def fake_product(_target: str, _timeout: int) -> AmazonResult:
        return AmazonResult(
            [
                {
                    "asin": "B0058LXNF0",
                    "title": "Wacoal Women's Visual Effects Minimizer Bra",
                    "brand": "Wacoal",
                    "product_url": "https://www.amazon.com/dp/B0058LXNF0",
                    "price_text": "$65.00",
                    "price_value": 65.0,
                    "rating_value": 4.5,
                    "review_count": 5200,
                    "badges": ["Overall Pick"],
                    "bullet_points": ["Full coverage minimizer bra with smoothing side support."],
                    "review_samples": [],
                }
            ],
            [],
        )

    def fake_discussion(_target: str, _limit: int, _timeout: int) -> AmazonResult:
        return AmazonResult(
            [
                {
                    "asin": "B0058LXNF0",
                    "review_samples": [
                        {
                            "id": "R1",
                            "title": "Great under shirts",
                            "body": "It minimizes without flattening and the straps do not dig.",
                            "rating_value": 5,
                            "date_text": "June 1, 2026",
                            "verified_purchase": True,
                        },
                        {
                            "id": "R2",
                            "title": "Band felt tight",
                            "body": "Support is good, but the band felt tight after a long day.",
                            "rating_value": 3,
                            "date_text": "May 20, 2026",
                            "verified_purchase": True,
                        },
                    ],
                }
            ],
            [],
        )

    reddit_call: dict[str, int | None] = {}

    def fake_collect_reddit(
        _category: str,
        _limit: int,
        _time_range: str,
        _mode: str,
        bypass_cache: bool = False,
        detail_limit: int | None = None,
        comments_per_post: int | None = None,
    ) -> tuple[list[dict], list[str], str]:
        reddit_call["detail_limit"] = detail_limit
        reddit_call["comments_per_post"] = comments_per_post
        return (
            [
                {
                    "id": "abc",
                    "title": "Has anyone tried the Wacoal Visual Effects minimizer?",
                    "excerpt": "Looking for smoothing and support for a large bust.",
                    "subreddit": "ABraThatFits",
                    "url": "https://www.reddit.com/r/ABraThatFits/comments/abc/example/",
                    "created_utc": "2026-06-01T00:00:00+00:00",
                    "score": 12,
                    "comments": 2,
                    "comment_items": [
                        {
                            "id": "c1",
                            "text": "It works under button-down shirts but the wires can dig.",
                            "score": 4,
                            "url": "https://www.reddit.com/r/ABraThatFits/comments/abc/example/c1/",
                        }
                    ],
                    "source": "agent_reach",
                }
            ],
            ["Bypassed local cache for this run."] if bypass_cache else [],
            "agent_reach",
        )

    def fake_web_sources(
        _product: dict,
        _category: str,
        _candidate_limit: int,
        bypass_cache: bool = False,
        run_id: str = "",
    ) -> dict:
        return {
            "source_mode": "web_search_agent_reach",
            "queries": ["Wacoal Visual Effects official site"],
            "candidates": [],
            "articles": [
                {
                    "title": "Visual Effects Minimizer Bra",
                    "url": "https://www.wacoal-america.com/visual-effects-minimizer-bra",
                    "domain": "wacoal-america.com",
                    "source_type": "brand_site",
                    "authority_score": 62,
                    "authority_level": "Medium",
                    "authority_evidence": ["Domain appears to match the product brand."],
                    "cautions": ["Brand-owned source."],
                    "brand_mentions": ["Wacoal"],
                    "product_signals": ["minimizer / visually smaller bust"],
                    "evidence_snippets": ["Official page emphasizes minimizer shaping, full coverage, and smoothing support."],
                    "readable_chars": 1200,
                    "fetched_at": "2026-06-01T00:00:00+00:00",
                }
            ],
            "warnings": [],
            "data_volume": {
                "query_count": 1,
                "raw_results": 1,
                "candidate_count": 1,
                "readable_sources": 1,
                "failed_sources": 0,
                "per_query_counts": [{"query": "Wacoal Visual Effects official site", "count": 1}],
            },
        }

    monkeypatch.setattr("insight_agent.server.read_amazon_product", fake_product)
    monkeypatch.setattr("insight_agent.server.read_amazon_discussion", fake_discussion)
    monkeypatch.setattr("insight_agent.server.collect_reddit", fake_collect_reddit)
    monkeypatch.setattr("insight_agent.server.discover_competitor_web_sources", fake_web_sources)

    result = analyze_competitor_deep_dive(
        {
            "candidate": {
                "asin": "B0058LXNF0",
                "title": "Wacoal Women's Visual Effects Minimizer Bra",
                "brand": "Wacoal",
                "product_url": "https://www.amazon.com/dp/B0058LXNF0",
                "review_count": 5200,
                "rating_value": 4.5,
            },
            "category": "minimizer bra",
            "amazonReviewLimit": 50,
            "redditLimit": 25,
            "redditDetailLimit": 5,
            "redditCommentsPerPost": 10,
            "webCandidateLimit": 3,
            "useLlm": False,
            "bypassCache": True,
        }
    )

    assert result["data_volume"]["amazon_reviews_collected"] == 2
    assert result["data_volume"]["reddit_posts_collected"] == 1
    assert result["data_volume"]["reddit_detail_posts_requested"] == 5
    assert result["data_volume"]["reddit_comments_per_post_requested"] == 10
    assert result["data_volume"]["reddit_comments_collected"] == 1
    assert reddit_call["detail_limit"] == 5
    assert reddit_call["comments_per_post"] == 10
    assert result["data_volume"]["web_sources_read"] == 1
    assert result["sales_proxy"]["signals"]
    assert result["verdict"]["citations"]
    assert any(item["source"] == "web" for item in result["evidence_pool"])


def test_cancel_competitor_analysis_marks_run_cancelled() -> None:
    result = server_module.cancel_competitor_analysis({"runId": "unit-test-competitor-run"})

    assert result["ok"] is True
    assert result["run_id"] == "unit-test-competitor-run"
    assert server_module.is_run_cancelled("unit-test-competitor-run") is True
    server_module.clear_run_cancel("unit-test-competitor-run")


def test_article_analysis_reads_public_urls_with_authority(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    sample_article = """
Title: The Best Minimizer Bras for Larger Busts

URL Source: https://www.goodhousekeeping.com/style-products/a123/best-minimizer-bras/

Markdown Content:

By Jane Editor
Updated Jun. 15, 2026

Our editors tested full coverage minimizer bras and reviewed support, smoothing, and comfort.
Wacoal, Bali, and Vanity Fair were compared for large bust support and underwire construction.
This article may earn commission from affiliate links.
"""

    def fake_http_get(_url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> bytes:
        return sample_article.encode("utf-8")

    monkeypatch.setattr(server_module, "http_get", fake_http_get)

    result = analyze_articles(
        {
            "category": "minimizer bra",
            "urls": ["https://www.goodhousekeeping.com/style-products/a123/best-minimizer-bras/"],
            "bypassCache": True,
        }
    )

    assert result["source_mode"] == "agent_reach_web"
    assert result["source"]["status"] == "ready"
    assert result["data_volume"]["collected_articles"] == 1
    assert result["articles"][0]["source_type"] == "public_ranking"
    assert result["articles"][0]["authority_level"] in {"High", "Medium"}
    assert "Wacoal" in result["articles"][0]["brand_mentions"]
    assert result["articles"][0]["product_signals"]


def test_youtube_analysis_summarizes_videos(monkeypatch) -> None:
    def fake_collect_youtube(
        _category: str,
        _limit: int,
        bypass_cache: bool = False,
        settings_override: dict[str, int] | None = None,
    ):
        return (
            [
                {
                    "id": "abc123",
                    "title": "Best minimizer bra review for large bust",
                    "url": "https://www.youtube.com/watch?v=abc123",
                    "channel": "Bra Reviewer",
                    "channel_url": "https://www.youtube.com/@brareviewer",
                    "duration_seconds": 420,
                    "view_count": 12000,
                    "like_count": 550,
                    "comment_count": 80,
                    "upload_date": "2026-06-01",
                    "description": "Testing support, smoothing, and comfort.",
                    "thumbnail": "https://img.youtube.com/vi/abc123/hqdefault.jpg",
                    "tags": ["minimizer bra", "large bust"],
                    "transcript": "This minimizer bra gives support and smoothing without strap digging.",
                    "transcript_chars": 74,
                    "comment_samples": [
                        {
                            "id": "c1",
                            "author": "shopper",
                            "text": "I need this for button-down shirts and shoulder comfort.",
                            "like_count": 3,
                            "timestamp": 0,
                        }
                    ],
                    "fetched_at": "2026-06-01T00:00:00+00:00",
                }
            ],
            ["Bypassed local cache for YouTube analysis."] if bypass_cache else [],
            "youtube_ytdlp",
            {
                "transcript_video_limit": 5,
                "comment_video_limit": 3,
                "comments_per_video": 10,
                "timeout_seconds": 120,
            },
        )

    monkeypatch.setattr(server_module, "collect_youtube", fake_collect_youtube)

    result = analyze_youtube_category(
        {
            "category": "minimizer bra",
            "limit": 10,
            "bypassCache": True,
        }
    )

    assert result["source_mode"] == "youtube_ytdlp"
    assert result["data_volume"]["requested_videos"] == 10
    assert result["data_volume"]["collected_videos"] == 1
    assert result["data_volume"]["videos_with_transcripts"] == 1
    assert result["data_volume"]["comment_samples"] == 1
    assert result["metrics"]["total_views"] == 12000
    assert result["channels"][0]["name"] == "Bra Reviewer"
    assert result["videos"][0]["comment_samples"][0]["text"]


def test_youtube_ytdlp_search_uses_partial_json_when_some_results_fail(monkeypatch) -> None:
    monkeypatch.setattr(youtube_module, "yt_dlp_command", lambda: ["yt-dlp"])

    def fake_run_command(args: list[str], _timeout_seconds: int):
        assert "--flat-playlist" not in args
        return (
            1,
            '{"id":"ok123","title":"Minimizer bra review","webpage_url":"https://www.youtube.com/watch?v=ok123","channel":"Reviewer"}\n',
            "ERROR: [youtube] bad123: This video is not available",
        )

    monkeypatch.setattr(youtube_module, "run_command", fake_run_command)

    result = youtube_module.fetch_youtube_ytdlp(
        "minimizer bra review",
        5,
        transcript_video_limit=0,
        comment_video_limit=0,
    )

    assert result.source_mode == "youtube_ytdlp"
    assert len(result.videos) == 1
    assert result.videos[0]["id"] == "ok123"
    assert "skipped one or more YouTube search results" in " ".join(result.warnings)


def test_youtube_ytdlp_search_falls_back_to_flat_results(monkeypatch) -> None:
    monkeypatch.setattr(youtube_module, "yt_dlp_command", lambda: ["yt-dlp"])
    calls: list[list[str]] = []

    def fake_run_command(args: list[str], _timeout_seconds: int):
        calls.append(args)
        if "--flat-playlist" in args:
            return (
                0,
                '{"id":"flat123","title":"Large bust bra haul","url":"flat123","channel":"Creator"}\n',
                "",
            )
        return 1, "", "ERROR: [youtube] gated123: Sign in to confirm your age."

    monkeypatch.setattr(youtube_module, "run_command", fake_run_command)

    result = youtube_module.fetch_youtube_ytdlp(
        "large bust bra review",
        5,
        transcript_video_limit=0,
        comment_video_limit=0,
    )

    assert len(calls) == 2
    assert any("--flat-playlist" in call for call in calls)
    assert len(result.videos) == 1
    assert result.videos[0]["url"] == "https://www.youtube.com/watch?v=flat123"
    assert "flat YouTube search fallback" in " ".join(result.warnings)


def test_tiktok_analysis_requires_detail_page_comment_samples(monkeypatch) -> None:
    def fake_collect_tiktok(
        _category: str,
        _limit: int,
        bypass_cache: bool = False,
        settings_override: dict[str, int] | None = None,
    ):
        return (
            [
                {
                    "id": "7350000000000000000",
                    "title": "Best minimizer bra for button-down shirts",
                    "url": "https://www.tiktok.com/@brareviewer/video/7350000000000000000",
                    "caption": "Testing minimizer bras for large bust support #minimizerbra #largebust",
                    "author": "@brareviewer",
                    "author_url": "https://www.tiktok.com/@brareviewer",
                    "cover_url": "https://example.com/tiktok.jpg",
                    "hashtags": ["minimizerbra", "largebust"],
                    "view_count": 220000,
                    "like_count": 18000,
                    "comment_count": 420,
                    "share_count": 1300,
                    "save_count": 700,
                    "published_at": "",
                    "comment_samples": [
                        {
                            "id": "c1",
                            "author": "@shopper",
                            "text": "I need this kind of smoothing for work shirts without shoulder digging.",
                            "like_count": 12,
                            "created_at": "",
                        }
                    ],
                    "fetched_at": "2026-06-01T00:00:00+00:00",
                }
            ],
            ["Bypassed local cache for TikTok analysis."] if bypass_cache else [],
            "tiktok_playwright",
            {
                "comments_per_video": (settings_override or {}).get("comments_per_video", 10),
                "timeout_seconds": 180,
            },
        )

    monkeypatch.setattr(server_module, "collect_tiktok", fake_collect_tiktok)

    result = analyze_tiktok_category(
        {
            "category": "minimizer bra",
            "limit": 8,
            "tiktokCommentsPerVideo": 12,
            "bypassCache": True,
        }
    )

    assert result["source_mode"] == "tiktok_playwright"
    assert result["data_volume"]["requested_videos"] == 8
    assert result["data_volume"]["collected_videos"] == 1
    assert result["data_volume"]["detail_pages_visited"] == 1
    assert result["data_volume"]["comments_per_video_limit"] == 12
    assert result["data_volume"]["comment_samples"] == 1
    assert result["metrics"]["total_views"] == 220000
    assert result["authors"][0]["name"] == "@brareviewer"
    assert result["hashtags"][0]["name"] == "minimizerbra"
    assert result["videos"][0]["comment_samples"][0]["text"]


def test_tiktok_login_wait_seconds_is_configurable(monkeypatch) -> None:
    monkeypatch.delenv("TIKTOK_LOGIN_WAIT_SECONDS", raising=False)
    assert tiktok_browser_module.tiktok_login_wait_seconds() == 240

    monkeypatch.setenv("TIKTOK_LOGIN_WAIT_SECONDS", "15")
    assert tiktok_browser_module.tiktok_login_wait_seconds() == 15

    monkeypatch.setenv("TIKTOK_LOGIN_WAIT_SECONDS", "9999")
    assert tiktok_browser_module.tiktok_login_wait_seconds() == 600

    monkeypatch.setenv("TIKTOK_LOGIN_WAIT_SECONDS", "bad")
    assert tiktok_browser_module.tiktok_login_wait_seconds() == 240


def test_tiktok_profile_uses_dedicated_chrome_profile(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(tiktok_browser_module.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("TIKTOK_BROWSER_PROFILE_DIR", raising=False)

    assert tiktok_browser_module.tiktok_profile_dir() == tmp_path / ".insight-agent" / "tiktok-chrome-profile"


def test_tiktok_chrome_path_env_overrides_discovery(monkeypatch, tmp_path) -> None:
    chrome_path = tmp_path / "chrome.exe"
    chrome_path.write_text("", encoding="utf-8")

    monkeypatch.setenv("TIKTOK_CHROME_PATH", str(chrome_path))

    assert tiktok_browser_module.find_chrome_executable() == chrome_path


def test_combined_insight_returns_fixed_cited_sections() -> None:
    reddit_report = {
        "category": "minimizer bra",
        "coverage": {"posts": 1},
        "data_volume": {"collected_comments": 1},
        "pain_points": [{"topic": "Fit and sizing"}],
        "posts": [
            {
                "title": "Looking for a minimizer bra that does not hurt",
                "url": "https://www.reddit.com/r/ABraThatFits/comments/test/minimizer/",
                "subreddit": "ABraThatFits",
                "excerpt": "Need smoothing under shirts without shoulder pain.",
                "comment_items": [{"text": "Side support and wire shape matter most."}],
            }
        ],
    }
    amazon_report = {
        "category": "minimizer bra",
        "metrics": {"products": 1, "review_samples": 1, "total_review_count": 1200, "price_avg": 29.99},
        "products": [
            {
                "title": "Smoothing Minimizer Bra",
                "brand": "Example",
                "product_url": "https://www.amazon.com/dp/B000000001",
                "price_text": "$29.99",
                "rating_value": 4.3,
                "review_count": 1200,
                "bullet_points": ["Minimizes bust line and smooths back."],
                "review_samples": [{"title": "Good shape", "body": "Fits well under button-down shirts.", "rating_value": 5}],
            }
        ],
    }

    result = analyze_combined_insight(
        {
            "category": "minimizer bra",
            "reddit_report": reddit_report,
            "amazon_report": amazon_report,
            "useLlm": False,
        }
    )

    assert result["verdict"]["citations"]
    assert len(result["opportunities"]) == 3
    assert len(result["risks"]) == 3
    assert len(result["data_gaps"]) == 3
    for section in (
        result["opportunities"],
        result["risks"],
        result["rd_recommendations"],
        result["brand_communication"],
        result["data_gaps"],
    ):
        assert all(item["citations"] for item in section)
    assert all(item["citations"] for item in result["evidence_chain"])


def test_run_agent_uses_planned_tools_and_synthesizes_artifact(monkeypatch) -> None:
    def fake_call_openai_compatible(messages):
        payload = messages[-1]["content"]
        if "tool_catalog" in payload:
            return {
                "provider": "test",
                "model": "planner",
                "usage": {"total_tokens": 12},
                "result": {
                    "tools": ["amazon_shelf", "competitor_discovery", "tiktok_social"],
                    "reason": "Competitor mode needs Amazon shelf and TikTok validation.",
                },
            }
        return {
            "provider": "test",
            "model": "synth",
            "usage": {"total_tokens": 24},
            "result": {
                "title": "AI competitor artifact",
                "executive_summary": "Amazon and TikTok tools found directional breakout evidence.",
                "key_findings": ["Wacoal is a strong candidate."],
                "opportunities": ["Validate smoother minimizer claims."],
                "risks": ["Review count is not true sales."],
                "next_steps": ["Send Wacoal to teardown."],
            },
        }

    monkeypatch.setattr(server_module, "call_openai_compatible", fake_call_openai_compatible)
    monkeypatch.setattr(
        server_module,
        "analyze_amazon_category",
        lambda payload: {
            "metrics": {"products": 1, "total_review_count": 1200},
            "price_bands": [],
            "brands": [{"name": "Wacoal", "count": 1}],
            "queries": ["minimizer bra"],
            "products": [
                {
                    "asin": "B000TEST",
                    "title": "Wacoal Visual Effects Minimizer",
                    "brand": "Wacoal",
                    "product_url": "https://www.amazon.com/dp/B000TEST",
                    "price_text": "$68.00",
                    "rating_value": 4.4,
                    "review_count": 1200,
                    "badges": ["Best Seller"],
                }
            ],
        },
    )
    monkeypatch.setattr(
        server_module,
        "analyze_tiktok_category",
        lambda payload: {
            "metrics": {"videos": 1},
            "data_volume": {"comment_samples": 2},
            "market_signal": {"summary": "TikTok has directional discussion."},
            "hashtags": [{"name": "minimizerbra", "count": 1}],
            "pain_points": [],
            "videos": [
                {
                    "title": "Minimizer bra review",
                    "url": "https://www.tiktok.com/@creator/video/1",
                    "author": "@creator",
                    "view_count": 1000,
                    "comment_samples": [{"text": "looks smooth"}, {"text": "need support"}],
                }
            ],
        },
    )

    result = server_module.run_agent(
        {
            "prompt": "帮我发现美国 minimizer bra 爆款竞品",
            "agentMode": "competitor",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert "competitor_discovery" not in server_module.AGENT_TOOL_CATALOG
    assert [tool["name"] for tool in result["tools"]] == ["amazon_shelf", "tiktok_social"]
    assert all(tool["status"] == "ok" for tool in result["tools"])
    assert result["planner"]["status"] == "ok"
    assert result["llm_analysis"]["status"] == "ok"
    assert result["artifact"]["title"] == "AI competitor artifact"
    assert result["artifact"]["key_findings"]


def test_run_agent_treats_workflow_as_plain_prompt(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    def fake_call_openai_compatible(messages):
        payload = json.loads(messages[-1]["content"])
        if "tool_catalog" in payload:
            captured["planner"] = payload
            return {
                "provider": "test",
                "model": "planner",
                "usage": {"total_tokens": 10},
                "result": {"tools": [], "reason": "Prompt-only workflow did not require live tools in this unit test."},
            }
        captured["synthesizer"] = payload
        return {
            "provider": "test",
            "model": "synth",
            "usage": {"total_tokens": 20},
            "result": {
                "title": "Prompt workflow artifact",
                "executive_summary": "Workflow instructions were included in the prompt.",
                "key_findings": ["Workflow passed through as prompt text."],
                "opportunities": [],
                "risks": [],
                "next_steps": [],
            },
        }

    monkeypatch.setattr(server_module, "call_openai_compatible", fake_call_openai_compatible)

    prompt = (
        "任务：帮我发现美国 minimizer bra 爆款竞品。\n\n"
        "工作流要求：调用 amazon_shelf 和 tiktok_social，排除 HSIA 作为竞品。"
    )
    result = server_module.run_agent(
        {
            "prompt": prompt,
            "agentMode": "competitor",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert "skill" not in result
    assert "workflow_skill" not in captured["planner"]
    assert "workflow_skill" not in captured["synthesizer"]
    assert "工作流要求：调用 amazon_shelf" in captured["planner"]["user_prompt"]
    assert "排除 HSIA" in captured["synthesizer"]["user_prompt"]
    assert result["artifact"]["title"] == "Prompt workflow artifact"


def test_run_agent_does_not_use_hardcoded_tool_routing_when_planner_unavailable(monkeypatch) -> None:
    def unavailable_llm(_messages):
        raise server_module.LLMUnavailable("No LLM configured")

    def fail_tool(_payload):
        raise AssertionError("Tool execution should only happen after LLM tool planning.")

    monkeypatch.setattr(server_module, "call_openai_compatible", unavailable_llm)
    monkeypatch.setattr(server_module, "analyze_amazon_category", fail_tool)
    monkeypatch.setattr(server_module, "analyze_tiktok_category", fail_tool)

    result = server_module.run_agent(
        {
            "prompt": "帮我发现美国 minimizer bra 爆款竞品，并用 TikTok 交叉验证",
            "agentMode": "competitor",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert result["planner"]["status"] == "unavailable"
    assert result["tools"] == []
    assert result["llm_analysis"]["status"] == "unavailable"
    assert result["artifact"]["key_findings"] == ["暂无成功工具结果。"]


def test_amazon_review_url_prefers_review_id_and_falls_back_to_review_anchor() -> None:
    assert (
        amazon_review_url({"id": "R123ABC"}, "https://www.amazon.com/dp/B000000001")
        == "https://www.amazon.com/gp/customer-reviews/R123ABC"
    )
    assert (
        amazon_review_url({}, "https://www.amazon.com/dp/B000000001?th=1")
        == "https://www.amazon.com/dp/B000000001?th=1#customerReviews"
    )


def test_research_history_save_list_delete(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "HISTORY_PATH", tmp_path / "research-history.json")

    saved = save_research_history(
        {
            "category": "minimizer bra",
            "combined_report": {
                "category": "minimizer bra",
                "verdict": {"text": "Directional demand signal."},
                "data_summary": {"evidence_items": 3},
            },
        }
    )

    item_id = saved["item"]["id"]
    listed = list_research_history()
    assert listed["storage_path"].endswith("research-history.json")
    assert listed["items"][0]["id"] == item_id
    assert listed["items"][0]["has_combined"] is True

    deleted = delete_research_history_item(item_id)
    assert deleted["deleted_id"] == item_id
    assert deleted["items"] == []


def test_bypass_cache_forces_fresh_collection(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    query = build_reddit_query("wireless bras for large bust")
    cache_path = server_module.cache_key(
        [
            server_module.CACHE_VERSION,
            "analysis",
            query,
            "10",
            "year",
            "agent_reach",
            os.getenv("AGENT_REACH_DETAIL_LIMIT", ""),
            os.getenv("AGENT_REACH_COMMENTS_PER_POST", ""),
        ]
    )
    server_module.write_cache(
        cache_path,
        {
            "posts": [
                {
                    "id": "cached",
                    "title": "Cached post",
                    "excerpt": "cached text",
                    "subreddit": "ABraThatFits",
                    "url": "https://www.reddit.com/r/ABraThatFits/comments/cached/post/",
                    "created_utc": "",
                    "score": 1,
                    "comments": 1,
                    "comment_items": [{"text": "cached comment"}],
                    "source": "reddit_agent_reach_opencli",
                }
            ],
            "mode": "agent_reach",
        },
    )

    def fake_fetch(_query: str, _limit: int, _time_range: str) -> ProviderResult:
        return ProviderResult(
            [
                EvidenceItem(
                    source="reddit",
                    provider="agent_reach_opencli",
                    content_type="post",
                    title="Fresh post",
                    text="fresh text",
                    url="https://www.reddit.com/r/ABraThatFits/comments/fresh/post/",
                    external_id="fresh",
                    community="ABraThatFits",
                    metrics={"score": 2, "comments": 1},
                    comments=[{"text": "fresh comment"}],
                )
            ],
            [],
            "agent_reach",
        )

    monkeypatch.setattr("insight_agent.server.fetch_reddit_agent_reach", fake_fetch)

    cached = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "agent_reach",
            "limit": 10,
            "timeRange": "year",
            "useLlm": False,
        }
    )
    fresh = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "agent_reach",
            "limit": 10,
            "timeRange": "year",
            "bypassCache": True,
            "useLlm": False,
        }
    )

    assert cached["posts"][0]["title"] == "Cached post"
    assert fresh["posts"][0]["title"] == "Fresh post"
    assert "Bypassed local cache" in " ".join(fresh["warnings"])


def test_opencli_read_rows_are_normalized_as_comments() -> None:
    items = normalize_opencli_read_items(
        [
            {
                "type": "POST",
                "author": "op",
                "score": 9,
                "text": "Balconette bra fit check\n\nLooking for strap and cup feedback.",
            },
            {
                "type": "L0",
                "author": "helper",
                "score": 0,
                "text": "The wire looks too narrow in this size.",
            },
            {
                "type": "L1",
                "author": "reply",
                "score": 2,
                "text": "Try a wider cup or a different brand.",
            },
            {"type": "", "text": "[+3 more top-level comments]"},
        ],
        "https://www.reddit.com/r/ABraThatFits/comments/abc123/balconette_bra_fit_check/",
        "agent_reach_opencli",
    )

    assert len(items) == 1
    assert items[0].external_id == "abc123"
    assert items[0].title == "Balconette bra fit check"
    assert len(items[0].comments) == 2
    assert items[0].comments[0]["score"] == 0


def test_explicit_agent_reach_does_not_fallback_to_rss_or_sample(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    def fake_fetch(_query: str, _limit: int, _time_range: str) -> ProviderResult:
        return ProviderResult([], ["OpenCLI is installed, but the Chrome extension is not connected."], "agent_reach")

    def fail_rss(*_args, **_kwargs):
        raise AssertionError("RSS should not be called for explicit Agent Reach mode")

    monkeypatch.setattr("insight_agent.server.fetch_reddit_agent_reach", fake_fetch)
    monkeypatch.setattr("insight_agent.server.fetch_reddit_rss", fail_rss)

    result = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "agent_reach",
            "limit": 10,
            "timeRange": "year",
            "bypassCache": True,
            "useLlm": False,
        }
    )

    assert result["source_mode"] == "agent_reach"
    assert result["coverage"]["posts"] == 0
    assert result["data_volume"]["collected_posts"] == 0
    assert "OpenCLI is installed" in " ".join(result["warnings"])
    assert "Not falling back" in " ".join(result["warnings"])


def test_reconnect_opencli_restarts_daemon_and_refreshes_health(monkeypatch) -> None:
    commands: list[list[str]] = []
    health_calls = {"count": 0}

    def fake_health() -> dict[str, object]:
        health_calls["count"] += 1
        connected = health_calls["count"] >= 3
        return {
            "agent_reach_installed": True,
            "opencli_installed": True,
            "opencli_connected": connected,
            "rdt_installed": False,
            "agent_reach_path": "agent-reach",
            "opencli_path": "opencli",
            "rdt_path": "",
            "ready": connected,
            "recommended_backend": "opencli" if connected else "",
        }

    def fake_run_command(args: list[str], _timeout_seconds: int) -> tuple[int, str, str]:
        commands.append(args)
        if args == ["opencli", "daemon", "restart"]:
            return 0, "Daemon restarted", ""
        if args == ["opencli", "profile", "list"]:
            return 0, "Default profile", ""
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr(agent_reach_module, "agent_reach_health", fake_health)
    monkeypatch.setattr(agent_reach_module, "run_command", fake_run_command)
    monkeypatch.setattr(agent_reach_module.time, "sleep", lambda _seconds: None)

    result = agent_reach_module.reconnect_opencli_extension()

    assert result["ok"] is True
    assert result["health"]["opencli_connected"] is True
    assert ["opencli", "daemon", "restart"] in commands
    assert result["profiles"]["stdout"] == "Default profile"


def test_llm_provider_settings_are_data_driven() -> None:
    providers = load_llm_providers()
    names = {provider.name for provider in providers}
    settings = build_llm_settings_response()

    assert "openai" in names
    assert settings["providers"]
    assert "api_key_configured" in settings


def test_reddit_settings_redacts_secret() -> None:
    settings = build_reddit_settings_response(
        {
            "REDDIT_CLIENT_ID": "client-id",
            "REDDIT_CLIENT_SECRET": "client-secret",
            "REDDIT_USER_AGENT": "InsightAgentTest/0.1 by tester",
        }
    )

    assert settings["client_id"] == "client-id"
    assert settings["client_secret_configured"] is True
    assert "client-secret" not in settings.values()
    assert settings["oauth_ready"] is True


def test_update_reddit_settings_writes_env_and_syncs_process(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    env_path.write_text("", encoding="utf-8")
    example_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(settings_module, "ENV_PATH", env_path)
    monkeypatch.setattr(settings_module, "ENV_EXAMPLE_PATH", example_path)
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)

    result = update_reddit_settings(
        {
            "client_id": "abc123",
            "client_secret": "secret456",
            "user_agent": "InsightAgentTest/0.1 by tester",
        }
    )

    assert result["oauth_ready"] is True
    assert os.environ["REDDIT_CLIENT_ID"] == "abc123"
    assert os.environ["REDDIT_CLIENT_SECRET"] == "secret456"
    assert "REDDIT_CLIENT_SECRET=secret456" in env_path.read_text(encoding="utf-8")


def test_update_research_settings_writes_data_volume_defaults(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    env_path.write_text("", encoding="utf-8")
    example_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(settings_module, "ENV_PATH", env_path)
    monkeypatch.setattr(settings_module, "ENV_EXAMPLE_PATH", example_path)
    for key in (
        "INSIGHT_RESEARCH_MODE",
        "INSIGHT_RESEARCH_TIME_RANGE",
        "INSIGHT_RESEARCH_POST_LIMIT",
        "INSIGHT_LLM_EVIDENCE_POSTS",
        "INSIGHT_LLM_COMMENT_SAMPLES_PER_POST",
        "AMAZON_PRODUCT_LIMIT",
        "AMAZON_KEYWORD_LIMIT",
        "AMAZON_DETAIL_LIMIT",
        "AMAZON_DISCUSSION_LIMIT",
        "AMAZON_REVIEWS_PER_PRODUCT",
        "AMAZON_LLM_PRODUCT_LIMIT",
        "AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT",
    ):
        monkeypatch.delenv(key, raising=False)

    result = update_research_settings(
        {
            "mode": "agent_reach",
            "timeRange": "month",
            "limit": 120,
            "llmEvidencePosts": 30,
            "llmCommentSamplesPerPost": 10,
            "amazonProductLimit": 60,
            "amazonKeywordLimit": 9,
            "amazonDetailLimit": 12,
            "amazonDiscussionLimit": 8,
            "amazonReviewsPerProduct": 15,
            "amazonLlmProductLimit": 40,
            "amazonLlmReviewSamplesPerProduct": 6,
        }
    )

    assert result["limit"] == 120
    assert result["llmEvidencePosts"] == 30
    assert result["amazonProductLimit"] == 60
    assert result["amazonKeywordLimit"] == 9
    assert os.environ["INSIGHT_RESEARCH_POST_LIMIT"] == "120"
    assert os.environ["AMAZON_PRODUCT_LIMIT"] == "60"
    assert os.environ["AMAZON_KEYWORD_LIMIT"] == "9"
    assert "INSIGHT_LLM_COMMENT_SAMPLES_PER_POST=10" in env_path.read_text(encoding="utf-8")
    assert "AMAZON_DISCUSSION_LIMIT=8" in env_path.read_text(encoding="utf-8")


def test_web_search_settings_redacts_key() -> None:
    settings = build_web_search_settings_response(
        {
            "INSIGHT_WEB_SEARCH_PROVIDER": "brave",
            "BRAVE_SEARCH_API_KEY": "brave-secret",
        }
    )

    assert settings["provider"] == "brave"
    assert settings["api_key_configured"] is True
    assert "brave-secret" not in settings.values()


def test_web_search_settings_default_agent_reach_requires_no_key() -> None:
    settings = build_web_search_settings_response({})

    assert settings["provider"] == "agent_reach"
    assert settings["api_key_required"] is False
    assert settings["api_key_configured"] is True


def test_update_web_search_settings_writes_env_and_syncs_process(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    env_path.write_text("", encoding="utf-8")
    example_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(settings_module, "ENV_PATH", env_path)
    monkeypatch.setattr(settings_module, "ENV_EXAMPLE_PATH", example_path)
    monkeypatch.delenv("INSIGHT_WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    result = update_web_search_settings(
        {
            "provider": "tavily",
            "api_key": "tvly-test",
        }
    )

    assert result["provider"] == "tavily"
    assert result["api_key_configured"] is True
    assert os.environ["INSIGHT_WEB_SEARCH_PROVIDER"] == "tavily"
    assert os.environ["TAVILY_API_KEY"] == "tvly-test"
    assert "TAVILY_API_KEY=tvly-test" in env_path.read_text(encoding="utf-8")


def test_research_settings_clamps_defaults() -> None:
    settings = build_research_settings_response(
        {
            "INSIGHT_RESEARCH_MODE": "auto",
            "INSIGHT_RESEARCH_TIME_RANGE": "year",
            "INSIGHT_RESEARCH_POST_LIMIT": "999",
            "INSIGHT_LLM_EVIDENCE_POSTS": "0",
            "INSIGHT_LLM_COMMENT_SAMPLES_PER_POST": "99",
            "AMAZON_PRODUCT_LIMIT": "999",
            "AMAZON_KEYWORD_LIMIT": "99",
            "AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT": "99",
        }
    )

    assert settings["limit"] == 500
    assert settings["llmEvidencePosts"] == 1
    assert settings["llmCommentSamplesPerPost"] == 50
    assert settings["amazonProductLimit"] == 100
    assert settings["amazonKeywordLimit"] == 20
    assert settings["amazonLlmReviewSamplesPerProduct"] == 50


def test_article_search_queries_include_media_site_queries() -> None:
    queries = build_article_search_queries("large bust minimizer bra", limit=8)

    joined = " ".join(queries).lower()
    assert "minimizer bra" in joined
    assert any(query.startswith("site:goodhousekeeping.com") for query in queries)


def test_discover_article_urls_scores_and_dedupes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    def fake_web_search(query: str, count: int, bypass_cache: bool = False) -> tuple[str, list[dict[str, str]], list[str]]:
        assert count == 5
        return (
            "brave",
            [
                {
                    "title": "Best Minimizer Bras for Large Busts, Tested",
                    "url": "https://www.goodhousekeeping.com/clothing/bra-reviews/best-minimizer-bras/?utm_source=test",
                    "snippet": "Our editors tested supportive minimizer bras for large busts.",
                    "published": "2026",
                },
                {
                    "title": "Amazon minimizer bra",
                    "url": "https://www.amazon.com/dp/B000000000",
                    "snippet": "Product page",
                    "published": "",
                },
            ],
            [],
        )

    monkeypatch.setattr(server_module, "web_search_query", fake_web_search)

    result = discover_article_urls(
        {
            "category": "large bust minimizer bra",
            "queryLimit": 2,
            "resultsPerQuery": 5,
            "candidateLimit": 10,
        }
    )

    assert result["data_volume"]["raw_results"] == 4
    assert result["data_volume"]["candidate_count"] == 1
    assert result["candidates"][0]["domain"] == "goodhousekeeping.com"
    assert result["candidates"][0]["score"] >= 70


def test_llm_analysis_is_requested_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    def fake_enhance(_report: dict[str, object]) -> dict[str, object]:
        return {
            "provider": "test",
            "model": "test-model",
            "result": {"executive_summary": "Default AI synthesis ran."},
        }

    monkeypatch.setattr("insight_agent.server.enhance_report_with_llm", fake_enhance)

    result = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "sample",
            "limit": 6,
            "timeRange": "year",
        }
    )

    assert result["data_volume"]["llm_requested"] is True
    assert result["llm_analysis"]["enabled"] is True
    assert result["llm_analysis"]["status"] == "ok"
    assert result["llm_analysis"]["result"]["executive_summary"] == "Default AI synthesis ran."


def test_llm_analysis_fails_closed_without_key(monkeypatch) -> None:
    monkeypatch.setenv("INSIGHT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("INSIGHT_LLM_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    result = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "sample",
            "limit": 6,
            "timeRange": "year",
            "useLlm": True,
        }
    )

    assert result["llm_analysis"]["enabled"] is True
    assert result["llm_analysis"]["status"] == "unavailable"

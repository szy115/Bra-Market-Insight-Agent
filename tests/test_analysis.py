import json
import os
from collections import Counter
from typing import Any

import pytest

from insight_agent import server as server_module
from insight_agent import settings as settings_module
from insight_agent.ingestion import agent_reach as agent_reach_module
from insight_agent.ingestion import tiktok_browser as tiktok_browser_module
from insight_agent.ingestion import youtube_ytdlp as youtube_module
from insight_agent.ingestion.agent_reach import normalize_opencli_read_items
from insight_agent.ingestion.amazon_opencli import (
    AmazonResult,
    build_amazon_queries,
    normalize_review_samples,
)
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
    build_mcp_settings_response,
    build_reddit_settings_response,
    build_research_settings_response,
    build_web_search_settings_response,
    load_llm_providers,
    update_mcp_settings,
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


def test_reddit_flexible_time_range_fetches_broader_window_and_filters(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    now = server_module.dt.datetime.now(server_module.dt.UTC)
    captured: dict[str, object] = {}

    def fake_fetch(query: str, limit: int, time_range: str, **_kwargs) -> ProviderResult:
        captured["query"] = query
        captured["limit"] = limit
        captured["time_range"] = time_range
        recent = EvidenceItem(
            source="reddit",
            provider="agent_reach_opencli",
            content_type="post",
            title="Recent minimizer bra discussion",
            text="Need a smoother minimizer bra for a large bust.",
            url="https://www.reddit.com/r/ABraThatFits/comments/recent/post/",
            external_id="recent",
            community="ABraThatFits",
            created_at=(now - server_module.dt.timedelta(days=10)).isoformat(),
            metrics={"score": 10, "comments": 1},
        )
        old = EvidenceItem(
            source="reddit",
            provider="agent_reach_opencli",
            content_type="post",
            title="Old minimizer bra discussion",
            text="Older thread about minimizer bra.",
            url="https://www.reddit.com/r/ABraThatFits/comments/old/post/",
            external_id="old",
            community="ABraThatFits",
            created_at=(now - server_module.dt.timedelta(days=200)).isoformat(),
            metrics={"score": 8, "comments": 1},
        )
        return ProviderResult([recent, old], [], "agent_reach")

    monkeypatch.setattr("insight_agent.server.fetch_reddit_agent_reach", fake_fetch)

    result = analyze_category(
        {
            "category": "minimizer bra",
            "mode": "agent_reach",
            "limit": 10,
            "timeRange": "90d",
            "useLlm": False,
        }
    )

    assert captured["time_range"] == "year"
    assert captured["limit"] == 40
    assert [post["id"] for post in result["posts"]] == ["recent"]
    assert "Filtered 1 Reddit posts outside requested time range 90d." in " ".join(result["warnings"])


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


def test_compact_agent_amazon_shelf_keeps_all_products() -> None:
    products = [
        {
            "asin": f"B000000{i:03d}",
            "title": f"Example Minimizer Bra {i}",
            "brand": "Example",
            "product_url": f"https://www.amazon.com/dp/B000000{i:03d}",
            "image_url": f"https://images.example.com/B000000{i:03d}.jpg",
            "price_text": "$29.99",
            "rating_value": 4.2,
            "review_count": 100 + i,
            "badges": ["Overall Pick", "Sponsored", "Prime", "Deal", "Extra"],
            "review_samples": [
                {"title": f"Review {i}", "body": f"Review body {i}", "rating_value": 5}
            ]
            if i in (0, 11)
            else [],
        }
        for i in range(12)
    ]

    result = server_module.compact_agent_result(
        "amazon_shelf",
        {
            "metrics": {"products": len(products)},
            "price_bands": [],
            "brands": [],
            "queries": ["minimizer bra"],
            "products": products,
        },
    )

    assert len(result["products"]) == 12
    assert result["products"][0]["asin"] == "B000000000"
    assert result["products"][0]["image_url"] == "https://images.example.com/B000000000.jpg"
    assert result["products"][-1]["asin"] == "B000000011"
    assert result["products"][0]["review_sample_count"] == 1
    assert result["products"][0]["review_samples"][0]["body"] == "Review body 0"
    assert result["products"][-1]["review_samples"][0]["body"] == "Review body 11"
    assert "review_samples" not in result


def test_normalize_review_samples_keeps_review_media_urls() -> None:
    reviews = normalize_review_samples(
        [
            {
                "review_id": "R1",
                "title": "Band rolls up",
                "body": "The band rolls and the cup gaps.",
                "images": [{"url": "https://images.example.com/review-1.jpg"}],
                "media_urls": ["https://images.example.com/review-2.jpg"],
            }
        ]
    )

    assert reviews[0]["media_urls"] == [
        "https://images.example.com/review-2.jpg",
        "https://images.example.com/review-1.jpg",
    ]


def test_hot_product_pain_report_uses_generic_llm_html_renderer(monkeypatch) -> None:
    tool_results = [
        {
            "name": "sellersprite_market_research",
            "label": "SellerSprite market research",
            "status": "ok",
            "summary": "SellerSprite returned top product candidates.",
            "data": {
                "data": {
                    "items": [
                        {
                            "asin": "B000TEST1",
                            "title": "Smoothing Minimizer Bra",
                            "brand": "Example",
                            "price": "$25.99",
                            "rating": 4.1,
                            "review_count": 1234,
                            "image_url": "https://m.media-amazon.com/images/I/product._SY200.jpg",
                        }
                    ]
                }
            },
        },
        {
            "name": "sellersprite_review",
            "label": "SellerSprite review",
            "status": "ok",
            "outcome": "ok_with_data",
            "summary": "SellerSprite review completed.",
            "input": {"asin": "B000TEST1"},
            "data": {
                "data": {
                    "total": 1,
                    "items": [
                        {
                            "star": 1,
                            "title": "Too small",
                            "content": "Band is too tight.",
                            "images": ["https://m.media-amazon.com/images/I/review._SY200.jpg"],
                            "skus": ["Size: 40DDD"],
                        }
                    ],
                }
            },
        },
    ]

    def fake_call_openai_compatible(messages):
        payload = json.loads(messages[-1]["content"])
        serialized = json.dumps(payload["tool_results"], ensure_ascii=False)
        assert "market_report_data" not in payload
        assert "B000TEST1" in serialized
        assert "https://m.media-amazon.com/images/I/product._SY200.jpg" in serialized
        assert "https://m.media-amazon.com/images/I/review._SY200.jpg" in serialized
        assert payload["required_product_image_urls"] == [
            "https://m.media-amazon.com/images/I/product._SY200.jpg"
        ]
        assert payload["required_review_image_urls"] == [
            "https://m.media-amazon.com/images/I/review._SY200.jpg"
        ]
        assert "逐商品卡片" in payload["style_reference_from_skill"]
        return {
            "provider": "test-provider",
            "model": "html-model",
            "usage": {"total_tokens": 222},
            "result": {
                "title": "LLM 自写爆款痛点报告",
                "executive_summary": "LLM directly authored the hot product pain report from SellerSprite evidence.",
                "html": """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LLM 自写爆款痛点报告</title>
<style>
body{margin:0;background:#fff;color:#172033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.65}
.report{max-width:1180px;margin:0 auto;padding:32px;display:grid;grid-template-columns:minmax(0,1fr) 220px;gap:24px}
.hero{border-bottom:1px solid #e5e7eb;padding-bottom:20px}
.product-card{display:grid;grid-template-columns:120px minmax(0,1fr);gap:18px;border:1px solid #e5e7eb;border-radius:8px;padding:18px;margin-top:18px}
.product-card img{width:120px;aspect-ratio:1;object-fit:contain;border:1px solid #eef2f7;border-radius:6px}
.evidence{color:#64748b;font-size:12px}
.matrix{border-top:1px solid #e5e7eb;margin-top:22px;padding-top:18px}
aside{position:sticky;top:16px;align-self:start;border-left:3px solid #2563eb;padding-left:14px}
</style>
</head>
<body>
<div class="report">
<main>
<header class="hero"><h1>LLM 自写爆款痛点报告</h1><p>答案先行：头部商品被购买是因为平滑显小，但差评集中在尺码偏小和穿着压迫。</p></header>
<article class="product-card">
<img src="https://m.media-amazon.com/images/I/product._SY200.jpg" alt="B000TEST1 product">
<div><h2>B000TEST1 · Smoothing Minimizer Bra</h2><p>痛点证据：1 星评论 Too small，内容为 Band is too tight。</p><img src="https://m.media-amazon.com/images/I/review._SY200.jpg" alt="review media"><p class="evidence">SellerSprite review · ASIN B000TEST1 · Size: 40DDD</p></div>
</article>
<section class="matrix"><h2>横向痛点矩阵</h2><p>尺码/版型：偏小；舒适度：压迫。该判断只来自 SellerSprite review 样本，不扩展为全市场结论。</p></section>
</main>
<aside><strong>目录</strong><a href="#cards">逐商品证据</a></aside>
</div>
</body>
</html>""",
                "artifact": {
                    "title": "LLM 自写爆款痛点报告",
                    "executive_summary": "LLM directly authored the hot product pain report from SellerSprite evidence.",
                    "key_findings": ["尺码偏小来自 B000TEST1 评论证据。"],
                    "opportunity_pool": [],
                    "risks": [],
                    "next_steps": [],
                },
            },
        }

    monkeypatch.setattr(
        server_module,
        "call_openai_compatible_chat",
        lambda messages: html_chat_response_from_result(fake_call_openai_compatible(messages)),
    )

    rendered = server_module.execute_agent_tool_with_timeout(
        "render_html_report",
        "minimizer bra",
        {
            "prompt": "使用 hot_product_pain_analysis Skill 做爆款痛点分析。参数：head_listing_count=1。",
            "toolResults": tool_results,
            "useLlm": True,
            "skillId": "hot_product_pain_analysis",
            "skillMarkdown": "### HTML Report Style Reference\n\n必须输出逐商品卡片和横向痛点矩阵。",
            "agentToolRetryDelayMs": 0,
        },
    )

    assert rendered["status"] == "ok"
    assert rendered["data"]["renderer"] == "llm-html"
    assert "LLM 自写爆款痛点报告" in rendered["data"]["html"]
    assert "https://m.media-amazon.com/images/I/review._SY200.jpg" in rendered["data"]["html"]
    assert "Hot Product Pain Analysis" not in rendered["data"]["html"]
    assert "report-shell" not in rendered["data"]["html"]


def test_competitor_product_deep_dive_skill_loads_product_report_template() -> None:
    skill = server_module.AGENT_SKILL_REGISTRY["competitor_product_deep_dive"]
    required_sections = server_module.html_template_required_sections(skill["html_template"])

    assert skill["html_template_path"].replace("\\", "/").endswith(
        "skills/competitor_product_deep_dive/assets/report-template.html"
    )
    assert required_sections == [
        "executive",
        "product-baseline",
        "positioning",
        "product-system",
        "fit-voc",
        "comparison",
        "genes",
        "hsia-actions",
        "evidence-gaps",
    ]
    assert "Listing SEO" in skill["markdown"]
    assert "不应照搬" in skill["markdown"]


def test_hot_product_pain_and_competitor_deep_dive_remain_separate_skills() -> None:
    pain_skill = server_module.AGENT_SKILL_REGISTRY["hot_product_pain_analysis"]
    deep_dive_skill = server_module.AGENT_SKILL_REGISTRY["competitor_product_deep_dive"]

    assert pain_skill["name"] == "爆款痛点分析 Skill"
    assert pain_skill["input_schema"]["required"] == ["marketplace", "category", "head_listing_count"]
    assert pain_skill["html_template"] == ""
    assert deep_dive_skill["name"] == "爆款深度拆解 Skill"
    assert deep_dive_skill["input_schema"]["required"] == ["marketplace", "asin"]
    assert deep_dive_skill["html_template"]


def test_hot_product_pain_skill_requires_complete_review_and_sif_evidence() -> None:
    skill = server_module.AGENT_SKILL_REGISTRY["hot_product_pain_analysis"]
    policy = {row["tool"]: row["policy"] for row in skill["tool_policy"]}
    evidence = {row["evidence_id"]: row for row in skill["evidence_contract"]}

    assert skill["input_schema"]["defaults"]["time_range"] == "180d"
    assert skill["input_schema"]["defaults"]["review_sample_size"] == 30
    assert policy["sellersprite_product_node"] == "required"
    assert policy["sellersprite_market_product_concentration"] == "required"
    assert policy["sellersprite_review"] == "required"
    assert policy["sif_ops_get_asin_sales_list"] == "required"
    assert policy["sif_market_get_keyword_competition"] == "required"
    assert evidence["sellersprite_review_samples"]["min_success"] == "param:head_listing_count"
    assert evidence["sellersprite_review_samples"]["severity"] == "block"
    assert evidence["sif_sales_proxy"]["severity"] == "block"


def test_competitor_product_deep_dive_skill_registers_single_asin_and_reddit_contract() -> None:
    skill = server_module.AGENT_SKILL_REGISTRY["competitor_product_deep_dive"]
    policy = {row["tool"]: row["policy"] for row in skill["tool_policy"]}
    evidence = {row["evidence_id"]: row for row in skill["evidence_contract"]}

    assert skill["input_schema"]["required"] == ["marketplace", "asin"]
    assert policy["sellersprite_asin_detail"] == "required"
    assert policy["sellersprite_review"] == "required"
    assert policy["reddit_voc"] == "required"
    assert policy["sellersprite_market_research"] == "disallowed"
    assert evidence["product_identity"]["severity"] == "block"
    assert evidence["reddit_user_voc"]["severity"] == "warn"
    for expected in ("这个款为什么卖", "核心用户是谁", "Hsia 能学什么", "不应该照搬什么"):
        assert expected in skill["markdown"]


def test_product_report_template_is_sent_to_llm_and_enforced(monkeypatch) -> None:
    skill = server_module.AGENT_SKILL_REGISTRY["competitor_product_deep_dive"]
    required_sections = server_module.html_template_required_sections(skill["html_template"])
    captured: dict[str, Any] = {}

    def fake_call_openai_compatible(messages):
        payload = json.loads(messages[-1]["content"])
        captured.update(payload)
        sections = "".join(
            f'<section data-required-section="{section_id}"><h2>{section_id}</h2></section>'
            for section_id in required_sections
        )
        return {
            "provider": "test-provider",
            "model": "html-model",
            "usage": {"total_tokens": 321},
            "result": {
                "title": "产品研发竞品拆解",
                "executive_summary": "基于商品和评论证据的产品判断。",
                "html": (
                    "<!doctype html><html lang=\"zh-CN\"><head><style>"
                    "body{font-family:sans-serif;color:#222}section{padding:16px;border-bottom:1px solid #ddd}"
                    "</style></head><body>"
                    f"{sections}<p>{'产品证据与研发验证。' * 80}</p></body></html>"
                ),
                "artifact": {"title": "产品研发竞品拆解"},
            },
        }

    monkeypatch.setattr(
        server_module,
        "call_openai_compatible_chat",
        lambda messages: html_chat_response_from_result(fake_call_openai_compatible(messages)),
    )

    html_content, _, analysis = server_module.compose_html_report_with_llm(
        {
            "prompt": "从产品研发角度深拆 Amazon US ASIN B000TEST1。",
            "category": "minimizer bra",
            "toolResults": [{"name": "sellersprite_asin_detail", "status": "ok", "data": {"asin": "B000TEST1"}}],
            "skillId": "competitor_product_deep_dive",
            "skillMarkdown": skill["markdown"],
            "skillHtmlTemplate": skill["html_template"],
        }
    )

    assert analysis["status"] == "ok"
    assert captured["required_template_sections"] == required_sections
    assert "data-required-section=\"executive\"" in captured["skill_html_template"]
    assert all(f'data-required-section="{section_id}"' in html_content for section_id in required_sections)


def test_html_validator_rejects_missing_product_report_section() -> None:
    template = (
        '<section data-required-section="executive"></section>'
        '<section data-required-section="genes"></section>'
    )
    html_content = (
        "<!doctype html><html><head><style>body{color:#222}</style></head><body>"
        '<section data-required-section="executive"><h1>结论</h1></section>'
        f"<p>{'evidence ' * 80}</p></body></html>"
    )

    assert server_module.validate_llm_html_document(html_content, template) == (
        "LLM HTML is missing required template section: genes."
    )


def test_html_normalizer_extracts_raw_document_and_supports_legacy_json() -> None:
    html_content = (
        "<!doctype html><html><head><style>body{color:#222}</style></head>"
        f"<body><p>{'完整报告内容。' * 80}</p></body></html>"
    )

    assert server_module.normalize_llm_html_document(f"preface\n{html_content}\ntrailing") == html_content
    assert server_module.normalize_llm_html_document(
        json.dumps({"result": {"html": html_content}}, ensure_ascii=False)
    ) == html_content


def test_html_validator_requires_ready_business_chart_ids() -> None:
    html_content = (
        "<!doctype html><html><head><style>body{color:#222}</style></head><body>"
        f"<main><p>{'完整市场报告。' * 80}</p></main></body></html>"
    )

    assert server_module.validate_llm_html_document(
        html_content,
        required_chart_ids=["price_band_distribution"],
    ) == "LLM HTML is missing required business chart: price_band_distribution."


def test_html_validator_rejects_javascript_chart_rendering() -> None:
    html_content = (
        "<!doctype html><html><head><style>body{color:#222}</style></head><body>"
        '<figure data-chart-id="price_band_distribution"><svg viewBox="0 0 100 100"></svg></figure>'
        "<script>document.querySelector('svg').innerHTML='<rect width=\"50\" height=\"50\" />';</script>"
        f"<p>{'完整市场报告。' * 80}</p></body></html>"
    )

    assert server_module.validate_llm_html_document(
        html_content,
        required_chart_ids=["price_band_distribution"],
    ) == (
        "LLM HTML must render in the sandboxed preview without JavaScript; "
        "use static HTML, CSS, and populated inline SVG charts."
    )


def test_html_validator_rejects_empty_required_chart_svg() -> None:
    html_content = (
        "<!doctype html><html><head><style>body{color:#222}</style></head><body>"
        '<figure data-chart-id="price_band_distribution"><svg viewBox="0 0 100 100"></svg></figure>'
        f"<p>{'完整市场报告。' * 80}</p></body></html>"
    )

    assert server_module.validate_llm_html_document(
        html_content,
        required_chart_ids=["price_band_distribution"],
    ) == (
        "Required business chart price_band_distribution contains an empty SVG. "
        "Write visible path, rect, circle, line, polyline, or polygon data marks directly into the HTML."
    )


def test_html_validator_accepts_static_required_chart_svg() -> None:
    html_content = (
        "<!doctype html><html><head><style>body{color:#222}</style></head><body>"
        '<figure data-chart-id="price_band_distribution">'
        '<svg viewBox="0 0 100 100"><rect x="10" y="20" width="30" height="70"></rect></svg>'
        "</figure>"
        f"<p>{'完整市场报告。' * 80}</p></body></html>"
    )

    assert server_module.validate_llm_html_document(
        html_content,
        required_chart_ids=["price_band_distribution"],
    ) == ""


def test_compact_agent_reddit_voc_keeps_all_posts_with_comments() -> None:
    posts = [
        {
            "id": f"post-{i}",
            "title": f"Reddit post {i}",
            "url": f"https://www.reddit.com/r/ABraThatFits/comments/{i}/post/",
            "subreddit": "ABraThatFits",
            "score": 10 + i,
            "comments": 2,
            "excerpt": f"Post excerpt {i}",
            "comment_items": [
                {"author": "user-a", "text": f"Comment {i}A", "score": 3},
                {"author": "user-b", "text": f"Comment {i}B", "score": 1},
            ],
        }
        for i in range(9)
    ]

    result = server_module.compact_agent_result(
        "reddit_voc",
        {
            "coverage": {"posts": len(posts)},
            "market_signal": {},
            "sentiment": {},
            "pain_points": [],
            "brands": [],
            "sizes": [],
            "posts": posts,
        },
    )

    assert len(result["posts"]) == 9
    assert result["posts"][0]["comment_sample_count"] == 2
    assert result["posts"][0]["comment_items"][0]["text"] == "Comment 0A"
    assert result["posts"][-1]["id"] == "post-8"


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


def native_tool_call(call_id: str, name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def native_chat_response(tool_calls: list[dict] | None = None, content: str = "") -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "provider": "test",
        "model": "native-tool-model",
        "usage": {"total_tokens": 12},
        "message": message,
    }


def html_chat_response_from_result(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    return {
        "provider": response.get("provider") or "test",
        "model": response.get("model") or "html-model",
        "usage": response.get("usage") or {},
        "finish_reason": response.get("finish_reason") or "stop",
        "message": {"role": "assistant", "content": str(result.get("html") or "")},
    }


def install_weekly_market_test_catalog(monkeypatch) -> None:
    monkeypatch.setattr(
        server_module,
        "get_sif_tool_catalog",
        lambda: {
            "sif_market_get_keyword_demand": {
                "label": "Sif keyword demand",
                "description": "Mock Sif keyword demand tool.",
                "source": "sif_mcp",
            },
            "sif_market_get_keyword_history": {
                "label": "Sif keyword history",
                "description": "Mock Sif keyword history tool.",
                "source": "sif_mcp",
            },
            "sif_market_get_keyword_root_trend": {
                "label": "Sif root trend",
                "description": "Mock Sif root trend tool.",
                "source": "sif_mcp",
            },
            "sif_market_get_keyword_competition": {
                "label": "Sif keyword competition",
                "description": "Mock Sif keyword competition tool.",
                "source": "sif_mcp",
            },
        },
    )
    monkeypatch.setattr(
        server_module,
        "get_sellersprite_tool_catalog",
        lambda: {
            "sellersprite_market_research": {
                "label": "SellerSprite market research",
                "description": "Mock SellerSprite market baseline tool.",
                "source": "sellersprite_mcp",
            },
            "sellersprite_aba_research_weekly": {
                "label": "SellerSprite ABA weekly",
                "description": "Mock SellerSprite weekly ABA keyword tool.",
                "source": "sellersprite_mcp",
            }
        },
    )


WEEKLY_MARKET_BASELINE_TOOLS = [
    "sif_market_get_keyword_demand",
    "sif_market_get_keyword_history",
    "sif_market_get_keyword_root_trend",
    "sif_market_get_keyword_competition",
    "sellersprite_market_research",
    "sellersprite_aba_research_weekly",
]


def weekly_market_baseline_tool_responses() -> list[dict[str, Any]]:
    return [
        native_chat_response([native_tool_call(f"call-{tool_name}", tool_name, {})])
        for tool_name in WEEKLY_MARKET_BASELINE_TOOLS
    ]


WEEKLY_MARKET_REPORT_TOOLS = [
    "build_market_report_data",
    "render_html_report",
]


def weekly_market_report_tool_responses() -> list[dict[str, Any]]:
    return [
        native_chat_response([native_tool_call(f"call-{tool_name}", tool_name, {})])
        for tool_name in WEEKLY_MARKET_REPORT_TOOLS
    ]


def fake_agent_tool_result(tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
    catalog = server_module.agent_tool_catalog()
    data: dict[str, Any] = {}
    if tool_name == "build_market_report_data":
        data = {
            "schema_version": "market_report_data.v1",
            "title": f"Hsia Amazon US市场 {category} 洞察报告",
            "category": category,
            "market_kpis": [{"label": "需求锚点", "value": "100", "source": "E01"}],
            "chart_specs": [
                {
                    "id": "keyword-demand",
                    "title": "关键词需求",
                    "type": "bar",
                    "data": [{"label": category, "value": 100}, {"label": "adjacent", "value": 60}],
                }
            ],
            "artifact": {"title": f"Hsia Amazon US市场 {category} 洞察报告"},
        }
    elif tool_name == "render_html_report":
        data = {
            "format": "html",
            "title": "Fake LLM-authored market report",
            "html": "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><style>body{font-family:sans-serif}</style></head><body><main><h1>Fake LLM-authored market report</h1><p>Rendered by the test HTML tool.</p></main></body></html>",
            "artifact": {
                "title": "Fake LLM-authored market report",
                "executive_summary": "Rendered by the test HTML tool.",
                "key_findings": [],
                "opportunity_pool": [],
                "risks": [],
                "next_steps": [],
            },
            "renderer": "llm-html",
            "html_analysis": {"enabled": True, "status": "ok", "provider": "test", "model": "html"},
        }
    return {
        "name": tool_name,
        "label": catalog[tool_name]["label"],
        "status": "ok",
        "summary": f"{tool_name} completed",
        "duration_ms": 1,
        "input": {"category": category, **payload},
        "data": data,
    }


def test_market_report_data_tools_compile_and_render_llm_authored_report(monkeypatch) -> None:
    assert "build_market_report_charts" not in server_module.agent_tool_catalog()
    tool_results = [
        {
            "name": "sif_market_get_keyword_history",
            "label": "Sif keyword history",
            "status": "ok",
            "summary": "Sif returned keyword history.",
            "data": {
                "keywords": [
                    {"keyword": "minimizer bra", "search_volume": 18787, "rank": 18},
                    {"keyword": "full coverage bra", "search_volume": 12000, "rank": 24},
                ]
            },
        },
        {
            "name": "sellersprite_market_research",
            "label": "SellerSprite market research",
            "status": "ok",
            "summary": "SellerSprite returned market data.",
            "data": {
                "monthly_sales": 141000,
                "monthly_revenue": 3670000,
                "avg_price": 26.17,
                "brands": [{"brand": "HSIA", "share": 12}, {"brand": "Bali", "share": 10}],
                "price_distribution": [{"priceRange": "$25-$35", "sales": 72000}],
            },
        },
    ]

    compiled = server_module.execute_agent_tool_with_timeout(
        "build_market_report_data",
        "minimizer bra",
        {
            "brand": "Hsia",
            "marketplace": "Amazon US",
            "timeRange": "90d",
            "toolResults": tool_results,
            "agentToolRetryDelayMs": 0,
        },
    )

    assert compiled["status"] == "ok"
    assert compiled["data"]["schema_version"] == "market_report_data.v1"
    assert compiled["data"]["market_kpis"]
    assert compiled["data"]["keyword_trends"]
    assert compiled["data"]["brand_competition"]
    assert compiled["data"]["analysis_sections"]
    assert compiled["data"]["swot"]
    assert compiled["data"]["decision_matrix"]
    assert compiled["data"]["chart_specs"]
    assert len(compiled["data"]["chart_specs"]) <= 5
    assert all(chart["quality_status"] == "ready" for chart in compiled["data"]["chart_specs"])
    assert all(chart["type"] != "line" for chart in compiled["data"]["chart_specs"])
    assert compiled["data"]["opportunity_pool"]
    assert compiled["data"]["evidence_map"][0]["tool"] == "sif_market_get_keyword_history"

    assert "evidence_sources" not in {chart["id"] for chart in compiled["data"]["chart_specs"]}
    assert "data_readiness" not in {chart["id"] for chart in compiled["data"]["chart_specs"]}

    def fake_call_openai_compatible(messages):
        payload = json.loads(messages[-1]["content"])
        assert payload["market_report_data"]["chart_specs"]
        assert payload["market_report_data"]["market_kpis"]
        assert "tool_results" not in payload
        assert payload["output_contract"]["javascript_forbidden"] is True
        assert payload["output_contract"]["static_inline_svg_charts_required"] is True
        chart_figures = "".join(
            f'<figure class="chart-card" data-chart-id="{chart_id}">'
            f'<figcaption>{chart_id}</figcaption>'
            '<svg viewBox="0 0 100 100"><rect x="10" y="20" width="30" height="70"></rect></svg>'
            "</figure>"
            for chart_id in payload["required_chart_ids"]
        )
        return {
            "provider": "test-provider",
            "model": "html-model",
            "usage": {"total_tokens": 321},
            "result": {
                "title": "Hsia LLM 市场洞察报告",
                "executive_summary": "LLM authored the final HTML from MarketReportData and chart_specs.",
                "html": """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hsia LLM 市场洞察报告</title>
<style>
body{margin:0;background:#fff;color:#172033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.65}
.report{max-width:1180px;margin:0 auto;padding:32px;display:grid;grid-template-columns:minmax(0,1fr) 220px;gap:24px}
.report-header{background:linear-gradient(135deg,#4f46e5,#06b6d4);color:white;border-radius:12px;padding:28px}
.content-section{padding:22px 0;border-bottom:1px solid #e5e7eb}
.source{color:#64748b;font-size:12px}
</style>
</head>
<body>
<div class="report">
<main>
<header class="report-header"><h1>Hsia LLM 市场洞察报告</h1><p>MarketReportData 和 chart_specs 已交给 LLM 直接组织最终 HTML。</p></header>
<section id="answer" class="content-section"><h2>答案先行</h2><p>基于关键词和 SellerSprite 市场证据，先判断需求入口，再判断价格与竞争锚点。</p><p class="source">数据源：Sif / SellerSprite</p></section>
<section class="content-section"><h2>业务图表</h2>{chart_figures}<p>chart_specs 被用于组织业务图表，而不是生成工具执行调试图。</p></section>
</main>
<aside><a href="#answer">答案先行</a></aside>
</div>
</body>
</html>""".replace("{chart_figures}", chart_figures),
                "artifact": {
                    "title": "Hsia LLM 市场洞察报告",
                    "executive_summary": "LLM authored the final HTML from MarketReportData and chart_specs.",
                    "key_findings": ["MarketReportData was used."],
                    "opportunity_pool": [],
                    "risks": [],
                    "next_steps": [],
                },
            },
        }

    monkeypatch.setattr(
        server_module,
        "call_openai_compatible_chat",
        lambda messages: html_chat_response_from_result(fake_call_openai_compatible(messages)),
    )

    rendered = server_module.execute_agent_tool_with_timeout(
        "render_html_report",
        "minimizer bra",
        {
            "marketReportData": compiled["data"],
            "useLlm": True,
            "skillMarkdown": "### HTML Report Style Reference\n\n使用 LinkFox editorial 风格，必须答案先行。",
            "agentToolRetryDelayMs": 0,
        },
    )

    assert rendered["status"] == "ok"
    assert rendered["data"]["format"] == "html"
    assert rendered["data"]["renderer"] == "llm-html"
    assert "<html" in rendered["data"]["html"]
    assert "MarketReportData 和 chart_specs" in rendered["data"]["html"]
    assert "mr-shell" not in rendered["data"]["html"]
    assert rendered["data"]["artifact"]["title"] == compiled["data"]["title"]


def test_market_report_data_preserves_requested_sports_bra_category() -> None:
    tool_results = [
        {
            "name": "sif_market_get_keyword_history",
            "label": "Sif keyword history",
            "status": "ok",
            "summary": "Sif returned keyword history.",
            "data": {"keywords": [{"keyword": "sports bra", "search_volume": 26000, "rank": 9}]},
        },
        {
            "name": "sellersprite_market_research",
            "label": "SellerSprite market research",
            "status": "ok",
            "summary": "SellerSprite returned sports bra category data.",
            "data": {
                "nodeLabelName": "Sports Bras",
                "monthly_revenue": 29107722,
                "avg_price": 24.96,
                "brands": [{"brand": "Nike", "share": 12}],
            },
        },
    ]

    report_data = server_module.build_market_report_data(
        {
            "category": "sports bra",
            "brand": "Hsia",
            "marketplace": "Amazon US",
            "timeRange": "90d",
            "toolResults": tool_results,
        }
    )
    charts = server_module.build_market_report_charts(report_data)

    assert report_data["category"] == "sports bra"
    assert "sports bra" in report_data["title"]
    assert "minimizer bra" not in json.dumps(report_data, ensure_ascii=False).lower()
    assert all(chart["quality_status"] == "ready" for chart in charts["chart_specs"])
    assert len(charts["chart_specs"]) <= 5

    with pytest.raises(ValueError, match="category is required"):
        server_module.build_market_report_data({"brand": "Hsia", "toolResults": tool_results})


def test_market_report_data_maps_node_tools_to_semantic_chart_specs() -> None:
    tool_results = [
        {
            "name": "sif_market_get_keyword_history",
            "label": "Sif keyword history",
            "status": "ok",
            "data": {
                "keywords": [
                    {"keyword": "minimizer bra", "search_volume": 18000, "rank": 10},
                    {"keyword": "minimizer bras", "search_volume": 9000, "rank": 18},
                ]
            },
        },
        {
            "name": "sellersprite_market_research",
            "label": "SellerSprite market research",
            "status": "ok",
            "data": {"data": {"items": [{"nodeLabelName": "Minimizers", "totalUnits": 146474, "avgPrice": 26.17}]}},
        },
        {
            "name": "sellersprite_market_product_demand_trend",
            "label": "SellerSprite demand trend",
            "status": "ok",
            "data": {
                "data": {
                    "asinCount": 73101,
                    "items": [
                        {"date": "2026-03-01", "glanceViews": 1807620},
                        {"date": "2026-04-01", "glanceViews": 1818243},
                        {"date": "2026-05-01", "glanceViews": 2031461},
                        {"date": "2026-06-01", "glanceViews": 938946},
                    ],
                }
            },
        },
        {
            "name": "sellersprite_market_product_concentration",
            "label": "SellerSprite product concentration",
            "status": "ok",
            "data": {"data": [
                {"asin": "B001", "brand": "Bali", "price": 22.42, "totalUnits": 40128},
                {"asin": "B002", "brand": "Vanity Fair", "price": 26.99, "totalUnits": 30100},
            ]},
        },
        {
            "name": "sellersprite_market_brand_concentration",
            "label": "SellerSprite brand concentration",
            "status": "ok",
            "data": {"data": [
                {"brand": "Bali", "totalUnitsRatio": 0.40},
                {"brand": "Vanity Fair", "totalUnitsRatio": 0.30},
                {"brand": "Playtex", "totalUnitsRatio": 0.20},
            ]},
        },
        {
            "name": "sellersprite_market_price_distribution",
            "label": "SellerSprite price distribution",
            "status": "ok",
            "data": {"data": [
                {"label": "20-25", "units": 75089, "unitsRatio": 0.60},
                {"label": "25-35", "units": 40810, "unitsRatio": 0.40},
            ]},
        },
        {
            "name": "sellersprite_market_ratings_count_distribution",
            "label": "SellerSprite ratings distribution",
            "status": "ok",
            "data": {"data": [{"label": "1000+", "units": 90000, "unitsRatio": 0.7}]},
        },
        {
            "name": "sellersprite_market_listing_date_distribution",
            "label": "SellerSprite listing date distribution",
            "status": "ok",
            "data": {"data": [{"label": "5年以上", "units": 80000, "unitsRatio": 0.6}]},
        },
        {
            "name": "sellersprite_aba_research_weekly",
            "label": "SellerSprite ABA weekly",
            "status": "ok",
            "data": {"data": {"items": [
                {"keyword": "airpods", "searches": 2531170},
                {"keyword": "minimizer bra for women", "searches": 4200},
            ]}},
        },
    ]

    report_data = server_module.build_market_report_data(
        {
            "category": "minimizer bra",
            "brand": "Hsia",
            "marketplace": "US",
            "toolResults": tool_results,
        }
    )

    assert report_data["price_distribution"][0]["label"] == "20-25"
    assert report_data["price_distribution"][0]["evidence_id"] == "E06"
    assert report_data["brand_competition"][0]["brand"] == "Bali"
    assert report_data["brand_competition"][0]["evidence_id"] == "E05"
    assert report_data["top_products"][0]["asin"] == "B001"
    assert report_data["demand_trend"][0]["date"] == "2026-03-01"
    assert all(row["keyword"] != "airpods" for row in report_data["keyword_trends"])
    charts = {chart["id"]: chart for chart in report_data["chart_specs"]}
    assert set(charts) == {
        "category_demand_trend",
        "keyword_demand",
        "price_band_distribution",
        "brand_competition",
        "top_product_signal",
    }
    assert [point["value"] for point in charts["price_band_distribution"]["data"]] == [60.0, 40.0]
    assert charts["brand_competition"]["type"] == "donut"
    assert charts["category_demand_trend"]["type"] == "line"
    assert all(chart["quality_status"] == "ready" for chart in charts.values())


def test_market_report_llm_context_keeps_full_annual_chart_series() -> None:
    report_data = {
        "chart_specs": [
            {
                "id": "category_demand_trend",
                "title": "类目需求趋势",
                "type": "line",
                "quality_status": "ready",
                "data": [
                    {"label": f"2025-{month:02d}", "value": month * 1000}
                    for month in range(1, 14)
                ],
            }
        ]
    }

    context = server_module.market_report_llm_context(report_data)

    assert len(context["chart_specs"][0]["data"]) == 13


def test_market_report_html_can_be_authored_by_llm_from_skill_style(monkeypatch) -> None:
    report_data = {
        "schema_version": "market_report_data.v1",
        "title": "Hsia Amazon US市场 minimizer bra 洞察报告",
        "brand": "Hsia",
        "marketplace": "Amazon US",
        "category": "minimizer bra",
        "time_range": "90d",
        "generated_at": "2026-07-08T00:00:00Z",
        "executive_summary": "Compiled summary should be rewritten into the final HTML report.",
        "market_kpis": [{"label": "搜索量", "value": "18787", "source": "E01"}],
        "keyword_trends": [{"keyword": "minimizer bra", "search_volume": 18787, "source": "Sif MCP", "evidence_id": "E01"}],
        "category_benchmark": [],
        "top_products": [],
        "brand_competition": [],
        "price_distribution": [],
        "opportunity_pool": [],
        "evidence_map": [{"id": "E01", "source": "Sif MCP", "tool": "sif_market_get_keyword_history", "status": "ok"}],
        "data_gaps": [],
        "chart_specs": [],
        "artifact": {"title": "Hsia Amazon US市场 minimizer bra 洞察报告"},
    }

    def fake_call_openai_compatible(messages):
        payload = json.loads(messages[-1]["content"])
        assert "HTML Report Style Reference" not in payload["style_reference_from_skill"]
        assert payload["market_report_data"]["category"] == "minimizer bra"
        assert payload["output_contract"]["format"] == "raw_html_only"
        return {
            "provider": "test-provider",
            "model": "html-model",
            "usage": {"total_tokens": 123},
            "result": {
                "title": "LLM 主导市场洞察报告",
                "executive_summary": "LLM 直接基于证据写最终 HTML。",
                "html": """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LLM 主导市场洞察报告</title>
<style>
body{margin:0;background:#fff;color:#172033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.65}
.report{max-width:1180px;margin:0 auto;padding:32px;display:grid;grid-template-columns:minmax(0,1fr) 220px;gap:24px}
.report-header{background:linear-gradient(135deg,#4f46e5,#06b6d4);color:white;border-radius:12px;padding:28px}
.kpi-grid{display:flex;gap:12px;border-bottom:1px solid #e5e7eb;padding:16px 0}
.kpi-card{display:flex;gap:8px;align-items:baseline}
.content-section{padding:22px 0;border-bottom:1px solid #e5e7eb}
.source{color:#64748b;font-size:12px}
aside{position:sticky;top:16px;align-self:start;border-left:3px solid #4f46e5;padding-left:14px}
</style>
</head>
<body>
<div class="report">
<main>
<header class="report-header">
<h1>LLM 主导市场洞察报告</h1>
<p>答案先行：当前可以进入企划验证，但只基于 E01 的关键词搜索量证据做方向判断。</p>
</header>
<section class="kpi-grid">
<article class="kpi-card"><span>需求锚点</span><strong>18787</strong><em>E01 / Sif MCP</em></article>
</section>
<section id="llm-authored" class="content-section">
<h2>LLM 自定义洞察章节</h2>
<p>这一段由 LLM 直接组织最终 HTML，不再经过固定中间蓝图渲染层。判断依赖 minimizer bra 的搜索量字段，来源为 E01。</p>
<p class="source">数据源：Sif MCP · 证据：E01 · 周期：90d</p>
</section>
<section class="content-section">
<h2>数据缺口</h2>
<p>没有节点级价格分布和品牌集中度时，报告只能给方向性判断，不能断言类目垄断程度。</p>
</section>
</main>
<aside><strong>目录</strong><a href="#llm-authored">LLM 自定义洞察章节</a></aside>
</div>
</body>
</html>""",
                "artifact": {
                    "title": "LLM 主导市场洞察报告",
                    "executive_summary": "LLM 直接基于证据写最终 HTML。",
                    "key_findings": ["只使用已有搜索量字段。"],
                    "opportunity_pool": [],
                    "risks": ["节点级证据缺口仍需标注。"],
                    "next_steps": ["验证尺码和结构承接。"],
                },
                "quality_notes": ["HTML was authored directly from MarketReportData."],
            },
        }

    monkeypatch.setattr(
        server_module,
        "call_openai_compatible_chat",
        lambda messages: html_chat_response_from_result(fake_call_openai_compatible(messages)),
    )

    rendered = server_module.execute_agent_tool_with_timeout(
        "render_html_report",
        "minimizer bra",
        {
            "marketReportData": report_data,
            "useLlm": True,
            "skillMarkdown": "### HTML Report Style Reference\n\n使用 LinkFox editorial 风格，必须答案先行。",
            "agentToolRetryDelayMs": 0,
        },
    )

    assert rendered["status"] == "ok"
    assert rendered["data"]["html_analysis"]["status"] == "ok"
    assert rendered["data"]["renderer"] == "llm-html"
    assert "blueprint_analysis" not in rendered["data"]
    assert "report_blueprint" not in rendered["data"]
    assert "LLM 自定义洞察章节" in rendered["data"]["html"]
    assert 'id="llm-authored"' in rendered["data"]["html"]
    assert rendered["data"]["artifact"]["executive_summary"] == report_data["executive_summary"]


def test_market_report_html_fails_closed_when_llm_html_is_invalid(monkeypatch) -> None:
    report_data = {
        "schema_version": "market_report_data.v1",
        "title": "Hsia Amazon US市场 minimizer bra 洞察报告",
        "brand": "Hsia",
        "marketplace": "Amazon US",
        "category": "minimizer bra",
        "time_range": "90d",
        "executive_summary": "Compiled summary should not be rendered by the old template.",
        "market_kpis": [{"label": "搜索量", "value": "18787", "source": "E01"}],
        "evidence_map": [{"id": "E01", "source": "Sif MCP", "tool": "sif_market_get_keyword_history", "status": "ok"}],
        "chart_specs": [],
    }

    calls: list[list[dict[str, Any]]] = []

    def fake_call_openai_compatible(messages):
        calls.append(messages)
        return {
            "provider": "test-provider",
            "model": "html-model",
            "usage": {"total_tokens": 12},
            "result": {
                "title": "Bad HTML",
                "executive_summary": "Bad HTML should fail.",
                "html": "<html><body>too short</body></html>",
            },
        }

    monkeypatch.setattr(
        server_module,
        "call_openai_compatible_chat",
        lambda messages: html_chat_response_from_result(fake_call_openai_compatible(messages)),
    )

    rendered = server_module.execute_agent_tool_with_timeout(
        "render_html_report",
        "minimizer bra",
        {
            "marketReportData": report_data,
            "useLlm": True,
            "skillMarkdown": "### HTML Report Style Reference\n\n使用 LinkFox editorial 风格，必须答案先行。",
            "agentToolRetryAttempts": 0,
            "agentToolRetryDelayMs": 0,
        },
    )

    assert rendered["status"] == "retry_exhausted"
    assert rendered["data"]["html_analysis"]["status"] == "validation_failed"
    assert rendered["data"]["html_analysis"]["attempt_count"] == 2
    assert len(calls) == 2
    assert "previous response failed HTML validation" in calls[1][-1]["content"]
    assert rendered["recovery"]["attempt_count"] == 1
    assert "LLM HTML is too short" in rendered["summary"]
    assert "mr-shell" not in rendered["summary"]


def test_breakout_competitor_discovery_skill_is_not_registered() -> None:
    assert "breakout_competitor_discovery" not in server_module.AGENT_SKILL_REGISTRY
    assert all(
        skill.get("skill_id") != "breakout_competitor_discovery"
        for skill in server_module.agent_skill_manifests()
    )
    assert "competitor_discovery" not in server_module.AGENT_TOOL_CATALOG


def test_run_agent_evidence_contract_blocks_early_synthesis_and_then_allows_gap_disclosure(monkeypatch) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {
                        "skill_id": "weekly_market_insight",
                        "extracted_params": {
                            "brand": "Hsia",
                            "marketplace": "Amazon US",
                            "category": "minimizer bra",
                            "time_range": "90d",
                        },
                    },
                )
            ]
        ),
        native_chat_response([native_tool_call("call-synth-too-early", "synthesize_artifact", {})]),
        *weekly_market_baseline_tool_responses(),
        *weekly_market_report_tool_responses(),
        native_chat_response([native_tool_call("call-synth", "synthesize_artifact", {})]),
    ]
    synth_tool_results: list[list[dict[str, Any]]] = []

    def fake_call_chat(messages, tools=None, tool_choice=None):
        return chat_responses.pop(0)

    def fake_call_openai_compatible(messages):
        payload = json.loads(messages[-1]["content"])
        synth_tool_results.append(payload["tool_results"])
        return {
            "provider": "test",
            "model": "synth",
            "usage": {"total_tokens": 20},
            "result": {
                "title": "Evidence gated artifact",
                "executive_summary": "MarketReportData was built after the gate blocked early synthesis.",
                "key_findings": ["The final gate required the report data and HTML renderer tools."],
                "opportunities": [],
                "risks": [],
                "next_steps": [],
            },
        }

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)
    monkeypatch.setattr(server_module, "call_openai_compatible", fake_call_openai_compatible)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_agent_tool_result)

    result = server_module.run_agent(
        {
            "prompt": "帮我分析美国 minimizer bra 市场最近90天在变什么，品牌 Hsia，市场 Amazon US",
            "agentMode": "market",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert [tool["name"] for tool in result["tools"]] == [*WEEKLY_MARKET_BASELINE_TOOLS, *WEEKLY_MARKET_REPORT_TOOLS]
    assert any(event["title"] == "Evidence Contract 阻止生成 Artifact" for event in result["events"])
    assert result["evidence_gaps"] == []
    assert result["artifact"]["title"] == "Fake LLM-authored market report"
    assert result["llm_analysis"]["renderer"] == "llm-html"
    assert synth_tool_results == []


def test_weekly_market_agent_does_not_fallback_to_generic_html_when_render_file_missing(monkeypatch) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {
                        "skill_id": "weekly_market_insight",
                        "extracted_params": {
                            "brand": "Hsia",
                            "marketplace": "Amazon US",
                            "category": "minimizer bra",
                            "time_range": "90d",
                        },
                    },
                )
            ]
        ),
        *weekly_market_baseline_tool_responses(),
        *weekly_market_report_tool_responses(),
        native_chat_response([native_tool_call("call-synth", "synthesize_artifact", {})]),
    ]

    def fake_call_chat(messages, tools=None, tool_choice=None):
        return chat_responses.pop(0)

    def fake_tool_without_render_file(tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = fake_agent_tool_result(tool_name, category, payload)
        if tool_name == "render_html_report":
            result["data"] = {}
            result["summary"] = "render_html_report completed without an HTML file"
        return result

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_tool_without_render_file)

    result = server_module.run_agent(
        {
            "prompt": "帮我分析美国 minimizer bra 市场最近90天在变什么，品牌 Hsia，市场 Amazon US",
            "agentMode": "market",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert result["response_type"] == "message"
    assert "artifact" not in result
    assert not any(item.get("type") == "report" for item in result.get("output_files", []))
    assert any(event["type"] == "artifact" and event["status"] == "error" for event in result["events"])
    assert "不会再改用固定模板" in result["message"]["content"]


def test_weekly_market_agent_blocks_html_render_when_node_evidence_is_missing(monkeypatch) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {
                        "skill_id": "weekly_market_insight",
                        "extracted_params": {
                            "brand": "Hsia",
                            "marketplace": "Amazon US",
                            "category": "minimizer bra",
                            "time_range": "90d",
                            "category_node_id": "7141123011:1045002",
                        },
                    },
                )
            ]
        ),
        *weekly_market_baseline_tool_responses(),
        native_chat_response([native_tool_call("call-build", "build_market_report_data", {})]),
        native_chat_response([native_tool_call("call-render", "render_html_report", {})]),
        native_chat_response(
            [
                native_tool_call(
                    "call-respond",
                    "respond_to_user",
                    {"message": "节点级必需证据未成功，因此未生成报告。"},
                )
            ]
        ),
    ]

    def fake_call_chat(messages, tools=None, tool_choice=None):
        return chat_responses.pop(0)

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_agent_tool_result)

    result = server_module.run_agent(
        {
            "prompt": "生成 minimizer bra 市场洞察报告，节点 7141123011:1045002。",
            "agentMode": "market",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert all(tool["name"] != "render_html_report" for tool in result["tools"])
    assert "artifact" not in result
    assert not any(item.get("type") == "report" for item in result.get("output_files", []))
    blocked_event = next(event for event in result["events"] if event["title"] == "Evidence Contract 阻止 HTML renderer")
    missing = blocked_event["output"]["recommended_tool_calls"]
    assert "sellersprite_market_product_demand_trend" in missing
    assert "sellersprite_market_price_distribution" in missing
    assert "sellersprite_market_ratings_count_distribution" in missing
    assert "sellersprite_market_listing_date_distribution" in missing


def test_run_agent_native_loop_can_choose_tools_after_loading_skill(monkeypatch) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    chat_calls: list[list[dict]] = []
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {
                        "skill_id": "weekly_market_insight",
                        "extracted_params": {
                            "brand": "Hsia",
                            "marketplace": "US",
                            "category": "minimizer bra",
                            "time_range": "90d",
                        },
                    },
                )
            ]
        ),
        *weekly_market_baseline_tool_responses(),
        *weekly_market_report_tool_responses(),
        native_chat_response([native_tool_call("call-synth", "synthesize_artifact", {})]),
    ]

    def fake_call_chat(messages, tools=None, tool_choice=None):
        chat_calls.append(messages)
        return chat_responses.pop(0)

    def fake_call_openai_compatible(messages):
        return {
            "provider": "test",
            "model": "synth",
            "usage": {"total_tokens": 20},
            "result": {
                "title": "Action-loop market artifact",
                "executive_summary": "The model built MarketReportData before rendering HTML.",
                "key_findings": ["Tool choice came from the action loop."],
                "opportunities": [],
                "risks": [],
                "next_steps": [],
            },
        }

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)
    monkeypatch.setattr(server_module, "call_openai_compatible", fake_call_openai_compatible)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_agent_tool_result)

    result = server_module.run_agent(
        {
            "prompt": "帮我分析美国 minimizer bra 市场，先做市场底盘，再生成标准市场洞察报告",
            "agentMode": "market",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert result["runtime"]["engine"] == "langgraph"
    assert result["runtime"]["pattern"] == "native_tool_call_loop"
    assert result["skill"]["skill_id"] == "weekly_market_insight"
    assert [tool["name"] for tool in result["tools"]] == [*WEEKLY_MARKET_BASELINE_TOOLS, *WEEKLY_MARKET_REPORT_TOOLS]
    assert result["planner"]["planned_tools"] == [*WEEKLY_MARKET_BASELINE_TOOLS, *WEEKLY_MARKET_REPORT_TOOLS]
    assert result["artifact"]["title"] == "Fake LLM-authored market report"
    assert result["llm_analysis"]["renderer"] == "llm-html"
    render_tool = next(tool for tool in result["tools"] if tool["name"] == "render_html_report")
    assert render_tool["input"]["marketReportData"]["schema_version"] == "market_report_data.v1"
    assert render_tool["input"]["toolResults"] == []
    assert "chartSpecs" not in render_tool["input"]
    assert len(chat_calls) == 10
    assert any(message.get("role") == "tool" and message.get("name") == "load_skill" for message in chat_calls[1])


def test_weekly_market_agent_uses_llm_extracted_open_category(monkeypatch) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    chat_system_prompts: list[str] = []
    tool_categories: list[tuple[str, str, str]] = []
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {
                        "skill_id": "weekly_market_insight",
                        "extracted_params": {
                            "brand": "Hsia",
                            "market": "US",
                            "category": "yoga pants",
                        },
                    },
                )
            ]
        ),
        *weekly_market_baseline_tool_responses(),
        *weekly_market_report_tool_responses(),
        native_chat_response([native_tool_call("call-synth", "synthesize_artifact", {})]),
    ]

    def fake_call_chat(messages, tools=None, tool_choice=None):
        chat_system_prompts.append(messages[0]["content"])
        return chat_responses.pop(0)

    def fake_tool_result(tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
        tool_categories.append((tool_name, category, str(payload.get("category") or "")))
        return fake_agent_tool_result(tool_name, category, payload)

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_tool_result)

    result = server_module.run_agent(
        {
            "prompt": "帮我分析美国 Amazon US 市场 yoga pants 最近90天在变什么。",
            "agentMode": "market",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert result["category"] == "yoga pants"
    assert result["skill"]["params"]["category"] == "yoga pants"
    assert "Current requested category: unresolved" in chat_system_prompts[0]
    assert "Current requested category: yoga pants." in chat_system_prompts[1]
    assert "US minimizer-bra research" not in chat_system_prompts[0]
    assert "US minimizer-bra research" not in "\n".join(chat_system_prompts)
    assert [tool for tool, _, _ in tool_categories] == [*WEEKLY_MARKET_BASELINE_TOOLS, *WEEKLY_MARKET_REPORT_TOOLS]
    assert all(category == "yoga pants" for _, category, _ in tool_categories)
    assert all(payload_category == "yoga pants" for _, _, payload_category in tool_categories)


def test_weekly_market_agent_promotes_resolved_category_node_for_followup_tool(monkeypatch) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    seller_catalog = {
        "sellersprite_market_research": {
            "label": "SellerSprite market research",
            "description": "Mock SellerSprite market baseline tool.",
            "source": "sellersprite_mcp",
        },
        "sellersprite_aba_research_weekly": {
            "label": "SellerSprite ABA weekly",
            "description": "Mock SellerSprite weekly ABA keyword tool.",
            "source": "sellersprite_mcp",
        },
        "sellersprite_product_node": {
            "label": "SellerSprite product node",
            "description": "Resolve a category node path.",
            "source": "sellersprite_mcp",
        },
        "sellersprite_market_product_concentration": {
            "label": "SellerSprite product concentration",
            "description": "Use a resolved category node path.",
            "source": "sellersprite_mcp",
        },
    }
    monkeypatch.setattr(server_module, "get_sellersprite_tool_catalog", lambda: seller_catalog)
    node_id_path = "7141123011:7147440011:1040660:9522931011:14333511:1044960:1045002"
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {
                        "skill_id": "weekly_market_insight",
                        "extracted_params": {
                            "brand": "Hsia",
                            "marketplace": "Amazon US",
                            "category": "minimizer bra",
                        },
                    },
                )
            ]
        ),
        native_chat_response(
            [native_tool_call("call-node", "sellersprite_product_node", {"keyword": "Minimizers"})]
        ),
        native_chat_response(
            [native_tool_call("call-concentration", "sellersprite_market_product_concentration", {})]
        ),
        native_chat_response(
            [native_tool_call("call-done", "respond_to_user", {"message": "节点已自动解析。"})]
        ),
    ]
    tool_payloads: list[tuple[str, dict[str, Any]]] = []

    def fake_call_chat(messages, tools=None, tool_choice=None):
        return chat_responses.pop(0)

    def fake_tool_result(tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
        tool_payloads.append((tool_name, dict(payload)))
        data: dict[str, Any] = {}
        if tool_name == "sellersprite_product_node":
            data = {
                "resolved_params": {
                    "category_node_id": node_id_path,
                    "category_node_label_path": "Clothing, Shoes & Jewelry:Women:Clothing:Lingerie:Bras:Minimizers",
                }
            }
        return {
            "name": tool_name,
            "label": seller_catalog[tool_name]["label"],
            "status": "ok",
            "summary": f"{tool_name} completed",
            "duration_ms": 1,
            "input": {"category": category},
            "data": data,
        }

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_tool_result)

    result = server_module.run_agent(
        {
            "prompt": "帮我分析 Amazon US minimizer bra 市场，品牌 Hsia，并自动解析类目节点。",
            "agentMode": "market",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert result["skill"]["params"]["category_node_id"] == node_id_path
    followup_payload = next(payload for name, payload in tool_payloads if name == "sellersprite_market_product_concentration")
    assert followup_payload["category_node_id"] == node_id_path


def test_weekly_market_agent_rejects_example_category_extracted_by_model(monkeypatch) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {
                        "skill_id": "weekly_market_insight",
                        "extracted_params": {
                            "brand": "Hsia",
                            "market": "US",
                            "category": "minimizer bra",
                        },
                    },
                )
            ]
        ),
        native_chat_response(
            [
                native_tool_call(
                    "call-ask",
                    "ask_user",
                    {
                        "reason": "需要确认研究品类。",
                        "missing_params": ["category"],
                        "questions": [{"field": "category", "question": "请确认要研究的具体品类。"}],
                    },
                )
            ]
        ),
    ]

    def fake_call_chat(messages, tools=None, tool_choice=None):
        return chat_responses.pop(0)

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)

    result = server_module.run_agent(
        {
            "prompt": "帮我生成 Hsia 美国市场 Sports Bras 本周洞察报告。重点回答：市场最近在变什么。",
            "agentMode": "market",
            "useLlm": True,
        }
    )

    assert result["status"] == "needs_input"
    assert result["skill"]["missing_params"] == ["category"]
    assert result["tools"] == []


def test_run_agent_can_return_normal_chat_without_artifact(monkeypatch) -> None:
    def fake_call_chat(messages, tools=None, tool_choice=None):
        assert any(tool["function"]["name"] == "respond_to_user" for tool in tools)
        return native_chat_response(
            [
                native_tool_call(
                    "call-respond",
                    "respond_to_user",
                    {"message": "你好，我可以帮你做市场洞察、爆款痛点分析和证据驱动的研发机会分析。"},
                )
            ]
        )

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)

    result = server_module.run_agent(
        {
            "prompt": "你好",
            "agentMode": "market",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert result["response_type"] == "message"
    assert "artifact" not in result
    assert result["message"]["content"].startswith("你好")
    assert result["tools"] == []
    assert [event["type"] for event in result["events"]] == ["input", "message"]


def test_run_agent_can_inspect_capabilities_for_general_tool_questions(monkeypatch) -> None:
    monkeypatch.delenv("SIF_MCP_TOKEN", raising=False)
    monkeypatch.delenv("SIF_API_KEY", raising=False)
    monkeypatch.delenv("SIF_TOKEN", raising=False)
    monkeypatch.setattr(
        server_module,
        "get_sif_tool_catalog",
        lambda: {
            "sif_market_get_keyword_demand": {
                "label": "Sif: market_get_keyword_demand",
                "description": "Get Sif keyword demand evidence.",
                "input_schema": {"type": "object", "properties": {"keywords": {"type": "array"}}},
                "source": "sif_mcp",
                "mcp_tool": "market_get_keyword_demand",
                "auth_env_names": ["SIF_MCP_TOKEN", "SIF_API_KEY", "SIF_TOKEN"],
            }
        },
    )
    chat_calls: list[list[dict]] = []

    def fake_call_chat(messages, tools=None, tool_choice=None):
        chat_calls.append(messages)
        assert any(tool["function"]["name"] == "inspect_agent_capabilities" for tool in tools)
        if len(chat_calls) == 1:
            system_prompt = messages[0]["content"]
            assert "inspect_agent_capabilities" in system_prompt
            assert "sif_market_get_keyword_demand (sif_mcp)" in system_prompt
            return native_chat_response(
                [
                    native_tool_call(
                        "call-inspect",
                        "inspect_agent_capabilities",
                        {"focus": "Sif MCP"},
                    )
                ]
            )
        capability_observation = next(
            message for message in messages if message.get("role") == "tool" and message.get("name") == "inspect_agent_capabilities"
        )
        payload = json.loads(capability_observation["content"])
        assert payload["status"] == "ok"
        assert payload["tool_sources"][0]["source"] == "sif_mcp"
        assert payload["tool_sources"][0]["registered"] is True
        assert payload["tool_sources"][0]["auth_configured"] is False
        assert "sif_market_get_keyword_demand" in payload["tool_sources"][0]["tools"]
        return native_chat_response(
            [
                native_tool_call(
                    "call-respond",
                    "respond_to_user",
                    {
                        "message": (
                            "当前已经注册了 Sif MCP 工具入口，但未检测到 SIF_MCP_TOKEN / SIF_API_KEY。"
                            "配置密钥后可以尝试调用 sif_market_get_keyword_demand。"
                        )
                    },
                )
            ]
        )

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)

    result = server_module.run_agent(
        {
            "prompt": "你现在能调用 sif 工具吗",
            "agentMode": "market",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert result["response_type"] == "message"
    assert "Sif MCP 工具入口" in result["message"]["content"]
    assert "sif_market_get_keyword_demand" in result["message"]["content"]
    assert [event["title"] for event in result["events"]] == ["接收用户输入", "检查 Agent 能力", "回复用户"]
    assert result["tools"] == []


def test_run_agent_empty_general_response_falls_back_to_capability_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        server_module,
        "get_sif_tool_catalog",
        lambda: {
            "sif_market_get_keyword_history": {
                "label": "Sif: market_get_keyword_history",
                "description": "Get Sif keyword history evidence.",
                "input_schema": {"type": "object", "properties": {"keywords": {"type": "array"}}},
                "source": "sif_mcp",
                "mcp_tool": "market_get_keyword_history",
                "auth_env_names": ["SIF_MCP_TOKEN", "SIF_API_KEY", "SIF_TOKEN"],
            }
        },
    )

    def fake_call_chat(messages, tools=None, tool_choice=None):
        return native_chat_response(tool_calls=None, content="")

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)

    result = server_module.run_agent(
        {
            "prompt": "你有哪些工具，能调用 Sif MCP 吗？",
            "agentMode": "market",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert result["response_type"] == "message"
    assert "当前工具目录共有" in result["message"]["content"]
    assert "Sif MCP" in result["message"]["content"]
    assert "artifact" not in result
    assert [event["type"] for event in result["events"]] == ["input", "message"]


def test_run_agent_capability_answer_uses_inventory_observation(monkeypatch) -> None:
    monkeypatch.setattr(
        server_module,
        "get_sif_tool_catalog",
        lambda: {
            "sif_market_get_keyword_demand": {
                "label": "Sif: market_get_keyword_demand",
                "description": "Get Sif keyword demand evidence.",
                "input_schema": {"type": "object", "properties": {"keywords": {"type": "array"}}},
                "source": "sif_mcp",
                "mcp_tool": "market_get_keyword_demand",
                "auth_env_names": ["SIF_MCP_TOKEN", "SIF_API_KEY", "SIF_TOKEN"],
            }
        },
    )
    chat_calls: list[list[dict]] = []

    def fake_call_chat(messages, tools=None, tool_choice=None):
        chat_calls.append(messages)
        if len(chat_calls) == 1:
            return native_chat_response(
                [native_tool_call("call-inspect", "inspect_agent_capabilities", {"focus": "数据工具"})]
            )
        capability_observation = next(
            message for message in messages if message.get("role") == "tool" and message.get("name") == "inspect_agent_capabilities"
        )
        payload = json.loads(capability_observation["content"])
        tool_rows = "\n".join(
            f"| `{tool['name']}` | {tool['source']} |"
            for tool in payload["tools"]
        )
        return native_chat_response(
            [
                native_tool_call(
                    "call-respond",
                    "respond_to_user",
                    {
                        "message": "| 工具 | 来源 |\n| --- | --- |\n" + tool_rows
                    },
                )
            ]
        )

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)

    result = server_module.run_agent(
        {
            "prompt": "列出你现在所有数据工具，包括 MCP",
            "agentMode": "market",
            "useLlm": True,
        }
    )

    assert result["response_type"] == "message"
    assert "`amazon_shelf`" in result["message"]["content"]
    assert "`sif_market_get_keyword_demand`" in result["message"]["content"]
    assert "sif_mcp" in result["message"]["content"]


def test_run_agent_forces_capability_inspection_when_model_answers_directly(monkeypatch) -> None:
    monkeypatch.setattr(
        server_module,
        "get_sif_tool_catalog",
        lambda: {
            "sif_market_get_keyword_demand": {
                "label": "Sif: market_get_keyword_demand",
                "description": "Get Sif keyword demand evidence.",
                "input_schema": {"type": "object", "properties": {"keywords": {"type": "array"}}},
                "source": "sif_mcp",
                "mcp_tool": "market_get_keyword_demand",
                "auth_env_names": ["SIF_MCP_TOKEN", "SIF_API_KEY", "SIF_TOKEN"],
            }
        },
    )
    chat_calls: list[list[dict]] = []

    def fake_call_chat(messages, tools=None, tool_choice=None):
        chat_calls.append(messages)
        if len(chat_calls) == 1:
            return native_chat_response(
                [
                    native_tool_call(
                        "call-respond",
                        "respond_to_user",
                        {"message": "你好，我可以帮你做市场洞察、爆款痛点分析和证据驱动的研发机会分析。"},
                    )
                ]
            )
        capability_observation = next(
            message for message in messages if message.get("role") == "tool" and message.get("name") == "inspect_agent_capabilities"
        )
        payload = json.loads(capability_observation["content"])
        assert "sif_market_get_keyword_demand" in [tool["name"] for tool in payload["tools"]]
        return native_chat_response(
            [
                native_tool_call(
                    "call-respond-final",
                    "respond_to_user",
                    {"message": "我当前可以调用 amazon_shelf，也可以看到 sif_market_get_keyword_demand。"},
                )
            ]
        )

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)

    result = server_module.run_agent(
        {
            "prompt": "我是说你可以调用的工具有哪些？",
            "agentMode": "market",
            "useLlm": True,
        }
    )

    assert result["response_type"] == "message"
    assert "sif_market_get_keyword_demand" in result["message"]["content"]
    assert [event["type"] for event in result["events"]] == ["input", "message", "message"]
    assert result["events"][0]["message"] == "正在判断是直接回复、补齐参数，还是调用工具执行任务。"


def test_run_agent_treats_workflow_as_plain_prompt(monkeypatch) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    captured_messages: list[list[dict]] = []
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {
                        "skill_id": "weekly_market_insight",
                        "extracted_params": {
                            "brand": "Hsia",
                            "marketplace": "Amazon US",
                            "category": "minimizer bra",
                            "time_range": "90d",
                        },
                    },
                )
            ]
        ),
        *weekly_market_baseline_tool_responses(),
        *weekly_market_report_tool_responses(),
        native_chat_response([native_tool_call("call-synth", "synthesize_artifact", {})]),
    ]

    def fake_call_chat(messages, tools=None, tool_choice=None):
        captured_messages.append(messages)
        return chat_responses.pop(0)

    def fake_call_openai_compatible(messages):
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

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)
    monkeypatch.setattr(server_module, "call_openai_compatible", fake_call_openai_compatible)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_agent_tool_result)

    prompt = (
        "任务：帮我分析美国 minimizer bra 市场，品牌 Hsia。\n\n"
        "工作流要求：先调用 Sif 和 SellerSprite 市场工具，再生成标准 HTML 报告。"
    )
    result = server_module.run_agent(
        {
            "prompt": prompt,
            "agentMode": "market",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert result["skill"]["skill_id"] == "weekly_market_insight"
    first_user_message = next(message["content"] for message in captured_messages[0] if message["role"] == "user")
    assert "workflow_skill" not in first_user_message
    assert "工作流要求：先调用 Sif" in first_user_message
    assert "SellerSprite 市场工具" in first_user_message
    assert result["artifact"]["title"] == "Fake LLM-authored market report"
    assert result["llm_analysis"]["renderer"] == "llm-html"
    assert [event["type"] for event in result["events"][:2]] == ["input", "skill"]
    assert result["events"][1]["status"] == "ok"


def test_run_agent_returns_needs_input_when_skill_required_params_are_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {"skill_id": "weekly_market_insight", "extracted_params": {"category": "minimizer bra"}},
                )
            ]
        ),
        native_chat_response(
            [
                native_tool_call(
                    "call-ask",
                    "ask_user",
                    {
                        "reason": "需要品牌、市场和时间范围后才能执行工具。",
                        "missing_params": ["brand", "marketplace", "time_range"],
                        "questions": [
                            {"field": "brand", "question": "请确认研究品牌。"},
                            {"field": "marketplace", "question": "请确认市场。"},
                            {"field": "time_range", "question": "请确认时间范围。"},
                        ],
                    },
                )
            ]
        ),
    ]

    def fake_call_chat(messages, tools=None, tool_choice=None):
        return chat_responses.pop(0)

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)

    result = server_module.run_agent(
        {
            "runId": "abcdef123456",
            "prompt": "分析 minimizer bra 市场",
            "agentMode": "market",
            "useLlm": True,
        }
    )

    assert result["run_id"] == "abcdef123456"
    assert result["status"] == "needs_input"
    assert result["tools"] == []
    assert result["skill"]["status"] == "needs_input"
    assert result["skill"]["missing_params"] == ["brand", "marketplace", "time_range"]
    assert result["pending"]["skill_id"] == "weekly_market_insight"
    assert result["pending"]["continue_run_id"] == result["run_id"]
    assert [event["type"] for event in result["events"]] == ["input", "skill"]
    assert result["events"][1]["status"] == "needs_input"
    assert "artifact" not in result
    assert "需要品牌、市场和时间范围" in result["message"]["content"]
    assert [item["type"] for item in result["output_files"]] == ["skill"]
    assert all(event["run_id"] == "abcdef123456" for event in result["events"])
    progress_path = tmp_path / "agent-runs" / "abcdef123456" / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["run_id"] == "abcdef123456"
    assert progress["status"] == "running"
    restored = server_module.load_agent_run_state("abcdef123456")
    assert restored is not None
    assert restored["status"] == "needs_input"
    assert restored["result"]["run_id"] == "abcdef123456"


def test_load_agent_run_state_recovers_progress_without_final_result(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    server_module.write_agent_run_json(
        "123456abcdef",
        "progress.json",
        {
            "run_id": "123456abcdef",
            "status": "running",
            "updated_at": "2026-07-10T00:00:00+00:00",
            "events": [{"id": "evt-001", "run_id": "123456abcdef", "status": "ok"}],
        },
    )

    restored = server_module.load_agent_run_state("123456abcdef")

    assert restored is not None
    assert restored["status"] == "running"
    assert "result" not in restored
    assert restored["events"][0]["run_id"] == "123456abcdef"


def test_run_agent_normalizes_skill_param_aliases_before_missing_input_check(monkeypatch) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {
                        "skill_id": "weekly_market_insight",
                        "extracted_params": {
                            "brand": "Hsia",
                            "market": "Amazon US",
                            "category": "minimizer bra",
                            "time_range": "90d",
                        },
                    },
                )
            ]
        ),
        *weekly_market_baseline_tool_responses(),
        *weekly_market_report_tool_responses(),
        native_chat_response([native_tool_call("call-synth", "synthesize_artifact", {})]),
    ]

    def fake_call_chat(messages, tools=None, tool_choice=None):
        return chat_responses.pop(0)

    def fake_call_openai_compatible(messages):
        return {
            "provider": "test",
            "model": "synth",
            "usage": {"total_tokens": 20},
            "result": {
                "title": "Alias normalized artifact",
                "executive_summary": "The market alias was normalized into marketplace.",
                "key_findings": ["market alias did not trigger needs_input."],
                "opportunities": [],
                "risks": [],
                "next_steps": [],
            },
        }

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)
    monkeypatch.setattr(server_module, "call_openai_compatible", fake_call_openai_compatible)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_agent_tool_result)

    result = server_module.run_agent(
        {
            "prompt": "帮我分析美国 Amazon US 市场 minimizer bra 最近90天在变什么，品牌 Hsia。",
            "agentMode": "market",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert result["skill"]["missing_params"] == []
    assert result["skill"]["params"]["marketplace"] == "Amazon US"
    assert result["artifact"]["title"] == "Fake LLM-authored market report"
    assert result["llm_analysis"]["renderer"] == "llm-html"


def test_run_agent_uses_prompt_params_when_load_skill_omits_extracted_params(monkeypatch) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {"skill_id": "weekly_market_insight", "extracted_params": {}},
                )
            ]
        ),
        *weekly_market_baseline_tool_responses(),
        *weekly_market_report_tool_responses(),
        native_chat_response([native_tool_call("call-synth", "synthesize_artifact", {})]),
    ]

    def fake_call_chat(messages, tools=None, tool_choice=None):
        return chat_responses.pop(0)

    def fake_call_openai_compatible(messages):
        return {
            "provider": "test",
            "model": "synth",
            "usage": {"total_tokens": 20},
            "result": {
                "title": "Prompt params artifact",
                "executive_summary": "The prompt provided all required params.",
                "key_findings": ["No clarification was needed."],
                "opportunities": [],
                "risks": [],
                "next_steps": [],
            },
        }

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)
    monkeypatch.setattr(server_module, "call_openai_compatible", fake_call_openai_compatible)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_agent_tool_result)

    result = server_module.run_agent(
        {
            "prompt": "帮我分析美国 Amazon US 市场 minimizer bra 最近90天在变什么，品牌 Hsia，输出 Hsia 下一步研发机会。",
            "agentMode": "market",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert result["skill"]["missing_params"] == []
    assert result["skill"]["params"]["brand"] == "Hsia"
    assert result["skill"]["params"]["marketplace"] == "Amazon US"
    assert result["skill"]["params"]["time_range"] == "90d"
    assert result["artifact"]["title"] == "Fake LLM-authored market report"
    assert result["llm_analysis"]["renderer"] == "llm-html"


def test_run_agent_can_continue_pending_skill_after_user_supplies_params(monkeypatch, tmp_path) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load-pending",
                    "load_skill",
                    {"skill_id": "weekly_market_insight", "extracted_params": {"category": "minimizer bra"}},
                )
            ]
        ),
        native_chat_response(
            [
                native_tool_call(
                    "call-ask",
                    "ask_user",
                    {
                        "reason": "需要品牌、市场和时间范围后才能执行工具。",
                        "missing_params": ["brand", "marketplace", "time_range"],
                        "questions": [
                            {"field": "brand", "question": "请确认研究品牌。"},
                            {"field": "marketplace", "question": "请确认市场。"},
                            {"field": "time_range", "question": "请确认时间范围。"},
                        ],
                    },
                )
            ]
        ),
        native_chat_response(
            [
                native_tool_call(
                    "call-load-continued",
                    "load_skill",
                    {
                        "skill_id": "weekly_market_insight",
                        "extracted_params": {
                            "brand": "Hsia",
                            "marketplace": "US",
                            "category": "minimizer bra",
                            "time_range": "90d",
                        },
                    },
                )
            ]
        ),
        *weekly_market_baseline_tool_responses(),
        *weekly_market_report_tool_responses(),
        native_chat_response([native_tool_call("call-synth", "synthesize_artifact", {})]),
    ]

    def fake_call_chat(messages, tools=None, tool_choice=None):
        return chat_responses.pop(0)

    def fake_call_openai_compatible(messages):
        return {
            "provider": "test",
            "model": "synth",
            "usage": {"total_tokens": 20},
            "result": {
                "title": "Continued market artifact",
                "executive_summary": "The continued run used supplied parameters.",
                "key_findings": ["The pending skill continued."],
                "opportunities": [],
                "risks": [],
                "next_steps": [],
            },
        }

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)
    monkeypatch.setattr(server_module, "call_openai_compatible", fake_call_openai_compatible)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_agent_tool_result)

    pending = server_module.run_agent(
        {
            "prompt": "分析 minimizer bra 市场",
            "agentMode": "market",
            "useLlm": True,
        }
    )
    continued = server_module.run_agent(
        {
            "prompt": "品牌 Hsia，市场美国，时间最近90天",
            "agentMode": "market",
            "continueRunId": pending["run_id"],
            "useLlm": True,
        }
    )

    assert pending["status"] == "needs_input"
    assert continued["status"] == "ok"
    assert continued["skill"]["missing_params"] == []
    assert continued["skill"]["params"]["brand"] == "Hsia"
    assert continued["skill"]["params"]["marketplace"] == "US"
    assert continued["skill"]["params"]["time_range"] == "90d"
    assert [tool["name"] for tool in continued["tools"]] == [*WEEKLY_MARKET_BASELINE_TOOLS, *WEEKLY_MARKET_REPORT_TOOLS]
    assert continued["events"][2]["input"]["timeRange"] == "90d"
    assert continued["artifact"]["title"] == "Fake LLM-authored market report"
    assert continued["llm_analysis"]["renderer"] == "llm-html"


def test_run_agent_ignores_confirmation_ask_user_when_required_params_are_resolved(monkeypatch) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    chat_calls: list[list[dict]] = []
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {
                        "skill_id": "weekly_market_insight",
                        "extracted_params": {
                            "brand": "Bali",
                            "marketplace": "US",
                            "category": "minimizer bra",
                            "time_range": "90d",
                        },
                    },
                )
            ]
        ),
        native_chat_response(
            [
                native_tool_call(
                    "call-confirm",
                    "ask_user",
                    {
                        "reason": "需要确认 Bali 和 Amazon US 是否映射正确。",
                        "missing_params": [],
                        "questions": [
                            {"field": "brand", "question": "研究对象品牌是 Bali 吗？"},
                            {"field": "marketplace", "question": "目标电商市场是 Amazon US 吗？"},
                        ],
                    },
                )
            ]
        ),
        *weekly_market_baseline_tool_responses(),
        *weekly_market_report_tool_responses(),
        native_chat_response([native_tool_call("call-synth", "synthesize_artifact", {})]),
    ]

    def fake_call_chat(messages, tools=None, tool_choice=None):
        chat_calls.append(messages)
        return chat_responses.pop(0)

    def fake_call_openai_compatible(messages):
        return {
            "provider": "test",
            "model": "synth",
            "usage": {"total_tokens": 20},
            "result": {
                "title": "Resolved params artifact",
                "executive_summary": "The run continued after resolved params.",
                "key_findings": ["Confirmation ask_user was ignored."],
                "opportunities": [],
                "risks": [],
                "next_steps": [],
            },
        }

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)
    monkeypatch.setattr(server_module, "call_openai_compatible", fake_call_openai_compatible)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_agent_tool_result)

    result = server_module.run_agent(
        {
            "prompt": "分析 minimizer bra 市场。品牌 Bali，目标电商市场 Amazon US，最近90天",
            "agentMode": "market",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert result["skill"]["missing_params"] == []
    assert [tool["name"] for tool in result["tools"]] == [*WEEKLY_MARKET_BASELINE_TOOLS, *WEEKLY_MARKET_REPORT_TOOLS]
    assert result["artifact"]["title"] == "Fake LLM-authored market report"
    assert result["llm_analysis"]["renderer"] == "llm-html"
    ask_user_observation = [
        json.loads(message["content"])
        for message in chat_calls[2]
        if message.get("role") == "tool" and message.get("name") == "ask_user"
    ][0]
    assert ask_user_observation["status"] == "ignored"


def test_run_agent_does_not_use_hardcoded_tool_routing_when_planner_unavailable(monkeypatch) -> None:
    def unavailable_llm(_messages, tools=None, tool_choice=None):
        raise server_module.LLMUnavailable("No LLM configured")

    def fail_tool(*_args, **_kwargs):
        raise AssertionError("Tool execution should only happen after LLM tool planning.")

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", unavailable_llm)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fail_tool)

    result = server_module.run_agent(
        {
            "prompt": "帮我分析美国 minimizer bra 前 10 名爆款痛点，并输出研发机会",
            "agentMode": "competitor",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert result["planner"]["status"] == "unavailable"
    assert result["tools"] == []
    assert result["response_type"] == "message"
    assert result["llm_analysis"]["status"] == "unavailable"
    assert "artifact" not in result
    assert "无法继续执行" in result["message"]["content"]
    assert [event["status"] for event in result["events"]] == ["ok", "error", "skipped", "ok"]


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


def test_mcp_settings_redact_sellersprite_and_sif_credentials() -> None:
    settings = build_mcp_settings_response(
        {
            "SELLERSPRITE_MCP_SECRET_KEY": "seller-secret",
            "SIF_API_KEY": "sif-secret",
        }
    )
    sources = {source["id"]: source for source in settings["sources"]}

    assert sources["sellersprite"]["configured"] is True
    assert sources["sif"]["configured"] is True
    assert sources["sellersprite"]["env_name"] == "SELLERSPRITE_MCP_SECRET_KEY"
    assert sources["sif"]["env_name"] == "SIF_MCP_TOKEN"
    assert "seller-secret" not in json.dumps(settings)
    assert "sif-secret" not in json.dumps(settings)


def test_update_mcp_settings_writes_env_and_syncs_process(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    env_path.write_text("", encoding="utf-8")
    example_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(settings_module, "ENV_PATH", env_path)
    monkeypatch.setattr(settings_module, "ENV_EXAMPLE_PATH", example_path)
    for key in (
        "SELLERSPRITE_MCP_SECRET_KEY",
        "SELLERSPRITE_SECRET_KEY",
        "SELLERSPRITE_API_KEY",
        "SIF_MCP_TOKEN",
        "SIF_API_KEY",
        "SIF_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)

    result = update_mcp_settings(
        {
            "credentials": {
                "sellersprite": {"value": "seller-test"},
                "sif": {"value": "sif-test"},
            }
        }
    )

    assert all(source["configured"] for source in result["sources"])
    assert os.environ["SELLERSPRITE_MCP_SECRET_KEY"] == "seller-test"
    assert os.environ["SIF_MCP_TOKEN"] == "sif-test"
    env_text = env_path.read_text(encoding="utf-8")
    assert "SELLERSPRITE_MCP_SECRET_KEY=seller-test" in env_text
    assert "SIF_MCP_TOKEN=sif-test" in env_text

    cleared = update_mcp_settings(
        {
            "credentials": {
                "sellersprite": {"clear": True},
                "sif": {"clear": True},
            }
        }
    )

    assert not any(source["configured"] for source in cleared["sources"])
    assert "SELLERSPRITE_MCP_SECRET_KEY" not in os.environ
    assert "SIF_MCP_TOKEN" not in os.environ


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

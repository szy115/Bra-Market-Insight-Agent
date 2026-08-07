import json
import os
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from insight_agent import server as server_module
from insight_agent import settings as settings_module
from insight_agent.agent_skill_harness import validate_evidence_contract
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
    report_data = server_module.build_hot_product_pain_report_data(
        {
            "category": "minimizer bra",
            "marketplace": "Amazon US",
            "toolResults": tool_results,
        }
    )

    def fake_call_openai_compatible(messages):
        payload = json.loads(messages[-1]["content"])
        serialized = json.dumps(payload["hot_product_pain_report_data"], ensure_ascii=False)
        assert "market_report_data" not in payload
        assert "tool_results" not in payload
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
        lambda messages, **_kwargs: html_chat_response_from_result(
            fake_call_openai_compatible(messages)
        ),
    )

    rendered = server_module.execute_agent_tool_with_timeout(
        "render_html_report",
        "minimizer bra",
        {
                "prompt": "使用 hot_product_pain_analysis Skill 做爆款痛点分析。参数：head_listing_count=1。",
                "hotProductPainReportData": report_data,
                "toolResults": [],
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
    ]
    assert "Listing SEO" in skill["markdown"]
    assert "不应照搬" in skill["markdown"]


def test_product_design_research_skill_registers_markdown_contract() -> None:
    skill = server_module.AGENT_SKILL_REGISTRY["product_design_research"]
    policy = {row["tool"]: row["policy"] for row in skill["tool_policy"]}
    evidence = {row["evidence_id"]: row for row in skill["evidence_contract"]}

    assert skill["input_schema"]["required"] == ["category", "design_goal"]
    assert skill["input_schema"]["defaults"]["listing_sample_size"] == 100
    assert skill["input_schema"]["defaults"]["review_sample_size"] == 60
    assert policy["build_product_design_brief_data"] == "required"
    assert policy["render_markdown_report"] == "required"
    assert policy["render_html_report"] == "disallowed"
    assert evidence["review_minimum"]["min_success"] == 5
    assert evidence["review_minimum"]["severity"] == "block"
    assert evidence["review_target"]["min_success"] == "param:head_listing_count"
    assert evidence["review_target"]["severity"] == "warn"


def test_product_design_brief_data_tracks_collection_ai_volume_and_review_layers() -> None:
    def ok(name: str, data: dict[str, Any], tool_input: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "name": name,
            "label": name,
            "status": "ok",
            "summary": f"{name} completed",
            "input": tool_input or {"category": "strapless bra"},
            "data": data,
        }

    tool_results = [
        ok("sif_market_get_keyword_root_trend", {"roots": [{"keyword": "strapless"}]}),
        ok("sif_market_get_keyword_demand", {"keywords": [{"keyword": "strapless bra", "search_volume": 1000}]}, {"keyword": "strapless bra"}),
        ok("sif_market_get_keyword_demand", {"keywords": [{"keyword": "bra that stays up", "search_volume": 500}]}, {"keyword": "bra that stays up"}),
        ok("sif_market_get_keyword_history", {"keywords": [{"keyword": "strapless bra", "search_volume": 1000}]}),
        ok("sif_market_get_keyword_competition", {"items": [{"asin": "B000000001"}]}, {"keyword": "strapless bra"}),
        ok("sif_market_get_keyword_competition", {"items": [{"asin": "B000000002"}]}, {"keyword": "bra that stays up"}),
        ok("sellersprite_aba_research_weekly", {"data": {"items": [{"keyword": "strapless bra"}]}}),
        ok("sellersprite_product_node", {"resolved_params": {"category_node_id": "1:2"}}),
        ok("sellersprite_market_research", {"data": {"items": [{"asin": "B000000001"}]}}),
        ok(
            "sellersprite_market_product_concentration",
            {
                "product_selection": {
                    "candidate_count": 3,
                    "eligible_count": 3,
                    "selected": [
                        {"asin": "B000000001", "family_asin": "B000PARENT", "title": "Alpha Strapless Bra", "price": 29.99},
                        {"asin": "B000000002", "family_asin": "B000PARENT", "title": "Alpha Strapless Bra Black", "price": 29.99},
                        {"asin": "B000000003", "title": "Beta Strapless Bra", "price": 39.99},
                    ],
                }
            },
        ),
        ok(
            "sellersprite_review",
            {
                "data": {
                    "items": [
                        {"star": 1, "title": "Slips", "content": "It slides down."},
                        {"star": 3, "title": "Mixed", "content": "Supportive but too tight."},
                        {"star": 5, "title": "Works", "content": "It stays up all day."},
                    ]
                },
                "review_sampling": {"selected_review_asin": "B000000001", "scope": "exact_asin"},
            },
            {"asin": "B000000001"},
        ),
        ok(
            "tiktok_social",
            {
                "videos": [
                    {
                        "title": "Strapless support test",
                        "url": "https://www.tiktok.com/@creator/video/1",
                        "views": 1000,
                        "comment_samples": [{"text": "Does it stay up?"}],
                    }
                ]
            },
        ),
        ok(
            "media_rankings",
            {
                "articles": [
                    {
                        "title": "Wacoal Best Sellers",
                        "domain": "wacoal-america.com",
                        "url": "https://wacoal-america.com/collections/best-sellers",
                        "source_type": "brand_site",
                        "authority_level": "Medium",
                        "evidence_snippets": ["Public product positioning and feature claims."],
                    }
                ]
            },
        ),
    ]

    brief = server_module.build_product_design_brief_data(
        {
            "category": "strapless bra",
            "designGoal": "开发稳定不下滑的大胸日常抹胸文胸",
            "toolResults": tool_results,
        }
    )

    assert brief["schema_version"] == "product_design_brief_data.v1"
    assert [product["asin"] for product in brief["products"]] == ["B000000001", "B000000003"]
    assert {review["group"] for review in brief["reviews"]} == {
        "failure_1_2_star",
        "tradeoff_3_star",
        "purchase_driver_4_5_star",
    }
    assert brief["data_volume"]["planned"]["reviews"] == 600
    assert brief["data_volume"]["actual"]["reviews"] == 3
    assert brief["data_volume"]["included_in_llm"]["reviews"] == 3
    assert brief["data_volume"]["actual"]["unique_products"] == 2
    assert any(item["id"].startswith("R") for item in brief["evidence_map"])
    assert any("FastMoss" in gap for gap in brief["data_gaps"])


def test_markdown_report_renderer_requires_sections_and_known_evidence(monkeypatch) -> None:
    evidence_ids = ["K01", "K02", "M01", "P01", "P02", "R01", "R02", "T01", "W01"]
    brief = {
        "schema_version": "product_design_brief_data.v1",
        "title": "Hsia Strapless Bra 产品研发调研任务书",
        "research_scope": {"category": "strapless bra", "design_goal": "stay up"},
        "data_volume": {
            "planned": {"reviews": 600},
            "actual": {"reviews": 300},
            "included_in_llm": {"reviews": 120},
        },
        "keyword_evidence": [],
        "market_evidence": [],
        "products": [],
        "reviews": [],
        "tiktok_evidence": [],
        "web_evidence": [],
        "reddit_evidence": [],
        "evidence_map": [
            {"id": evidence_id, "source": "test", "kind": "test", "title": evidence_id}
            for evidence_id in evidence_ids
        ],
        "data_gaps": ["TikTok Shop reviews unavailable."],
        "report_contract": {"required_sections": server_module.PRODUCT_DESIGN_REPORT_SECTIONS},
        "artifact": {"title": "Hsia Strapless Bra 产品研发调研任务书"},
    }
    markdown = product_design_test_markdown()
    captured_payloads: list[dict[str, Any]] = []

    def fake_chat(messages):
        captured_payloads.append(json.loads(messages[-1]["content"]))
        return native_chat_response(content=markdown)

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)
    rendered = server_module.execute_agent_tool_with_timeout(
        "render_markdown_report",
        "strapless bra",
        {
            "productDesignBriefData": brief,
            "useLlm": True,
            "skillId": "product_design_research",
            "skillMarkdown": "# 产品研发调研",
            "agentToolRetryDelayMs": 0,
        },
    )

    assert rendered["status"] == "ok"
    assert rendered["data"]["format"] == "markdown"
    assert rendered["data"]["renderer"] == "llm-markdown"
    assert rendered["data"]["markdown"] == markdown.strip()
    assert captured_payloads[0]["output_contract"]["required_sections"][0] == "## 1. 研发课题与研究范围"
    assert "tool_results" not in captured_payloads[0]


def test_media_rankings_prioritizes_user_urls_before_discovery(monkeypatch) -> None:
    captured_urls: list[str] = []
    provided = "https://wacoal-america.com/collections/best-sellers"
    discovered = "https://example.com/strapless-bra-guide"

    monkeypatch.setattr(
        server_module,
        "discover_article_urls",
        lambda _payload: {
            "candidates": [{"url": provided}, {"url": discovered}],
            "warnings": [],
        },
    )

    def fake_analyze_articles(payload):
        captured_urls.extend(payload["urls"])
        return {
            "summary": {},
            "data_volume": {"collected_articles": len(payload["urls"])},
            "articles": [
                {
                    "title": url,
                    "url": url,
                    "domain": "example.com",
                    "source_type": "brand_site",
                    "authority_level": "Medium",
                }
                for url in payload["urls"]
            ],
            "warnings": [],
        }

    monkeypatch.setattr(server_module, "analyze_articles", fake_analyze_articles)
    result = server_module.execute_agent_tool(
        "media_rankings",
        "strapless bra",
        {
            "params": {"brand_site_urls": [provided]},
            "articleCandidateLimit": 8,
        },
    )

    assert result["status"] == "ok"
    assert captured_urls == [provided, discovered]
    assert result["data"]["data_volume"]["collected_articles"] == 2


def test_product_design_agent_publishes_persistent_markdown_report(monkeypatch, tmp_path) -> None:
    sif_tools = [
        "sif_market_get_keyword_root_trend",
        "sif_market_get_keyword_demand",
        "sif_market_get_keyword_history",
        "sif_market_get_keyword_competition",
    ]
    monkeypatch.setattr(
        server_module,
        "get_sif_tool_catalog",
        lambda: {name: {"label": name, "description": name, "source": "sif_mcp"} for name in sif_tools},
    )
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        server_module,
        "agent_tool_input_payload",
        lambda _name, category, payload: {"category": category, **payload},
    )

    asins = [f"B00000000{index}" for index in range(1, 6)]
    data_tool_calls = [
        ("sif_market_get_keyword_root_trend", {}),
        ("sif_market_get_keyword_demand", {"keyword": "strapless bra"}),
        ("sif_market_get_keyword_demand", {"keyword": "bra that stays up"}),
        ("sif_market_get_keyword_history", {"keyword": "strapless bra"}),
        ("sif_market_get_keyword_competition", {"keyword": "strapless bra"}),
        ("sif_market_get_keyword_competition", {"keyword": "bra that stays up"}),
        ("sellersprite_aba_research_weekly", {}),
        ("sellersprite_product_node", {}),
        ("sellersprite_market_research", {}),
        ("sellersprite_market_product_concentration", {}),
        *[("sellersprite_review", {"asin": asin}) for asin in asins],
        ("tiktok_social", {}),
        ("media_rankings", {}),
    ]
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {
                        "skill_id": "product_design_research",
                        "extracted_params": {
                            "category": "strapless bra",
                            "design_goal": "开发稳定不下滑的大胸日常抹胸文胸",
                        },
                    },
                )
            ]
        ),
        *[
            native_chat_response([native_tool_call(f"call-{index}", name, args)])
            for index, (name, args) in enumerate(data_tool_calls, start=1)
        ],
        native_chat_response(content=""),
    ]

    def fake_chat(_messages, tools=None, tool_choice=None):
        return chat_responses.pop(0)

    def fake_execute(tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if tool_name == "sellersprite_product_node":
            data = {"resolved_params": {"category_node_id": "1:2"}}
        elif tool_name == "sellersprite_market_product_concentration":
            data = {
                "resolved_params": {
                    "selected_product_asins": asins,
                    "candidate_product_asins": asins,
                }
            }
        elif tool_name == "sellersprite_review":
            data = {"data": {"items": [{"star": 3, "content": "Supportive with a fit tradeoff."}]}}
        elif tool_name == "build_product_design_brief_data":
            data = {
                "schema_version": "product_design_brief_data.v1",
                "title": "Hsia Strapless Bra 产品研发调研任务书",
                "evidence_map": [{"id": f"K{index:02d}"} for index in range(1, 9)],
                "artifact": {"title": "Hsia Strapless Bra 产品研发调研任务书"},
            }
        elif tool_name == "render_markdown_report":
            data = {
                "format": "markdown",
                "title": "Hsia Strapless Bra 产品研发调研任务书",
                "markdown": product_design_test_markdown(),
                "artifact": {
                    "title": "Hsia Strapless Bra 产品研发调研任务书",
                    "executive_summary": "优先验证防下滑支撑系统。",
                    "key_findings": [],
                    "risks": [],
                    "next_steps": [],
                },
                "renderer": "llm-markdown",
                "markdown_analysis": {
                    "status": "ok",
                    "provider": "test",
                    "model": "markdown-model",
                },
            }
        return {
            "name": tool_name,
            "label": tool_name,
            "status": "ok",
            "summary": f"{tool_name} completed",
            "duration_ms": 1,
            "input": {"category": category, **payload},
            "data": data,
        }

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_execute)

    result = server_module.run_agent(
        {
            "prompt": "调研美国 strapless bra，研发目标是开发稳定不下滑的大胸日常抹胸文胸。",
            "category": "strapless bra",
            "agentMode": "market",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert result["skill"]["skill_id"] == "product_design_research"
    assert result["llm_analysis"]["renderer"] == "llm-markdown"
    assert result["llm_analysis"]["markdown_generation_status"] == "ok"
    assert result["output_files"][0]["label"] == "Markdown report"
    assert result["output_files"][0]["name"] == "report.md"
    restored = server_module.read_agent_output_file(result["output_files"][0]["path"])
    assert restored["format"] == "markdown"
    assert "## 13. 验证动作、证据链和数据缺口" in restored["content"]


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
    assert policy["build_hot_product_pain_report_data"] == "required"
    assert evidence["sellersprite_review_samples"]["min_success"] == "param:head_listing_count"
    assert evidence["sellersprite_review_samples"]["severity"] == "block"
    assert evidence["sif_sales_proxy"]["severity"] == "block"
    assert evidence["hot_product_pain_report_data"]["severity"] == "block"


def test_competitor_product_deep_dive_skill_registers_single_asin_and_reddit_contract() -> None:
    skill = server_module.AGENT_SKILL_REGISTRY["competitor_product_deep_dive"]
    policy = {row["tool"]: row["policy"] for row in skill["tool_policy"]}
    evidence = {row["evidence_id"]: row for row in skill["evidence_contract"]}

    assert skill["input_schema"]["required"] == ["marketplace", "asin"]
    assert skill["input_schema"]["defaults"]["review_sample_size"] == 500
    assert skill["input_schema"]["defaults"]["report_image_limit"] == 60
    assert policy["sellersprite_asin_detail"] == "required"
    assert policy["sellersprite_review"] == "required"
    assert policy["reddit_voc"] == "required"
    assert policy["build_competitor_product_report_data"] == "required"
    assert policy["sellersprite_market_research"] == "disallowed"
    assert evidence["product_identity"]["severity"] == "block"
    assert evidence["review_base"]["min_success"] == 1
    assert evidence["review_base"]["severity"] == "block"
    assert evidence["reddit_user_voc"]["severity"] == "warn"
    assert evidence["competitor_product_report_data"]["severity"] == "block"
    assert "collected_unique_count" in skill["markdown"]
    assert "只调用一次 `sellersprite_review`" in skill["markdown"]
    assert "不得只取前 12 条" in skill["markdown"]
    assert "评论区买家返图" in skill["markdown"]
    for expected in ("这个款为什么卖", "核心用户是谁", "Hsia 能学什么", "不应该照搬什么"):
        assert expected in skill["markdown"]


def test_competitor_combined_review_result_satisfies_review_evidence_gate() -> None:
    skill = server_module.AGENT_SKILL_REGISTRY["competitor_product_deep_dive"]
    review_contract = [
        row
        for row in skill["evidence_contract"]
        if row["tool"] == "sellersprite_review"
    ]
    gate = validate_evidence_contract(
        {"evidence_contract": review_contract},
        prompt="深拆 B0012M839K",
        params={"asin": "B0012M839K"},
        tools=[
            {
                "name": "sellersprite_review",
                "status": "partial_ok",
                "input": {"asin": "B0012M839K"},
                "data": {
                    "review_sampling": {
                        "mode": "exhaustive_balanced_pagination",
                        "buckets": {
                            "low_star": {"collected_unique_count": 356, "complete": True},
                            "high_star": {"collected_unique_count": 242, "complete": False},
                        },
                    }
                },
            }
        ],
        success_statuses={"ok", "partial_ok"},
    )

    assert gate["status"] == "pass"
    assert gate["block_gaps"] == []


def test_html_report_review_context_keeps_every_collected_review() -> None:
    compacted = server_module.html_report_compact_tool_results(
        [
            {
                "name": "sellersprite_review",
                "status": "ok",
                "data": {
                    "data": {
                        "page": 1,
                        "total": 30,
                        "items": [
                            {
                                "id": f"R{index:03d}",
                                "star": 5,
                                "title": f"Review {index}",
                                "content": f"Complete review body {index}",
                            }
                            for index in range(30)
                        ],
                    },
                    "review_sampling": {
                        "source_total": 30,
                        "collected_unique_count": 30,
                        "complete": True,
                    },
                },
            }
        ]
    )

    review_data = compacted[0]["data"]["data"]
    assert review_data["report_input_review_count"] == 30
    assert len(review_data["items"]) == 30
    assert review_data["items"][-1]["content"] == "Complete review body 29"


def test_html_report_fastmoss_context_keeps_late_cross_market_evidence() -> None:
    tool_results = [
        {
            "name": f"mcp__fastmoss__tool_{index:02d}",
            "status": "ok",
            "input": {"filter": {"region": "US" if index < 25 else "MX"}},
            "data": {"value": index},
        }
        for index in range(1, 35)
    ]

    compacted = server_module.html_report_compact_tool_results(tool_results)

    assert len(compacted) == 34
    assert compacted[-1]["name"] == "mcp__fastmoss__tool_34"
    assert "MX" in compacted[-1]["input"]["filter"]


def test_legacy_html_workflows_now_build_versioned_bounded_report_data() -> None:
    tool_results = [
        {
            "name": "sellersprite_asin_detail",
            "label": "ASIN detail",
            "status": "ok",
            "input": {"asin": "B000TEST1"},
            "data": {"asin": "B000TEST1", "title": "Test minimizer bra"},
        },
        {
            "name": "sellersprite_review",
            "label": "Reviews",
            "status": "ok",
            "input": {"asin": "B000TEST1"},
            "data": {
                "data": {
                    "items": [
                        {
                            "star": 2,
                            "title": "Strap slips",
                            "content": "The strap slips after washing.",
                            "images": ["https://example.com/review.jpg"],
                        }
                    ]
                }
            },
        },
    ]

    competitor = server_module.build_competitor_product_report_data(
        {
            "asin": "B000TEST1",
            "marketplace": "Amazon US",
            "toolResults": tool_results,
            "reportImageLimit": 10,
        }
    )
    hot_product = server_module.build_hot_product_pain_report_data(
        {
            "category": "minimizer bra",
            "marketplace": "Amazon US",
            "toolResults": tool_results,
        }
    )

    assert competitor["schema_version"] == "competitor_product_report_data.v1"
    assert hot_product["schema_version"] == "hot_product_pain_report_data.v1"
    assert competitor["output_contract"]["raw_tool_results_forbidden"] is True
    assert hot_product["output_contract"]["raw_tool_results_forbidden"] is True
    assert competitor["bounds"]["max_source_results"] == 48
    assert competitor["review_image_evidence"][0]["image_url"] == "https://example.com/review.jpg"
    assert all("file_path" not in source for source in competitor["evidence_sources"])


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
        lambda messages, **_kwargs: html_chat_response_from_result(
            fake_call_openai_compatible(messages)
        ),
    )

    html_content, _, analysis = server_module.compose_html_report_with_llm(
        {
            "prompt": "从产品研发角度深拆 Amazon US ASIN B000TEST1。",
            "category": "minimizer bra",
            "competitorProductReportData": server_module.build_competitor_product_report_data(
                {
                    "asin": "B000TEST1",
                    "toolResults": [
                        {
                            "name": "sellersprite_asin_detail",
                            "status": "ok",
                            "data": {"asin": "B000TEST1"},
                        }
                    ],
                }
            ),
            "skillId": "competitor_product_deep_dive",
            "skillMarkdown": skill["markdown"],
            "skillHtmlTemplate": skill["html_template"],
        }
    )

    assert analysis["status"] == "ok"
    assert captured["required_template_sections"] == required_sections
    assert "data-required-section=\"executive\"" in captured["skill_html_template"]
    assert all(f'data-required-section="{section_id}"' in html_content for section_id in required_sections)


def test_competitor_review_gallery_renders_every_selected_buyer_image(monkeypatch) -> None:
    skill = server_module.AGENT_SKILL_REGISTRY["competitor_product_deep_dive"]
    required_sections = server_module.html_template_required_sections(skill["html_template"])
    captured: dict[str, Any] = {}
    image_urls = [
        "https://m.media-amazon.com/images/I/review-a-1._SY200.jpg",
        "https://m.media-amazon.com/images/I/review-a-2._SY200.jpg",
        "https://m.media-amazon.com/images/I/review-b-1._SY200.jpg",
    ]

    def fake_call(messages, **_kwargs):
        captured.update(json.loads(messages[-1]["content"]))
        sections = "".join(
            f'<section data-required-section="{section_id}"><h2>{section_id}</h2></section>'
            for section_id in required_sections
        )
        return native_chat_response(
            content=(
                "<!doctype html><html lang=\"zh-CN\"><head><style>"
                "body{font-family:sans-serif;color:#222}section{padding:16px}"
                "</style></head><body>"
                f"{sections}<p>{'产品证据与研发验证。' * 80}</p></body></html>"
            )
        )

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call)
    html_content, _, analysis = server_module.compose_html_report_with_llm(
        {
            "prompt": "深拆目标 ASIN 并展示买家返图。",
            "skillId": "competitor_product_deep_dive",
            "skillMarkdown": skill["markdown"],
            "skillHtmlTemplate": skill["html_template"],
            "reportImageLimit": 3,
            "competitorProductReportData": server_module.build_competitor_product_report_data(
                {
                    "reportImageLimit": 3,
                    "toolResults": [
                        {
                            "name": "sellersprite_review",
                            "status": "ok",
                            "input": {"asin": "B000TEST1"},
                            "data": {
                                "data": {
                                    "items": [
                                        {
                                            "star": 1,
                                            "title": "Poor stitching",
                                            "content": "The seam opened after one wear.",
                                            "skus": ["Size: 36DD", "Color: Black"],
                                            "images": f"{image_urls[0]},{image_urls[1]}",
                                        },
                                        {
                                            "star": 4,
                                            "title": "Useful fit photo",
                                            "content": "The cup shape is visible in the photo.",
                                            "skus": ["Size: 38D"],
                                            "images": [image_urls[2]],
                                        },
                                    ]
                                }
                            },
                        }
                    ],
                }
            ),
        }
    )

    assert analysis["status"] == "ok"
    assert analysis["server_rendered_review_image_count"] == 3
    assert analysis["available_review_image_count"] == 3
    assert captured["review_image_coverage"]["selected_image_count"] == 3
    assert captured["required_review_image_urls"] == [image_urls[0], image_urls[2], image_urls[1]]
    assert 'data-review-gallery="seller-review-images"' in html_content
    assert "INSIGHT_AGENT_REVIEW_GALLERY" not in html_content
    assert html_content.count("评论区买家返图") == 1
    assert "已展示 3 / 3 张去重返图" in html_content
    assert "Size: 36DD" in html_content
    assert all(url in html_content for url in image_urls)


def test_competitor_review_gallery_retries_model_generated_duplicate(monkeypatch) -> None:
    skill = server_module.AGENT_SKILL_REGISTRY["competitor_product_deep_dive"]
    required_sections = server_module.html_template_required_sections(skill["html_template"])
    image_url = "https://m.media-amazon.com/images/I/review-duplicate._SY200.jpg"
    call_count = 0

    def fake_call(_messages, **_kwargs):
        nonlocal call_count
        call_count += 1
        sections = []
        for section_id in required_sections:
            extra = ""
            if section_id == "fit-voc":
                extra = "<!-- INSIGHT_AGENT_REVIEW_GALLERY -->"
                if call_count == 1:
                    extra += f'<div><h3>评论区买家返图</h3><img src="{image_url}"></div>'
            sections.append(
                f'<section data-required-section="{section_id}"><h2>{section_id}</h2>{extra}</section>'
            )
        return native_chat_response(
            content=(
                "<!doctype html><html lang=\"zh-CN\"><head><style>"
                "body{font-family:sans-serif;color:#222}section{padding:16px}"
                "</style></head><body>"
                f"{''.join(sections)}<p>{'产品证据与研发验证。' * 80}</p></body></html>"
            )
        )

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call)
    html_content, _, analysis = server_module.compose_html_report_with_llm(
        {
            "prompt": "深拆目标 ASIN 并展示买家返图。",
            "skillId": "competitor_product_deep_dive",
            "skillMarkdown": skill["markdown"],
            "skillHtmlTemplate": skill["html_template"],
            "reportImageLimit": 1,
            "competitorProductReportData": server_module.build_competitor_product_report_data(
                {
                    "reportImageLimit": 1,
                    "toolResults": [
                        {
                            "name": "sellersprite_review",
                            "status": "ok",
                            "input": {"asin": "B000TEST1"},
                            "data": {
                                "data": {
                                    "items": [
                                        {
                                            "star": 5,
                                            "title": "Useful fit photo",
                                            "content": "The fit is visible.",
                                            "images": [image_url],
                                        }
                                    ]
                                }
                            },
                        }
                    ],
                }
            ),
        }
    )

    assert analysis["status"] == "ok"
    assert call_count == 2
    assert html_content.count("评论区买家返图") == 1
    assert html_content.count(image_url) == 1


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
        "Final HTML must render in the sandboxed preview without JavaScript; "
        "analytical charts must use server-injected static inline SVG."
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
        "Required business chart price_band_distribution still contains an empty SVG after server chart injection."
    )


def test_html_validator_rejects_duplicate_chart_with_populated_and_empty_copies() -> None:
    html_content = (
        "<!doctype html><html><head><style>body{color:#222}</style></head><body>"
        '<figure data-chart-id="market_capacity">'
        '<svg viewBox="0 0 100 100"><rect width="80" height="40"></rect></svg>'
        "</figure>"
        '<figure data-chart-id="market_capacity"><svg viewBox="0 0 100 100"></svg></figure>'
        f"<p>{'完整市场报告。' * 80}</p></body></html>"
    )

    assert server_module.validate_llm_html_document(
        html_content,
        required_chart_ids=["market_capacity"],
    ) == "Required business chart market_capacity must appear exactly once; found 2 figures."


def test_html_validator_rejects_two_populated_copies_of_same_chart() -> None:
    html_content = (
        "<!doctype html><html><head><style>body{color:#222}</style></head><body>"
        '<figure data-chart-id="market_capacity">'
        '<svg viewBox="0 0 100 100"><rect width="80" height="40"></rect></svg>'
        "</figure>"
        '<figure data-chart-id="market_capacity">'
        '<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="20"></circle></svg>'
        "</figure>"
        f"<p>{'完整市场报告。' * 80}</p></body></html>"
    )

    assert server_module.validate_llm_html_document(
        html_content,
        required_chart_ids=["market_capacity"],
    ) == "Required business chart market_capacity must appear exactly once; found 2 figures."


def test_html_validator_rejects_multiple_svgs_inside_required_chart() -> None:
    html_content = (
        "<!doctype html><html><head><style>body{color:#222}</style></head><body>"
        '<figure data-chart-id="market_capacity">'
        '<svg viewBox="0 0 100 100"><rect width="80" height="40"></rect></svg>'
        '<svg viewBox="0 0 100 100"></svg>'
        "</figure>"
        f"<p>{'完整市场报告。' * 80}</p></body></html>"
    )

    assert server_module.validate_llm_html_document(
        html_content,
        required_chart_ids=["market_capacity"],
    ) == "Required business chart market_capacity must contain exactly one inline SVG; found 2."


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


def test_core_chart_overview_is_forced_to_single_column_without_changing_atlas() -> None:
    html_content = """<!doctype html>
<html lang="zh-CN"><head><style>
.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.chart-card svg{max-width:100%;height:auto}
</style></head><body><main>
<section class="content-section"><h2>数据完整性与未完成任务</h2><p>完整性说明。</p></section>
<section class="content-section"><h2>核心图表速览</h2><div class="chart-grid">
<figure class="chart-card" data-chart-id="market_capacity"><svg viewBox="0 0 100 100"><rect x="5" y="5" width="90" height="40"></rect></svg></figure>
<figure class="chart-card" data-chart-id="category_demand_trend"><svg viewBox="0 0 100 100"><polyline points="0,90 50,20 100,60"></polyline><text x="98" y="70">末值</text></svg></figure>
</div></section>
<section class="content-section"><h2>市场任务图谱</h2><div class="chart-grid">
<figure class="chart-card" data-chart-id="keyword_boundary"><svg viewBox="0 0 100 100"><rect x="5" y="5" width="80" height="30"></rect><text x="98" y="70">末值</text></svg></figure>
</div></section>
</main></body></html>"""

    updated = server_module.enforce_summary_chart_single_column(html_content)

    assert "insight-agent-summary-chart-single-column" in updated
    assert '<section class="content-section summary-charts-single-column"><h2>核心图表速览</h2>' in updated
    assert '<div class="chart-grid summary-chart-layout">' in updated
    assert '<section class="content-section"><h2>数据完整性与未完成任务</h2>' in updated
    assert '<section class="content-section"><h2>市场任务图谱</h2>' in updated
    assert "grid-template-columns: minmax(0, 1fr) !important" in updated
    assert '<text x="96" y="70" text-anchor="end">末值</text>' in updated
    assert updated.count('text-anchor="end"') == 1
    assert '<text x="98" y="70">末值</text>' in updated
    assert server_module.enforce_summary_chart_single_column(updated) == updated


def product_design_test_markdown() -> str:
    detail = (
        "本段严格区分工具观察、分析判断与设计师下一步验证，不把公开代理信号解释为真实销量或完整市场。"
        "所有产品机制都需要通过样衣、版型、面料和尺码测试继续确认。"
    )
    sections = [
        "研究对象为美国站 strapless bra，目标是提升大胸用户的稳定性、支撑和日常舒适度。",
        "优先验证防下滑支撑系统，同时控制压迫与勒痕风险。[P01] [R01]",
        "原始品类词需要与防下滑、无肩带场景和大胸支撑需求词共同界定市场。[K01] [K02]",
        "公开网页只提供方向性趋势证据；未接入付费趋势报告时不做确定性流行预测。[W01]",
        "头部商品显示价格、结构和评论门槛存在差异，不能用单一 ASIN 代表市场。[P01] [P02]",
        "低星评论用于识别失败机制，3 星用于识别权衡，高星用于识别已验证购买理由。[R01] [R02]",
        "达人内容可用于识别演示语言和穿着场景，播放量不能替代销量。[T01]",
        "品牌站用于核验产品定位、结构卖点和公开信息，动态评价仍是缺口。[W01]",
        "- 防滑不足 → 穿着中下移 → 验证侧翼、底围与杯体协同支撑。[R01] [P01]",
        "- 必须解决：稳定性与压迫的平衡。[R01]\n- 值得探索：可拆肩带与侧翼支撑组合。[P02]\n- 不建议照搬：仅增加硅胶面积而不验证皮肤舒适度。[R02]",
        "- 结构：优先做底围、侧翼和杯体协同验证。[P01] [R01]\n- 面料与颜色：只依据现有产品和公开网页做候选，不宣称趋势结论。[P02] [W01]\n- 尺码与价格：以工具样本为边界，进入打样前复核。[K02] [P02]",
        "- 概念 A：日常稳定型，强调防下滑与低压迫。[R01] [P01]\n- 概念 B：大胸支撑型，强化侧翼和杯体包容。[R02] [P02]",
        "计划采集、实际采集、进入 LLM 三个口径必须分开展示。证据链包括关键词 [K01]、商品 [P01]、评论 [R01]、视频 [T01] 和网页 [W01]。数据缺口包括 TikTok Shop 买家评价、付费趋势报告、品牌站动态评论和 Pinterest 视觉研究。",
    ]
    body = ["# Hsia Strapless Bra 产品研发调研任务书"]
    for index, (title, content) in enumerate(
        zip(server_module.PRODUCT_DESIGN_REPORT_SECTIONS, sections, strict=True),
        start=1,
    ):
        body.extend([f"## {index}. {title}", "", content, "", detail, ""])
    return "\n".join(body)


def install_weekly_market_test_catalog(monkeypatch) -> None:
    monkeypatch.setattr(
        server_module,
        "synthesize_report_insights_node",
        lambda payload: {
            "schema_version": "report_insight_narrative.v1",
            "skill_id": str(payload.get("skillId") or ""),
            "status": "completed",
            "section_count": 1,
            "insight_count": 1,
            "sections": [
                {
                    "section_id": "market_signal",
                    "title": "市场信号",
                    "insights": [
                        {
                            "conclusion": "需求锚点形成可验证方向",
                            "observation": "当前结构化样本给出需求锚点。",
                            "interpretation": "该信号适合进入产品验证。",
                            "business_implication": "优先做小样而非直接放量。",
                            "action": "启动小样验证。",
                            "evidence_ids": ["E01"],
                            "chart_ids": ["keyword-demand"],
                            "confidence": "medium",
                        }
                    ],
                }
            ],
            "internal_audit": {"unsupported_dimensions_visible": False},
        },
    )
    monkeypatch.setattr(
        server_module,
        "review_html_report_node",
        lambda payload: {
            "round": int(payload.get("reviewRound") or 1),
            "status": "ok",
            "decision": "approve",
            "approved": True,
            "summary": "事实审批通过。",
            "issues": [],
            "duration_ms": 1,
        },
    )
    monkeypatch.setattr(
        server_module,
        "red_team_html_report_node",
        lambda payload: {
            "schema_version": "report_red_team_review.v1",
            "round": int(payload.get("reviewRound") or 1),
            "status": "ok",
            "decision": "approve",
            "approved": True,
            "summary": "红队审查通过。",
            "reviewed_claim_count": 1,
            "findings": [],
            "issues": [],
            "duration_ms": 1,
        },
    )
    monkeypatch.setattr(
        server_module,
        "render_report_charts_via_flint",
        lambda payload: {
            "schema_version": "chart_render_bundle.v1",
            "renderer": "flint-mcp",
            "native_tool": "render_chart",
            "status": "partial_ok",
            "summary": {
                "chart_spec_count": len(
                    (payload.get("reportData") or {}).get("chart_specs") or []
                ),
                "requested_count": 0,
                "rendered_count": 0,
                "failed_count": 0,
                "skipped_count": len(
                    (payload.get("reportData") or {}).get("chart_specs") or []
                ),
            },
            "charts": [],
            "skipped_charts": [],
        },
    )
    monkeypatch.setattr(
        server_module,
        "review_html_report_node",
        lambda payload: {
            "round": int(payload.get("reviewRound") or 1),
            "status": "ok",
            "decision": "approve",
            "approved": True,
            "summary": "测试审批通过。",
            "issues": [],
            "duration_ms": 1,
        },
    )
    monkeypatch.setattr(
        server_module,
        "revise_html_report_node",
        lambda payload: {
            "html": str(payload.get("html") or ""),
            "revision": {
                "round": int(payload.get("revisionRound") or 1),
                "status": "ok",
                "applied": True,
                "message": "",
                "duration_ms": 1,
            },
        },
    )
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


WEEKLY_MARKET_BASELINE_TOOLS = [
    "sif_market_get_keyword_demand",
    "sif_market_get_keyword_history",
    "sif_market_get_keyword_root_trend",
    "sif_market_get_keyword_competition",
    "sellersprite_market_research",
    "sellersprite_aba_research_weekly",
    "sellersprite_keyword_research",
    "sellersprite_keyword_research_trends",
    "sellersprite_google_trend",
]


def weekly_market_baseline_tool_responses() -> list[dict[str, Any]]:
    return [
        native_chat_response([native_tool_call(f"call-{tool_name}", tool_name, {})])
        for tool_name in WEEKLY_MARKET_BASELINE_TOOLS
    ]


WEEKLY_MARKET_REPORT_TOOLS = [
    "build_market_report_data",
    "analyze_market_report",
    "synthesize_report_insights",
    "render_report_charts",
    "render_html_report",
]

HTML_REPORT_APPROVAL_TOOLS = [
    "review_html_report",
    "red_team_html_report",
    "join_report_approval",
]


def weekly_market_report_tool_responses() -> list[dict[str, Any]]:
    return [native_chat_response(content="")]


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
    elif tool_name == "build_tiktok_new_product_report_data":
        data = {
            "schema_version": "tiktok_new_product_report_data.v1",
            "title": "TikTok Shop 美国女士文胸新品洞察",
            "category": category,
            "summary": {
                "candidate_count": 20,
                "head_product_count": 5,
                "detail_success_count": 5,
                "trend_success_count": 5,
            },
            "candidate_products": [],
            "head_products": [],
            "data_gaps": [],
            "artifact": {"title": "TikTok Shop 美国女士文胸新品洞察"},
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
            "market_report_data": (
                payload.get("marketReportData")
                if isinstance(payload.get("marketReportData"), dict)
                else {}
            ),
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
        {
            "name": "sellersprite_review",
            "label": "SellerSprite reviews",
            "status": "ok",
            "summary": "SellerSprite returned a balanced review sample.",
            "data": {
                "data": {
                    "items": [
                        {
                            "asin": "B00000001",
                            "star": 2,
                            "content": "The straps dig in and the band rolls up.",
                            "date": "2026-06-01",
                        }
                    ]
                }
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
    assert len(compiled["data"]["chart_manifest"]) == 19
    assert len(compiled["data"]["dimension_results"]) == 19
    assert len(compiled["data"]["summary_chart_ids"]) <= 5
    assert all(chart["quality_status"] == "ready" for chart in compiled["data"]["chart_specs"])
    assert all(chart["type"] != "line" for chart in compiled["data"]["chart_specs"])
    assert compiled["data"]["opportunity_pool"]
    assert compiled["data"]["evidence_map"][0]["tool"] == "sif_market_get_keyword_history"
    assert compiled["data"]["analysis_coverage"]["summary"]["p0_total"] == 17
    assert compiled["data"]["tool_methodology"]
    assert all(item["role"] == "methodology_only" for item in compiled["data"]["tool_methodology"])
    assert compiled["data"]["deduplication"]["applied"] is False
    assert compiled["data"]["deduplication"]["implementation"] == "passthrough_v0"
    assert compiled["data"]["deduplication"]["datasets"]
    assert compiled["data"]["review_pain_points"][0]["review_group"] == "low_star"
    assert compiled["data"]["review_pain_points"][0]["asin"] == "B00000001"

    assert "evidence_sources" not in {chart["id"] for chart in compiled["data"]["chart_specs"]}
    assert "data_readiness" not in {chart["id"] for chart in compiled["data"]["chart_specs"]}

    def fake_call_openai_compatible(messages):
        payload = json.loads(messages[-1]["content"])
        assert payload["market_report_data"]["chart_specs"]
        assert payload["market_report_data"]["market_kpis"]
        assert "analysis_coverage" not in payload["market_report_data"]
        assert "chart_manifest" not in payload["market_report_data"]
        assert "dimension_results" not in payload["market_report_data"]
        assert payload["market_report_data"]["deduplication"]["applied"] is False
        assert payload["market_report_data"]["tool_methodology"]
        assert payload["market_report_data"]["review_pain_points"][0]["review_group"] == "low_star"
        assert "tool_results" not in payload
        assert payload["output_contract"]["javascript_forbidden"] is True
        assert payload["output_contract"]["chart_placeholders_required"] is True
        assert payload["output_contract"]["server_managed_svg_injection"] is True
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
        lambda messages, **_kwargs: html_chat_response_from_result(
            fake_call_openai_compatible(messages)
        ),
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


def test_market_report_data_hides_recovered_failures_and_keeps_listing_date_evidence() -> None:
    report = server_module.build_market_report_data(
        {
            "category": "sports bra",
            "brand": "Hsia",
            "marketplace": "Amazon US",
            "toolResults": [
                {
                    "name": "sellersprite_aba_research_weekly",
                    "label": "SellerSprite ABA weekly",
                    "status": "fatal_error",
                    "summary": "日期参数错误，只能查询上一周的数据",
                    "data": {"code": "ERROR_PARAM"},
                },
                {
                    "name": "sellersprite_market_listing_date_distribution",
                    "label": "SellerSprite listing date distribution",
                    "status": "ok",
                    "summary": "SellerSprite returned listing-date evidence.",
                    "data": {"data": {"items": [{"label": "1年内", "unitsRatio": 0.2}]}},
                },
                {
                    "name": "sellersprite_aba_research_weekly",
                    "label": "SellerSprite ABA weekly",
                    "status": "ok",
                    "summary": "SellerSprite returned ABA evidence.",
                    "data": {"data": {"items": [{"keyword": "sports bra", "searches": 12000}]}},
                },
                {
                    "name": "sif_market_get_keyword_history",
                    "label": "Sif keyword history",
                    "status": "ok",
                    "summary": "Sif returned keyword history.",
                    "data": {"keywords": [{"keyword": "sports bra", "search_volume": 26000}]},
                },
                {
                    "name": "sellersprite_market_research",
                    "label": "SellerSprite market research",
                    "status": "ok",
                    "summary": "SellerSprite returned market evidence.",
                    "data": {"data": {"items": [{"departmentName": "Sports Bras"}]}},
                },
            ],
        }
    )

    assert all(item["status"] == "ok" for item in report["evidence_map"])
    assert not any(item["id"] == "E01" for item in report["evidence_map"])
    assert any(
        item["tool"] == "sellersprite_market_listing_date_distribution"
        for item in report["evidence_map"]
    )
    assert not any("ABA weekly" in gap for gap in report["data_gaps"])
    llm_context = server_module.market_report_llm_context(report)
    assert any(
        item["tool"] == "sellersprite_market_listing_date_distribution"
        for item in llm_context["evidence_map"]
    )


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
    assert len(charts["chart_manifest"]) == 19
    assert len(charts["summary_chart_ids"]) <= 5

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
    assert {
        "market_capacity",
        "keyword_boundary",
        "category_demand_trend",
        "node_demand_quality",
        "price_band_distribution",
        "brand_competition",
        "top_product_signal",
    } <= set(charts)
    assert "market_boundary_map" not in charts
    assert "product_universe_coverage" not in charts
    non_chart = {
        item["dimension_id"]: item
        for item in report_data["non_chart_presentations"]
    }
    assert non_chart["M01"]["presentation_type"] == "scope_summary"
    assert "keyword_demand" not in charts
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


def test_market_report_llm_context_keeps_all_task_charts() -> None:
    report_data = {
        "chart_specs": [
            {
                "id": f"task_chart_{index}",
                "dimension_id": f"M{index:02d}",
                "title": f"Task {index}",
                "type": "bar",
                "quality_status": "ready",
                "data": [{"label": "sample", "value": index}],
            }
            for index in range(1, 20)
        ]
    }

    context = server_module.market_report_llm_context(report_data)

    assert len(context["chart_specs"]) == 19


def test_empty_llm_svg_is_recovered_before_a_second_llm_attempt(monkeypatch) -> None:
    chart = {
        "id": "market_capacity",
        "title": "市场容量与成熟度",
        "type": "metric_group",
        "quality_status": "ready",
        "source": "SellerSprite MCP · E06",
        "data": [
            {
                "label": "月销量",
                "value": 146474,
                "value_format": "compact_integer",
                "unit": "units",
                "evidence_id": "E06",
            }
        ],
    }
    report_data = {
        "schema_version": "market_report_data.v1",
        "title": "Hsia 市场报告",
        "category": "minimizer bra",
        "chart_specs": [chart],
        "summary_chart_ids": ["market_capacity"],
        "data_gaps": [],
        "artifact": {"title": "Hsia 市场报告", "executive_summary": "测试摘要"},
    }
    llm_calls: list[list[dict[str, Any]]] = []
    empty_chart_html = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Hsia 市场报告</title>
<style>body{font-family:sans-serif;color:#111827}.chart-card{border:1px solid #e5e7eb}</style></head>
<body><main><h1>Hsia 市场报告</h1><p>正文和证据链已经生成，只有业务图表的 SVG 为空。</p>
<figure class="chart-card" data-chart-id="market_capacity"><svg viewBox="0 0 100 100"></svg></figure>
<p>该错误应由 chart_specs 自动恢复，不应再次请求模型重写整份报告。</p></main></body></html>"""

    def fake_call(messages, **_kwargs):
        llm_calls.append(messages)
        return native_chat_response(content=empty_chart_html)

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call)

    html_content, artifact, analysis = server_module.compose_html_report_with_llm(
        {
            "marketReportData": report_data,
            "useLlm": True,
            "prompt": "生成市场报告",
        }
    )

    assert len(llm_calls) == 1
    assert analysis["status"] == "ok"
    assert analysis["attempt_count"] == 1
    assert analysis["recovered_chart_ids"] == ["market_capacity"]
    render_prompt = llm_calls[0][0]["content"]
    assert "empty inline svg placeholder" in render_prompt
    assert "placement.section_hint" in render_prompt
    assert "Never duplicate the same data-chart-id" in render_prompt
    assert "chart_layout_contract.required_chart_bindings" in render_prompt
    assert "insight-chart-layout" in render_prompt
    assert "multi-chart analysis section is allowed" in render_prompt
    assert "one column at every viewport" in render_prompt
    assert ".compiled-chart-svg svg{display:block;width:100%;height:auto}" in render_prompt
    assert "Do not add a visible list of omitted" in render_prompt
    assert "populated inline SVG only" not in render_prompt
    assert "write all visible paths, bars, lines, points, labels, and axes" not in render_prompt
    render_payload = json.loads(llm_calls[0][-1]["content"])
    assert render_payload["output_contract"]["chart_placeholders_required"] is True
    assert render_payload["output_contract"]["server_managed_svg_injection"] is True
    assert render_payload["output_contract"]["insight_chart_interleaving_required"] is True
    assert render_payload["chart_layout_contract"]["chart_only_atlas_forbidden"] is True
    assert render_payload["chart_layout_contract"]["chart_insight_contract"] == {
        "one_per_ready_chart": True,
        "required_fields": ["observation", "interpretation"],
        "optional_fields": ["conclusion", "business_implication", "action"],
        "count_limits": None,
    }
    assert (
        render_payload["chart_layout_contract"]["side_by_side_chart_explanation_forbidden"]
        is True
    )
    assert 'data-chart-renderer="server-recovery"' in html_content
    assert "146.5K" in html_content
    assert artifact["title"] == "Hsia 市场报告"


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
        chart_figures = "".join(
            f'<figure data-chart-id="{chart_id}"><svg viewBox="0 0 100 100"><rect x="10" y="10" width="80" height="50"></rect></svg></figure>'
            for chart_id in payload["required_chart_ids"]
        )
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
    <section class="content-section">{chart_figures}</section>
</main>
<aside><strong>目录</strong><a href="#llm-authored">LLM 自定义洞察章节</a></aside>
</div>
</body>
    </html>""".replace("{chart_figures}", chart_figures),
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
        lambda messages, **_kwargs: html_chat_response_from_result(
            fake_call_openai_compatible(messages)
        ),
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


def test_hot_product_required_images_ignore_superseded_candidate_pool() -> None:
    tool_results = [
        {
            "name": "sellersprite_market_product_concentration",
            "status": "partial_ok",
            "data": {
                "product_selection": {
                    "selected": [
                        {
                            "asin": "BROAD00001",
                            "imageUrl": "https://images.example.com/broad.jpg",
                        }
                    ]
                }
            },
        },
        {
            "name": "sellersprite_market_product_concentration",
            "status": "ok",
            "data": {
                "product_selection": {
                    "selected": [
                        {
                            "asin": "FINAL00001",
                            "imageUrl": "https://images.example.com/final-1.jpg",
                        },
                        {
                            "asin": "FINAL00002",
                            "imageUrl": "https://images.example.com/final-2.jpg",
                        },
                    ]
                }
            },
        },
        {
            "name": "sellersprite_review",
            "status": "ok",
            "input": {"asin": "FINAL00001"},
            "data": {"data": {"items": []}},
        },
        {
            "name": "sellersprite_review",
            "status": "ok",
            "input": {"asin": "FINAL00002"},
            "data": {"data": {"items": []}},
        },
    ]

    product_urls, review_urls = server_module.hot_product_required_image_urls(tool_results)

    assert product_urls == [
        "https://images.example.com/final-1.jpg",
        "https://images.example.com/final-2.jpg",
    ]
    assert review_urls == []


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
        lambda messages, **_kwargs: html_chat_response_from_result(
            fake_call_openai_compatible(messages)
        ),
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


def test_weekly_market_renderer_hides_internal_gaps_when_one_chart_is_missing(monkeypatch) -> None:
    report_data = {
        "schema_version": "market_report_data.v1",
        "title": "Hsia Amazon US市场 minimizer bra 洞察报告",
        "brand": "Hsia",
        "marketplace": "Amazon US",
        "category": "minimizer bra",
        "time_range": "90d",
        "analysis_coverage": {
            "summary": {"p0_total": 1, "p0_covered": 1},
            "dimensions": [
                {
                    "dimension_id": "M04",
                    "name": "搜索需求规模 VoS",
                    "market_question": "搜索量、购买量和购买率处于什么水平？",
                    "priority": "P0",
                    "status": "covered",
                    "evidence_ids": ["E01"],
                }
            ],
        },
        "chart_specs": [],
        "chart_manifest": [
            {
                "dimension_id": "M04",
                "name": "搜索需求规模 VoS",
                "priority": "P0",
                "analysis_status": "covered",
                "chart_id": "keyword_demand",
                "chart_status": "missing_data",
                "reason": "No semantically valid numeric chart data was compiled.",
                "evidence_ids": ["E01"],
            }
        ],
        "evidence_map": [{"id": "E01", "tool": "sellersprite_keyword_research", "status": "ok"}],
        "data_gaps": [],
    }
    captured_payloads: list[dict[str, Any]] = []
    html = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
body{font-family:sans-serif;color:#172033}.section{border-bottom:1px solid #e5e7eb;padding:16px}
</style><title>市场洞察报告</title></head><body><main>
<h1>市场洞察报告</h1>
<section class="section"><h2>可用市场信号</h2>
<p>本轮结构化证据显示目标关键词仍能形成明确的需求入口，后续产品企划应围绕同一市场、周期和样本口径展开比较。</p>
<p>报告只保留当前证据能够支持的观察、解释和业务动作，不使用估算值、评论数或模型猜测代替结构化指标。</p></section>
<section class="section"><h2>产品动作</h2><p>优先把已有需求锚点转成小样验证任务，并以同口径结果决定是否扩大资源投入。</p></section>
</main></body></html>"""

    def fake_chat(messages, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        captured_payloads.append(payload)
        return html_chat_response_from_result(
            {
                "provider": "test",
                "model": "html-model",
                "result": {"html": html},
            }
        )

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)

    rendered = server_module.execute_agent_tool_with_timeout(
        "render_html_report",
        "minimizer bra",
        {
            "marketReportData": report_data,
            "skillId": "weekly_market_insight",
            "useLlm": True,
            "agentToolRetryAttempts": 0,
            "agentToolRetryDelayMs": 0,
        },
    )

    assert rendered["status"] == "ok"
    assert rendered["data"]["report_quality"]["status"] == "degraded"
    assert rendered["data"]["report_quality"]["publishable"] is True
    assert rendered["data"]["market_report_data"]["report_quality"]["unavailable_dimensions"][0]["dimension_id"] == "M04"
    assert any("M04" in gap for gap in rendered["data"]["market_report_data"]["data_gaps"])
    assert "report_quality" not in captured_payloads[0]["market_report_data"]
    assert "data_gaps" not in captured_payloads[0]["market_report_data"]
    assert "chart_manifest" not in captured_payloads[0]["market_report_data"]
    assert "数据完整性与未完成任务" not in rendered["data"]["html"]
    assert "数据缺口" not in rendered["data"]["html"]
    assert (
        rendered["data"]["html_analysis"]["approval"]["status"]
        == "pending_langgraph_review"
    )


def test_breakout_competitor_discovery_skill_is_not_registered() -> None:
    assert "breakout_competitor_discovery" not in server_module.AGENT_SKILL_REGISTRY
    assert all(
        skill.get("skill_id") != "breakout_competitor_discovery"
        for skill in server_module.agent_skill_manifests()
    )
    assert "competitor_discovery" not in server_module.AGENT_TOOL_CATALOG


def test_run_agent_evidence_contract_blocks_early_report_handoff_and_then_allows_gap_disclosure(monkeypatch) -> None:
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
        native_chat_response(content=""),
        *weekly_market_baseline_tool_responses(),
        *weekly_market_report_tool_responses(),
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
    assert [tool["name"] for tool in result["tools"]] == [
        *WEEKLY_MARKET_BASELINE_TOOLS,
        *WEEKLY_MARKET_REPORT_TOOLS,
        *HTML_REPORT_APPROVAL_TOOLS,
    ]
    assert any(event["title"] == "Evidence Contract 阻止 reportData Builder" for event in result["events"])
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
    assert result["status"] == "error"
    assert "artifact" not in result
    assert not any(item.get("type") == "report" for item in result.get("output_files", []))
    assert any(event["type"] == "artifact" and event["status"] == "error" for event in result["events"])
    assert result["events"][-1]["type"] == "message"
    assert result["events"][-1]["status"] == "error"
    assert "不会再改用固定模板" in result["message"]["content"]


def test_weekly_market_agent_generates_degraded_html_when_node_evidence_is_missing(monkeypatch) -> None:
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
        native_chat_response(content=""),
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

    assert result["status"] == "ok"
    assert any(tool["name"] == "render_html_report" for tool in result["tools"])
    assert result["artifact"]["title"] == "Fake LLM-authored market report"
    assert any(item.get("type") == "report" for item in result.get("output_files", []))
    degraded_event = next(
        event for event in result["events"] if event["title"] == "Evidence Contract 降级生成 HTML 报告"
    )
    missing = degraded_event["output"]["recommended_tool_calls"]
    assert "sellersprite_market_product_demand_trend" in missing
    assert "sellersprite_market_price_distribution" in missing
    assert "sellersprite_market_ratings_count_distribution" in missing
    assert "sellersprite_market_listing_date_distribution" in missing
    assert {gap["tool"] for gap in result["evidence_gaps"]} >= set(missing)


def test_generic_report_approval_nodes_are_visible_and_publish_v3_after_two_rejections(
    monkeypatch, tmp_path
) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    review_rounds: list[int] = []
    red_team_rounds: list[int] = []
    revision_rounds: list[int] = []
    approval_barrier = threading.Barrier(2)
    approval_threads: dict[int, set[int]] = {}

    def reject_review(payload: dict[str, Any]) -> dict[str, Any]:
        review_round = int(payload.get("reviewRound") or 1)
        review_rounds.append(review_round)
        approval_threads.setdefault(review_round, set()).add(threading.get_ident())
        approval_barrier.wait(timeout=3)
        return {
            "round": review_round,
            "status": "ok",
            "decision": "revise",
            "approved": False,
            "summary": f"第 {review_round} 轮审批未通过。",
            "issues": [{"repair_instruction": f"执行第 {review_round} 轮修订。"}],
            "duration_ms": 1,
        }

    def approve_red_team(payload: dict[str, Any]) -> dict[str, Any]:
        review_round = int(payload.get("reviewRound") or 1)
        red_team_rounds.append(review_round)
        approval_threads.setdefault(review_round, set()).add(threading.get_ident())
        approval_barrier.wait(timeout=3)
        return {
            "schema_version": "report_red_team_review.v1",
            "round": review_round,
            "status": "ok",
            "decision": "approve",
            "approved": True,
            "summary": f"第 {review_round} 轮红队通过。",
            "findings": [],
            "issues": [],
            "duration_ms": 1,
        }

    def revise_report(payload: dict[str, Any]) -> dict[str, Any]:
        revision_round = int(payload.get("revisionRound") or 1)
        revision_rounds.append(revision_round)
        version = revision_round + 1
        return {
            "html": (
                "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
                f"<title>V{version}</title></head><body><main><h1>V{version}</h1>"
                "<p>审批意见已应用到这个市场洞察版本。</p></main></body></html>"
            ),
            "revision": {
                "round": revision_round,
                "status": "ok",
                "applied": True,
                "message": "",
                "duration_ms": 1,
            },
        }

    monkeypatch.setattr(server_module, "review_html_report_node", reject_review)
    monkeypatch.setattr(server_module, "red_team_html_report_node", approve_red_team)
    monkeypatch.setattr(server_module, "revise_html_report_node", revise_report)
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
    ]

    def fake_call_chat(messages, tools=None, tool_choice=None):  # noqa: ARG001
        return chat_responses.pop(0)

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call_chat)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_agent_tool_result)

    result = server_module.run_agent(
        {
            "runId": "def456def456",
            "prompt": "生成 Hsia 美国 minimizer bra 最近90天市场洞察报告。",
            "agentMode": "market",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    approval_chain = [
        tool["name"]
        for tool in result["tools"]
        if tool["name"]
        in {
            "render_html_report",
            "review_html_report",
            "revise_html_report",
        }
    ]
    assert approval_chain == [
        "render_html_report",
        "review_html_report",
        "revise_html_report",
        "review_html_report",
        "revise_html_report",
    ]
    report_tool_labels = [
        tool["label"]
        for tool in result["tools"]
        if tool["name"] in {"render_html_report", "review_html_report", "revise_html_report"}
    ]
    assert report_tool_labels == [
        "HTML 渲染 Agent",
        "报告事实审批 Agent",
        "HTML 渲染 Agent",
        "报告事实审批 Agent",
        "HTML 渲染 Agent",
    ]
    assert review_rounds == [1, 2]
    assert red_team_rounds == [1, 2]
    assert all(len(approval_threads[review_round]) == 2 for review_round in (1, 2))
    assert revision_rounds == [1, 2]
    node_events = [
        event
        for event in result["events"]
        if event.get("tool") in {"review_html_report", "revise_html_report"}
    ]
    assert [event["tool"] for event in node_events] == approval_chain[1:]
    assert all(event["data"]["langgraph_node"] is True for event in node_events)
    assert [event["data"]["graph_node"] for event in node_events] == [
        "report_review",
        "html_revision",
        "report_review",
        "html_revision",
    ]
    node_tools = [
        tool
        for tool in result["tools"]
        if tool["name"] in {"review_html_report", "revise_html_report"}
    ]
    assert all(tool["runtime"]["timeout_scope"] == "independent_node" for tool in node_tools)
    approval = result["llm_analysis"]["approval"]
    assert approval["orchestrator"] == "langgraph_nodes"
    assert approval["status"] == "published_after_round_2_rejection"
    assert approval["approved"] is False
    assert approval["published_without_approval"] is True
    assert approval["review_count"] == 2
    assert approval["red_team_count"] == 2
    assert approval["revision_count"] == 2
    assert approval["render_version_count"] == 3
    assert result["response_type"] == "artifact"
    assert len(chat_responses) == 0
    assert result["planner"]["synthesize_artifact"]["status"] == "published"
    publish_event = next(
        event
        for event in result["events"]
        if event["title"] == "调用工具：生成 Artifact"
        and event["status"] == "ok"
    )
    assert publish_event["data"]["graph_node"] == "synthesize_artifact"
    report_file = next(item for item in result["output_files"] if item["type"] == "report")
    assert report_file["name"] == "report.html"
    report_link_events = [
        event
        for event in result["events"]
        if event.get("file_path") == report_file["path"]
    ]
    assert [event.get("tool") for event in report_link_events] == ["synthesize_artifact"]
    join_events = [
        event for event in result["events"] if event.get("tool") == "join_report_approval"
    ]
    assert len(join_events) == 2
    assert all(event["data"]["graph_node"] == "approval_join" for event in join_events)
    assert len({event["seq"] for event in result["events"]}) == len(result["events"])
    assert not any(
        event["type"] == "artifact"
        and event["status"] == "ok"
        and event["title"] == "生成 Artifact"
        for event in result["events"]
    )
    assert "<h1>V3</h1>" in Path(report_file["path"]).read_text(encoding="utf-8")
    saved_run = json.loads(
        (tmp_path / "agent-runs" / result["run_id"] / "run.json").read_text(encoding="utf-8")
    )
    assert saved_run["response_type"] == "artifact"
    assert saved_run["output_files"][0]["name"] == "report.html"


def test_red_team_rejection_uses_same_two_round_revision_budget(monkeypatch, tmp_path) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    red_team_rounds: list[int] = []
    revision_rounds: list[int] = []

    def reject_red_team(payload: dict[str, Any]) -> dict[str, Any]:
        review_round = int(payload.get("reviewRound") or 1)
        red_team_rounds.append(review_round)
        return {
            "schema_version": "report_red_team_review.v1",
            "round": review_round,
            "status": "ok",
            "decision": "revise",
            "approved": False,
            "summary": f"第 {review_round} 轮红队要求收窄关键结论。",
            "findings": [
                {
                    "severity": "major",
                    "repair_instruction": "收窄关键结论。",
                }
            ],
            "issues": [
                {
                    "severity": "major",
                    "repair_instruction": "收窄关键结论。",
                }
            ],
            "duration_ms": 1,
        }

    def revise_report(payload: dict[str, Any]) -> dict[str, Any]:
        revision_round = int(payload.get("revisionRound") or 1)
        revision_rounds.append(revision_round)
        version = revision_round + 1
        return {
            "html": (
                "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
                f"<title>V{version}</title></head><body><main><h1>V{version}</h1>"
                "<p>关键结论已经按红队意见收窄。</p></main></body></html>"
            ),
            "revision": {
                "round": revision_round,
                "status": "ok",
                "applied": True,
                "duration_ms": 1,
            },
        }

    monkeypatch.setattr(server_module, "red_team_html_report_node", reject_red_team)
    monkeypatch.setattr(server_module, "revise_html_report_node", revise_report)
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
    ]

    monkeypatch.setattr(
        server_module,
        "call_openai_compatible_chat",
        lambda messages, tools=None, tool_choice=None: chat_responses.pop(0),
    )
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_agent_tool_result)

    result = server_module.run_agent(
        {
            "runId": "redteam123456",
            "prompt": "生成 Hsia 美国 minimizer bra 最近90天市场洞察报告。",
            "agentMode": "market",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    approval_chain = [
        tool["name"]
        for tool in result["tools"]
        if tool["name"]
        in {
            "render_html_report",
            "review_html_report",
            "red_team_html_report",
            "revise_html_report",
        }
    ]
    assert approval_chain == [
        "render_html_report",
        "review_html_report",
        "red_team_html_report",
        "revise_html_report",
        "review_html_report",
        "red_team_html_report",
        "revise_html_report",
    ]
    assert red_team_rounds == [1, 2]
    assert revision_rounds == [1, 2]
    approval = result["llm_analysis"]["approval"]
    assert approval["status"] == "published_after_round_2_rejection"
    assert approval["review_count"] == 2
    assert approval["red_team_count"] == 2
    assert approval["revision_count"] == 2
    assert approval["published_without_approval"] is True


def test_legacy_red_team_evidence_request_routes_to_revision_without_data_calls(
    monkeypatch, tmp_path
) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    builder_calls: list[dict[str, Any]] = []
    render_calls: list[dict[str, Any]] = []
    demand_tool_calls: list[dict[str, Any]] = []
    red_team_calls: list[dict[str, Any]] = []
    review_rounds: list[int] = []
    revision_rounds: list[int] = []

    def approve_review(payload: dict[str, Any]) -> dict[str, Any]:
        review_round = int(payload.get("reviewRound") or 1)
        review_rounds.append(review_round)
        return {
            "round": review_round,
            "status": "ok",
            "decision": "approve",
            "approved": True,
            "summary": f"第 {review_round} 轮事实审批通过。",
            "issues": [],
            "duration_ms": 1,
        }

    def legacy_request_red_team(payload: dict[str, Any]) -> dict[str, Any]:
        red_team_calls.append(payload)
        review_round = int(payload.get("reviewRound") or 1)
        return {
            "schema_version": "report_red_team_review.v1",
            "round": review_round,
            "status": "needs_evidence",
            "decision": "request_evidence",
            "approved": False,
            "summary": "旧式红队响应请求额外证据。",
            "findings": [],
            "issues": [],
            "evidence_requests": [
                {
                    "id": "legacy-red-evidence-1",
                    "name": "sif_market_get_keyword_demand",
                    "arguments": {"keyword": "minimizer bra validation"},
                }
            ],
        }

    def revise_report(payload: dict[str, Any]) -> dict[str, Any]:
        revision_round = int(payload.get("revisionRound") or 1)
        revision_rounds.append(revision_round)
        version = revision_round + 1
        return {
            "html": (
                "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
                f"<title>V{version}</title></head><body><main><h1>V{version}</h1>"
                "<p>关键结论已依据现有证据收窄。</p></main></body></html>"
            ),
            "revision": {
                "round": revision_round,
                "status": "ok",
                "applied": True,
                "duration_ms": 1,
            },
        }

    def execute_and_count(
        tool_name: str,
        category: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        result = fake_agent_tool_result(tool_name, category, payload)
        if tool_name == "build_market_report_data":
            builder_calls.append(payload)
        elif tool_name == "render_html_report":
            render_calls.append(payload)
        elif tool_name == "sif_market_get_keyword_demand":
            demand_tool_calls.append(payload)
        return result

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
    ]

    monkeypatch.setattr(
        server_module,
        "call_openai_compatible_chat",
        lambda messages, tools=None, tool_choice=None: chat_responses.pop(0),
    )
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", execute_and_count)
    monkeypatch.setattr(server_module, "review_html_report_node", approve_review)
    monkeypatch.setattr(server_module, "red_team_html_report_node", legacy_request_red_team)
    monkeypatch.setattr(server_module, "revise_html_report_node", revise_report)

    result = server_module.run_agent(
        {
            "runId": "abcd1234ef56",
            "prompt": "生成 Hsia 美国 minimizer bra 最近90天市场洞察报告。",
            "agentMode": "market",
            "category": "minimizer bra",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert len(builder_calls) == 1
    assert len(render_calls) == 1
    assert len(demand_tool_calls) == 1
    assert review_rounds == [1, 2]
    assert [int(item.get("reviewRound") or 1) for item in red_team_calls] == [1, 2]
    assert all("availableTools" not in item for item in red_team_calls)
    assert all("evidenceObservations" not in item for item in red_team_calls)
    assert revision_rounds == [1, 2]
    assert not any(tool["name"] == "validate_red_team_evidence" for tool in result["tools"])
    assert not any(
        (tool.get("runtime") or {}).get("node") == "red_team_evidence"
        for tool in result["tools"]
    )
    approval = result["llm_analysis"]["approval"]
    assert approval["policy"] == "two_parallel_review_rounds"
    assert approval["status"] == "published_after_round_2_rejection"
    assert approval["review_count"] == 2
    assert approval["red_team_count"] == 2
    assert approval["revision_count"] == 2
    assert "red_team_enrichment_count" not in approval
    assert "red_team_evidence_attempts" not in approval
    assert all(item["decision"] == "revise" for item in approval["red_teams"])
    assert all("evidence_requests" not in item for item in approval["red_teams"])


def test_run_agent_native_loop_can_choose_tools_after_loading_skill(monkeypatch) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    chat_calls: list[list[dict]] = []
    chat_tool_names: list[list[str]] = []
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
    ]

    def fake_call_chat(messages, tools=None, tool_choice=None):
        chat_calls.append(messages)
        chat_tool_names.append([tool["function"]["name"] for tool in tools or []])
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
    assert [tool["name"] for tool in result["tools"]] == [
        *WEEKLY_MARKET_BASELINE_TOOLS,
        *WEEKLY_MARKET_REPORT_TOOLS,
        *HTML_REPORT_APPROVAL_TOOLS,
    ]
    assert result["planner"]["planned_tools"] == [
        *WEEKLY_MARKET_BASELINE_TOOLS,
        *WEEKLY_MARKET_REPORT_TOOLS,
        *HTML_REPORT_APPROVAL_TOOLS,
    ]
    assert result["artifact"]["title"] == "Fake LLM-authored market report"
    assert result["llm_analysis"]["renderer"] == "llm-html"
    analysis_tool = next(
        tool for tool in result["tools"] if tool["name"] == "analyze_market_report"
    )
    chart_render_tool = next(
        tool for tool in result["tools"] if tool["name"] == "render_report_charts"
    )
    render_tool = next(tool for tool in result["tools"] if tool["name"] == "render_html_report")
    builder_tool = next(tool for tool in result["tools"] if tool["name"] == "build_market_report_data")
    assert builder_tool["runtime"]["node"] == "report_data_builder"
    assert analysis_tool["runtime"]["node"] == "data_analysis"
    assert chart_render_tool["runtime"]["node"] == "chart_render"
    assert render_tool["runtime"]["node"] == "html_render"
    report_node_events = [
        event
        for event in result["events"]
        if event.get("data", {}).get("graph_node")
        in {
            "report_data_builder",
            "data_analysis",
            "insight_synthesis",
            "chart_render",
            "html_render",
            "synthesize_artifact",
        }
        and event.get("status") == "ok"
    ]
    assert [event["data"]["graph_node"] for event in report_node_events] == [
        "report_data_builder",
        "data_analysis",
        "insight_synthesis",
        "chart_render",
        "html_render",
        "synthesize_artifact",
    ]
    assert all(event["data"]["langgraph_node"] is True for event in report_node_events)
    assert render_tool["input"]["marketReportData"]["schema_version"] == "market_report_data.v1"
    assert render_tool["input"]["toolResults"] == []
    assert "chartSpecs" not in render_tool["input"]
    assert len(chat_calls) == 11
    assert "build_market_report_data" not in chat_tool_names[1]
    assert "render_html_report" not in chat_tool_names[1]
    assert all("synthesize_artifact" not in tool_names for tool_names in chat_tool_names)
    assert len(chat_responses) == 0
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
    assert [tool for tool, _, _ in tool_categories] == [
        *WEEKLY_MARKET_BASELINE_TOOLS,
        *[
                tool
                for tool in WEEKLY_MARKET_REPORT_TOOLS
                if tool
                not in {
                    "analyze_market_report",
                    "synthesize_report_insights",
                    "render_report_charts",
                }
            ],
        ]
    assert all(category == "yoga pants" for _, category, _ in tool_categories)
    assert all(payload_category == "yoga pants" for _, _, payload_category in tool_categories)


def test_weekly_market_agent_promotes_resolved_category_node_for_followup_tool(monkeypatch) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    seller_catalog = server_module.planner_agent_tool_catalog()
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
            [native_tool_call("call-node-again", "sellersprite_product_node", {"keyword": "minimizer"})]
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
    assert sum(name == "sellersprite_product_node" for name, _ in tool_payloads) == 1
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


def test_product_design_skill_asks_for_missing_design_goal_before_data_tools(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "call-load",
                    "load_skill",
                    {
                        "skill_id": "product_design_research",
                        "extracted_params": {"category": "strapless bra"},
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
                        "reason": "需要明确本轮产品研发目标。",
                        "missing_params": ["design_goal"],
                        "questions": [
                            {
                                "field": "design_goal",
                                "question": "这次希望解决什么产品问题？",
                            }
                        ],
                    },
                )
            ]
        ),
    ]
    monkeypatch.setattr(
        server_module,
        "call_openai_compatible_chat",
        lambda _messages, tools=None, tool_choice=None: chat_responses.pop(0),
    )

    result = server_module.run_agent(
        {
            "prompt": "调研美国 strapless bra 并生成研发任务书。",
            "category": "strapless bra",
            "useLlm": True,
        }
    )

    assert result["status"] == "needs_input"
    assert result["tools"] == []
    assert result["skill"]["skill_id"] == "product_design_research"
    assert result["skill"]["missing_params"] == ["design_goal"]


def test_load_agent_run_state_marks_inactive_progress_as_interrupted(monkeypatch, tmp_path) -> None:
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
    assert restored["status"] == "error"
    assert "interrupted" in restored["error"]
    assert "result" not in restored
    assert restored["events"][0]["run_id"] == "123456abcdef"


def test_load_agent_run_state_keeps_active_progress_running(monkeypatch, tmp_path) -> None:
    run_id = "123456abcdef"
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    server_module.write_agent_run_json(
        run_id,
        "progress.json",
        {
            "run_id": run_id,
            "status": "running",
            "updated_at": "2026-07-13T00:00:00+00:00",
            "events": [],
        },
    )
    with server_module.ACTIVE_AGENT_RUN_LOCK:
        server_module.ACTIVE_AGENT_RUN_IDS.add(run_id)
    try:
        restored = server_module.load_agent_run_state(run_id)
    finally:
        with server_module.ACTIVE_AGENT_RUN_LOCK:
            server_module.ACTIVE_AGENT_RUN_IDS.discard(run_id)

    assert restored is not None
    assert restored["status"] == "running"


def test_agent_stream_sends_heartbeat_while_run_is_busy(monkeypatch) -> None:
    sent_events: list[tuple[str, dict[str, Any]]] = []

    class FakeHandler:
        close_connection = False

        def send_response(self, _status):
            return None

        def send_header(self, _name, _value):
            return None

        def end_headers(self):
            return None

        def send_sse(self, event_name, payload):
            sent_events.append((event_name, payload))

    def slow_run(payload, emit_event=None):
        time.sleep(0.03)
        return {"run_id": payload["runId"], "status": "ok"}

    monkeypatch.setattr(server_module, "AGENT_STREAM_HEARTBEAT_SECONDS", 0.005)
    monkeypatch.setattr(server_module, "run_agent", slow_run)

    server_module.AppHandler.send_agent_run_stream(FakeHandler(), {"runId": "123456abcdef"})

    assert any(name == "heartbeat" for name, _ in sent_events)
    assert sent_events[-1] == ("result", {"run_id": "123456abcdef", "status": "ok"})


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
    assert [tool["name"] for tool in continued["tools"]] == [
        *WEEKLY_MARKET_BASELINE_TOOLS,
        *WEEKLY_MARKET_REPORT_TOOLS,
        *HTML_REPORT_APPROVAL_TOOLS,
    ]
    assert continued["events"][2]["input"]["timeRange"] == "90d"
    assert continued["artifact"]["title"] == "Fake LLM-authored market report"
    assert continued["llm_analysis"]["renderer"] == "llm-html"


def test_context_question_answers_without_loading_skill_or_data_tools(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    source_run_id = "abc123abc123"
    run_dir = tmp_path / "agent-runs" / source_run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": source_run_id,
                "status": "ok",
                "mode": "competitor",
                "category": "女士文胸",
                "prompt": "生成美国文胸竞品店铺分析。",
                "skill": {
                    "skill_id": "tiktok_us_bra_competitor_shop_analysis",
                    "name": "TikTok Shop 美国文胸竞品店铺分析",
                    "params": {"marketplace": "US", "category": "女士文胸"},
                },
                "artifact": {
                    "title": "美国文胸竞品店铺分析",
                    "executive_summary": "Shop A 的 28 天销售趋势最强。",
                    "key_findings": ["Shop A 增长最快"],
                },
                "tools": [
                    {
                        "name": "build_tiktok_bra_competitor_shop_report_data",
                        "status": "ok",
                        "summary": "Compiled 10 shops.",
                        "data": {
                            "shops": [
                                {"shop_name": "Shop A", "shop_id": "1001", "trend": "+32%"}
                            ]
                        },
                    }
                ],
                "output_files": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    observed: dict[str, Any] = {}

    def fake_chat(messages, tools=None, tool_choice=None):  # noqa: ARG001
        observed["messages"] = messages
        observed["tool_names"] = [tool["function"]["name"] for tool in tools or []]
        return native_chat_response(
            [
                native_tool_call(
                    "answer-follow-up",
                    "respond_to_user",
                    {"message": "Shop A 增长最快，报告记录的 28 天趋势为 +32%。"},
                )
            ]
        )

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)

    result = server_module.run_agent(
        {
            "runId": "def456def456",
            "contextRunId": source_run_id,
            "prompt": "为什么 Shop A 增长最快？",
            "agentMode": "competitor",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert result["response_type"] == "message"
    assert result["context_source_run_id"] == source_run_id
    assert result["skill"]["skill_id"] is None
    assert result["tools"] == []
    assert "respond_to_user" in observed["tool_names"]
    assert "load_skill" in observed["tool_names"]
    assert "resume_previous_run" in observed["tool_names"]
    assert "Shop A" in observed["messages"][1]["content"]
    assert "不会限制本轮只能追问" in observed["messages"][1]["content"]
    assert not any(event.get("type") == "skill" for event in result["events"])


def test_context_can_start_a_new_skill_workflow(monkeypatch, tmp_path) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    source_run_id = "abc123abc123"
    run_dir = tmp_path / "agent-runs" / source_run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": source_run_id,
                "status": "ok",
                "mode": "competitor",
                "category": "sports bra",
                "prompt": "分析 sports bra 竞品。",
                "skill": {
                    "skill_id": "competitor_product_deep_dive",
                    "params": {"category": "sports bra"},
                },
                "tools": [],
                "output_files": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    first_turn_tools: list[str] = []
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "load-new-research",
                    "load_skill",
                    {
                        "skill_id": "weekly_market_insight",
                        "extracted_params": {
                            "brand": "Hsia",
                            "marketplace": "US",
                            "category": "minimizer bra",
                            "time_range": "30d",
                        },
                    },
                )
            ]
        ),
        native_chat_response(
            [
                native_tool_call(
                    "collect-new-demand",
                    "sif_market_get_keyword_demand",
                    {"keywords": ["minimizer bra"], "country": "US"},
                )
            ]
        ),
        native_chat_response(
            [
                native_tool_call(
                    "answer-new-research-status",
                    "respond_to_user",
                    {"message": "已按新调研意图加载市场洞察 Skill，并开始采集 minimizer bra 数据。"},
                )
            ]
        ),
    ]

    def fake_chat(messages, tools=None, tool_choice=None):  # noqa: ARG001
        if not first_turn_tools:
            first_turn_tools.extend(tool["function"]["name"] for tool in tools or [])
        return chat_responses.pop(0)

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_agent_tool_result)

    result = server_module.run_agent(
        {
            "runId": "def456def456",
            "contextRunId": source_run_id,
            "prompt": "现在重新调研 Hsia 美国 minimizer bra 最近30天市场。",
            "agentMode": "market",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert result["skill"]["skill_id"] == "weekly_market_insight"
    assert [tool["name"] for tool in result["tools"]] == ["sif_market_get_keyword_demand"]
    assert "load_skill" in first_turn_tools
    assert "resume_previous_run" in first_turn_tools
    assert not any(event["title"].startswith("恢复任务") for event in result["events"])


def test_failed_context_can_resume_builder_and_retry_only_renderer(monkeypatch, tmp_path) -> None:
    install_weekly_market_test_catalog(monkeypatch)
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    source_run_id = "abc123abc123"
    run_dir = tmp_path / "agent-runs" / source_run_id
    run_dir.mkdir(parents=True)
    restored_market_report = {
        "schema_version": "market_report_data.v1",
        "title": "Hsia minimizer bra 市场洞察",
        "category": "minimizer bra",
        "market_kpis": [{"label": "需求锚点", "value": "100", "source": "E01"}],
        "chart_specs": [],
        "artifact": {"title": "Hsia minimizer bra 市场洞察"},
    }
    restored_tools = [
        {
            "name": tool_name,
            "label": tool_name,
            "status": "ok",
            "summary": f"{tool_name} completed",
            "input": {},
            "data": {},
        }
        for tool_name in WEEKLY_MARKET_BASELINE_TOOLS
    ]
    restored_tools.extend(
        [
            {
                "name": "build_market_report_data",
                "label": "MarketReportData builder",
                "status": "ok",
                "summary": "MarketReportData compiled.",
                "input": {},
                "data": restored_market_report,
            },
            {
                "name": "render_html_report",
                "label": "HTML report renderer",
                "status": "timeout",
                "summary": "Tool timed out after 600 seconds.",
                "input": {},
                "data": {},
            },
        ]
    )
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": source_run_id,
                "status": "error",
                "mode": "market",
                "category": "minimizer bra",
                "prompt": "生成 Hsia 美国 minimizer bra 本周洞察报告。",
                "skill": {
                    "skill_id": "weekly_market_insight",
                    "name": "市场洞察 Skill",
                    "params": {
                        "brand": "Hsia",
                        "marketplace": "US",
                        "category": "minimizer bra",
                        "time_range": "30d",
                    },
                },
                "tools": restored_tools,
                "evidence_gaps": [],
                "message": {
                    "role": "assistant",
                    "content": "HTML 报告生成失败：Tool timed out after 600 seconds.",
                },
                "output_files": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chat_responses = [
        native_chat_response(
            [
                native_tool_call(
                    "resume-failed-run",
                    "resume_previous_run",
                    {"reason": "用户要求重新渲染上一轮失败报告。"},
                )
            ]
        ),
        native_chat_response(content=""),
    ]

    def fake_chat(messages, tools=None, tool_choice=None):  # noqa: ARG001
        return chat_responses.pop(0)

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_agent_tool_result)

    result = server_module.run_agent(
        {
            "runId": "def456def456",
            "contextRunId": source_run_id,
            "prompt": "重新渲染，继续上一轮失败任务。",
            "agentMode": "market",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert result["skill"]["skill_id"] == "weekly_market_insight"
    assert result["resumed_from_run_id"] == source_run_id
    assert sum(
        tool["name"] == "build_market_report_data" for tool in result["tools"]
    ) == 1
    assert sum(tool["name"] == "render_html_report" for tool in result["tools"]) == 2
    retried_render = next(
        tool
        for tool in reversed(result["tools"])
        if tool["name"] == "render_html_report" and tool["status"] == "ok"
    )
    assert (
        retried_render["input"]["marketReportData"]["schema_version"]
        == "market_report_data.v1"
    )
    assert "用户继续指令：重新渲染" in retried_render["input"]["prompt"]
    assert any(event["title"].startswith("恢复任务") for event in result["events"])


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
    assert [tool["name"] for tool in result["tools"]] == [
        *WEEKLY_MARKET_BASELINE_TOOLS,
        *WEEKLY_MARKET_REPORT_TOOLS,
        *HTML_REPORT_APPROVAL_TOOLS,
    ]
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


def test_mcp_settings_redact_fastmoss_sellersprite_and_sif_credentials() -> None:
    settings = build_mcp_settings_response(
        {
            "FASTMOSS_MCP_API_KEY": "fastmoss-secret",
            "SELLERSPRITE_MCP_SECRET_KEY": "seller-secret",
            "SIF_API_KEY": "sif-secret",
        }
    )
    sources = {source["id"]: source for source in settings["sources"]}

    assert sources["fastmoss"]["configured"] is True
    assert sources["sellersprite"]["configured"] is True
    assert sources["sif"]["configured"] is True
    assert sources["fastmoss"]["env_name"] == "FASTMOSS_MCP_API_KEY"
    assert sources["sellersprite"]["env_name"] == "SELLERSPRITE_MCP_SECRET_KEY"
    assert sources["sif"]["env_name"] == "SIF_MCP_TOKEN"
    assert "fastmoss-secret" not in json.dumps(settings)
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
        "FASTMOSS_MCP_API_KEY",
        "FASTMOSS_MCP_KEY",
        "FASTMOSS_API_KEY",
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
                "fastmoss": {"value": "fastmoss-test"},
                "sellersprite": {"value": "seller-test"},
                "sif": {"value": "sif-test"},
            }
        }
    )

    assert all(source["configured"] for source in result["sources"])
    assert os.environ["FASTMOSS_MCP_API_KEY"] == "fastmoss-test"
    assert os.environ["SELLERSPRITE_MCP_SECRET_KEY"] == "seller-test"
    assert os.environ["SIF_MCP_TOKEN"] == "sif-test"
    env_text = env_path.read_text(encoding="utf-8")
    assert "FASTMOSS_MCP_API_KEY=fastmoss-test" in env_text
    assert "SELLERSPRITE_MCP_SECRET_KEY=seller-test" in env_text
    assert "SIF_MCP_TOKEN=sif-test" in env_text

    cleared = update_mcp_settings(
        {
            "credentials": {
                "fastmoss": {"clear": True},
                "sellersprite": {"clear": True},
                "sif": {"clear": True},
            }
        }
    )

    assert not any(source["configured"] for source in cleared["sources"])
    assert "FASTMOSS_MCP_API_KEY" not in os.environ
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

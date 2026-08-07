from __future__ import annotations

from typing import Any

import pytest

from insight_agent import server as server_module
from insight_agent.tool_capabilities import InvocationScope

LOCAL_PLANNER_CAPABILITY_IDS = {
    "reddit_voc",
    "amazon_shelf",
    "media_rankings",
    "trend_platforms",
    "tiktok_social",
}


def test_all_local_planner_capabilities_have_one_registry_catalog_source() -> None:
    registry = server_module.AGENT_TOOL_CAPABILITY_REGISTRY

    assert set(registry.catalog(InvocationScope.PLANNER)) == LOCAL_PLANNER_CAPABILITY_IDS
    assert LOCAL_PLANNER_CAPABILITY_IDS.isdisjoint(server_module.AGENT_TOOL_CATALOG)
    for capability_id in LOCAL_PLANNER_CAPABILITY_IDS:
        metadata = server_module.agent_tool_catalog()[capability_id]
        assert metadata["invocation_scope"] == "planner"
        assert metadata["result_contract"] == f"{capability_id}_result.v1"
        assert metadata["output_kind"] == capability_id


@pytest.mark.parametrize(
    ("capability_id", "expected"),
    [
        (
            "amazon_shelf",
            {
                "category": "minimizer bra",
                "limit": 33,
                "amazonKeywordLimit": 7,
                "useLlm": False,
                "bypassCache": True,
            },
        ),
        (
            "media_rankings",
            {
                "category": "minimizer bra",
                "queryLimit": 6,
                "resultsPerQuery": 9,
                "candidateLimit": 11,
                "includeIndustryReports": True,
                "urls": ["https://example.com/report"],
                "bypassCache": True,
            },
        ),
        (
            "trend_platforms",
            {
                "category": "minimizer bra",
                "marketplace": "US",
                "timeRange": "90d",
                "designGoal": "support",
                "targetUser": "full bust",
                "trendContext": "summer",
                "resultsPerQuery": 9,
                "resultsPerPlatform": 9,
                "pageReadLimit": 11,
                "reportImageLimit": 8,
                "bypassCache": True,
            },
        ),
        (
            "tiktok_social",
            {
                "category": "minimizer bra",
                "limit": 9,
                "tiktokCommentsPerVideo": 6,
                "bypassCache": True,
            },
        ),
    ],
)
def test_local_planner_capability_inputs_match_legacy_behavior(
    capability_id: str,
    expected: dict[str, Any],
) -> None:
    payload = {
        "params": {
            "category": "minimizer bra",
            "marketplace": "US",
            "time_range": "90d",
            "listing_sample_size": 33,
            "amazon_keyword_limit": 7,
            "article_query_limit": 6,
            "article_results_per_query": 9,
            "article_candidate_limit": 11,
            "report_image_limit": 8,
            "tiktok_video_limit": 9,
            "tiktok_comments_per_video": 6,
            "design_goal": "support",
            "target_user": "full bust",
            "trend_context": "summer",
            "brand_site_urls": ["https://example.com/report"],
            "bypass_cache": True,
        }
    }

    assert server_module.agent_tool_input_payload(capability_id, "fallback", payload) == expected


def test_amazon_shelf_success_matches_the_legacy_golden_result(monkeypatch) -> None:
    monkeypatch.setattr(
        server_module,
        "analyze_amazon_category",
        lambda _tool_input: {
            "metrics": {"products": 1, "total_review_count": 120},
            "price_bands": [{"label": "$20-$30", "count": 1}],
            "brands": [{"name": "Example"}],
            "queries": ["minimizer bra"],
            "products": [
                {
                    "asin": "B000TEST",
                    "title": "Example bra",
                    "brand": "Example",
                    "product_url": "https://example.com/product",
                    "image_url": "https://example.com/image.jpg",
                    "price_text": "$24.99",
                    "rating_value": 4.3,
                    "review_count": 120,
                    "review_samples": [{"text": "Comfortable"}],
                    "badges": ["Best Seller"],
                }
            ],
        },
    )

    result = server_module.execute_agent_tool("amazon_shelf", "minimizer bra", {})

    assert result["status"] == "ok"
    assert result["summary"] == "1 Amazon products, 120 review/rating signals."
    assert result["data"]["products"] == [
        {
            "asin": "B000TEST",
            "title": "Example bra",
            "brand": "Example",
            "url": "https://example.com/product",
            "image_url": "https://example.com/image.jpg",
            "price": "$24.99",
            "rating": 4.3,
            "reviews": 120,
            "review_sample_count": 1,
            "review_samples": [{"text": "Comfortable"}],
            "badges": ["Best Seller"],
        }
    ]
    assert "output_kind" not in result


def test_media_rankings_keeps_discovery_and_bounded_articles(monkeypatch) -> None:
    analyzed_payloads: list[dict[str, Any]] = []

    monkeypatch.setattr(
        server_module,
        "discover_article_urls",
        lambda _tool_input: {
            "candidates": [{"url": "https://example.com/discovered"}],
            "warnings": ["discovery warning"],
        },
    )
    def analyze_articles(payload):
        analyzed_payloads.append(payload)
        return {
            "summary": {"collected_articles": 1},
            "data_volume": {"collected_articles": 1},
            "articles": [
                {
                    "title": "Best bras",
                    "domain": "example.com",
                    "url": payload["urls"][0],
                    "source_type": "ranking",
                    "authority_level": "medium",
                    "product_signals": ["support"],
                    "evidence_snippets": ["Strong side support"],
                    "cautions": [],
                }
            ],
            "warnings": [],
        }

    monkeypatch.setattr(server_module, "analyze_articles", analyze_articles)

    result = server_module.execute_agent_tool(
        "media_rankings",
        "requested category",
        {
            "params": {
                "category": "canonical input category",
                "brand_site_urls": ["https://example.com/provided"],
            }
        },
    )

    assert result["status"] == "ok"
    assert result["summary"] == "1 readable articles."
    assert result["data"]["articles"][0]["url"] == "https://example.com/provided"
    assert result["data"]["warnings"] == []
    assert result["input"]["category"] == "canonical input category"
    assert analyzed_payloads[0]["category"] == "requested category"


def test_trend_platforms_preserves_a_partial_collection(monkeypatch) -> None:
    monkeypatch.setattr(
        server_module,
        "crawl_trend_platforms",
        lambda _tool_input: {
            "category": "minimizer bra",
            "marketplace": "US",
            "time_range": "90d",
            "generated_at": "2026-08-07T00:00:00Z",
            "source_mode": "public_web",
            "coverage": {
                "accessed_platforms": 1,
                "required_platforms": 3,
                "readable_pages": 2,
                "recent_pages": 1,
            },
            "visual_evidence": [],
            "visual_coverage": {"selected_for_report": 0},
            "platforms": [
                {
                    "platform_id": "pinterest",
                    "name": "Pinterest",
                    "accessed": True,
                    "access_status": "partial",
                    "pages": [{"url": "https://example.com/page"}],
                    "warnings": ["limited coverage"],
                }
            ],
            "warnings": ["2 required platforms unavailable"],
            "method": {"kind": "public_pages"},
        },
    )

    result = server_module.execute_agent_tool("trend_platforms", "minimizer bra", {})

    assert result["status"] == "ok"
    assert result["summary"] == (
        "Accessed 1/3 required trend platforms; read 2 effective public page(s), "
        "including 1 within the requested window, and selected 0 visual evidence item(s)."
    )
    assert result["data"]["platforms"][0]["access_status"] == "partial"
    assert result["data"]["warnings"] == ["2 required platforms unavailable"]


def test_tiktok_social_preserves_runtime_availability_errors(monkeypatch) -> None:
    def unavailable(_tool_input):
        raise RuntimeError("TikTok browser unavailable")

    monkeypatch.setattr(server_module, "analyze_tiktok_category", unavailable)

    result = server_module.execute_agent_tool("tiktok_social", "minimizer bra", {})

    assert result["status"] == "error"
    assert result["summary"] == "TikTok browser unavailable"
    assert result["data"] == {}


def test_malformed_local_adapter_result_uses_the_common_error_envelope(monkeypatch) -> None:
    monkeypatch.setattr(
        server_module,
        "analyze_amazon_category",
        lambda _tool_input: {"products": "malformed"},
    )

    result = server_module.execute_agent_tool("amazon_shelf", "minimizer bra", {})

    assert result["status"] == "error"
    assert result["name"] == "amazon_shelf"
    assert result["label"] == "Amazon shelf"
    assert result["data"] == {}

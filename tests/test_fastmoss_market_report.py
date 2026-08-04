from __future__ import annotations

from typing import Any

import insight_agent.mcp_fastmoss as fastmoss_module
from insight_agent.fastmoss_market_report import (
    build_fastmoss_market_report_data,
    completed_us_periods,
)
from insight_agent.mcp_fastmoss import build_fastmoss_input_payload
from insight_agent.server import build_market_report_data


def tool(
    name: str,
    *,
    tool_input: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    status: str = "ok",
) -> dict[str, Any]:
    return {
        "name": f"mcp__fastmoss__{name}",
        "label": f"FastMoss: {name}",
        "status": status,
        "summary": f"{name} result",
        "input": tool_input or {},
        "data": data or {},
    }


def completed_tool_results() -> list[dict[str, Any]]:
    month_filter = {
        "category_id": 842888,
        "date_type": "month",
        "date_value": "2026-06",
        "region": "US",
    }
    week_filter = {
        "category_id": 842888,
        "date_type": "week",
        "date_value": "2026-W28",
        "region": "US",
    }
    product = {
        "product_id": "p1",
        "title": "Example Minimizer Bra",
        "period_gmv": 12000,
        "period_units_sold": 400,
        "region": "US",
    }
    return [
        tool(
            "search_category_by_words",
            tool_input={"query": ["minimizer bra", "full coverage bra"]},
            data={
                "result": {
                    "categories": [
                        {
                            "category_id_level3": 601262,
                            "cn_full_name": "女装与女士内衣-女士内衣-女士文胸",
                        }
                    ]
                }
            },
        ),
        tool(
            "product_search",
            tool_input={
                "keywords": "minimizer bra",
                "filter": {"region": "US"},
                "orderby": [{"field": "day28_gmv", "order": "desc"}],
                "page": 1,
                "pagesize": 10,
            },
            data={
                "list": [
                    {
                        "product": {
                            "product_id": "p1",
                            "title": "Example Minimizer Bra",
                            "region": "US",
                        },
                        "sales_summary": {
                            "day28_gmv": 24000,
                            "day28_units_sold": 800,
                        },
                    }
                ]
            },
        ),
        tool(
            "product_search",
            tool_input={
                "keywords": "minimizing bra",
                "filter": {"region": "US"},
                "orderby": [{"field": "day28_units_sold", "order": "desc"}],
                "page": 1,
                "pagesize": 10,
            },
            data={"list": [{**product, "day28_gmv": 24000, "day28_units_sold": 800}]},
        ),
        tool(
            "product_search",
            tool_input={
                "keywords": "minimizer bra",
                "filter": {"region": "US", "is_new_listed": True},
                "orderby": [{"field": "day28_gmv", "order": "desc"}],
                "page": 1,
                "pagesize": 10,
            },
            data={"list": [{**product, "day28_gmv": 24000, "is_new_listed": True}]},
        ),
        tool(
            "market_category_ranking",
            tool_input={
                "filter": month_filter,
                "orderby": [{"field": "category_units_sold", "order": "desc"}],
            },
            data={
                "ranked_categories": [
                    {
                        "category_id": 842888,
                        "category_name": "Women's Underwear",
                        "category_units_sold": 100000,
                        "region": "US",
                    }
                ],
                "ranking_scope": {"region": "US"},
            },
        ),
        tool(
            "market_category_analysis",
            tool_input={"filter": month_filter, "analysis_type": "basic_metrics"},
            data={
                "analysis_type": "basic_metrics",
                "category": {
                    "category_id": 842888,
                    "category_name": "Women's Underwear",
                    "region": "US",
                },
                "scale_metrics": {
                    "category_gmv": 2000000,
                    "category_units_sold": 100000,
                    "selling_video_count": 5000,
                },
                "growth_metrics": {"category_gmv_mom_percent": 8.2},
                "concentration_metrics": {"top_products_gmv_share": 24.0},
            },
        ),
        tool(
            "market_category_analysis",
            tool_input={"filter": month_filter, "analysis_type": "sales_trends"},
            data={
                "analysis_type": "sales_trends",
                "category": {
                    "category_id": 842888,
                    "category_name": "Women's Underwear",
                    "region": "US",
                },
                "trend_series": [
                    {
                        "period_label": "2026-06-01~07",
                        "category_units_sold": 22000,
                        "selling_video_count": 900,
                    },
                    {
                        "period_label": "2026-06-08~14",
                        "category_units_sold": 25000,
                        "selling_video_count": 1100,
                    },
                    {
                        "period_label": "2026-06-15~21",
                        "category_units_sold": 27000,
                        "selling_video_count": 1300,
                    },
                    {
                        "period_label": "2026-06-22~28",
                        "category_units_sold": 26000,
                        "selling_video_count": 1250,
                    },
                ],
            },
        ),
        tool(
            "market_category_analysis",
            tool_input={"filter": month_filter, "analysis_type": "price_distribution"},
            data={
                "analysis_type": "price_distribution",
                "product_count_price_distribution": [
                    {"price_range": "$20-30", "product_count": 120}
                ],
                "sales_price_distribution": {
                    "gmv_distribution": [{"price_range": "$20-30", "gmv_share_percent": 42.0}],
                    "units_sold_distribution": [
                        {"price_range": "$20-30", "units_sold_share_percent": 48.0}
                    ],
                },
            },
        ),
        tool(
            "market_category_author_sales_matrix",
            tool_input={"filter": {"category_id": 842888, "date_value": "2026-06", "region": "US"}},
            data={
                "list": [{"follower_tier": "10k-50k", "gmv_share_percent": 54.0, "region": "US"}]
            },
        ),
        tool(
            "creator_rank_top_ecommerce",
            tool_input={"filter": week_filter},
            data={
                "list": [
                    {
                        "creator_uid": "c1",
                        "creator_name": "Creator One",
                        "period_gmv": 50000,
                        "region": "US",
                    }
                ]
            },
        ),
        tool(
            "product_rank_top_selling",
            tool_input={
                "filter": week_filter,
                "orderby": [{"field": "period_gmv", "order": "desc"}],
            },
            data={"list": [product]},
        ),
        tool(
            "product_rank_top_selling",
            tool_input={
                "filter": week_filter,
                "orderby": [{"field": "units_sold_growth_rate_percent", "order": "desc"}],
            },
            data={"list": [{**product, "units_sold_growth_rate_percent": 45.0}]},
        ),
        tool(
            "product_rank_new_listed",
            tool_input={"filter": week_filter},
            data={"list": [{**product, "launch_date": "2026-07-01"}]},
        ),
        tool(
            "shop_rank_top_selling",
            tool_input={"filter": week_filter},
            data={
                "list": [
                    {
                        "shop": {"seller_id": "s1", "shop_name": "Hsia-Bras", "region": "US"},
                        "ranking_metrics": {"period_gmv": 85000},
                    }
                ]
            },
        ),
        tool(
            "product_sales_trend",
            tool_input={"filter": {"product_id": "p1", "time_range_days": 28}},
            data={
                "region": "US",
                "product_id": "p1",
                "period_summary": {"period_gmv": 24000, "period_units_sold": 800},
                "daily_trend": [{"date": "2026-07-01", "daily_gmv": 700, "daily_units_sold": 20}],
            },
        ),
        tool(
            "product_creator_analysis",
            tool_input={"filter": {"product_id": "p1"}},
            data={
                "region": "US",
                "product_id": "p1",
                "creator_summary": {
                    "follower_tier_distribution": [
                        {"follower_tier": "10k-50k", "creator_count": 20}
                    ]
                },
                "linked_creators": {
                    "total": 20,
                    "list": [{"creator": {"creator_uid": "c1", "region": "US"}}],
                },
            },
        ),
        tool(
            "product_video_list",
            tool_input={"filter": {"product_id": "p1", "time_range_days": 28}},
            data={
                "region": "US",
                "product_id": "p1",
                "total": 30,
                "videos": [{"video_id": "v1", "traffic_flags": {"is_ad": False}}],
            },
        ),
        tool(
            "product_overview",
            tool_input={"filter": {"product_id": "p1", "time_range_days": 28}},
            data={
                "region": "US",
                "product_id": "p1",
                "ads_distribution": {"ad_gmv_share_percent": 30},
                "channel_distribution": {"affiliate_gmv_share_percent": 60},
                "content_distribution": {"video_gmv_share_percent": 70},
            },
        ),
        tool(
            "shop_sale_analysis",
            tool_input={"filter": {"seller_id": "s1", "time_range_days": 28}},
            data={
                "shop": {"seller_id": "s1", "region": "US"},
                "sales_channel_distribution": {
                    "by_gmv": [{"sales_channel_label": "affiliate", "gmv_share_percent": 66}]
                },
                "content_type_distribution": {
                    "by_gmv": [{"content_type_label": "video", "gmv_share_percent": 70}]
                },
            },
        ),
    ]


def test_fastmoss_market_report_compiles_tasks_before_rendering() -> None:
    report = build_fastmoss_market_report_data(
        {
            "skillId": "tiktok_us_market_insight",
            "brand": "Hsia",
            "marketplace": "US",
            "category": "minimizer bra",
            "timeRange": "28d",
            "generatedAt": "2026-07-15T06:00:00+00:00",
            "listingSampleSize": 1,
            "headListingCount": 1,
            "brandFacts": {"target_margin": "provided"},
            "toolResults": completed_tool_results(),
        }
    )

    assert report["schema_version"] == "fastmoss_market_report_data.v1"
    assert report["marketplace"] == "US"
    assert report["period_contract"]["month"] == "2026-06"
    assert report["period_contract"]["week"] == "2026-W28"
    assert report["analysis_coverage"]["summary"] == {
        "task_total": 12,
        "task_covered": 12,
        "p0_total": 12,
        "p0_covered": 12,
    }
    assert report["report_quality"]["status"] == "ready"
    assert report["research_boundary"]["segment_type"] == "keyword_defined_product_sample"
    assert report["segment_query_summary"]["distinct_keyword_queries"] == 2
    assert report["segment_query_summary"]["deduplicated_product_records"] == 1
    assert report["fastmoss_segment_products"][0]["product_id"] == "p1"
    assert set(report["fastmoss_segment_products"][0]["matched_queries"]) == {
        "minimizer bra",
        "minimizing bra",
    }
    assert {task["dimension_id"] for task in report["fastmoss_task_results"]} == {
        f"FM{index:02d}" for index in range(1, 13)
    }
    assert len(report["chart_specs"]) >= 4
    assert report["artifact"]["executive_summary"] == report["executive_summary"]


def test_generic_market_builder_routes_fastmoss_to_task_compiler() -> None:
    report = build_market_report_data(
        {
            "skillId": "tiktok_us_market_insight",
            "brand": "Hsia",
            "category": "minimizer bra",
            "generatedAt": "2026-07-15T06:00:00+00:00",
            "listingSampleSize": 1,
            "headListingCount": 1,
            "brandFacts": {"provided": True},
            "toolResults": completed_tool_results(),
        }
    )
    assert report["schema_version"] == "fastmoss_market_report_data.v1"


def test_stale_proxy_category_period_degrades_background_but_preserves_segment_timing() -> None:
    tools = completed_tool_results()
    for item in tools:
        filter_payload = item.get("input", {}).get("filter")
        if not isinstance(filter_payload, dict):
            continue
        if filter_payload.get("date_type") == "month" or item["name"].endswith(
            "market_category_author_sales_matrix"
        ):
            filter_payload["date_value"] = "2025-06"
        elif filter_payload.get("date_type") == "week":
            filter_payload["date_value"] = "2025-W27"

    report = build_fastmoss_market_report_data(
        {
            "category": "minimizer bra",
            "generatedAt": "2026-07-15T06:00:00+00:00",
            "listingSampleSize": 1,
            "headListingCount": 1,
            "brandFacts": {"provided": True},
            "toolResults": tools,
        }
    )
    task_status = {item["dimension_id"]: item["status"] for item in report["fastmoss_task_results"]}
    assert task_status["FM01"] == "covered"
    assert task_status["FM04"] == "missing_data"
    assert task_status["FM05"] == "missing_data"
    assert task_status["FM06"] == "missing_data"
    assert task_status["FM11"] == "covered"
    assert report["report_quality"]["status"] == "degraded"
    assert any("周期不一致" in gap for gap in report["data_gaps"])


def test_non_us_product_evidence_cannot_complete_us_product_tasks() -> None:
    tools = completed_tool_results()
    product_tool_names = {
        "mcp__fastmoss__product_sales_trend",
        "mcp__fastmoss__product_creator_analysis",
        "mcp__fastmoss__product_video_list",
        "mcp__fastmoss__product_overview",
        "mcp__fastmoss__shop_sale_analysis",
    }
    for item in tools:
        if item["name"] not in product_tool_names:
            continue
        item["data"]["region"] = "CA"
        if isinstance(item["data"].get("shop"), dict):
            item["data"]["shop"]["region"] = "CA"

    report = build_fastmoss_market_report_data(
        {
            "category": "minimizer bra",
            "generatedAt": "2026-07-15T06:00:00+00:00",
            "headListingCount": 1,
            "brandFacts": {"provided": True},
            "toolResults": tools,
        }
    )

    task_status = {item["dimension_id"]: item["status"] for item in report["fastmoss_task_results"]}
    assert task_status["FM01"] == "missing_data"
    assert task_status["FM08"] == "missing_data"
    assert task_status["FM09"] == "missing_data"
    assert task_status["FM10"] == "missing_data"
    assert report["fastmoss_product_trends"] == []
    assert report["fastmoss_product_creators"] == []
    assert report["fastmoss_product_videos"] == []
    assert report["fastmoss_channel_attribution"] == []


def test_empty_keyword_search_keeps_proxy_background_but_freezes_segment_conclusions() -> None:
    tools = completed_tool_results()
    for item in tools:
        if item["name"] == "mcp__fastmoss__product_search":
            item["data"] = {"list": []}

    report = build_fastmoss_market_report_data(
        {
            "category": "minimizer bra",
            "generatedAt": "2026-07-15T06:00:00+00:00",
            "listingSampleSize": 5,
            "headListingCount": 1,
            "brandFacts": {"provided": True},
            "toolResults": tools,
        }
    )

    task_status = {item["dimension_id"]: item["status"] for item in report["fastmoss_task_results"]}
    assert task_status["FM01"] == "covered"
    assert task_status["FM02"] == "missing_data"
    assert task_status["FM03"] == "covered"
    assert task_status["FM04"] == "covered"
    assert task_status["FM08"] == "missing_data"
    assert task_status["FM09"] == "missing_data"
    assert task_status["FM10"] == "missing_data"
    assert task_status["FM11"] == "missing_data"
    assert task_status["FM12"] == "missing_data"
    assert report["segment_query_summary"]["status"] == "missing_data"
    assert report["fastmoss_segment_products"] == []
    assert report["category_benchmark"]
    assert any("不表示该细分市场销量为零" in gap for gap in report["data_gaps"])


def test_tiktok_us_fastmoss_input_rewrites_model_period_to_completed_period(
    monkeypatch: Any,
) -> None:
    tool_name = "mcp__fastmoss__market_category_analysis"
    monkeypatch.setattr(
        fastmoss_module,
        "get_fastmoss_tool_catalog",
        lambda: {
            tool_name: {
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "analysis_type": {"type": "string"},
                        "filter": {
                            "type": "object",
                            "properties": {
                                "category_id": {"type": "integer"},
                                "date_type": {"type": "string"},
                                "date_value": {"type": "string"},
                                "region": {"type": "string"},
                            },
                        },
                    },
                }
            }
        },
    )
    result = build_fastmoss_input_payload(
        tool_name,
        "minimizer bra",
        {
            "skillId": "tiktok_us_market_insight",
            "generatedAt": "2026-07-15T06:00:00+00:00",
            "prompt": "分析最近 28 天美国 minimizer bra 市场",
            "filter": {
                "category_id": 842888,
                "date_type": "month",
                "date_value": "2025-06",
                "region": "US",
            },
            "analysis_type": "basic_metrics",
        },
    )
    assert result["filter"]["date_value"] == "2026-06"


def test_product_search_uses_category_as_plural_keywords_when_not_explicit(
    monkeypatch: Any,
) -> None:
    tool_name = "mcp__fastmoss__product_search"
    monkeypatch.setattr(
        fastmoss_module,
        "get_fastmoss_tool_catalog",
        lambda: {
            tool_name: {
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "keywords": {"type": "string"},
                        "filter": {
                            "type": "object",
                            "properties": {"region": {"type": "string"}},
                        },
                    },
                }
            }
        },
    )

    result = build_fastmoss_input_payload(
        tool_name,
        "minimizer bra",
        {"skillId": "tiktok_us_market_insight", "marketplace": "US"},
    )

    assert result == {"keywords": "minimizer bra", "filter": {"region": "US"}}


def test_completed_us_periods_returns_previous_natural_periods() -> None:
    periods = completed_us_periods("2026-07-15T06:00:00+00:00")
    assert periods["day"] == "2026-07-13"
    assert periods["week"] == "2026-W28"
    assert periods["month"] == "2026-06"


def test_completed_us_periods_uses_winter_pacific_offset_at_utc_date_boundary() -> None:
    periods = completed_us_periods("2026-01-02T07:30:00+00:00")
    assert periods["reference_date"] == "2026-01-01"
    assert periods["day"] == "2025-12-31"
    assert periods["month"] == "2025-12"

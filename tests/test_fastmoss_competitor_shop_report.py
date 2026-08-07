from __future__ import annotations

import copy
import datetime as dt
import json
from typing import Any

import pytest

import insight_agent.server as server_module
from insight_agent.fastmoss_competitor_shop_report import (
    build_tiktok_bra_competitor_shop_report_data,
)
from insight_agent.server import compose_html_report_with_llm


def tool(
    name: str,
    data: dict[str, Any],
    *,
    tool_input: dict[str, Any] | None = None,
    status: str = "ok",
) -> dict[str, Any]:
    return {
        "name": name,
        "label": name,
        "status": status,
        "summary": name,
        "input": tool_input or {},
        "data": data,
    }


def ranking_row(index: int, *, hsia: bool = False) -> dict[str, Any]:
    seller_id = "hsia-us" if hsia else f"seller-{index:02d}"
    return {
        "shop": {
            "seller_id": seller_id,
            "shop_name": "Hsia Official" if hsia else f"Bra Shop {index:02d}",
            "region": "US",
            "currency_code": "USD",
            "shop_type_code": "local",
            "is_cross_border": False,
            "shop_rating": 4.5,
        },
        "ranking_metrics": {
            "period_gmv": 100_000 - index * 1_000,
            "period_units_sold": 5_000 - index * 20,
            "gmv_growth_rate_percent": index - 5,
            "units_sold_growth_rate_percent": index - 6,
            "linked_creator_count": 100 - index,
            "products_with_sales_count": 40 - index // 2,
        },
        "ranking_scope": {
            "ranked_category_id": 601262,
            "ranked_category_name": "Bras",
        },
    }


def daily_trend() -> list[dict[str, Any]]:
    start = dt.date(2026, 7, 8)
    return [
        {
            "date": (start + dt.timedelta(days=offset)).isoformat(),
            "gmv": 100 if offset < 7 else 200,
            "units_sold": 10 if offset < 7 else 20,
        }
        for offset in range(14)
    ]


def completed_tool_results() -> list[dict[str, Any]]:
    results = [
        tool(
            "mcp__fastmoss__search_category_by_words",
            {
                "categories": [
                    {
                        "category_id_level3": 601262,
                        "category_name_level3": "Bras",
                        "category_path": "Womenswear > Women's Underwear > Bras",
                    },
                    {
                        "category_id_level3": 845576,
                        "category_name_level3": "Wireless Bras",
                        "category_path": "Womenswear > Women's Underwear > Wireless Bras",
                    },
                    {
                        "category_id_level3": 844936,
                        "category_name_level3": "Bra Accessories",
                        "category_path": "Womenswear > Women's Underwear > Bra Accessories",
                    },
                ]
            },
            tool_input={"query": ["women's bras", "bras", "女士文胸"]},
        ),
        tool(
            "mcp__fastmoss__fastmoss_detail_url_examples",
            {
                "detail_pages": {
                    "shop": {"template": "https://www.fastmoss.com/shop/{seller_id}"},
                    "product": {"template": "https://www.fastmoss.com/product/{product_id}"},
                    "creator": {"template": "https://www.fastmoss.com/creator/{uid}"},
                }
            },
        ),
    ]

    rows = [ranking_row(0, hsia=True), *[ranking_row(index) for index in range(1, 51)]]
    for page in range(1, 7):
        page_rows = rows[(page - 1) * 10 : page * 10]
        if not page_rows:
            continue
        results.append(
            tool(
                "mcp__fastmoss__shop_rank_top_selling",
                {"list": page_rows, "total": len(rows)},
                tool_input={
                    "page": page,
                    "pagesize": 10,
                    "filter": {
                        "region": "US",
                        "category_id": 601262,
                        "date_type": "month",
                        "date_value": "2026-06",
                    },
                    "orderby": [{"field": "usd_gmv", "order": "desc"}],
                },
            )
        )

    for index in range(1, 11):
        seller_id = f"seller-{index:02d}"
        filter_input = {"filter": {"seller_id": seller_id, "time_range_days": 28}}
        results.extend(
            [
                tool(
                    "mcp__fastmoss__shop_base_info",
                    {
                        "shop": {
                            "seller_id": seller_id,
                            "shop_name": f"Bra Shop {index:02d}",
                            "shop_rating": 4.6,
                        },
                        "active_product_count": 30,
                    },
                    tool_input={"filter": {"seller_id": seller_id}},
                ),
                tool(
                    "mcp__fastmoss__shop_product_analysis",
                    {
                        "products": {
                            "list": [
                                {
                                    "product_id": f"{seller_id}-low",
                                    "title": "Low price wireless bra",
                                    "category": {
                                        "l3": {"id": 601262, "name": "Bras"}
                                    },
                                    "real_price": "$15",
                                    "launch_date": "2026-07-01",
                                    "day28_gmv": 600,
                                    "day28_units_sold": 40,
                                },
                                {
                                    "product_id": f"{seller_id}-high",
                                    "title": "Premium full coverage bra",
                                    "category": {
                                        "l3": {
                                            "id": 845576,
                                            "name": "Wireless Bras",
                                        }
                                    },
                                    "real_price": "$120",
                                    "launch_date": "2026-06-01",
                                    "day28_gmv": 400,
                                    "day28_units_sold": 5,
                                },
                            ],
                            "total": 2,
                        }
                    },
                    tool_input={
                        "page": 1,
                        "pagesize": 10,
                        "filter": {"seller_id": seller_id},
                        "orderby": [{"field": "day28_gmv", "order": "desc"}],
                    },
                ),
                tool(
                    "mcp__fastmoss__shop_sale_analysis",
                    {
                        "content_type_distribution": {
                            "by_gmv": [
                                {"content_type_label": "Video", "gmv_share_percent": 70},
                                {"content_type_label": "Live", "gmv_share_percent": 30},
                            ]
                        },
                        "sales_channel_distribution": {
                            "by_gmv": [
                                {"sales_channel_label": "Affiliate", "gmv_share_percent": 80},
                                {"sales_channel_label": "Shop", "gmv_share_percent": 20},
                            ]
                        },
                    },
                    tool_input=filter_input,
                ),
                tool(
                    "mcp__fastmoss__shop_data_trends",
                    {"daily_trend": daily_trend()},
                    tool_input=filter_input,
                ),
                tool(
                    "mcp__fastmoss__shop_creator_analysis",
                    {
                        "list": [
                            {"uid": f"creator-{index}-1", "nickname": "Creator A", "sale_amount": 800},
                            {"uid": f"creator-{index}-2", "nickname": "Creator B", "sale_amount": 200},
                        ]
                    },
                    tool_input=filter_input,
                ),
            ]
        )
    return results


def payload(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "skillId": "tiktok_us_bra_competitor_shop_analysis",
        "brand": "Hsia",
        "marketplace": "US",
        "category": "女士文胸",
        "timeRange": "28d",
        "newProductWindow": "30d",
        "shopCandidateSize": 50,
        "shopAnalysisCount": 10,
        "generatedAt": "2026-07-22T08:00:00+00:00",
        "toolResults": tool_results,
    }


def test_builder_compiles_50_candidates_and_same_10_seller_ids() -> None:
    assert (
        server_module.agent_tool_catalog()["build_tiktok_bra_competitor_shop_report_data"][
            "invocation_scope"
        ]
        == "runtime_internal"
    )

    report = build_tiktok_bra_competitor_shop_report_data(payload(completed_tool_results()))

    assert report["schema_version"] == "tiktok_bra_competitor_shop_report_data.v1"
    assert report["status"] == "complete"
    assert report["summary"]["candidate_count"] == 50
    assert report["summary"]["analyzed_shop_count"] == 10
    assert report["source_scope"]["subject_brand_excluded_count"] == 1
    assert [row["seller_id"] for row in report["candidate_shops"][:10]] == [
        f"seller-{index:02d}" for index in range(1, 11)
    ]
    assert [row["seller_id"] for row in report["shop_comparison"]] == [
        f"seller-{index:02d}" for index in range(1, 11)
    ]
    first = report["shop_comparison"][0]
    assert first["shop_name"] == "Bra Shop 01"
    assert first["product_structure"]["price_band_product_counts"] == {
        "under_20": 1,
        "over_100": 1,
    }
    assert first["product_structure"]["observed_product_count"] == 2
    assert first["trend"]["trend_label"] == "加速"
    assert first["channel_structure"]["leading_sales_channel"] == "Affiliate"
    assert first["creator_structure"]["observed_top3_creator_gmv_share_percent"] == 100
    assert "whole-shop" in first["comparison_scope_notes"][2]
    assert first["fastmoss_url"].endswith("/seller-01")


def test_builder_merges_product_pages_and_filters_nested_bra_categories() -> None:
    results = completed_tool_results()
    results.append(
        tool(
            "mcp__fastmoss__shop_product_analysis",
            {
                "products": {
                    "list": [
                        {
                            "product_id": "seller-01-low",
                            "title": "Duplicate bra row with newer metrics",
                            "category": {"l3": {"id": 601262, "name": "Bras"}},
                            "real_price": "$15",
                            "day28_gmv": 700,
                            "day28_units_sold": 45,
                        },
                        {
                            "product_id": "seller-01-wireless",
                            "title": "Wireless minimizer bra",
                            "category": {
                                "l3": {"id": 845576, "name": "Wireless Bras"}
                            },
                            "real_price": "$35",
                            "day28_gmv": 300,
                            "day28_units_sold": 12,
                        },
                        {
                            "product_id": "seller-01-accessory",
                            "title": "Bra strap accessory",
                            "category": {
                                "l3": {"id": 844936, "name": "Bra Accessories"}
                            },
                            "real_price": "$8",
                            "day28_gmv": 200,
                        },
                        {
                            "product_id": "seller-01-shapewear",
                            "title": "Shapewear",
                            "category": {
                                "l3": {"id": 601259, "name": "Women's Shapewear"}
                            },
                            "real_price": "$45",
                            "day28_gmv": 100,
                        },
                        {
                            "product_id": "seller-01-unknown",
                            "title": "Unknown category row",
                            "real_price": "$20",
                            "day28_gmv": 50,
                        },
                    ],
                    "total": 15,
                }
            },
            tool_input={
                "page": 2,
                "pagesize": 10,
                "filter": {"seller_id": "seller-01"},
                "orderby": [{"field": "day28_gmv", "order": "desc"}],
            },
        )
    )

    report = build_tiktok_bra_competitor_shop_report_data(payload(results))

    product_structure = report["shop_comparison"][0]["product_structure"]
    assert product_structure["sampled_page_count"] == 2
    assert product_structure["sampled_product_row_count"] == 7
    assert product_structure["observed_product_count"] == 3
    assert product_structure["resolved_bra_category_ids"] == ["601262", "845576"]
    assert product_structure["excluded_explicit_non_bra_count"] == 2
    assert product_structure["excluded_unknown_category_count"] == 1
    assert product_structure["price_band_product_counts"] == {
        "under_20": 1,
        "20_40": 1,
        "over_100": 1,
    }
    assert product_structure["top_products"][0]["product_id"] == "seller-01-low"
    assert product_structure["top_products"][0]["day28_gmv"] == 700


def test_builder_accepts_actual_fastmoss_chinese_category_fields() -> None:
    results = completed_tool_results()
    category_tool = results[0]
    category_tool["data"] = {
        "categories": [
            {
                "category_id_level3": 601262,
                "cn_name": "女士文胸",
                "cn_full_name": "女装与女士内衣-女士内衣-女士文胸",
            }
        ]
    }

    report = build_tiktok_bra_competitor_shop_report_data(payload(results))

    assert report["source_scope"]["category_id_l3"] == "601262"
    assert report["source_scope"]["category_name_l3"] == "女士文胸"
    assert report["source_scope"]["category_path"].endswith("女士文胸")


def test_builder_uses_l2_weekly_candidate_fallback_only_after_empty_l3_month() -> None:
    results = [
        item
        for item in completed_tool_results()
        if item["name"] != "mcp__fastmoss__shop_rank_top_selling"
    ]
    results.append(
        tool(
            "mcp__fastmoss__shop_rank_top_selling",
            {"list": [], "total": 0},
            status="empty",
            tool_input={
                "page": 1,
                "pagesize": 10,
                "filter": {
                    "region": "US",
                    "category_id": 601262,
                    "date_type": "month",
                    "date_value": "2026-06",
                },
            },
        )
    )
    fallback_rows = [ranking_row(index) for index in range(1, 51)]
    for page in range(1, 6):
        results.append(
            tool(
                "mcp__fastmoss__shop_rank_top_selling",
                {"list": fallback_rows[(page - 1) * 10 : page * 10], "total": 50},
                tool_input={
                    "page": page,
                    "pagesize": 10,
                    "filter": {
                        "region": "US",
                        "category_id": 842888,
                        "date_type": "week",
                        "date_value": "2026-W29",
                    },
                    "orderby": [{"field": "usd_gmv", "order": "desc"}],
                },
            )
        )

    report = build_tiktok_bra_competitor_shop_report_data(payload(results))

    assert report["status"] == "degraded"
    assert report["source_scope"]["ranking_scope_is_fallback"] is True
    assert report["source_scope"]["ranking_category_id"] == "842888"
    assert report["source_scope"]["ranking_period_type"] == "week"
    assert "not a Top Bras shop claim" in report["shop_comparison"][0][
        "comparison_scope_notes"
    ][0]
    assert any("不能称为文胸店铺 Top 排名" in gap for gap in report["data_gaps"])


def test_builder_rejects_unattempted_selected_shop_tool_without_swapping_shop() -> None:
    results = completed_tool_results()
    results = [
        item
        for item in results
        if not (
            item["name"] == "mcp__fastmoss__shop_creator_analysis"
            and item["input"]["filter"]["seller_id"] == "seller-10"
        )
    ]

    with pytest.raises(ValueError, match="seller-10"):
        build_tiktok_bra_competitor_shop_report_data(payload(results))


def test_builder_keeps_attempted_failures_as_local_gaps() -> None:
    results = copy.deepcopy(completed_tool_results())
    for item in results:
        if (
            item["name"] == "mcp__fastmoss__shop_base_info"
            and item["input"]["filter"]["seller_id"] == "seller-03"
        ):
            item["status"] = "error"
            item["data"] = {}

    report = build_tiktok_bra_competitor_shop_report_data(payload(results))

    assert report["status"] == "degraded"
    assert [row["seller_id"] for row in report["shop_comparison"]] == [
        f"seller-{index:02d}" for index in range(1, 11)
    ]
    shop = report["shop_comparison"][2]
    assert shop["base_snapshot"] == {}
    assert shop["data_gaps"] == ["shop_base_info 未成功返回数据。"]


def test_renderer_receives_only_compiled_competitor_data(monkeypatch) -> None:
    report = build_tiktok_bra_competitor_shop_report_data(payload(completed_tool_results()))
    captured: dict[str, Any] = {}

    def fake_chat(messages: list[dict[str, Any]], **_kwargs: Any) -> dict[str, Any]:
        captured["messages"] = messages
        return {
            "provider": "test",
            "model": "test",
            "usage": {"total_tokens": 10},
            "finish_reason": "stop",
            "message": {
                "content": (
                    "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
                    "<title>竞品店铺分析</title><style>body{font-family:sans-serif}</style>"
                    "</head><body><main><h1>竞品店铺分析</h1>"
                    + "<p>基于结构化店铺数据生成的测试报告内容。</p>" * 30
                    + "</main></body></html>"
                )
            },
        }

    monkeypatch.setattr("insight_agent.server.call_openai_compatible_chat", fake_chat)
    html, _, analysis = compose_html_report_with_llm(
        {
            "skillId": "tiktok_us_bra_competitor_shop_analysis",
            "category": "女士文胸",
            "marketplace": "US",
            "generatedAt": "2026-07-22T08:00:00+00:00",
            "prompt": "生成竞品店铺分析",
            "tiktokCompetitorShopReportData": report,
            "toolResults": [{"name": "must_not_reach_renderer"}],
            "skillMarkdown": "## Output Rules\n- reader first",
        }
    )

    assert html.startswith("<!doctype html>")
    assert analysis["status"] == "ok"
    assert analysis["input_profile"]["tool_results_chars"] == 2
    assert analysis["input_profile"]["tiktok_competitor_shop_report_chars"] > 0
    request = json.loads(captured["messages"][1]["content"])
    assert request["report_data_schema"] == "tiktok_bra_competitor_shop_report_data.v1"
    assert request["tiktok_competitor_shop_report_data"]["summary"]["candidate_count"] == 50
    assert "tool_results" not in request
    assert "whole-shop" in captured["messages"][0]["content"]


def native_tool_call(call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def native_chat_response(tool_call: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": "test",
        "model": "test",
        "usage": {"total_tokens": 10},
        "finish_reason": "tool_calls",
        "message": {"role": "assistant", "content": "", "tool_calls": [tool_call]},
    }


def passthrough_fastmoss_input(
    _tool_name: str,
    _category: str,
    payload: dict[str, Any],
    *,
    tool_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        key: copy.deepcopy(payload[key])
        for key in ("query", "filter", "page", "pagesize", "orderby")
        if key in payload
    }


def test_runtime_forces_competitor_builder_before_renderer(monkeypatch) -> None:
    fastmoss_tools = (
        "search_category_by_words",
        "fastmoss_detail_url_examples",
        "shop_rank_top_selling",
        "shop_base_info",
        "shop_product_analysis",
        "shop_sale_analysis",
        "shop_data_trends",
        "shop_creator_analysis",
    )
    monkeypatch.setattr(
        server_module,
        "get_fastmoss_tool_catalog",
        lambda: {
            f"mcp__fastmoss__{name}": {
                "label": f"FastMoss: {name}",
                "description": f"Mock FastMoss {name}",
                "source": "fastmoss_mcp",
            }
            for name in fastmoss_tools
        },
    )
    monkeypatch.setattr(
        server_module, "build_fastmoss_input_payload", passthrough_fastmoss_input
    )
    seller_ids = [f"seller-{index:02d}" for index in range(1, 11)]
    shop_tool_names = (
        "mcp__fastmoss__shop_base_info",
        "mcp__fastmoss__shop_product_analysis",
        "mcp__fastmoss__shop_sale_analysis",
        "mcp__fastmoss__shop_data_trends",
        "mcp__fastmoss__shop_creator_analysis",
    )
    calls = [
        native_tool_call(
            "load",
            "load_skill",
            {
                "skill_id": "tiktok_us_bra_competitor_shop_analysis",
                "extracted_params": {
                    "brand": "Hsia",
                    "marketplace": "US",
                    "category": "女士文胸",
                    "time_range": "28d",
                    "shop_candidate_size": 50,
                    "shop_analysis_count": 10,
                    "new_product_window": "30d",
                },
            },
        ),
        native_tool_call("category", "mcp__fastmoss__search_category_by_words", {}),
        native_tool_call("urls", "mcp__fastmoss__fastmoss_detail_url_examples", {}),
        *[
            native_tool_call(
                f"ranking-{page}",
                "mcp__fastmoss__shop_rank_top_selling",
                {
                    "page": page,
                    "pagesize": 10,
                    "filter": {
                        "region": "US",
                        "category_id": 601262,
                        "date_type": "month",
                        "date_value": "2026-06",
                    },
                    "orderby": [{"field": "usd_gmv", "order": "desc"}],
                },
            )
            for page in range(1, 6)
        ],
        *[
            native_tool_call(
                f"{tool_name.rsplit('__', 1)[-1]}-{seller_id}",
                tool_name,
                {
                    "filter": {
                        "seller_id": seller_id,
                        **(
                            {}
                            if tool_name == "mcp__fastmoss__shop_product_analysis"
                            else {"time_range_days": 28}
                            if tool_name != "mcp__fastmoss__shop_base_info"
                            else {}
                        ),
                    },
                    **(
                        {
                            "page": 1,
                            "pagesize": 10,
                            "orderby": [{"field": "day28_gmv", "order": "desc"}],
                        }
                        if tool_name == "mcp__fastmoss__shop_product_analysis"
                        else {}
                    ),
                },
            )
            for tool_name in shop_tool_names
            for seller_id in seller_ids
        ],
    ]
    chat_responses = [
        *[native_chat_response(call) for call in calls],
        {
            "provider": "test",
            "model": "test",
            "usage": {"total_tokens": 10},
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": ""},
        },
    ]
    observed_payloads: dict[str, dict[str, Any]] = {}

    def fake_chat(messages, tools=None, tool_choice=None):
        return chat_responses.pop(0)

    def fake_execute(tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
        observed_payloads[tool_name] = payload
        data: dict[str, Any] = {}
        if tool_name == "mcp__fastmoss__search_category_by_words":
            data = {
                "categories": [
                    {
                        "category_id_level3": 601262,
                        "cn_name": "女士文胸",
                        "cn_full_name": "女装与女士内衣-女士内衣-女士文胸",
                    }
                ]
            }
        elif tool_name == "mcp__fastmoss__shop_rank_top_selling":
            page = int(payload.get("page") or 1)
            data = {
                "list": [ranking_row((page - 1) * 10 + index) for index in range(1, 11)],
                "total": 50,
            }
        elif tool_name == "build_tiktok_bra_competitor_shop_report_data":
            data = {
                "schema_version": "tiktok_bra_competitor_shop_report_data.v1",
                "title": "TikTok Shop 美国文胸竞品店铺分析",
                "summary": {"candidate_count": 50, "analyzed_shop_count": 10},
                "candidate_shops": [],
                "shop_comparison": [],
                "data_gaps": [],
            }
        elif tool_name == "render_html_report":
            data = {
                "format": "html",
                "title": "TikTok Shop 美国文胸竞品店铺分析",
                "html": (
                    "<!doctype html><html><head><style>body{font-family:sans-serif}</style>"
                    "</head><body><main><h1>竞品店铺分析</h1></main></body></html>"
                ),
                "artifact": {
                    "title": "TikTok Shop 美国文胸竞品店铺分析",
                    "executive_summary": "compiled first",
                    "key_findings": [],
                    "opportunities": [],
                    "risks": [],
                    "next_steps": [],
                },
                "renderer": "llm-html",
                "html_analysis": {"status": "ok", "provider": "test", "model": "test"},
            }
        return {
            "name": tool_name,
            "label": server_module.agent_tool_catalog()[tool_name]["label"],
            "status": "ok",
            "summary": f"{tool_name} completed",
            "duration_ms": 1,
            "input": payload,
            "data": data,
        }

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_execute)
    monkeypatch.setattr(
        server_module,
        "synthesize_report_insights_node",
        lambda payload: {
            "schema_version": "report_insight_narrative.v1",
            "status": "empty_supported_insights",
            "sections": [],
            "section_count": 0,
            "insight_count": 0,
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
            "summary": "通用报告审批通过。",
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
            "findings": [],
            "issues": [],
            "duration_ms": 1,
        },
    )

    result = server_module.run_agent(
        {
            "prompt": "生成 TikTok Shop 美国文胸竞品店铺分析报告。",
            "agentMode": "competitor",
            "category": "女士文胸",
            "skillId": "tiktok_us_bra_competitor_shop_analysis",
            "useLlm": True,
        }
    )

    tool_names = [item["name"] for item in result["tools"]]
    assert tool_names[-8:] == [
        "build_tiktok_bra_competitor_shop_report_data",
        "analyze_market_report",
        "synthesize_report_insights",
        "render_report_charts",
        "render_html_report",
        "review_html_report",
        "red_team_html_report",
        "join_report_approval",
    ]
    builder_payload = observed_payloads["build_tiktok_bra_competitor_shop_report_data"]
    assert len(builder_payload["toolResults"]) == 57, [
        event.get("summary") or event.get("message")
        for event in result.get("events", [])
        if event.get("status") == "skipped"
    ]
    renderer_payload = observed_payloads["render_html_report"]
    assert renderer_payload["toolResults"] == []
    assert renderer_payload["marketReportData"] == {}
    assert renderer_payload["tiktokNewProductReportData"] == {}
    assert renderer_payload["tiktokCompetitorShopReportData"]["schema_version"] == (
        "tiktok_bra_competitor_shop_report_data.v1"
    )
    assert result["status"] == "ok"


def test_runtime_pauses_on_fastmoss_user_action_and_resumes_from_checkpoint(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        server_module,
        "get_fastmoss_tool_catalog",
        lambda: {
            "mcp__fastmoss__search_category_by_words": {
                "label": "FastMoss category search",
                "description": "Mock category search",
                "source": "fastmoss_mcp",
            },
            "mcp__fastmoss__fastmoss_detail_url_examples": {
                "label": "FastMoss URL templates",
                "description": "Mock URL templates",
                "source": "fastmoss_mcp",
            },
        },
    )
    monkeypatch.setattr(
        server_module, "build_fastmoss_input_payload", passthrough_fastmoss_input
    )
    responses = [
        native_chat_response(
            native_tool_call(
                "load-1",
                "load_skill",
                {
                    "skill_id": "tiktok_us_bra_competitor_shop_analysis",
                    "extracted_params": {},
                },
            )
        ),
        native_chat_response(
            native_tool_call(
                "url-1", "mcp__fastmoss__fastmoss_detail_url_examples", {}
            )
        ),
        native_chat_response(
            native_tool_call(
                "category-1", "mcp__fastmoss__search_category_by_words", {}
            )
        ),
        native_chat_response(
            native_tool_call(
                "load-2",
                "load_skill",
                {
                    "skill_id": "tiktok_us_bra_competitor_shop_analysis",
                    "extracted_params": {},
                },
            )
        ),
        native_chat_response(
            native_tool_call(
                "url-2", "mcp__fastmoss__fastmoss_detail_url_examples", {}
            )
        ),
        native_chat_response(
            native_tool_call(
                "respond-2",
                "respond_to_user",
                {"message": "断点结果已恢复，继续执行时不会重复请求已完成工具。"},
            )
        ),
    ]
    remote_calls: list[str] = []

    def fake_chat(messages, tools=None, tool_choice=None):  # noqa: ARG001
        return responses.pop(0)

    def fake_execute(tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
        remote_calls.append(tool_name)
        tool_input = server_module.agent_tool_input_payload(tool_name, category, payload)
        if tool_name == "mcp__fastmoss__search_category_by_words":
            return {
                "name": tool_name,
                "label": "FastMoss category search",
                "status": "needs_user_action",
                "summary": "FastMoss credits are exhausted; recharge before continuing.",
                "duration_ms": 1,
                "input": tool_input,
                "data": {},
            }
        return {
            "name": tool_name,
            "label": "FastMoss URL templates",
            "status": "ok",
            "summary": "URL templates returned.",
            "duration_ms": 1,
            "input": tool_input,
            "data": {
                "detail_pages": {
                    "shop": {"template": "https://www.fastmoss.com/shop/{seller_id}"}
                }
            },
        }

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_execute)

    pending = server_module.run_agent(
        {
            "runId": "abc123def456",
            "prompt": "生成美国文胸竞品店铺报告。",
            "skillId": "tiktok_us_bra_competitor_shop_analysis",
            "category": "女士文胸",
            "useLlm": True,
        }
    )
    continued = server_module.run_agent(
        {
            "runId": "def456abc123",
            "continueRunId": pending["run_id"],
            "prompt": "已完成充值，继续。",
            "skillId": "tiktok_us_bra_competitor_shop_analysis",
            "useLlm": True,
        }
    )

    assert pending["status"] == "needs_input"
    assert pending["pending"]["reason_type"] == "external_action"
    assert pending["pending"]["resume_supported"] is True
    assert pending["pending"]["completed_tool_count"] == 1
    assert pending["pending"]["blocked_tool"] == (
        "mcp__fastmoss__search_category_by_words"
    )
    assert continued["status"] == "ok"
    assert len(continued["tools"]) == 2
    assert remote_calls.count("mcp__fastmoss__fastmoss_detail_url_examples") == 1
    assert not any(event.get("type") == "skill" for event in continued["events"])
    assert any(
        event.get("data", {}).get("outcome") == "checkpoint_reuse"
        for event in continued["events"]
    )

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest

import insight_agent.server as server_module
from insight_agent.fastmoss_new_product_report import build_tiktok_new_product_report_data
from insight_agent.server import AGENT_TOOL_CATALOG, compose_html_report_with_llm


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


def ranking_row(
    product_id: str,
    units: int,
    *,
    title: str,
    launch_date: str,
    price: float,
    l3_name: str = "Bras",
    l3_id: int = 601262,
) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "title": title,
        "region": "US",
        "currency_code": "USD",
        "current_price": price,
        "price_display": f"${price:.2f}",
        "launch_date": launch_date,
        "first_3d_units_sold": max(1, units // 4),
        "first_3d_gmv": round(price * max(1, units // 4), 2),
        "total_units_sold": units,
        "lifetime_gmv": round(price * units, 2),
        "cover_url": f"https://img.example/{product_id}.webp",
        "is_off_shelf": False,
        "category": {
            "l1": {"id": 2, "name": "Womenswear & Underwear"},
            "l2": {"id": 842888, "name": "Women's Underwear"},
            "l3": {"id": l3_id, "name": l3_name},
        },
        "shop": {"shop_id": f"shop-{product_id}", "shop_name": f"Shop {product_id}"},
    }


def daily_trend(*, p7_units: int, l7_units: int) -> list[dict[str, Any]]:
    start = dt.date(2026, 7, 1)
    rows: list[dict[str, Any]] = []
    for offset in range(19):
        day = start + dt.timedelta(days=offset)
        if day < dt.date(2026, 7, 6):
            units = 0
        elif day <= dt.date(2026, 7, 12):
            units = p7_units
        else:
            units = l7_units
        rows.append(
            {
                "date": day.isoformat(),
                "daily_units_sold": units,
                "daily_gmv": units * 20,
            }
        )
    return rows


def completed_tool_results() -> list[dict[str, Any]]:
    ranking_filter = {
        "region": "US",
        "category_l3_id": 601262,
        "listing_start_date": "2026-06-18",
        "listing_end_date": "2026-07-17",
    }
    product_a = ranking_row(
        "A",
        300,
        title="3PC seamless wireless bra with wide straps and full coverage",
        launch_date="2026-07-10",
        price=29.99,
    )
    product_b = ranking_row(
        "B",
        200,
        title="Plus-size minimizer bra with adjustable straps",
        launch_date="2026-07-12",
        price=39.99,
    )
    product_c = ranking_row(
        "C",
        1000,
        title="Tummy control shapewear bodysuit",
        launch_date="2026-07-08",
        price=59.99,
        l3_name="Shapewear",
        l3_id=601277,
    )
    duplicate_a = {**product_a, "total_units_sold": 250}
    return [
        tool(
            "mcp__fastmoss__search_category_by_words",
            {
                "result": {
                    "categories": [
                        {
                            "category_id_level1": 2,
                            "category_id_level2": 842888,
                            "category_id_level3": 601262,
                            "cn_name": "女士文胸",
                            "cn_full_name": "女装与女士内衣-女士内衣-女士文胸",
                            "matched_query": "女士文胸",
                            "score": 0.9,
                        }
                    ]
                }
            },
            tool_input={"query": ["women's bras", "bras", "女士文胸"]},
        ),
        tool(
            "mcp__fastmoss__fastmoss_detail_url_examples",
            {
                "detail_pages": {
                    "product": {
                        "template": "https://www.fastmoss.com/e-commerce/detail/{product_id}"
                    }
                }
            },
        ),
        tool(
            "mcp__fastmoss__product_rank_new_listed",
            {"list": [product_b, product_a], "total": 3},
            tool_input={"page": 1, "filter": ranking_filter},
        ),
        tool(
            "mcp__fastmoss__product_rank_new_listed",
            {"list": [duplicate_a, product_c], "total": 3},
            tool_input={"page": 2, "filter": ranking_filter},
        ),
        tool(
            "mcp__fastmoss__product_detail_info",
            {
                "product": {
                    "title": product_a["title"],
                    "cover_url": product_a["cover_url"],
                    "product_rating": 4.8,
                    "review_count": 10,
                },
                "shop": {"shop_id": "shop-A", "shop_name": "Shop A"},
            },
            tool_input={"filter": {"product_id": "A"}},
        ),
        tool(
            "mcp__fastmoss__product_detail_info",
            {
                "product": {
                    "title": product_b["title"],
                    "cover_url": product_b["cover_url"],
                    "product_rating": 4.5,
                    "review_count": 5,
                },
                "shop": {"shop_id": "shop-B", "shop_name": "Shop B"},
            },
            tool_input={"filter": {"product_id": "B"}},
        ),
        tool(
            "mcp__fastmoss__product_sales_trend",
            {
                "region": "US",
                "currency_code": "USD",
                "daily_trend": daily_trend(p7_units=10, l7_units=20),
                "period_summary": {"period_units_sold": 210, "period_gmv": 4200},
            },
            tool_input={"filter": {"product_id": "A", "time_range_days": 28}},
        ),
        tool(
            "mcp__fastmoss__product_sales_trend",
            {
                "region": "US",
                "currency_code": "USD",
                "daily_trend": daily_trend(p7_units=0, l7_units=5),
                "period_summary": {"period_units_sold": 35, "period_gmv": 700},
            },
            tool_input={"filter": {"product_id": "B", "time_range_days": 28}},
        ),
    ]


def build_payload(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "skillId": "tiktok_us_lingerie_new_product_insight",
        "brand": "Hsia",
        "marketplace": "US",
        "category": "女士文胸",
        "timeRange": "28d",
        "newProductWindow": "30d",
        "listingSampleSize": 20,
        "headListingCount": 2,
        "generatedAt": "2026-07-20T08:00:00+00:00",
        "toolResults": tool_results,
    }


def test_builder_is_registered_and_compiles_stable_top_products() -> None:
    assert "build_tiktok_new_product_report_data" in AGENT_TOOL_CATALOG

    report = build_tiktok_new_product_report_data(build_payload(completed_tool_results()))

    assert report["schema_version"] == "tiktok_new_product_report_data.v1"
    assert report["status"] == "complete"
    assert [row["product_id"] for row in report["candidate_products"]] == ["A", "B"]
    assert [row["product_id"] for row in report["head_products"]] == ["A", "B"]
    assert report["title"] == "TikTok Shop 美国女士文胸新品洞察"
    assert report["category"] == "女士文胸"
    assert report["source_scope"]["pages_collected"] == [1, 2]
    assert report["source_scope"]["category_l3"] == {"id": 601262, "name": "Bras"}
    assert report["source_scope"]["qualifying_bra_count"] == 2
    assert report["source_scope"]["excluded_non_bra_count"] == 1
    assert report["source_scope"]["excluded_l3_categories"] == ["Shapewear"]
    assert report["source_scope"]["price_filter"] == {
        "currency_code": "USD",
        "minimum_inclusive": 20.0,
        "maximum_inclusive": 100.0,
    }
    assert report["category_resolution"]["selected_category_level"] == "L3"
    assert report["candidate_products"][0]["shop_name"] == "Shop A"
    assert report["candidate_products"][0]["shop_id"] == "shop-A"
    assert report["head_products"][0]["shop"] == {
        "shop_id": "shop-A",
        "shop_name": "Shop A",
        "total_units_sold": None,
    }
    required_fields = {
        item["field"]
        for item in report["output_contract"]["new_product_ranking_required_columns"]
    }
    assert {"shop_name", "shop_id"} <= required_fields
    assert report["head_products"][0]["fastmoss_url"].endswith("/A")
    assert report["head_products"][0]["detail"]["product_rating"] == 4.8
    labels = {item["label"] for item in report["head_products"][0]["feature_tags"]}
    assert {"文胸", "无缝", "无钢圈", "宽肩带", "全覆盖/侧收", "3 件装"} <= labels


def test_builder_filters_prices_before_counting_and_ranking_with_inclusive_bounds() -> None:
    results = completed_tool_results()
    ranking = next(
        item for item in results if item["name"] == "mcp__fastmoss__product_rank_new_listed"
    )
    under = ranking_row(
        "UNDER",
        5000,
        title="Low-price wireless bra",
        launch_date="2026-07-11",
        price=19.99,
    )
    over = ranking_row(
        "OVER",
        4000,
        title="Premium underwire bra",
        launch_date="2026-07-11",
        price=100.01,
    )
    missing = ranking_row(
        "MISSING",
        3000,
        title="Bra with missing price",
        launch_date="2026-07-11",
        price=50.0,
    )
    missing["current_price"] = None
    missing["price_display"] = None
    boundary_20 = ranking_row(
        "BOUNDARY20",
        50,
        title="Bra at lower price boundary",
        launch_date="2026-07-11",
        price=20.0,
    )
    boundary_100 = ranking_row(
        "BOUNDARY100",
        40,
        title="Bra at upper price boundary",
        launch_date="2026-07-11",
        price=100.0,
    )
    ranking["data"]["list"].extend([under, over, missing, boundary_20, boundary_100])
    ranking["data"]["total"] = 8

    report = build_tiktok_new_product_report_data(build_payload(results))

    product_ids = [row["product_id"] for row in report["candidate_products"]]
    assert product_ids == ["A", "B", "BOUNDARY20", "BOUNDARY100"]
    assert all(20 <= row["current_price"] <= 100 for row in report["candidate_products"])
    assert report["source_scope"]["excluded_price_count"] == 3
    assert report["source_scope"]["excluded_under_price_count"] == 1
    assert report["source_scope"]["excluded_over_price_count"] == 1
    assert report["source_scope"]["excluded_missing_price_count"] == 1
    assert report["summary"]["excluded_price_count"] == 3


def test_builder_hard_filters_non_bras_even_when_the_parent_ranking_leaks_them() -> None:
    results = completed_tool_results()
    for item in results:
        if item["name"] != "mcp__fastmoss__product_rank_new_listed":
            continue
        filters = item["input"]["filter"]
        filters.pop("category_l3_id", None)
        filters["category_l2_id"] = 842888

    report = build_tiktok_new_product_report_data(build_payload(results))

    assert [row["product_id"] for row in report["candidate_products"]] == ["A", "B"]
    assert report["status"] == "degraded"
    assert report["source_scope"]["used_exact_l3_query"] is False
    assert any("category_l3_id=601262" in gap for gap in report["data_gaps"])


def test_builder_stops_when_no_l3_bra_products_remain_after_filtering() -> None:
    results = completed_tool_results()
    for item in results:
        if item["name"] != "mcp__fastmoss__product_rank_new_listed":
            continue
        item["data"]["list"] = [
            row for row in item["data"]["list"] if row.get("product_id") == "C"
        ]

    with pytest.raises(ValueError, match="confirmed as L3 Bras"):
        build_tiktok_new_product_report_data(build_payload(results))


def test_builder_uses_latest_complete_fourteen_days_for_l7_p7() -> None:
    report = build_tiktok_new_product_report_data(build_payload(completed_tool_results()))
    trend_a = report["head_products"][0]["trend"]
    trend_b = report["head_products"][1]["trend"]

    assert trend_a["p7_units_sold"] == 70
    assert trend_a["l7_units_sold"] == 140
    assert trend_a["l7_p7_ratio"] == 2.0
    assert trend_a["trend_label"] == "加速"
    assert trend_a["daily_trend"][-1]["date"] == "2026-07-19"
    assert trend_b["p7_units_sold"] == 0
    assert trend_b["l7_units_sold"] == 35
    assert trend_b["l7_p7_ratio"] is None
    assert trend_b["trend_label"] == "新启动"


def test_builder_requires_every_top_product_enrichment_attempt() -> None:
    results = [
        item
        for item in completed_tool_results()
        if not (
            item["name"] == "mcp__fastmoss__product_sales_trend"
            and item["input"]["filter"]["product_id"] == "B"
        )
    ]

    with pytest.raises(ValueError, match="trend=B"):
        build_tiktok_new_product_report_data(build_payload(results))


def test_builder_allows_failed_attempt_and_marks_only_that_product_degraded() -> None:
    results = completed_tool_results()
    for item in results:
        if (
            item["name"] == "mcp__fastmoss__product_sales_trend"
            and item["input"]["filter"]["product_id"] == "B"
        ):
            item["status"] = "error"
            item["data"] = {}

    report = build_tiktok_new_product_report_data(build_payload(results))

    assert report["status"] == "degraded"
    assert report["head_products"][0]["trend"]["trend_label"] == "加速"
    assert report["head_products"][1]["trend"]["trend_label"] == "趋势数据缺失"
    assert report["summary"]["trend_success_count"] == 1


def test_renderer_receives_compiled_data_instead_of_raw_tool_results(monkeypatch) -> None:
    report = build_tiktok_new_product_report_data(build_payload(completed_tool_results()))
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
                    "<title>新品洞察</title><style>body{font-family:sans-serif}</style>"
                    "</head><body><main><h1>新品洞察</h1>"
                    "<table><thead><tr><th>店铺名称</th><th>shop_id</th></tr></thead>"
                    "<tbody><tr><td>Shop A</td><td>shop-A</td></tr></tbody></table>"
                    + "<p>基于结构化新品数据生成的测试报告内容。</p>" * 30
                    + "</main></body></html>"
                )
            },
        }

    monkeypatch.setattr("insight_agent.server.call_openai_compatible_chat", fake_chat)
    html, _, analysis = compose_html_report_with_llm(
        {
            "skillId": "tiktok_us_lingerie_new_product_insight",
            "category": "女士文胸",
            "marketplace": "US",
            "generatedAt": "2026-07-20T08:00:00+00:00",
            "prompt": "生成新品洞察",
            "tiktokNewProductReportData": report,
            "toolResults": [{"name": "must_not_reach_renderer"}],
            "skillMarkdown": "## Output Rules\n- reader first",
        }
    )

    assert html.startswith("<!doctype html>")
    assert analysis["status"] == "ok"
    assert analysis["input_profile"]["tool_results_chars"] == 2
    assert analysis["input_profile"]["tiktok_new_product_report_chars"] > 0
    assert "Omit unavailable dimensions" in captured["messages"][0]["content"]
    assert "data-gap" in captured["messages"][0]["content"]
    request = json.loads(captured["messages"][1]["content"])
    assert request["report_data_schema"] == "tiktok_new_product_report_data.v1"
    assert request["tiktok_new_product_report_data"]["head_products"][0]["product_id"] == "A"
    assert "Shop Name and shop_id" in captured["messages"][0]["content"]
    assert "tool_results" not in request


def test_tiktok_renderer_validation_requires_shop_name_and_shop_id_headers() -> None:
    missing_shop = (
        "<!doctype html><html><head><style>body{font-family:sans-serif}</style></head>"
        "<body><table><tr><th>商品</th><th>累计销量</th></tr></table></body></html>"
    )
    complete = (
        "<!doctype html><html><head><style>body{font-family:sans-serif}</style></head>"
        "<body><table><tr><th>商品</th><th>店铺名称</th><th>shop_id</th></tr>"
        "</table></body></html>"
    )

    assert "Shop Name" in server_module.validate_tiktok_new_product_table_markup(
        missing_shop
    )
    assert server_module.validate_tiktok_new_product_table_markup(complete) == ""


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


def test_runtime_forces_builder_before_renderer_and_passes_only_compiled_data(
    monkeypatch,
) -> None:
    fastmoss_tools = (
        "search_category_by_words",
        "fastmoss_detail_url_examples",
        "product_rank_new_listed",
        "product_detail_info",
        "product_sales_trend",
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
    product_ids = ["A", "B", "C", "D", "E"]
    calls = [
        native_tool_call(
            "load",
            "load_skill",
            {
                "skill_id": "tiktok_us_lingerie_new_product_insight",
                "extracted_params": {
                    "brand": "Hsia",
                    "marketplace": "US",
                    "category": "女士文胸",
                    "time_range": "28d",
                    "listing_sample_size": 20,
                    "head_listing_count": 5,
                    "new_product_window": "30d",
                },
            },
        ),
        native_tool_call("category", "mcp__fastmoss__search_category_by_words", {}),
        native_tool_call("urls", "mcp__fastmoss__fastmoss_detail_url_examples", {}),
        native_tool_call("ranking", "mcp__fastmoss__product_rank_new_listed", {}),
        *[
            native_tool_call(
                f"detail-{product_id}",
                "mcp__fastmoss__product_detail_info",
                {"filter": {"product_id": product_id}},
            )
            for product_id in product_ids
        ],
        *[
            native_tool_call(
                f"trend-{product_id}",
                "mcp__fastmoss__product_sales_trend",
                {"filter": {"product_id": product_id, "time_range_days": 28}},
            )
            for product_id in product_ids
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
        if tool_name == "build_tiktok_new_product_report_data":
            data = {
                "schema_version": "tiktok_new_product_report_data.v1",
                "title": "TikTok Shop 美国女士文胸新品洞察",
                "summary": {
                    "candidate_count": 20,
                    "head_product_count": 5,
                    "detail_success_count": 5,
                    "trend_success_count": 5,
                },
                "candidate_products": [],
                "head_products": [],
                "data_gaps": [],
            }
        elif tool_name == "render_html_report":
            data = {
                "format": "html",
                "title": "TikTok Shop 美国女士文胸新品洞察",
                "html": (
                    "<!doctype html><html><head><style>body{font-family:sans-serif}</style>"
                    "</head><body><main><h1>新品洞察</h1></main></body></html>"
                ),
                "artifact": {
                    "title": "TikTok Shop 美国女士文胸新品洞察",
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
            "prompt": "生成 TikTok Shop 美国女士文胸新品洞察报告。",
            "agentMode": "market",
            "category": "女士文胸",
            "useLlm": True,
        }
    )

    tool_names = [item["name"] for item in result["tools"]]
    assert tool_names[-8:] == [
        "build_tiktok_new_product_report_data",
        "analyze_market_report",
        "synthesize_report_insights",
        "render_report_charts",
        "render_html_report",
        "review_html_report",
        "red_team_html_report",
        "join_report_approval",
    ]
    builder_payload = observed_payloads["build_tiktok_new_product_report_data"]
    assert len(builder_payload["toolResults"]) == 13
    renderer_payload = observed_payloads["render_html_report"]
    assert renderer_payload["toolResults"] == []
    assert renderer_payload["marketReportData"] == {}
    assert renderer_payload["tiktokNewProductReportData"]["schema_version"] == (
        "tiktok_new_product_report_data.v1"
    )
    assert result["status"] == "ok"

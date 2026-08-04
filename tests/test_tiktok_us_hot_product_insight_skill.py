from pathlib import Path

from insight_agent.report_metric_analysis import available_metric_catalog_for_skill
from insight_agent.server import (
    HTML_REPORT_DATA_BUILDERS,
    build_market_report_data,
    load_agent_skill_registry,
    market_report_llm_context,
)

SKILL_ID = "tiktok_us_hot_product_insight"


def test_hot_product_skill_loads_with_canonical_inputs() -> None:
    skill = load_agent_skill_registry()[SKILL_ID]
    markdown = skill["markdown"]
    required_sections = (
        "## What It Does",
        "## When To Use",
        "## Required Inputs",
        "## Optional Defaults",
        "## Missing Params",
        "## Tool Policy",
        "## Recommended Tool Use",
        "## Evidence Contract",
        "## Output Rules",
    )

    assert [markdown.index(section) for section in required_sections] == sorted(
        markdown.index(section) for section in required_sections
    )
    assert skill["input_schema"]["required"] == ["category"]
    assert skill["input_schema"]["defaults"]["marketplace"] == "US"
    assert skill["input_schema"]["defaults"]["time_range"] == "28d"
    assert skill["input_schema"]["defaults"]["review_sample_size"] == 30


def test_hot_product_skill_requires_comments_and_content_momentum() -> None:
    skill = load_agent_skill_registry()[SKILL_ID]
    policy = {item["tool"]: item for item in skill["tool_policy"]}
    evidence = {item["evidence_id"]: item for item in skill["evidence_contract"]}

    for tool in (
        "mcp__fastmoss__product_overview",
        "mcp__fastmoss__product_sales_trend",
        "mcp__fastmoss__product_creator_analysis",
        "mcp__fastmoss__product_video_list",
        "mcp__fastmoss__product_review_list",
    ):
        assert policy[tool]["policy"] == "required"

    assert evidence["fastmoss_product_reviews"]["min_success"] == "param:head_listing_count"
    assert evidence["fastmoss_product_reviews"]["severity"] == "block"
    assert "评论分析是主链路，不是可选附录" in skill["markdown"]
    assert "达人和视频增量是领先信号，GMV 与销量是滞后结果" in skill["markdown"]
    assert "同一评论重复出现、同一文本变体或词频不得重复计数" in skill["markdown"]


def test_hot_product_skill_uses_registered_html_builder_and_metric_profile() -> None:
    skill = load_agent_skill_registry()[SKILL_ID]
    policy = {item["tool"]: item for item in skill["tool_policy"]}
    evidence = {item["evidence_id"]: item for item in skill["evidence_contract"]}
    metric_ids = {item["metric_id"] for item in available_metric_catalog_for_skill(SKILL_ID)}

    assert "build_market_report_data" in HTML_REPORT_DATA_BUILDERS
    assert policy["build_market_report_data"]["policy"] == "required"
    assert policy["render_html_report"]["policy"] == "required"
    assert evidence["hot_product_report_data"]["if_missing"] == "call_missing_tool"
    assert evidence["final_html_report"]["if_missing"] == "call_missing_tool"
    assert {"period_growth_rate", "gmv_per_video", "content_lead_gap"} <= metric_ids
    assert (
        "Planner 不调用 builder、`data_analysis`、`insight_synthesis`、`chart_render`、"
        "renderer、`report_review`、`report_red_team`、`approval_join`、`html_revision` "
        "或 `synthesize_artifact`"
    ) in skill["markdown"]


def test_hot_product_builder_uses_ranked_products_and_bounds_review_evidence() -> None:
    def tool(name: str, *, tool_input: dict, data: dict) -> dict:
        return {
            "name": f"mcp__fastmoss__{name}",
            "status": "ok",
            "summary": f"{name} result",
            "input": tool_input,
            "data": data,
        }

    report = build_market_report_data(
        {
            "skillId": SKILL_ID,
            "brand": "Hsia",
            "category": "sports bra",
            "generatedAt": "2026-07-15T06:00:00+00:00",
            "listingSampleSize": 1,
            "headListingCount": 1,
            "reviewSampleSize": 2,
            "toolResults": [
                tool(
                    "product_rank_top_selling",
                    tool_input={
                        "filter": {
                            "region": "US",
                            "category_id": 123,
                            "date_type": "month",
                            "date_value": "2026-06",
                        }
                    },
                    data={
                        "list": [
                            {
                                "product_id": "p1",
                                "title": "Support Sports Bra",
                                "period_gmv": 12000,
                                "period_units_sold": 400,
                            }
                        ]
                    },
                ),
                tool(
                    "product_review_list",
                    tool_input={"filter": {"region": "US", "product_id": "p1"}},
                    data={
                        "list": [
                            {
                                "review_id": "r1",
                                "rating": 2,
                                "content": "Band rolls after washing.",
                            },
                            {
                                "review_id": "r1",
                                "rating": 2,
                                "content": "Duplicate row.",
                            },
                            {
                                "review_id": "r2",
                                "rating": 5,
                                "content": "Supportive for workouts.",
                            },
                            {
                                "review_id": "r3",
                                "rating": 4,
                                "content": "Comfortable straps.",
                            },
                        ]
                    },
                ),
            ],
        }
    )

    assert report["title"] == "Hsia TikTok Shop US sports bra 爆款洞察报告"
    assert report["research_boundary"]["segment_type"] == "category_ranked_hot_product_sample"
    assert [row["product_id"] for row in report["fastmoss_segment_products"]] == ["p1"]
    review_block = report["fastmoss_product_reviews"][0]
    assert review_block["product_id"] == "p1"
    assert review_block["sample_size"] == 2
    assert [row["review_id"] for row in review_block["reviews"]] == ["r1", "r2"]
    assert report["review_pain_points"] == report["fastmoss_product_reviews"]


def test_hot_product_builder_reads_fastmoss_review_text_and_sku_variant_fields() -> None:
    def tool(name: str, *, tool_input: dict, data: dict) -> dict:
        return {
            "name": f"mcp__fastmoss__{name}",
            "status": "ok",
            "summary": f"{name} result",
            "input": tool_input,
            "data": data,
        }

    report = build_market_report_data(
        {
            "skillId": SKILL_ID,
            "brand": "Hsia",
            "category": "sports bra",
            "reviewSampleSize": 2,
            "toolResults": [
                tool(
                    "product_rank_top_selling",
                    tool_input={"filter": {"region": "US", "category_id": 123}},
                    data={"list": [{"product_id": "p1", "title": "Support Sports Bra"}]},
                ),
                tool(
                    "product_review_list",
                    tool_input={
                        "page": 1,
                        "filter": {
                            "region": "US",
                            "product_id": "p1",
                            "time_range_days": 90,
                        },
                    },
                    data={
                        "reviews": [
                            {
                                "review_id": "r1",
                                "rating": 5,
                                "review_text": "Very comfortable soft fabric.",
                                "sku_variant_text": "Black, M",
                                "like_count": 0,
                            },
                            {
                                "review_id": "r2",
                                "rating": 2,
                                "review_text": "Band rolls after washing.",
                                "sku_variant_text": "Blue, L",
                            },
                        ],
                        "total_review_count": 450,
                    },
                ),
            ],
        }
    )

    reviews = report["fastmoss_product_reviews"][0]["reviews"]
    assert [row["content"] for row in reviews] == [
        "Very comfortable soft fabric.",
        "Band rolls after washing.",
    ]
    assert [row["sku"] for row in reviews] == ["Black, M", "Blue, L"]
    assert reviews[0]["like_count"] == 0
    assert reviews[0]["source_page"] == 1
    assert reviews[0]["time_range_days"] == 90


def test_hot_product_builder_merges_review_pages_and_preserves_voc_context() -> None:
    def tool(*, page: int, rows: list[dict]) -> dict:
        return {
            "name": "mcp__fastmoss__product_review_list",
            "status": "ok",
            "summary": "review result",
            "input": {"page": page, "filter": {"region": "US", "product_id": "p1"}},
            "data": {"reviews": rows, "total_review_count": 450},
        }

    report = build_market_report_data(
        {
            "skillId": SKILL_ID,
            "category": "sports bra",
            "reviewSampleSize": 3,
            "toolResults": [
                {
                    "name": "mcp__fastmoss__product_rank_top_selling",
                    "status": "ok",
                    "summary": "ranking result",
                    "input": {"filter": {"region": "US", "category_id": 123}},
                    "data": {"list": [{"product_id": "p1", "title": "Support Sports Bra"}]},
                },
                tool(
                    page=1,
                    rows=[
                        {"review_id": "r1", "rating": 5, "review_text": "Soft fabric."},
                        {"review_id": "r2", "rating": 5, "review_text": ""},
                    ],
                ),
                tool(
                    page=2,
                    rows=[
                        {"review_id": "r1", "rating": 5, "review_text": "Duplicate."},
                        {"review_id": "r3", "rating": 2, "review_text": "Band rolls."},
                        {"review_id": "r3-copy", "rating": 2, "review_text": " band  ROLLS. "},
                        {"review_id": "r4", "rating": 4, "review_text": "Beyond limit."},
                    ],
                ),
            ],
        }
    )

    review_block = report["fastmoss_product_reviews"][0]
    assert review_block["sample_size"] == 3
    assert review_block["text_sample_size"] == 2
    assert review_block["rating_only_sample_size"] == 1
    assert review_block["total_review_count"] == 450
    assert [row["review_id"] for row in review_block["reviews"]] == ["r1", "r2", "r3"]

    context_reviews = market_report_llm_context(report)["fastmoss_product_reviews"][0][
        "reviews"
    ]
    assert [row["review_id"] for row in context_reviews] == ["r1", "r2", "r3"]
    assert context_reviews[0]["content"] == "Soft fabric."
    assert context_reviews[2]["content"] == "Band rolls."


def test_hot_product_skill_is_available_in_frontend_picker() -> None:
    app_source = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    i18n_source = Path("frontend/src/lib/i18n.ts").read_text(encoding="utf-8")

    assert '| "tiktok_us_hot_product_insight"' in app_source
    assert 'id: "tiktok_us_hot_product_insight"' in app_source
    assert 'value === "tiktok_us_hot_product_insight"' in app_source
    assert "使用 tiktok_us_hot_product_insight Skill" in i18n_source
    assert "必须包含评论分析" in i18n_source

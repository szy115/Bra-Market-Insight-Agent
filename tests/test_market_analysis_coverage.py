from insight_agent.market_analysis_coverage import (
    build_market_dimension_results,
    build_tool_methodology,
    evaluate_market_analysis_coverage,
)

P0_TOOL_NAMES = (
    "sellersprite_product_node",
    "sif_market_get_keyword_root_trend",
    "sellersprite_market_research",
    "sellersprite_market_research_statistics",
    "sif_market_get_keyword_history",
    "sellersprite_keyword_research",
    "sif_market_get_keyword_demand",
    "sellersprite_keyword_research_trends",
    "sellersprite_google_trend",
    "sellersprite_aba_research_weekly",
    "sif_market_get_keyword_competition",
    "sellersprite_market_product_demand_trend",
    "sellersprite_market_product_concentration",
    "sellersprite_market_brand_concentration",
    "sellersprite_market_seller_concentration",
    "sellersprite_market_price_distribution",
    "sellersprite_market_rating_distribution",
    "sellersprite_market_ratings_count_distribution",
    "sellersprite_market_listing_date_distribution",
    "sellersprite_market_listing_trend_distribution",
)


def test_market_analysis_coverage_maps_successful_tools_to_all_p0_questions() -> None:
    coverage = evaluate_market_analysis_coverage(
        [
            {"name": tool_name, "status": "ok", "data": {"value": index}}
            for index, tool_name in enumerate(P0_TOOL_NAMES, start=1)
        ]
    )

    assert coverage["summary"] == {
        "p0_total": 17,
        "p0_covered": 17,
        "p0_partial": 0,
        "p0_missing": 0,
        "p1_triggered": 0,
    }
    dimensions = {item["dimension_id"]: item for item in coverage["dimensions"]}
    assert dimensions["M02"]["used_tools"] == [
        "sellersprite_market_research",
        "sellersprite_market_research_statistics",
    ]
    assert dimensions["M17"]["status"] == "not_triggered"
    assert dimensions["M18"]["status"] == "not_triggered"
    assert dimensions["M19"]["status"] == "covered"
    assert dimensions["M19"]["used_tools"] == ["sellersprite_google_trend"]


def test_market_analysis_coverage_reports_partial_and_failed_evidence() -> None:
    coverage = evaluate_market_analysis_coverage(
        [
            {"name": "sellersprite_market_research", "status": "ok"},
            {"name": "sellersprite_market_research_statistics", "status": "error"},
        ]
    )

    dimensions = {item["dimension_id"]: item for item in coverage["dimensions"]}
    assert dimensions["M02"]["status"] == "partial"
    assert dimensions["M02"]["evidence_ids"] == ["E01"]
    assert dimensions["M02"]["missing_tool_groups"] == [["sellersprite_market_research_statistics"]]
    assert dimensions["M19"]["status"] == "missing"


def test_tool_methodology_is_explicitly_not_evidence() -> None:
    methodology = build_tool_methodology(
        [{"name": "sellersprite_keyword_research", "status": "ok"}],
        {"sellersprite_keyword_research": "Analyze search, purchase, competition, and cost fields."},
    )

    assert methodology[0]["role"] == "methodology_only"
    assert methodology[0]["analysis_dimensions"] == ["M04", "M07"]
    assert methodology[0]["mcp_description"].startswith("Analyze search")
    assert methodology[0]["limitations"]


def test_dimension_results_join_analysis_and_chart_contracts() -> None:
    coverage = evaluate_market_analysis_coverage(
        [{"name": "sellersprite_product_research", "status": "ok", "data": {"items": [{}]}}]
    )
    results = build_market_dimension_results(
        coverage,
        [
            {
                "dimension_id": "M17",
                "chart_id": None,
                "title": "样本范围与去重口径",
                "type": "sample_audit_table",
                "chart_status": "text_only",
                "reason": "Structured non-chart presentation compiled.",
                "evidence_ids": ["E01"],
            }
        ],
    )

    m17 = next(item for item in results if item["dimension_id"] == "M17")
    assert m17["analysis_status"] == "covered"
    assert m17["used_tools"] == ["sellersprite_product_research"]
    assert m17["chart"] == {
        "chart_id": None,
        "title": "样本范围与去重口径",
        "type": "sample_audit_table",
        "status": "text_only",
        "reason": "Structured non-chart presentation compiled.",
        "evidence_ids": ["E01"],
    }

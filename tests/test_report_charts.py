from insight_agent.market_analysis_coverage import evaluate_market_analysis_coverage
from insight_agent.report_charts import (
    build_market_report_charts,
    render_recovery_chart_figure,
    repair_missing_or_empty_chart_figures,
    replace_compiled_chart_figures,
)
from insight_agent.server import (
    validate_llm_html_document,
    weekly_market_report_quality,
    weekly_market_report_readiness_issues,
)

P0_AND_P1_TOOLS = (
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
    "sellersprite_product_research",
    "sellersprite_review",
)


def complete_dimension_report_data() -> dict:
    tool_results = [
        {"name": name, "status": "ok", "data": {"value": index}}
        for index, name in enumerate(P0_AND_P1_TOOLS, start=1)
    ]
    return {
        "category": "minimizer bra",
        "category_node_id": "3760901:1044960",
        "analysis_coverage": evaluate_market_analysis_coverage(tool_results),
        "keyword_trends": [
            {"keyword": "minimizer bra", "search_volume": 18000, "source": "Sif", "evidence_id": "E01"},
            {"keyword": "full coverage minimizer bra", "search_volume": 9000, "source": "Sif", "evidence_id": "E01"},
        ],
        "keyword_opportunities": [
            {
                "keywords": "minimizer bra",
                "searches": 18000,
                "purchaseRate": 0.12,
                "purchases": 2160,
                "searchRankGrowthRate": 0.08,
                "source": "SellerSprite",
                "evidence_id": "E06",
            },
            {
                "keywords": "large bust minimizer bra",
                "searches": 9000,
                "purchaseRate": 0.15,
                "purchases": 1350,
                "w1RankGrowthRate": -0.03,
                "source": "SellerSprite",
                "evidence_id": "E06",
            },
            {"date": "2026-03", "searches": 13000, "source": "SellerSprite", "evidence_id": "E08"},
            {"date": "2026-04", "searches": 14200, "source": "SellerSprite", "evidence_id": "E08"},
            {"date": "2026-05", "searches": 15800, "source": "SellerSprite", "evidence_id": "E08"},
            {"date": "2026-06", "searches": 18000, "source": "SellerSprite", "evidence_id": "E08"},
        ],
        "keyword_competition": [
            {"asin": "B000000001", "total_share": 0.32, "source": "Sif", "evidence_id": "E10"},
            {"asin": "B000000002", "total_share": 0.21, "source": "Sif", "evidence_id": "E10"},
        ],
        "demand_trend": [
            {"date": "2026-03", "glanceViews": 1000},
            {"date": "2026-04", "glanceViews": 1100},
            {"date": "2026-05", "glanceViews": 1200},
            {"date": "2026-06", "glanceViews": 1300},
        ],
        "external_demand_trend": [
            {"month": "2026-03", "value": 54, "source": "Google Trends", "evidence_id": "E09"},
            {"month": "2026-04", "value": 61, "source": "Google Trends", "evidence_id": "E09"},
            {"month": "2026-05", "value": 72, "source": "Google Trends", "evidence_id": "E09"},
            {"month": "2026-06", "value": 80, "source": "Google Trends", "evidence_id": "E09"},
        ],
        "node_demand_quality": [
            {
                "glanceViews": 1300,
                "asinCount": 420,
                "searchToPurchaseRatio": 8.36,
                "returnRatio": 15.91,
                "avgReturnRatio": 16.12,
                "source": "SellerSprite",
                "evidence_id": "E11",
            }
        ],
        "category_benchmark": [
            {"nodeLabelName": "Minimizers", "totalUnits": 120000, "avgPrice": 28.5, "source": "SellerSprite", "evidence_id": "E03"}
        ],
        "market_statistics": [
            {"totalUnits": 120000, "totalRevenue": 3420000, "avgPrice": 28.5, "newProductUnitsRatio": 0.18, "asinCount": 420, "source": "SellerSprite", "evidence_id": "E04"}
        ],
        "top_products": [
            {"asin": "B000000001", "totalUnits": 22000, "source": "SellerSprite", "evidence_id": "E12"},
            {"asin": "B000000002", "totalUnits": 16000, "source": "SellerSprite", "evidence_id": "E12"},
        ],
        "brand_competition": [
            {"brand": "Brand A", "unitsRatio": 0.35},
            {"brand": "Brand B", "unitsRatio": 0.25},
            {"brand": "Brand C", "unitsRatio": 0.15},
        ],
        "seller_competition": [
            {"seller": "Seller A", "unitsRatio": 0.30},
            {"seller": "Seller B", "unitsRatio": 0.20},
            {"seller": "Seller C", "unitsRatio": 0.10},
        ],
        "price_distribution": [
            {"label": "$20-30", "unitsRatio": 0.55},
            {"label": "$30-40", "unitsRatio": 0.45},
        ],
        "rating_distribution": [
            {"label": "4.5+", "unitsRatio": 0.60},
            {"label": "4.0-4.4", "unitsRatio": 0.40},
        ],
        "ratings_count_distribution": [
            {"label": "0-500", "unitsRatio": 0.30},
            {"label": "500+", "unitsRatio": 0.70},
        ],
        "listing_date_distribution": [
            {"label": "0-12 months", "unitsRatio": 0.25},
            {"label": "12+ months", "unitsRatio": 0.75},
        ],
        "listing_trend_distribution": [
            {"label": "2025-2026", "unitsRatio": 0.28},
            {"label": "Before 2025", "unitsRatio": 0.72},
        ],
        "product_universe": [
            {"asin": "B000000001", "source_tool": "sellersprite_product_research", "evidence_id": "E20"},
            {"asin": "B000000002", "source_tool": "sellersprite_competitor_lookup", "evidence_id": "E20"},
        ],
        "review_pain_points": [
            {"review_group": "low_star", "source": "SellerSprite", "evidence_id": "E21"},
            {"review_group": "high_star", "source": "SellerSprite", "evidence_id": "E21"},
        ],
    }


def first_batch_chart_report_data() -> dict:
    report_data = complete_dimension_report_data()
    report_data["node_demand_quality"][0]["avgSearchToPurchaseRatio"] = 9.56
    report_data["brand_competition"] = [
        {
            "brand": "Brand A",
            "totalUnitsRatio": 0.35,
            "totalRevenueRatio": 0.39,
            "source": "SellerSprite",
            "evidence_id": "E14",
        },
        {
            "brand": "Brand B",
            "totalUnitsRatio": 0.25,
            "totalRevenueRatio": 0.23,
            "source": "SellerSprite",
            "evidence_id": "E14",
        },
        {
            "brand": "Brand C",
            "totalUnitsRatio": 0.15,
            "totalRevenueRatio": 0.13,
            "source": "SellerSprite",
            "evidence_id": "E14",
        },
    ]
    report_data["product_universe"] = [
        {
            "family_id": f"family-{index:02d}",
            "representative_asin": f"B{index:09d}",
            "asin": f"B{index:09d}",
            "brand_norm": f"brand-{index % 5}",
            "price_normalized": 19.99 + index,
            "sales_value": 3000 - index * 55,
            "sales_metric": "total_units",
            "snapshot_month": "2026-06",
            "source": "SellerSprite",
            "source_tool": "sellersprite_market_product_concentration",
            "source_tools": ["sellersprite_market_product_concentration"],
            "evidence_id": "E13",
        }
        for index in range(24)
    ]
    return report_data


def test_each_market_dimension_has_a_valid_presentation_when_data_is_complete() -> None:
    report_data = complete_dimension_report_data()
    charts = build_market_report_charts(report_data)

    manifest = {item["dimension_id"]: item for item in charts["chart_manifest"]}
    assert len(manifest) == 19
    assert manifest["M01"]["chart_status"] == "text_only"
    assert manifest["M17"]["chart_status"] == "text_only"
    assert all(
        manifest[f"M{index:02d}"]["chart_status"] == "ready"
        for index in range(1, 20)
        if index not in {1, 17}
    )
    assert len(charts["summary_chart_ids"]) <= 5
    assert "bra_attribute_distribution" not in charts["summary_chart_ids"]
    assert len(charts["chart_specs"]) >= 17
    assert {
        item["dimension_id"] for item in charts["non_chart_presentations"]
    } == {"M01", "M17"}
    sample_audit = next(
        item
        for item in charts["non_chart_presentations"]
        if item["dimension_id"] == "M17"
    )
    assert sample_audit["content"]["source_count"] == 2
    assert sample_audit["content"]["cross_source_check_applicable"] is True
    assert sample_audit["content"]["cross_source_overlap_count"] == 0
    assert sample_audit["content"]["representativeness_claim_allowed"] is False
    assert all(
        chart["dimension_id"] not in {"M01", "M17"}
        for chart in charts["chart_specs"]
        if chart.get("dimension_id")
    )
    external_chart = next(item for item in charts["chart_specs"] if item["dimension_id"] == "M19")
    assert external_chart["id"] == "external_search_trend"
    assert external_chart["type"] == "line"
    assert [point["value"] for point in external_chart["data"]] == [54.0, 61.0, 72.0, 80.0]

    ready_report = {
        **report_data,
        "chart_specs": charts["chart_specs"],
        "chart_manifest": charts["chart_manifest"],
    }
    assert weekly_market_report_readiness_issues(ready_report) == []


def test_single_source_sample_audit_omits_cross_source_overlap() -> None:
    charts = build_market_report_charts(
        {
            "category": "minimizer bra",
            "marketplace": "Amazon US",
            "product_universe": [
                {
                    "asin": f"B{index:09d}",
                    "source_tool": "sellersprite_market_product_concentration",
                }
                for index in range(4)
            ],
        }
    )

    sample_audit = next(
        item
        for item in charts["non_chart_presentations"]
        if item["dimension_id"] == "M17"
    )
    assert sample_audit["content"]["source_count"] == 1
    assert sample_audit["content"]["cross_source_check_applicable"] is False
    assert sample_audit["content"]["cross_source_overlap_count"] is None
    assert sample_audit["content"]["representativeness_claim_allowed"] is False
    assert all(chart.get("dimension_id") != "M17" for chart in charts["chart_specs"])


def test_first_batch_market_charts_use_richer_flint_types_when_data_is_valid() -> None:
    charts = build_market_report_charts(first_batch_chart_report_data())
    specs_by_id = {item["id"]: item for item in charts["chart_specs"]}

    assert specs_by_id["node_demand_quality"]["type"] == "bullet"
    assert len(specs_by_id["node_demand_quality"]["data"]) == 2
    assert {
        item["label"]: item["status"]
        for item in specs_by_id["node_demand_quality"]["data"]
    } == {
        "转化率 ↑": "弱于同级",
        "退货率 ↓": "优于同级",
    }
    assert specs_by_id["top_product_signal"]["type"] == "bar_table"
    assert specs_by_id["brand_competition"]["type"] == "grouped_bar"
    assert {item["group"] for item in specs_by_id["brand_competition"]["data"]} == {
        "销量份额",
        "销售额份额",
    }
    scatter = specs_by_id["price_sales_positioning"]
    assert scatter["type"] == "scatter"
    assert scatter["field_semantics"] == {"x": "Price", "y": "Quantity"}
    assert scatter["sample_contract"]["valid_sample_size"] == 24
    assert scatter["placement"] == {
        "section_hint": "竞争格局与产品定位",
        "summary_eligible": False,
        "supplemental": True,
    }
    assert "price_sales_positioning" not in charts["summary_chart_ids"]


def test_price_sales_scatter_rejects_mixed_metric_or_period_samples() -> None:
    report_data = first_batch_chart_report_data()
    report_data["product_universe"][0]["sales_metric"] = "monthly_orders"

    charts = build_market_report_charts(report_data)

    assert "price_sales_positioning" not in {
        item["id"] for item in charts["chart_specs"]
    }

    report_data = first_batch_chart_report_data()
    report_data["product_universe"][0]["snapshot_month"] = "2026-05"
    charts = build_market_report_charts(report_data)

    assert "price_sales_positioning" not in {
        item["id"] for item in charts["chart_specs"]
    }


def test_first_batch_chart_fallbacks_render_deterministic_graphics() -> None:
    charts = build_market_report_charts(first_batch_chart_report_data())
    specs_by_id = {item["id"]: item for item in charts["chart_specs"]}

    for chart_id in (
        "node_demand_quality",
        "top_product_signal",
        "brand_competition",
        "price_sales_positioning",
    ):
        figure = render_recovery_chart_figure(specs_by_id[chart_id])
        assert f'data-chart-id="{chart_id}"' in figure
        assert 'data-chart-renderer="server-recovery"' in figure
        assert "<svg" in figure
        assert any(mark in figure for mark in ("<rect", "<circle"))


def test_missing_google_trend_blocks_m19_and_degrades_the_report() -> None:
    report_data = complete_dimension_report_data()
    report_data["analysis_coverage"] = evaluate_market_analysis_coverage(
        [
            {"name": name, "status": "ok", "data": {"value": index}}
            for index, name in enumerate(P0_AND_P1_TOOLS, start=1)
            if name != "sellersprite_google_trend"
        ]
    )
    report_data.pop("external_demand_trend")

    charts = build_market_report_charts(report_data)
    manifest = {item["dimension_id"]: item for item in charts["chart_manifest"]}
    quality = weekly_market_report_quality(
        {
            **report_data,
            "chart_specs": charts["chart_specs"],
            "chart_manifest": charts["chart_manifest"],
        }
    )

    assert manifest["M19"]["analysis_status"] == "missing"
    assert manifest["M19"]["chart_status"] == "blocked_by_evidence"
    assert quality["status"] == "degraded"
    assert any(item["dimension_id"] == "M19" for item in quality["unavailable_dimensions"])


def test_sellersprite_plural_keywords_field_builds_m04_and_m06_charts() -> None:
    charts = build_market_report_charts(complete_dimension_report_data())
    manifest = {item["dimension_id"]: item for item in charts["chart_manifest"]}
    specs = {item["dimension_id"]: item for item in charts["chart_specs"]}

    assert manifest["M04"]["chart_status"] == "ready"
    assert manifest["M06"]["chart_status"] == "ready"
    assert {point["label"] for point in specs["M04"]["data"]} == {
        "minimizer bra",
        "large bust minimizer bra",
    }


def test_duplicate_chart_labels_are_rejected_instead_of_silently_deduplicated() -> None:
    report_data = complete_dimension_report_data()
    report_data["top_products"] = [
        {"asin": "B000000001", "totalUnits": 22000},
        {"asin": "B000000001", "totalUnits": 16000},
    ]

    charts = build_market_report_charts(report_data)
    manifest = {item["dimension_id"]: item for item in charts["chart_manifest"]}

    assert manifest["M09"]["analysis_status"] == "covered"
    assert manifest["M09"]["chart_status"] == "missing_data"
    assert "M09" in weekly_market_report_readiness_issues(
        {
            **report_data,
            "chart_specs": charts["chart_specs"],
            "chart_manifest": charts["chart_manifest"],
        }
    )[0]


def test_readiness_rejects_manifest_chart_missing_from_actual_specs() -> None:
    report_data = complete_dimension_report_data()
    charts = build_market_report_charts(report_data)
    incomplete_specs = [chart for chart in charts["chart_specs"] if chart.get("dimension_id") != "M09"]

    issues = weekly_market_report_readiness_issues(
        {
            **report_data,
            "chart_specs": incomplete_specs,
            "chart_manifest": charts["chart_manifest"],
        }
    )

    assert issues == ["Covered analysis dimensions missing valid charts: M09"]

    quality = weekly_market_report_quality(
        {
            **report_data,
            "chart_specs": incomplete_specs,
            "chart_manifest": charts["chart_manifest"],
        }
    )
    assert quality["status"] == "degraded"
    assert quality["publishable"] is True
    assert [item["dimension_id"] for item in quality["unavailable_dimensions"]] == ["M09"]
    assert quality["unavailable_dimensions"][0]["chart_status"] == "missing_spec"
    assert quality["diagnostic_issues"] == ["Covered analysis dimensions missing valid charts: M09"]


def test_empty_metric_group_svg_is_repaired_without_rejecting_report() -> None:
    chart = {
        "id": "market_capacity",
        "title": "市场容量与成熟度",
        "type": "metric_group",
        "quality_status": "ready",
        "insight": "各容量指标保留自己的单位。",
        "source": "SellerSprite MCP · E06",
        "data": [
            {
                "label": "月销量",
                "value": 146474,
                "unit": "units",
                "value_format": "compact_integer",
                "evidence_id": "E06",
            },
            {
                "label": "月销售额",
                "value": 3669293.51,
                "unit": "$",
                "value_format": "currency",
                "evidence_id": "E06",
            },
        ],
    }
    html = (
        '<!doctype html><html><head><style>body{font-family:sans-serif}</style></head><body><main>'
        '<h1>市场报告</h1><p>这是一份已经完成正文、但模型意外留下空图表的市场洞察报告。</p>'
        '<figure class="chart-card" data-chart-id="market_capacity"><svg viewBox="0 0 100 100"></svg></figure>'
        '<p>其他章节和证据链保持有效，因此只应修复这一张图，而不是丢弃整份报告。</p>'
        '</main></body></html>'
    )

    repaired, repaired_ids = repair_missing_or_empty_chart_figures(html, [chart])

    assert repaired_ids == ["market_capacity"]
    assert 'data-chart-renderer="server-recovery"' in repaired
    assert "146.5K" in repaired
    assert "$3.7M" in repaired
    assert validate_llm_html_document(repaired, required_chart_ids=["market_capacity"]) == ""


def test_missing_chart_is_appended_and_populated_chart_is_not_replaced() -> None:
    chart = {
        "id": "price_band_distribution",
        "title": "价格带销量占比",
        "type": "bar",
        "quality_status": "ready",
        "value_format": "percent_1",
        "unit": "%",
        "data": [
            {"label": "$20-25", "value": 46.97},
            {"label": "$25-35", "value": 26.47},
        ],
    }
    html_without_chart = (
        '<!doctype html><html><head><style>body{font-family:sans-serif}</style></head><body>'
        '<main><h1>市场报告</h1><p>正文已经完成，但必需图表没有被模型输出。</p></main>'
        '</body></html>'
    )

    appended, appended_ids = repair_missing_or_empty_chart_figures(html_without_chart, [chart])

    assert appended_ids == ["price_band_distribution"]
    assert 'data-chart-recovery-section="true"' in appended
    assert validate_llm_html_document(appended, required_chart_ids=["price_band_distribution"]) == ""

    populated = (
        '<!doctype html><html><head><style>body{font-family:sans-serif}</style></head><body><main>'
        '<figure data-chart-id="price_band_distribution">'
        '<svg viewBox="0 0 100 100"><rect x="10" y="10" width="80" height="40"></rect></svg>'
        '</figure></main></body></html>'
    )
    unchanged, unchanged_ids = repair_missing_or_empty_chart_figures(populated, [chart])
    assert unchanged_ids == []
    assert unchanged == populated


def test_compiled_chart_replaces_duplicates_once_at_narrative_location(tmp_path) -> None:
    svg_path = tmp_path / "market-capacity.svg"
    svg_path.write_text(
        '<svg viewBox="0 0 100 60"><rect x="2" y="2" width="90" height="20"/></svg>',
        encoding="utf-8",
    )
    chart = {
        "id": "market_capacity",
        "title": "市场容量与成熟度",
        "type": "metric_group",
        "quality_status": "ready",
        "data": [{"label": "月销量", "value": 156701}],
    }
    html = (
        '<!doctype html><html><body><main>'
        '<section id="summary"><p>summary-before</p>'
        '<figure data-chart-id="market_capacity"><svg></svg></figure>'
        '<p>summary-after</p></section>'
        '<section id="narrative"><p>narrative-before</p>'
        '<figure data-chart-id="market_capacity"><svg></svg></figure>'
        '<p>narrative-after</p></section>'
        '</main></body></html>'
    )

    result, replaced_ids = replace_compiled_chart_figures(
        html,
        [chart],
        {
            "charts": [
                {
                    "chart_id": "market_capacity",
                    "status": "rendered",
                    "svg_path": str(svg_path),
                }
            ]
        },
    )

    assert replaced_ids == ["market_capacity"]
    assert result.count('data-chart-id="market_capacity"') == 1
    assert result.count('data-chart-renderer="flint-mcp"') == 1
    assert "<svg></svg>" not in result
    assert '<rect x="2" y="2" width="90" height="20"/>' in result
    assert result.index("summary-after") < result.index("narrative-before")
    assert result.index("narrative-before") < result.index('data-chart-id="market_capacity"')
    assert result.index('data-chart-id="market_capacity"') < result.index("narrative-after")


def test_repair_moves_populated_duplicate_to_narrative_location_and_removes_empty_copy() -> None:
    chart = {
        "id": "price_band_distribution",
        "title": "价格带销量占比",
        "type": "bar",
        "quality_status": "ready",
        "data": [{"label": "$20-25", "value": 46.97}],
    }
    html = (
        '<!doctype html><html><body><main>'
        '<section id="summary"><p>summary-before</p>'
        '<figure data-chart-id="price_band_distribution">'
        '<svg viewBox="0 0 100 50"><rect width="80" height="20"/></svg>'
        '</figure><p>summary-after</p></section>'
        '<section id="narrative"><p>narrative-before</p>'
        '<figure data-chart-id="price_band_distribution"><svg></svg></figure>'
        '<p>narrative-after</p></section>'
        '</main></body></html>'
    )

    result, repaired_ids = repair_missing_or_empty_chart_figures(html, [chart])

    assert repaired_ids == ["price_band_distribution"]
    assert result.count('data-chart-id="price_band_distribution"') == 1
    assert "<svg></svg>" not in result
    assert '<rect width="80" height="20"/>' in result
    assert result.index("summary-after") < result.index("narrative-before")
    assert result.index("narrative-before") < result.index('data-chart-id="price_band_distribution"')
    assert result.index('data-chart-id="price_band_distribution"') < result.index("narrative-after")

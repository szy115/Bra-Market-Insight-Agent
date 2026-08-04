from __future__ import annotations

from pathlib import Path

import pytest

from insight_agent.flint_chart_mcp import (
    apply_business_semantics_to_svg,
    build_flint_render_arguments,
    build_flint_validate_arguments,
    extract_safe_svg,
    parse_flint_validation,
)
from insight_agent.report_charts import (
    replace_compiled_chart_figures,
    replace_degraded_chart_figures,
)


def test_build_flint_render_arguments_maps_horizontal_percent_bar() -> None:
    arguments = build_flint_render_arguments(
        {
            "id": "brand-share",
            "type": "bar",
            "quality_status": "ready",
            "orientation": "horizontal",
            "unit": "%",
            "x_label": "销量份额",
            "y_label": "品牌",
            "data": [
                {"label": "Amazon", "value": 63.18},
                {"label": "CRZ YOGA", "value": 14.32},
            ],
        }
    )

    assert arguments is not None
    assert arguments["backend"] == "vegalite"
    assert arguments["format"] == "svg"
    assert arguments["semantic_types"]["value"] == "Percentage"
    assert arguments["chart_spec"]["chartType"] == "Bar Chart"
    assert arguments["chart_spec"]["encodings"] == {
        "x": {"field": "value"},
        "y": {"field": "label"},
        "color": {"field": "label", "scheme": "tableau10"},
    }
    assert arguments["chart_spec"]["canvasSize"]["height"] >= 260


def test_build_flint_render_arguments_colors_diverging_bars_by_direction() -> None:
    arguments = build_flint_render_arguments(
        {
            "id": "keyword-movement",
            "type": "diverging_bar",
            "quality_status": "ready",
            "orientation": "horizontal",
            "unit": "%",
            "data": [
                {"label": "minimizer bra", "value": 18.4},
                {"label": "strapless minimizer", "value": -7.2},
            ],
        }
    )

    assert arguments is not None
    assert arguments["semantic_types"]["direction"] == "Direction"
    assert arguments["chart_spec"]["encodings"]["color"] == {
        "field": "direction"
    }
    assert arguments["data"]["values"] == [
        {"label": "minimizer bra", "value": 18.4, "direction": "上升"},
        {"label": "strapless minimizer", "value": -7.2, "direction": "下降"},
    ]


def test_build_flint_render_arguments_maps_bar_table() -> None:
    arguments = build_flint_render_arguments(
        {
            "id": "top-products",
            "type": "bar_table",
            "quality_status": "ready",
            "orientation": "horizontal",
            "unit": "%",
            "x_label": "销量份额",
            "y_label": "ASIN",
            "data": [
                {"label": "B000000001", "value": 25.6},
                {"label": "B000000002", "value": 14.3},
            ],
        }
    )

    assert arguments is not None
    assert arguments["chart_spec"]["chartType"] == "Bar Table"
    assert arguments["chart_spec"]["encodings"] == {
        "x": {"field": "销量份额"},
        "y": {"field": "ASIN"},
        "color": {"field": "ASIN", "scheme": "tableau10"},
    }
    assert [row["ASIN"].replace("\u200b", "") for row in arguments["data"]["values"]] == [
        "B000000001",
        "B000000002",
    ]
    assert [row["销量份额"] for row in arguments["data"]["values"]] == [25.6, 14.3]


def test_build_flint_render_arguments_maps_grouped_bar() -> None:
    arguments = build_flint_render_arguments(
        {
            "id": "brand-share",
            "type": "grouped_bar",
            "quality_status": "ready",
            "orientation": "horizontal",
            "unit": "%",
            "x_label": "份额",
            "y_label": "品牌",
            "data": [
                {"label": "Bali", "group": "销量份额", "value": 31.2},
                {"label": "Bali", "group": "销售额份额", "value": 34.8},
                {"label": "HSIA", "group": "销量份额", "value": 3.3},
                {"label": "HSIA", "group": "销售额份额", "value": 4.1},
            ],
        }
    )

    assert arguments is not None
    assert arguments["chart_spec"]["chartType"] == "Grouped Bar Chart"
    assert arguments["chart_spec"]["encodings"] == {
        "x": {"field": "value"},
        "y": {"field": "label"},
        "group": {"field": "group"},
    }
    assert arguments["chart_spec"]["chartProperties"]["dodge"] == "global"


def test_build_flint_render_arguments_maps_price_sales_scatter() -> None:
    arguments = build_flint_render_arguments(
        {
            "id": "price-sales-positioning",
            "type": "scatter",
            "quality_status": "ready",
            "x_label": "价格（USD）",
            "y_label": "销量",
            "field_semantics": {"x": "Price", "y": "Quantity"},
            "data": [
                {
                    "label": "B000000001",
                    "x": 27.99,
                    "y": 22000,
                    "group": "Bali",
                },
                {
                    "label": "B000000002",
                    "x": 35.99,
                    "y": 16000,
                    "group": "HSIA",
                },
            ],
        }
    )

    assert arguments is not None
    assert arguments["chart_spec"]["chartType"] == "Scatter Plot"
    assert arguments["semantic_types"]["x"] == "Price"
    assert arguments["semantic_types"]["y"] == "Quantity"
    assert arguments["chart_spec"]["encodings"]["color"] == {
        "field": "group",
        "scheme": "tableau10",
    }


def test_build_flint_render_arguments_maps_bullet_benchmark() -> None:
    arguments = build_flint_render_arguments(
        {
            "id": "node-quality",
            "type": "bullet",
            "quality_status": "ready",
            "unit": "%",
            "data": [
                {
                    "label": "转化率 ↑",
                    "value": 12.19,
                    "goal": 9.56,
                    "comparison_direction": "higher_is_better",
                },
                {
                    "label": "退货率 ↓",
                    "value": 18.81,
                    "goal": 16.12,
                    "comparison_direction": "lower_is_better",
                },
            ],
        }
    )

    assert arguments is not None
    assert arguments["chart_spec"]["chartType"] == "Bullet Chart"
    assert arguments["semantic_types"]["value"] == "Percentage"
    assert arguments["semantic_types"]["goal"] == "Percentage"
    assert arguments["chart_spec"]["encodings"] == {
        "y": {"field": "metric"},
        "x": {"field": "value"},
        "goal": {"field": "goal"},
    }
    assert [row["status"] for row in arguments["data"]["values"]] == [
        "优于同级",
        "弱于同级",
    ]


def test_apply_business_semantics_to_svg_corrects_lower_is_better_bullet() -> None:
    chart = {"id": "node-quality", "type": "bullet"}
    arguments = {
        "data": {
            "values": [
                {
                    "metric": "退货率（越低越好）",
                    "value": 18.81,
                    "goal": 16.12,
                    "status": "弱于同级",
                },
                {
                    "metric": "搜索购买比（越高越好）",
                    "value": 12.19,
                    "goal": 9.56,
                    "status": "优于同级",
                },
            ]
        }
    }
    svg = (
        '<svg width="800" height="200" viewBox="0 0 800 200">'
        '<path aria-label="当前值: 18.81; 指标: 退货率（越低越好）" '
        'aria-roledescription="bar" fill="#2f855a"/>'
        '<path aria-label="当前值: 12.19; 指标: 搜索购买比（越高越好）" '
        'aria-roledescription="bar" fill="#2f855a"/>'
        "<text>Below target</text><text>Meets target</text></svg>"
    )

    corrected = apply_business_semantics_to_svg(svg, chart, arguments)

    assert (
        '退货率（越低越好）" aria-roledescription="bar" fill="#c44e52"'
        in corrected
    )
    assert (
        '搜索购买比（越高越好）" aria-roledescription="bar" fill="#2f855a"'
        in corrected
    )
    assert "Below target" not in corrected
    assert "Meets target" not in corrected
    assert "弱于同级" in corrected
    assert "优于同级" in corrected
    assert 'width="836"' in corrected
    assert 'viewBox="-36 0 836 200"' in corrected


def test_new_flint_chart_mappings_reject_incomplete_shapes() -> None:
    assert (
        build_flint_render_arguments(
            {
                "type": "grouped_bar",
                "quality_status": "ready",
                "data": [
                    {"label": "Bali", "group": "销量份额", "value": 31.2},
                    {"label": "HSIA", "group": "销量份额", "value": 3.3},
                ],
            }
        )
        is None
    )
    assert (
        build_flint_render_arguments(
            {
                "type": "bullet",
                "quality_status": "ready",
                "data": [{"label": "退货率", "value": 18.8}],
            }
        )
        is None
    )


def test_build_flint_render_arguments_keeps_special_server_chart_out_of_mcp() -> None:
    assert (
        build_flint_render_arguments(
            {
                "id": "bra-attributes",
                "type": "stacked_bar_100",
                "quality_status": "ready",
                "rendering_contract": {"renderer": "server"},
                "data": [{"label": "罩杯", "value": 50}],
            }
        )
        is None
    )


def test_build_flint_render_arguments_maps_relationship_graph_to_echarts_tree() -> None:
    arguments = build_flint_render_arguments(
        {
            "id": "market-boundary",
            "type": "relationship_map",
            "quality_status": "ready",
            "data": [
                {"label": "minimizer bra", "kind": "input_category", "value": 1},
                {"label": "Amazon Minimizers", "kind": "amazon_node", "value": 1},
                {"label": "strapless minimizer", "kind": "search_term", "value": 1200},
            ],
        }
    )

    assert arguments is not None
    assert arguments["backend"] == "echarts"
    assert arguments["chart_spec"]["chartType"] == "Tree"
    assert arguments["chart_spec"]["encodings"] == {
        "color": {"field": "group"},
        "detail": {"field": "item"},
        "size": {"field": "weight"},
    }
    assert arguments["chart_spec"]["chartProperties"]["rootLabel"] == "minimizer bra"
    assert arguments["data"]["values"][0]["group"] == "Amazon正式节点"


def test_build_flint_render_arguments_maps_bra_attributes_to_normalized_stack() -> None:
    arguments = build_flint_render_arguments(
        {
            "id": "bra_attribute_distribution",
            "type": "stacked_bar_100",
            "quality_status": "ready",
            "unit": "%",
            "data": [
                {
                    "label": "钢圈结构",
                    "segments": [
                        {"label": "有钢圈", "value": 65},
                        {"label": "无钢圈", "value": 25},
                        {"label": "未知", "value": 10},
                    ],
                },
                {
                    "label": "肩带形态",
                    "segments": [
                        {"label": "有肩带", "value": 80},
                        {"label": "无肩带", "value": 20},
                    ],
                },
            ],
        }
    )

    assert arguments is not None
    assert arguments["backend"] == "vegalite"
    assert arguments["chart_spec"]["chartType"] == "Stacked Bar Chart"
    assert arguments["chart_spec"]["chartProperties"]["stackMode"] == "normalize"
    assert arguments["chart_spec"]["encodings"] == {
        "x": {"field": "value"},
        "y": {"field": "axis"},
        "color": {"field": "segment"},
    }
    assert arguments["data"]["values"][0] == {
        "axis": "钢圈结构",
        "segment": "有钢圈",
        "value": 65.0,
    }


def test_build_flint_render_arguments_uses_kpi_cards_for_metric_group() -> None:
    arguments = build_flint_render_arguments(
        {
            "id": "market-capacity",
            "type": "metric_group",
            "quality_status": "ready",
            "data": [
                {"label": "月销量", "value": 156700, "unit": "units"},
                {"label": "销售额", "value": 4300000, "unit": "$"},
                {"label": "均价", "value": 27.6, "unit": "$"},
            ],
        }
    )

    assert arguments is not None
    assert arguments["chart_spec"]["chartType"] == "KPI Card"
    assert arguments["data"]["values"][1]["metric"] == "销售额 ($)"
    assert arguments["chart_spec"]["canvasSize"]["height"] >= 600


def test_build_flint_validate_arguments_removes_render_only_fields() -> None:
    render_arguments = {
        "data": {"values": [{"label": "A", "value": 1}]},
        "semantic_types": {"label": "Category", "value": "Quantity"},
        "chart_spec": {"chartType": "Bar Chart"},
        "backend": "vegalite",
        "format": "svg",
        "scale": 2,
        "background": "#ffffff",
    }

    validation_arguments = build_flint_validate_arguments(render_arguments)

    assert validation_arguments["backend"] == "vegalite"
    assert validation_arguments["chart_spec"]["chartType"] == "Bar Chart"
    assert "format" not in validation_arguments
    assert "scale" not in validation_arguments
    assert "background" not in validation_arguments


def test_parse_flint_validation_normalizes_valid_result() -> None:
    validation = parse_flint_validation(
        """
        {
          "backend": "vegalite",
          "chartType": "Bar Chart",
          "valid": true,
          "warnings": [],
          "errors": [],
          "computedSize": {"width": 563, "height": 210}
        }
        """
    )

    assert validation == {
        "status": "valid",
        "valid": True,
        "warnings": [],
        "errors": [],
        "computed_size": {"width": 563, "height": 210},
    }


def test_parse_flint_validation_rejects_invalid_json() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_flint_validation("not-json")


def test_extract_safe_svg_rejects_active_or_external_content() -> None:
    assert extract_safe_svg('<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>')
    with pytest.raises(ValueError, match="forbidden"):
        extract_safe_svg('<svg><script>alert(1)</script></svg>')
    with pytest.raises(ValueError, match="forbidden"):
        extract_safe_svg('<svg><a href="https://example.com"><rect/></a></svg>')
    with pytest.raises(ValueError, match="forbidden"):
        extract_safe_svg('<svg><a href="//example.com"><rect/></a></svg>')


def test_replace_compiled_chart_figures_injects_cached_svg(tmp_path: Path) -> None:
    svg_path = tmp_path / "brand-share.svg"
    svg_path.write_text(
        '<svg viewBox="0 0 100 60"><rect x="2" y="2" width="90" height="20"/></svg>',
        encoding="utf-8",
    )
    html = (
        "<!doctype html><html><body><main>"
        '<figure data-chart-id="brand-share"><svg></svg></figure>'
        "</main></body></html>"
    )
    chart_specs = [
        {
            "id": "brand-share",
            "title": "品牌销量份额结构",
            "insight": "头部品牌份额较高。",
            "source": "SellerSprite MCP",
        }
    ]
    bundle = {
        "charts": [
            {
                "chart_id": "brand-share",
                "status": "rendered",
                "svg_path": str(svg_path),
            }
        ]
    }

    result, replaced = replace_compiled_chart_figures(html, chart_specs, bundle)

    assert replaced == ["brand-share"]
    assert 'data-chart-renderer="flint-mcp"' in result
    assert 'width="90"' in result
    assert "头部品牌份额较高。" in result
    assert "<svg></svg>" not in result


def test_replace_degraded_chart_figures_overwrites_llm_chart() -> None:
    html = (
        "<!doctype html><html><body><main>"
        '<figure data-chart-id="market-map">'
        '<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="3"/></svg>'
        "</figure></main></body></html>"
    )
    chart_specs = [
        {
            "id": "market-map",
            "title": "市场边界图",
            "type": "relationship_map",
            "data": [{"label": "核心市场", "value": 80}],
        }
    ]

    result, replaced = replace_degraded_chart_figures(
        html,
        chart_specs,
        {
            "charts": [],
            "skipped_charts": [
                {"chart_id": "market-map", "status": "skipped"}
            ],
        },
    )

    assert replaced == ["market-map"]
    assert 'data-chart-renderer="server-recovery"' in result
    assert '<circle cx="5"' not in result

from insight_agent.bra_attributes import (
    build_bra_attribute_distribution,
    classify_bra_attributes,
    is_bra_category,
)
from insight_agent.flint_chart_mcp import build_flint_render_arguments
from insight_agent.mcp_sellersprite import CATEGORY_REVIEW_SKILL_IDS, WEEKLY_MARKET_SKILL_ID
from insight_agent.report_charts import build_market_report_charts
from insight_agent.server import market_report_llm_context


def test_bra_attribute_classification_uses_explicit_mutually_exclusive_evidence() -> None:
    classified = classify_bra_attributes(
        {
            "title": (
                "Full Coverage Underwire Minimizer Bra with Adjustable Straps, "
                "Front Closure, Unlined U-Back, Longline, 3 Pack"
            )
        }
    )

    assert classified == {
        "wire_structure": "underwire",
        "strap_presence": "strapped",
        "closure_type": "front_closure",
        "cup_construction": "unlined",
        "cup_coverage": "full_coverage",
        "back_style": "u_back",
        "band_length": "longline",
        "pack_size": "multi_pack",
    }


def test_bra_attribute_classification_keeps_absent_properties_unknown() -> None:
    classified = classify_bra_attributes({"title": "Everyday Minimizer Bra for Women"})

    assert set(classified.values()) == {"unknown"}


def test_bra_category_detection_does_not_apply_contract_to_open_categories() -> None:
    assert is_bra_category("minimizer bra")
    assert is_bra_category("Minimizers")
    assert not is_bra_category("yoga pants")


def test_bra_attribute_distribution_deduplicates_families_and_keeps_unknown_in_denominator() -> None:
    tool_results = [
        {
            "name": "sellersprite_market_product_concentration",
            "label": "SellerSprite product concentration",
            "status": "ok",
            "data": {
                "data": [
                    {
                        "asin": "B000000001",
                        "parentAsin": "B000PARENT",
                        "title": "Underwire Full Coverage Front Closure Bra 2 Pack",
                        "totalUnits": 100,
                    },
                    {
                        "asin": "B000000002",
                        "parentAsin": "B000PARENT",
                        "title": "Underwire Full Coverage Front Closure Bra Black",
                        "totalUnits": 60,
                    },
                    {
                        "asin": "B000000003",
                        "title": "Wirefree Pullover Bra with Adjustable Straps",
                        "totalUnits": 50,
                    },
                    {
                        "asin": "B000000004",
                        "title": "Everyday Minimizer Bra",
                        "totalUnits": 50,
                    },
                ],
                "product_selection": {
                    "eligible_candidates": [
                        {"asin": "B000000001"},
                        {"asin": "B000000002"},
                        {"asin": "B000000003"},
                        {"asin": "B000000004"},
                    ]
                },
            },
        }
    ]

    distribution = build_bra_attribute_distribution(tool_results)
    wire_axis = next(axis for axis in distribution["axes"] if axis["id"] == "wire_structure")
    shares = {item["id"]: item["product_family_share"] for item in wire_axis["values"]}

    assert distribution["product_family_count"] == 3
    assert shares == {"underwire": 33.3, "wirefree": 33.3, "unknown": 33.3}
    assert round(sum(shares.values()), 1) == 99.9


def test_market_report_charts_require_attribute_stacked_bar_for_sufficient_sample() -> None:
    products = [
        {
            "asin": f"B{i:09d}",
            "title": (
                "Underwire Full Coverage Front Closure Bra with Adjustable Straps"
                if i % 2
                else "Wirefree Demi Strapless Pullover Bra"
            ),
            "totalUnits": 100 + i,
        }
        for i in range(1, 31)
    ]
    distribution = build_bra_attribute_distribution(
        [
            {
                "name": "sellersprite_market_product_concentration",
                "status": "ok",
                "data": {"data": products},
            }
        ]
    )
    chart_bundle = build_market_report_charts(
        {
            "category": "minimizer bra",
            "bra_attribute_distribution": distribution,
        }
    )
    charts = chart_bundle["chart_specs"]
    attribute_chart = next(chart for chart in charts if chart["id"] == "bra_attribute_distribution")

    assert "bra_attribute_distribution" not in chart_bundle["summary_chart_ids"]
    assert attribute_chart["type"] == "stacked_bar_100"
    assert attribute_chart["quality_status"] == "ready"
    assert len(attribute_chart["data"]) >= 3
    assert attribute_chart["rendering_contract"]["renderer"] == "flint"
    assert attribute_chart["rendering_contract"]["layout"] == "normalized_stacked_bar"
    assert (
        attribute_chart["coverage_summary"]["analyzable_axes"]
        + attribute_chart["coverage_summary"]["directional_axes"]
        + attribute_chart["coverage_summary"]["insufficient_axes"]
        == len(attribute_chart["data"])
    )
    assert all(isinstance(row["coverage"], dict) for row in attribute_chart["data"])
    assert all(isinstance(row["segments"], list) for row in attribute_chart["data"])

    context = market_report_llm_context({"chart_specs": [attribute_chart]})
    compact_chart = context["chart_specs"][0]
    assert isinstance(compact_chart["data"][0]["segments"][0], dict)
    assert compact_chart["rendering_contract"]["layout"] == "normalized_stacked_bar"

    flint_arguments = build_flint_render_arguments(attribute_chart)
    assert flint_arguments is not None
    assert flint_arguments["chart_spec"]["chartType"] == "Stacked Bar Chart"
    assert flint_arguments["chart_spec"]["chartProperties"]["stackMode"] == "normalize"


def test_weekly_market_skill_requests_large_category_candidate_pool() -> None:
    assert WEEKLY_MARKET_SKILL_ID in CATEGORY_REVIEW_SKILL_IDS

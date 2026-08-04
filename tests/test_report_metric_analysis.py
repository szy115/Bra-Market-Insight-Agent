from insight_agent.report_metric_analysis import (
    attach_metric_facts,
    available_metric_catalog_for_skill,
    calculate_metric_analysis,
    default_metric_proposals,
)


def _fact(
    fact_id: str,
    concept: str,
    value: float,
    *,
    period: str = "report_period",
    entity_id: str = "P1",
    observation: str = "products.0.period_summary",
    denominator_scope: str = "not_applicable",
    sample_complete: bool | None = None,
) -> dict:
    return {
        "fact_id": fact_id,
        "concept": concept,
        "value": value,
        "unit": "percent" if concept in {"share", "product_share"} else "count",
        "period_key": period,
        "time_semantics": period,
        "marketplace": "US",
        "category": "bras",
        "entity_type": "product",
        "entity_id": entity_id,
        "scope_key": f"US|bras|product:{entity_id}",
        "observation_key": observation,
        "denominator_scope": denominator_scope,
        "sample_complete": sample_complete,
        "evidence_ids": ["E01"],
        "status": "observed",
    }


def test_attach_metric_facts_emits_typed_builder_facts() -> None:
    report_data = attach_metric_facts(
        {
            "schema_version": "test_report_data.v1",
            "marketplace": "US",
            "category": "bras",
            "candidate_products": [
                {
                    "product_id": "P1",
                    "period_summary": {
                        "period_gmv": 4200,
                        "period_units_sold": 210,
                        "linked_video_count": 14,
                    },
                    "momentum": {"l7_gmv": 1400, "p7_gmv": 1000},
                }
            ],
        }
    )

    facts = report_data["metric_facts"]
    assert report_data["metric_facts_schema_version"] == "metric_facts.v1"
    assert {fact["concept"] for fact in facts} >= {"gmv", "units_sold", "video_count"}
    l7 = next(fact for fact in facts if fact["source_field"] == "l7_gmv")
    p7 = next(fact for fact in facts if fact["source_field"] == "p7_gmv")
    assert l7["period_key"] == "l7"
    assert p7["period_key"] == "p7"
    assert l7["scope_key"] == p7["scope_key"] == "US|bras|product:P1"


def test_calculator_computes_value_in_script_not_from_proposal() -> None:
    gmv = _fact("MF001", "gmv", 4200)
    gmv["unit"] = "USD"
    units = _fact("MF002", "units_sold", 210)
    report_data = {
        "schema_version": "test.v1",
        "metric_facts_schema_version": "metric_facts.v1",
        "metric_facts": [gmv, units],
    }
    analysis = calculate_metric_analysis(
        report_data,
        [
            {
                "metric_id": "average_order_value",
                "bindings": {"gmv": "MF001", "units": "MF002"},
                "value": 999999,
            }
        ],
        skill_id="tiktok_us_market_insight",
    )

    assert analysis["derived_metrics"][0]["value"] == 20
    assert analysis["calculation_audit"]["llm_can_calculate_values"] is False


def test_calculator_rejects_wrong_denominator_scope_and_period() -> None:
    gmv = _fact("MF001", "gmv", 4200, period="l7", observation="products.0.l7")
    gmv["unit"] = "USD"
    wrong_product_units = _fact(
        "MF002",
        "units_sold",
        210,
        period="p7",
        observation="products.1.p7",
    )
    analysis = calculate_metric_analysis(
        {
            "schema_version": "test.v1",
            "metric_facts_schema_version": "metric_facts.v1",
            "metric_facts": [gmv, wrong_product_units],
        },
        [
            {
                "metric_id": "average_order_value",
                "bindings": {"gmv": "MF001", "units": "MF002"},
            }
        ],
        skill_id="tiktok_us_market_insight",
    )

    assert analysis["derived_metrics"] == []
    assert analysis["rejected_metric_proposals"][0]["reason_code"] in {
        "denominator_scope_mismatch",
        "period_mismatch",
    }


def test_cr3_rejects_incomplete_observed_sample() -> None:
    shares = [
        _fact(
            f"MF00{index}",
            "share",
            value,
            entity_id=f"S{index}",
            observation=f"shops.{index}",
            denominator_scope="observed_sample",
            sample_complete=False,
        )
        for index, value in enumerate((40, 25, 15), start=1)
    ]
    analysis = calculate_metric_analysis(
        {
            "schema_version": "test.v1",
            "metric_facts_schema_version": "metric_facts.v1",
            "metric_facts": shares,
        },
        [
            {
                "metric_id": "cr3_concentration",
                "bindings": {"share_fact_ids": [fact["fact_id"] for fact in shares]},
            }
        ],
        skill_id="weekly_market_insight",
    )

    assert analysis["derived_metrics"] == []
    assert analysis["rejected_metric_proposals"][0]["reason_code"] == "incomplete_denominator"


def test_cr3_uses_three_distinct_entities_with_full_market_denominator() -> None:
    shares = [
        _fact(
            f"MF00{index}",
            "share",
            value,
            entity_id=f"S{index}",
            observation=f"shops.{index}",
            denominator_scope="full_market",
            sample_complete=True,
        )
        for index, value in enumerate((40, 25, 15), start=1)
    ]
    analysis = calculate_metric_analysis(
        {
            "schema_version": "test.v1",
            "metric_facts_schema_version": "metric_facts.v1",
            "metric_facts": shares,
        },
        [
            {
                "metric_id": "cr3_concentration",
                "bindings": {"share_fact_ids": [fact["fact_id"] for fact in shares]},
            }
        ],
        skill_id="weekly_market_insight",
    )

    assert analysis["derived_metrics"][0]["value"] == 80


def test_skill_profile_blocks_unavailable_metric() -> None:
    gmv = _fact("MF001", "gmv", 100)
    videos = _fact("MF002", "video_count", 10)
    analysis = calculate_metric_analysis(
        {
            "schema_version": "test.v1",
            "metric_facts_schema_version": "metric_facts.v1",
            "metric_facts": [gmv, videos],
        },
        [
            {
                "metric_id": "gmv_per_video",
                "bindings": {"gmv": "MF001", "videos": "MF002"},
            }
        ],
        skill_id="weekly_market_insight",
    )

    assert analysis["derived_metrics"] == []
    assert (
        analysis["rejected_metric_proposals"][0]["reason_code"]
        == "metric_not_available_for_skill"
    )


def test_fallback_only_proposes_registered_skill_metrics() -> None:
    gmv = _fact("MF001", "gmv", 4200)
    units = _fact("MF002", "units_sold", 210)
    proposals = default_metric_proposals(
        [gmv, units],
        available_metric_catalog_for_skill("tiktok_us_market_insight"),
    )

    assert any(item["metric_id"] == "average_order_value" for item in proposals)
    assert all(
        item["metric_id"]
        in {
            metric["metric_id"]
            for metric in available_metric_catalog_for_skill("tiktok_us_market_insight")
        }
        for item in proposals
    )

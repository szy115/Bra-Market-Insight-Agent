from __future__ import annotations

from insight_agent.report_insight_synthesis import (
    fallback_report_insight_narrative,
    normalize_report_insight_narrative,
)


def report_data() -> dict:
    return {
        "schema_version": "market_report_data.v1",
        "evidence_map": [
            {"id": "E01", "tool": "sif_market_get_keyword_history"},
            {"id": "E02", "tool": "sellersprite_market_research"},
        ],
        "chart_specs": [{"id": "demand_trend"}, {"id": "price_band"}],
    }


def test_normalizer_keeps_only_supported_unique_insights() -> None:
    result = normalize_report_insight_narrative(
        {
            "sections": [
                {
                    "section_id": "demand",
                    "title": "需求变化",
                    "insights": [
                        {
                            "conclusion": "需求正在向核心词集中",
                            "observation": "核心词份额由 42% 升至 51%。",
                            "interpretation": "新增需求更集中于明确任务词。",
                            "business_implication": "产品表达应优先承接核心任务。",
                            "action": "先验证核心任务词版本。",
                            "evidence_ids": ["E01", "UNKNOWN"],
                            "chart_ids": ["demand_trend", "unknown_chart"],
                            "confidence": "high",
                        },
                        {
                            "conclusion": "需求正在向核心词集中",
                            "observation": "重复观察。",
                            "interpretation": "重复解释。",
                            "business_implication": "重复影响。",
                            "evidence_ids": ["E01"],
                        },
                    ],
                }
            ]
        },
        report_data=report_data(),
        skill_id="weekly_market_insight",
    )

    assert result["status"] == "completed"
    assert result["section_insight_count"] == 1
    assert result["chart_insight_count"] == 1
    assert result["insight_count"] == 2
    insight = result["sections"][0]["insights"][0]
    assert insight["evidence_ids"] == ["E01"]
    assert "chart_ids" not in insight
    assert result["chart_insights"][0]["chart_id"] == "demand_trend"
    assert "removed_unknown_evidence_ids" in result["internal_audit"]["warnings"]
    assert "dropped_duplicate_insight" in result["internal_audit"]["warnings"]


def test_normalizer_drops_gap_prose_and_untraceable_claims() -> None:
    result = normalize_report_insight_narrative(
        {
            "sections": [
                {
                    "title": "竞争",
                    "insights": [
                        {
                            "conclusion": "数据缺口导致品牌集中度无法判断",
                            "observation": "数据不足。",
                            "interpretation": "无法得出结论。",
                            "business_implication": "需要补数。",
                            "evidence_ids": ["E01"],
                        },
                        {
                            "conclusion": "价格带存在集中趋势",
                            "observation": "主价格带份额较高。",
                            "interpretation": "成交更集中在中位价格。",
                            "business_implication": "定价验证应从中位带开始。",
                            "evidence_ids": ["UNKNOWN"],
                        },
                    ],
                }
            ]
        },
        report_data=report_data(),
        skill_id="weekly_market_insight",
    )

    assert result["status"] == "empty_supported_insights"
    assert result["sections"] == []
    assert "dropped_gap_prose" in result["internal_audit"]["warnings"]
    assert "dropped_untraceable_insight" in result["internal_audit"]["warnings"]
    assert result["internal_audit"]["unsupported_dimensions_visible"] is False


def test_normalizer_assigns_each_chart_to_only_one_insight_block() -> None:
    result = normalize_report_insight_narrative(
        {
            "sections": [
                {
                    "title": "需求",
                    "insights": [
                        {
                            "conclusion": "核心词贡献上升",
                            "observation": "核心词贡献份额高于外围词。",
                            "interpretation": "需求正在向明确任务表达集中。",
                            "business_implication": "商品表达应先承接核心任务。",
                            "evidence_ids": ["E01"],
                            "chart_ids": ["demand_trend", "price_band"],
                        },
                        {
                            "conclusion": "中位价格带更适合作为验证起点",
                            "observation": "中位价格带样本更密集。",
                            "interpretation": "验证应先控制价格偏差。",
                            "business_implication": "首轮测试应靠近中位价格带。",
                            "evidence_ids": ["E02"],
                            "chart_ids": ["demand_trend"],
                        },
                    ],
                }
            ]
        },
        report_data=report_data(),
        skill_id="weekly_market_insight",
    )

    assert len(result["sections"][0]["insights"]) == 2
    assert [item["chart_id"] for item in result["chart_insights"]] == [
        "demand_trend",
        "price_band",
    ]
    assert all(
        len([item["chart_id"]]) == 1 for item in result["chart_insights"]
    )
    assert result["internal_audit"]["bound_chart_id_count"] == 2
    assert result["internal_audit"]["display_chart_ids"] == [
        "demand_trend",
        "price_band",
    ]
    assert result["internal_audit"]["unbound_chart_ids"] == []
    assert "removed_duplicate_chart_bindings" in result["internal_audit"]["warnings"]


def test_normalizer_keeps_unified_chart_interpretation_without_business_impact() -> None:
    result = normalize_report_insight_narrative(
        {
            "sections": [
                {
                    "title": "需求",
                    "insights": [
                        {
                            "conclusion": "需求存在阶段波动",
                            "observation": "近期需求低于阶段峰值。",
                            "interpretation": "市场处于高峰后的调整期。",
                            "business_implication": "备货节奏应保持克制。",
                            "evidence_ids": ["E01"],
                        }
                    ],
                }
            ],
            "chart_insights": [
                {
                    "chart_id": "demand_trend",
                    "section_id": "demand",
                    "section_title": "需求",
                    "observation": "近期需求低于阶段峰值。",
                    "interpretation": "图表反映的是高峰后的调整，而不是稳定增长。",
                    "evidence_ids": ["E01"],
                    "interpretation_type": "descriptive",
                    "confidence": "medium",
                },
                {
                    "chart_id": "price_band",
                    "section_id": "price_structure",
                    "section_title": "价格结构",
                    "observation": "中位价格区间的样本数量最高。",
                    "interpretation": "该区间是更稳妥的首轮验证基准。",
                    "evidence_ids": ["E02"],
                    "interpretation_type": "scope",
                    "confidence": "medium",
                }
            ],
        },
        report_data=report_data(),
        skill_id="weekly_market_insight",
    )

    assert result["section_insight_count"] == 1
    assert result["chart_insight_count"] == 2
    assert result["insight_count"] == 3
    price = result["chart_insights"][1]
    assert price["chart_id"] == "price_band"
    assert price["interpretation"] == "该区间是更稳妥的首轮验证基准。"
    assert price["business_implication"] == ""
    assert price["action"] == ""
    assert result["internal_audit"]["display_chart_ids"] == [
        "demand_trend",
        "price_band",
    ]
    assert result["internal_audit"]["unbound_chart_ids"] == []


def test_normalizer_does_not_cap_sections_insights_or_chart_interpretations() -> None:
    chart_specs = [{"id": f"chart_{index}"} for index in range(30)]
    sections = [
        {
            "section_id": f"section_{section_index}",
            "title": f"分析 {section_index}",
            "insights": [
                {
                    "conclusion": f"结论 {section_index}-{insight_index}",
                    "observation": f"观测 {section_index}-{insight_index}。",
                    "interpretation": f"解释 {section_index}-{insight_index}。",
                    "evidence_ids": ["E01"],
                }
                for insight_index in range(5)
            ],
        }
        for section_index in range(13)
    ]
    chart_insights = [
        {
            "chart_id": f"chart_{index}",
            "section_id": f"section_{index % 13}",
            "section_title": f"分析 {index % 13}",
            "observation": f"图表 {index} 展示了具体分布。",
            "interpretation": f"图表 {index} 用于描述当前样本结构。",
            "evidence_ids": ["E01"],
            "interpretation_type": "descriptive",
        }
        for index in range(30)
    ]

    result = normalize_report_insight_narrative(
        {"sections": sections, "chart_insights": chart_insights},
        report_data={
            **report_data(),
            "chart_specs": chart_specs,
        },
        skill_id="weekly_market_insight",
    )

    assert result["section_count"] == 13
    assert result["section_insight_count"] == 65
    assert result["chart_insight_count"] == 30
    assert result["insight_count"] == 95
    assert result["internal_audit"]["unbound_chart_ids"] == []


def test_fallback_omits_legacy_gap_sections() -> None:
    data = {
        **report_data(),
        "analysis_sections": [
            {
                "id": "supported",
                "title": "价格",
                "summary": "中位价格带承接主要成交",
                "bullets": [
                    "中位价格带份额最高。",
                    "成交对中位价格更敏感。",
                    "新品定价应先对齐该区间。",
                    "先做两个价格点的小样测试。",
                ],
                "evidence_ids": ["E02"],
            },
            {
                "id": "gap",
                "title": "缺口",
                "summary": "数据缺口仍需补齐",
                "evidence_ids": ["E01"],
            },
        ],
    }

    result = fallback_report_insight_narrative(
        data,
        skill_id="weekly_market_insight",
    )

    assert result["status"] == "fallback_supported_insights"
    assert result["section_count"] == 1
    assert result["sections"][0]["section_id"] == "supported"

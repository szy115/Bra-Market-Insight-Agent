from __future__ import annotations

import re
from typing import Any

REPORT_INSIGHT_SCHEMA_VERSION = "report_insight_narrative.v1"

_GAP_PHRASES = (
    "数据缺失",
    "数据缺口",
    "补齐缺口",
    "数据不足",
    "证据不足",
    "字段不足",
    "样本不足",
    "无法判断",
    "不可判断",
    "不能判断",
    "无法得出",
    "未取得",
    "没有取得",
    "待补",
    "缺少",
    "missing data",
    "data gap",
    "insufficient evidence",
    "cannot conclude",
    "unavailable",
)


def _compact_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}…"


def _string_list(value: Any, *, limit: int = 12) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        text = _compact_text(item, 120)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def collect_report_evidence_ids(report_data: dict[str, Any]) -> set[str]:
    collected: set[str] = set()

    def visit(value: Any, parent_key: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized_key = str(key).lower()
                if normalized_key in {
                    "evidence_id",
                    "source_evidence_id",
                    "evidence_ids",
                    "source_evidence_ids",
                }:
                    collected.update(_string_list(item, limit=40))
                elif normalized_key == "id" and parent_key in {
                    "evidence_map",
                    "evidence",
                    "evidence_items",
                }:
                    collected.update(_string_list(item, limit=4))
                visit(item, normalized_key)
        elif isinstance(value, list):
            for item in value:
                visit(item, parent_key)

    visit(report_data)
    return {item for item in collected if item}


def collect_report_chart_ids(report_data: dict[str, Any]) -> set[str]:
    return {
        str(item.get("id") or "").strip()
        for item in report_data.get("chart_specs") or []
        if isinstance(item, dict)
        and str(item.get("id") or "").strip()
        and str(item.get("quality_status") or "ready") == "ready"
    }


def collect_bound_chart_ids(value: Any) -> list[str]:
    """Return validated narrative chart ids in their reader-facing order."""

    source = value if isinstance(value, dict) else {}
    narrative = (
        source.get("insight_narrative")
        if isinstance(source.get("insight_narrative"), dict)
        else source
    )
    result: list[str] = []
    chart_insights = (
        narrative.get("chart_insights")
        if isinstance(narrative.get("chart_insights"), list)
        else []
    )
    for insight in chart_insights:
        if not isinstance(insight, dict):
            continue
        chart_id = _compact_text(insight.get("chart_id"), 120)
        if chart_id and chart_id not in result:
            result.append(chart_id)
    if result:
        return result

    # Backward compatibility for persisted v1 narratives created before chart_insights.
    sections = narrative.get("sections") if isinstance(narrative.get("sections"), list) else []
    for section in sections:
        if not isinstance(section, dict):
            continue
        insights = section.get("insights") if isinstance(section.get("insights"), list) else []
        for insight in insights:
            if not isinstance(insight, dict):
                continue
            for chart_id in _string_list(insight.get("chart_ids"), limit=1000):
                if chart_id not in result:
                    result.append(chart_id)
    supplementary = (
        narrative.get("supplementary_chart_insights")
        if isinstance(narrative.get("supplementary_chart_insights"), list)
        else []
    )
    for insight in supplementary:
        if not isinstance(insight, dict):
            continue
        chart_id = _compact_text(insight.get("chart_id"), 120)
        if chart_id and chart_id not in result:
            result.append(chart_id)
    return result


def insight_contains_gap_prose(value: dict[str, Any]) -> bool:
    text = " ".join(
        str(value.get(key) or "")
        for key in (
            "conclusion",
            "observation",
            "interpretation",
            "business_implication",
            "action",
        )
    ).lower()
    return any(phrase.lower() in text for phrase in _GAP_PHRASES)


def normalize_report_insight_narrative(
    value: Any,
    *,
    report_data: dict[str, Any],
    skill_id: str,
) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    sections_source = source.get("sections") if isinstance(source.get("sections"), list) else []
    allowed_evidence_ids = collect_report_evidence_ids(report_data)
    allowed_chart_ids = collect_report_chart_ids(report_data)
    sections: list[dict[str, Any]] = []
    chart_insights: list[dict[str, Any]] = []
    warnings: list[str] = []
    dropped_count = 0
    seen_section_conclusions: set[str] = set()
    seen_chart_ids: set[str] = set()
    legacy_chart_candidates: list[dict[str, Any]] = []
    section_insight_count = 0

    for section_index, raw_section in enumerate(sections_source, 1):
        if not isinstance(raw_section, dict):
            dropped_count += 1
            continue
        title = _compact_text(raw_section.get("title"), 120)
        raw_insights = (
            raw_section.get("insights") if isinstance(raw_section.get("insights"), list) else []
        )
        normalized_insights: list[dict[str, Any]] = []
        for raw_insight in raw_insights:
            if not isinstance(raw_insight, dict):
                dropped_count += 1
                continue
            insight = {
                "conclusion": _compact_text(raw_insight.get("conclusion"), 500),
                "observation": _compact_text(raw_insight.get("observation"), 700),
                "interpretation": _compact_text(raw_insight.get("interpretation"), 700),
                "business_implication": _compact_text(
                    raw_insight.get("business_implication"), 700
                ),
                "action": _compact_text(raw_insight.get("action"), 500),
            }
            if not all(
                insight.get(key)
                for key in (
                    "conclusion",
                    "observation",
                    "interpretation",
                )
            ):
                dropped_count += 1
                warnings.append("dropped_incomplete_insight")
                continue
            if insight_contains_gap_prose(insight):
                dropped_count += 1
                warnings.append("dropped_gap_prose")
                continue
            conclusion_key = re.sub(r"\W+", "", insight["conclusion"]).lower()
            if not conclusion_key or conclusion_key in seen_section_conclusions:
                dropped_count += 1
                warnings.append("dropped_duplicate_insight")
                continue
            evidence_ids = _string_list(raw_insight.get("evidence_ids"), limit=12)
            if allowed_evidence_ids:
                invalid_evidence = [
                    item for item in evidence_ids if item not in allowed_evidence_ids
                ]
                if invalid_evidence:
                    warnings.append("removed_unknown_evidence_ids")
                evidence_ids = [
                    item for item in evidence_ids if item in allowed_evidence_ids
                ]
                if not evidence_ids:
                    dropped_count += 1
                    warnings.append("dropped_untraceable_insight")
                    continue
            confidence = str(raw_insight.get("confidence") or "medium").lower()
            if confidence not in {"high", "medium", "low"}:
                confidence = "medium"
            normalized_insights.append(
                {
                    **insight,
                    "evidence_ids": evidence_ids,
                    "confidence": confidence,
                }
            )
            section_id = re.sub(
                r"[^a-z0-9_]+",
                "_",
                str(raw_section.get("section_id") or f"section_{section_index}").lower(),
            ).strip("_")
            for chart_id in _string_list(raw_insight.get("chart_ids"), limit=1000):
                if chart_id in allowed_chart_ids:
                    legacy_chart_candidates.append(
                        {
                            **insight,
                            "section_id": section_id or f"section_{section_index}",
                            "section_title": title or f"分析结论 {section_index}",
                            "evidence_ids": evidence_ids,
                            "chart_id": chart_id,
                            "confidence": confidence,
                            "interpretation_type": "business",
                        }
                    )
            seen_section_conclusions.add(conclusion_key)
            section_insight_count += 1
        if not normalized_insights:
            continue
        section_id = re.sub(
            r"[^a-z0-9_]+",
            "_",
            str(raw_section.get("section_id") or f"section_{section_index}").lower(),
        ).strip("_")
        sections.append(
            {
                "section_id": section_id or f"section_{section_index}",
                "title": title or f"分析结论 {section_index}",
                "insights": normalized_insights,
            }
        )

    explicit_chart_insights = (
        source.get("chart_insights") if isinstance(source.get("chart_insights"), list) else []
    )
    legacy_supplementary = (
        source.get("supplementary_chart_insights")
        if isinstance(source.get("supplementary_chart_insights"), list)
        else []
    )
    chart_sources = [
        *explicit_chart_insights,
        *legacy_chart_candidates,
        *legacy_supplementary,
    ]
    for raw_insight in chart_sources:
        if not isinstance(raw_insight, dict):
            dropped_count += 1
            continue
        chart_id = _compact_text(raw_insight.get("chart_id"), 120)
        if not chart_id or chart_id not in allowed_chart_ids:
            dropped_count += 1
            warnings.append("dropped_unknown_chart_insight")
            continue
        if chart_id in seen_chart_ids:
            warnings.append("removed_duplicate_chart_bindings")
            continue
        insight = {
            "conclusion": _compact_text(raw_insight.get("conclusion"), 500),
            "observation": _compact_text(raw_insight.get("observation"), 700),
            "interpretation": _compact_text(raw_insight.get("interpretation"), 700),
            "business_implication": _compact_text(
                raw_insight.get("business_implication"), 700
            ),
            "action": _compact_text(raw_insight.get("action"), 500),
        }
        if not all(
            insight.get(key)
            for key in (
                "observation",
                "interpretation",
            )
        ):
            dropped_count += 1
            warnings.append("dropped_incomplete_chart_insight")
            continue
        if insight_contains_gap_prose(insight):
            dropped_count += 1
            warnings.append("dropped_gap_prose")
            continue
        evidence_ids = _string_list(raw_insight.get("evidence_ids"), limit=12)
        if allowed_evidence_ids:
            invalid_evidence = [
                item for item in evidence_ids if item not in allowed_evidence_ids
            ]
            if invalid_evidence:
                warnings.append("removed_unknown_evidence_ids")
            evidence_ids = [
                item for item in evidence_ids if item in allowed_evidence_ids
            ]
        confidence = str(raw_insight.get("confidence") or "medium").lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        section_id = re.sub(
            r"[^a-z0-9_]+",
            "_",
            str(raw_insight.get("section_id") or "chart_analysis").lower(),
        ).strip("_")
        interpretation_type = str(
            raw_insight.get("interpretation_type") or "descriptive"
        ).lower()
        if interpretation_type not in {
            "business",
            "methodology",
            "scope",
            "confidence",
            "descriptive",
        }:
            interpretation_type = "descriptive"
        chart_insights.append(
            {
                **insight,
                "section_id": section_id or "chart_analysis",
                "section_title": _compact_text(
                    raw_insight.get("section_title") or "图表分析", 120
                ),
                "evidence_ids": evidence_ids,
                "chart_id": chart_id,
                "confidence": confidence,
                "interpretation_type": interpretation_type,
            }
        )
        seen_chart_ids.add(chart_id)

    total_supported_insights = section_insight_count + len(chart_insights)
    return {
        "schema_version": REPORT_INSIGHT_SCHEMA_VERSION,
        "skill_id": skill_id,
        "status": "completed" if total_supported_insights else "empty_supported_insights",
        "section_count": len(sections),
        "section_insight_count": section_insight_count,
        "chart_insight_count": len(chart_insights),
        "insight_count": total_supported_insights,
        "sections": sections,
        "chart_insights": chart_insights,
        "internal_audit": {
            "allowed_evidence_id_count": len(allowed_evidence_ids),
            "allowed_chart_id_count": len(allowed_chart_ids),
            "bound_chart_id_count": len(seen_chart_ids),
            "display_chart_ids": [item["chart_id"] for item in chart_insights],
            "unbound_chart_ids": sorted(allowed_chart_ids - seen_chart_ids),
            "dropped_insight_count": dropped_count,
            "warnings": list(dict.fromkeys(warnings))[:12],
            "unsupported_dimensions_visible": False,
        },
    }


def _fallback_chart_observation(chart: dict[str, Any]) -> str:
    rows = chart.get("data") if isinstance(chart.get("data"), list) else []
    snippets: list[str] = []

    def present(item: Any) -> bool:
        return item is not None and item != ""

    for row in rows:
        if not isinstance(row, dict):
            continue
        label = next(
            (
                row.get(key)
                for key in ("label", "name", "category", "keyword", "date", "x")
                if present(row.get(key))
            ),
            "",
        )
        value = next(
            (
                row.get(key)
                for key in ("value", "y", "share", "sales", "count", "rate")
                if present(row.get(key))
            ),
            "",
        )
        if present(label) and present(value):
            snippets.append(f"{label}={value}")
        elif present(label):
            snippets.append(str(label))
        if len(snippets) >= 6:
            break
    if snippets:
        return f"图表包含 {len(rows)} 个观测点；主要观测包括：" + "、".join(snippets) + "。"
    return _compact_text(chart.get("subtitle") or chart.get("title"), 700)


def fallback_report_insight_narrative(
    report_data: dict[str, Any],
    *,
    skill_id: str,
) -> dict[str, Any]:
    candidate_sections = (
        report_data.get("analysis_sections")
        if isinstance(report_data.get("analysis_sections"), list)
        else []
    )
    sections: list[dict[str, Any]] = []
    for index, item in enumerate(candidate_sections, 1):
        if not isinstance(item, dict):
            continue
        summary = _compact_text(item.get("summary"), 500)
        bullets = _string_list(item.get("bullets"), limit=4)
        if not summary or any(phrase.lower() in summary.lower() for phrase in _GAP_PHRASES):
            continue
        observation = bullets[0] if bullets else summary
        interpretation = bullets[1] if len(bullets) > 1 else summary
        implication = bullets[2] if len(bullets) > 2 else summary
        sections.append(
            {
                "section_id": str(item.get("id") or f"section_{index}"),
                "title": str(item.get("title") or f"分析结论 {index}"),
                "insights": [
                    {
                        "conclusion": summary,
                        "observation": observation,
                        "interpretation": interpretation,
                        "business_implication": implication,
                        "action": bullets[3] if len(bullets) > 3 else "",
                        "evidence_ids": item.get("evidence_ids") or [],
                        "chart_ids": item.get("chart_ids") or [],
                        "confidence": "medium",
                    }
                ],
            }
        )
    chart_insights: list[dict[str, Any]] = []
    for chart in report_data.get("chart_specs") or []:
        if (
            not isinstance(chart, dict)
            or not chart.get("id")
            or str(chart.get("quality_status") or "ready") != "ready"
        ):
            continue
        placement = (
            chart.get("placement") if isinstance(chart.get("placement"), dict) else {}
        )
        interpretation = _compact_text(
            chart.get("insight")
            or chart.get("market_question")
            or "该图用于描述当前样本中的结构与变化。",
            700,
        )
        chart_insights.append(
            {
                "chart_id": str(chart.get("id")),
                "section_id": str(placement.get("section_hint") or "chart_analysis"),
                "section_title": str(placement.get("section_hint") or "图表分析"),
                "conclusion": _compact_text(chart.get("title"), 500),
                "observation": _fallback_chart_observation(chart),
                "interpretation": interpretation,
                "business_implication": "",
                "action": "",
                "evidence_ids": sorted(collect_report_evidence_ids(chart)),
                "confidence": "low",
                "interpretation_type": (
                    "methodology"
                    if chart.get("market_question")
                    else "descriptive"
                ),
            }
        )
    normalized = normalize_report_insight_narrative(
        {"sections": sections, "chart_insights": chart_insights},
        report_data=report_data,
        skill_id=skill_id,
    )
    normalized["status"] = (
        "fallback_supported_insights"
        if normalized.get("sections") or normalized.get("chart_insights")
        else "empty_supported_insights"
    )
    return normalized

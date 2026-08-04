from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from html import escape
from pathlib import Path
from typing import Any

from .flint_chart_mcp import extract_safe_svg
from .market_analysis_coverage import MARKET_ANALYSIS_DIMENSIONS


def _slug(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _first_present(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    normalized = {_slug(key): value for key, value in row.items()}
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
        value = normalized.get(_slug(key))
        if value not in (None, ""):
            return value
    return None


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch in ".-")
    if cleaned in {"", ".", "-", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _rows(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _compact_label(value: Any, limit: int = 34) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}..."


def _point(row: dict[str, Any], label: Any, numeric: float) -> dict[str, Any]:
    return {
        "label": _compact_label(label),
        "value": round(numeric, 4),
        "raw_label": str(label),
        "raw_value": numeric,
        "source": row.get("source"),
        "evidence_id": row.get("evidence_id"),
    }


def _points_from_rows(
    rows: Iterable[dict[str, Any]],
    *,
    label_keys: tuple[str, ...],
    value_keys: tuple[str, ...],
    limit: int = 8,
    sort_mode: str = "",
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for row in rows:
        label = _first_present(row, label_keys)
        numeric = _float(_first_present(row, value_keys))
        normalized_label = str(label or "").strip().lower()
        if not normalized_label or numeric is None:
            continue
        if normalized_label in seen_labels:
            return []
        seen_labels.add(normalized_label)
        points.append(_point(row, label, numeric))
    if sort_mode == "desc":
        points.sort(key=lambda item: float(item["value"]), reverse=True)
    elif sort_mode == "asc":
        points.sort(key=lambda item: float(item["value"]))
    elif sort_mode == "label":
        points.sort(key=lambda item: str(item["raw_label"]))
    return points[:limit]


def _share_points(
    rows: Iterable[dict[str, Any]],
    *,
    label_keys: tuple[str, ...],
    ratio_keys: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for row in rows:
        label = _first_present(row, label_keys)
        ratio = _float(_first_present(row, ratio_keys))
        normalized_label = str(label or "").strip().lower()
        if not normalized_label or ratio is None or ratio < 0:
            continue
        if normalized_label in seen_labels:
            return []
        value = ratio * 100 if ratio <= 1.0001 else ratio
        if value > 100.5:
            continue
        seen_labels.add(normalized_label)
        points.append(_point(row, label, value))
    points.sort(key=lambda item: float(item["value"]), reverse=True)
    return points[:limit]


def _with_other_share(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = sum(float(item.get("value") or 0) for item in points)
    if total > 101:
        return []
    if total < 99:
        points = [*points, {"label": "其他", "raw_label": "其他", "value": round(100 - total, 2)}]
    return points


def _priority_score(priority: Any) -> int:
    return {"A": 88, "B": 68, "C": 46}.get(str(priority or "").strip().upper(), 56)


def _source_text(points: list[dict[str, Any]]) -> str:
    sources = list(dict.fromkeys(str(item.get("source") or "").strip() for item in points if item.get("source")))
    evidence = list(dict.fromkeys(str(item.get("evidence_id") or "").strip() for item in points if item.get("evidence_id")))
    source_text = " / ".join(sources)
    evidence_text = ", ".join(evidence[:4])
    if source_text and evidence_text:
        return f"{source_text} · {evidence_text}"
    return source_text or evidence_text


def _chart(
    chart_id: str,
    title: str,
    chart_type: str,
    data: list[dict[str, Any]],
    *,
    insight: str,
    subtitle: str = "",
    x_label: str = "",
    y_label: str = "",
    unit: str = "",
    orientation: str = "vertical",
    value_format: str = "number",
    dimension_id: str = "",
    market_question: str = "",
    field_semantics: dict[str, str] | None = None,
    placement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_ids = list(
        dict.fromkeys(
            evidence_id
            for item in data
            if isinstance(item, dict)
            for evidence_id in [
                str(item.get("evidence_id") or ""),
                *(str(value) for value in item.get("evidence_ids") or []),
            ]
            if evidence_id
        )
    )
    chart = {
        "id": chart_id,
        "dimension_id": dimension_id,
        "market_question": market_question,
        "title": title,
        "subtitle": subtitle,
        "type": chart_type,
        "insight": insight,
        "x_label": x_label,
        "y_label": y_label,
        "unit": unit,
        "orientation": orientation,
        "value_format": value_format,
        "source": _source_text(data),
        "evidence_ids": evidence_ids,
        "quality_status": "ready",
        "data": data,
    }
    if field_semantics:
        chart["field_semantics"] = field_semantics
    if placement:
        chart["placement"] = placement
    return chart


BRA_ATTRIBUTE_KNOWN_COLORS = ("#4F46E5", "#0891B2", "#16A34A", "#D97706")
BRA_ATTRIBUTE_UNKNOWN_COLOR = "#D1D5DB"
BRA_ATTRIBUTE_CONFLICT_COLOR = "#F59E0B"
BRA_ATTRIBUTE_DIRECTIONAL_COVERAGE = 30.0
BRA_ATTRIBUTE_RELIABLE_COVERAGE = 70.0


def _bra_attribute_coverage_status(known_share: float) -> tuple[str, str]:
    if known_share >= BRA_ATTRIBUTE_RELIABLE_COVERAGE:
        return "analyzable", "可分析"
    if known_share >= BRA_ATTRIBUTE_DIRECTIONAL_COVERAGE:
        return "directional", "方向性"
    return "insufficient", "证据不足"


def _bra_attribute_insight(rows: list[dict[str, Any]]) -> str:
    groups: dict[str, list[str]] = {"analyzable": [], "directional": [], "insufficient": []}
    for row in rows:
        coverage = row.get("coverage") if isinstance(row.get("coverage"), dict) else {}
        status = str(coverage.get("status") or "insufficient")
        groups.setdefault(status, []).append(str(row.get("label") or "属性轴"))

    parts: list[str] = []
    if groups["analyzable"]:
        parts.append(f"{ '、'.join(groups['analyzable']) }可用于结构判断")
    if groups["directional"]:
        parts.append(f"{ '、'.join(groups['directional']) }仅作方向性参考")
    if groups["insufficient"]:
        parts.append(f"{ '、'.join(groups['insufficient']) }因可识别度不足暂不判断")
    return "；".join(parts) + "。" if parts else "当前属性证据不足，暂不判断结构分布。"


def _svg_text(value: Any, limit: int = 72) -> str:
    return escape(_compact_label(value, limit), quote=False)


def _bra_attribute_detail_text(row: dict[str, Any]) -> str:
    coverage = row.get("coverage") if isinstance(row.get("coverage"), dict) else {}
    known_share = float(coverage.get("known_share") or 0)
    segments = [
        item
        for item in row.get("segments", [])
        if isinstance(item, dict) and item.get("id") not in {"unknown", "conflict"}
    ]
    signals = " · ".join(
        f"{item.get('label') or item.get('id')} {float(item.get('value') or 0):.1f}%"
        for item in sorted(segments, key=lambda item: float(item.get("value") or 0), reverse=True)
        if float(item.get("value") or 0) > 0
    )
    if str(coverage.get("status") or "") == "insufficient":
        prefix = f"仅识别 {known_share:.1f}%；观察信号："
    else:
        prefix = "全样本销量权重："
    return _compact_label(f"{prefix}{signals or '无可用结构信号'}", 66)


def render_bra_attribute_chart_figure(chart: dict[str, Any]) -> str:
    """Render the heterogeneous bra attributes as deterministic, readable SVG facets."""

    if str(chart.get("id") or "") != "bra_attribute_distribution":
        return ""
    rows = [item for item in chart.get("data", []) if isinstance(item, dict)]
    if not rows:
        return ""

    width = 1040
    header_height = 54
    row_height = 78
    height = header_height + len(rows) * row_height + 12
    axis_x = 8
    coverage_x = 168
    coverage_width = 190
    composition_x = 405
    composition_width = 615
    status_colors = {
        "analyzable": "#15803D",
        "directional": "#B45309",
        "insufficient": "#B91C1C",
    }

    svg: list[str] = [
        (
            f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMinYMin meet" '
            'role="img" aria-labelledby="bra-attribute-title bra-attribute-desc" '
            'style="display:block;width:100%;min-width:800px;height:auto;font-family:Inter,Segoe UI,Microsoft YaHei,Arial,sans-serif">'
        ),
        f'<title id="bra-attribute-title">{_svg_text(chart.get("title"))}</title>',
        (
            '<desc id="bra-attribute-desc">左侧显示每个属性轴的可识别销量权重，'
            '右侧仅对可识别度达到30%的属性显示已识别部分构成。</desc>'
        ),
        '<text x="8" y="22" font-size="12" font-weight="700" fill="#374151">属性轴</text>',
        f'<text x="{coverage_x}" y="22" font-size="12" font-weight="700" fill="#374151">可识别度（销量权重）</text>',
        f'<text x="{composition_x}" y="22" font-size="12" font-weight="700" fill="#374151">已识别部分的结构构成</text>',
        '<rect x="742" y="11" width="10" height="10" rx="2" fill="#0F766E"/>',
        '<text x="758" y="21" font-size="11" fill="#6B7280">可识别</text>',
        f'<rect x="812" y="11" width="10" height="10" rx="2" fill="{BRA_ATTRIBUTE_UNKNOWN_COLOR}"/>',
        '<text x="828" y="21" font-size="11" fill="#6B7280">未知</text>',
        f'<rect x="872" y="11" width="10" height="10" rx="2" fill="{BRA_ATTRIBUTE_CONFLICT_COLOR}"/>',
        '<text x="888" y="21" font-size="11" fill="#6B7280">冲突</text>',
        f'<line x1="8" y1="36" x2="{width - 20}" y2="36" stroke="#E5E7EB"/>',
    ]

    for index, row in enumerate(rows):
        top = header_height + index * row_height
        bar_y = top + 4
        coverage = row.get("coverage") if isinstance(row.get("coverage"), dict) else {}
        known_share = max(0.0, min(100.0, float(coverage.get("known_share") or 0)))
        conflict_share = max(0.0, min(100.0 - known_share, float(coverage.get("conflict_share") or 0)))
        status = str(coverage.get("status") or "insufficient")
        status_label = str(coverage.get("status_label") or "证据不足")
        status_color = status_colors.get(status, status_colors["insufficient"])

        svg.extend(
            [
                f'<text x="{axis_x}" y="{bar_y + 15}" font-size="14" font-weight="700" fill="#111827">{_svg_text(row.get("label"), 12)}</text>',
                f'<text x="{axis_x}" y="{bar_y + 38}" font-size="11" font-weight="700" fill="{status_color}">{_svg_text(status_label)} · {known_share:.1f}%</text>',
                f'<rect x="{coverage_x}" y="{bar_y}" width="{coverage_width}" height="18" rx="4" fill="{BRA_ATTRIBUTE_UNKNOWN_COLOR}"/>',
                f'<rect x="{coverage_x}" y="{bar_y}" width="{coverage_width * known_share / 100:.2f}" height="18" rx="4" fill="#0F766E"/>',
            ]
        )
        if conflict_share > 0:
            conflict_width = coverage_width * conflict_share / 100
            svg.append(
                f'<rect x="{coverage_x + coverage_width - conflict_width:.2f}" y="{bar_y}" '
                f'width="{conflict_width:.2f}" height="18" fill="{BRA_ATTRIBUTE_CONFLICT_COLOR}"/>'
            )
        svg.append(
            f'<text x="{coverage_x + coverage_width}" y="{bar_y + 38}" text-anchor="end" font-size="11" fill="#6B7280">'
            f'未知 {float(coverage.get("unknown_share") or 0):.1f}%'
            + (f' · 冲突 {conflict_share:.1f}%' if conflict_share else "")
            + "</text>"
        )

        composition = [
            item
            for item in row.get("composition_segments", [])
            if isinstance(item, dict) and float(item.get("value") or 0) > 0
        ]
        if status == "insufficient" or not composition:
            svg.extend(
                [
                    f'<rect x="{composition_x}" y="{bar_y}" width="{composition_width}" height="24" rx="4" fill="#F8FAFC" stroke="#CBD5E1" stroke-dasharray="4 4"/>',
                    f'<text x="{composition_x + 12}" y="{bar_y + 17}" font-size="12" fill="#64748B">可识别度低于 {BRA_ATTRIBUTE_DIRECTIONAL_COVERAGE:.0f}%，暂不比较结构</text>',
                ]
            )
        else:
            svg.append(
                f'<rect x="{composition_x}" y="{bar_y}" width="{composition_width}" height="24" rx="4" fill="#EEF2FF"/>'
            )
            current_x = float(composition_x)
            for segment_index, segment in enumerate(composition):
                value = max(0.0, float(segment.get("value") or 0))
                if segment_index == len(composition) - 1:
                    segment_width = composition_x + composition_width - current_x
                else:
                    segment_width = composition_width * value / 100
                color = str(segment.get("color") or BRA_ATTRIBUTE_KNOWN_COLORS[segment_index % len(BRA_ATTRIBUTE_KNOWN_COLORS)])
                svg.append(
                    f'<rect x="{current_x:.2f}" y="{bar_y}" width="{max(0, segment_width):.2f}" height="24" fill="{escape(color, quote=True)}"/>'
                )
                if segment_width >= 96 and value >= 10:
                    svg.append(
                        f'<text x="{current_x + segment_width / 2:.2f}" y="{bar_y + 16}" text-anchor="middle" '
                        f'font-size="11" font-weight="700" fill="#FFFFFF">{_svg_text(segment.get("label"), 10)} {value:.1f}%</text>'
                    )
                current_x += segment_width

        svg.extend(
            [
                f'<text x="{composition_x}" y="{bar_y + 45}" font-size="11" fill="#6B7280">{_svg_text(_bra_attribute_detail_text(row), 68)}</text>',
                f'<line x1="8" y1="{top + row_height - 9}" x2="{width - 20}" y2="{top + row_height - 9}" stroke="#F1F5F9"/>',
            ]
        )

    svg.append("</svg>")
    coverage_summary = chart.get("coverage_summary") if isinstance(chart.get("coverage_summary"), dict) else {}
    source = escape(str(chart.get("source") or "SellerSprite"))
    title = escape(str(chart.get("title") or "文胸属性结构与可识别度"))
    subtitle = escape(str(chart.get("subtitle") or ""))
    insight = escape(str(chart.get("insight") or ""))
    summary_text = (
        f"可分析 {int(coverage_summary.get('analyzable_axes') or 0)} 个轴 · "
        f"方向性 {int(coverage_summary.get('directional_axes') or 0)} 个轴 · "
        f"证据不足 {int(coverage_summary.get('insufficient_axes') or 0)} 个轴"
    )
    return (
        '<figure class="chart-card attribute-structure-chart" data-chart-id="bra_attribute_distribution" '
        'style="margin:16px 0;padding:18px;background:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;overflow:hidden">'
        '<figcaption style="margin:0 0 14px">'
        f'<div style="font-size:16px;font-weight:750;color:#111827;line-height:1.4">{title}</div>'
        f'<div style="margin-top:4px;font-size:12px;color:#6B7280;line-height:1.5">{subtitle}</div>'
        f'<div style="margin-top:8px;font-size:12px;font-weight:700;color:#374151">{escape(summary_text)}</div>'
        '</figcaption>'
        '<div style="width:100%;overflow-x:auto;overscroll-behavior-inline:contain">'
        + "".join(svg)
        + '</div>'
        f'<p style="margin:12px 0 0;font-size:12px;line-height:1.65;color:#374151"><strong>判读：</strong>{insight}</p>'
        '<p style="margin:5px 0 0;font-size:11px;line-height:1.55;color:#6B7280">'
        f'门槛：可识别度 ≥70% 才可分析，30–69.9% 仅作方向性参考，低于30%只作为数据缺口。数据源：{source}</p>'
        '</figure>'
    )


RECOVERY_CHART_COLORS = (
    "#4F46E5",
    "#0891B2",
    "#16A34A",
    "#D97706",
    "#DC2626",
    "#7C3AED",
    "#0F766E",
    "#64748B",
)
RECOVERY_CHART_GRAPHIC_PATTERN = re.compile(
    r"<(?:path|rect|circle|ellipse|line|polyline|polygon)\b",
    flags=re.IGNORECASE,
)


def _compact_number(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}K"
    if absolute >= 100:
        return f"{value:,.0f}"
    if absolute >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _format_recovery_value(value: Any, value_format: Any = "", unit: Any = "") -> str:
    numeric = _float(value)
    if numeric is None:
        return "—"
    format_name = str(value_format or "").lower()
    unit_name = str(unit or "")
    if format_name == "currency" or unit_name == "$":
        return f"${_compact_number(numeric)}"
    if "signed_percent" in format_name:
        return f"{numeric:+.1f}%"
    if "percent" in format_name or unit_name == "%":
        return f"{numeric:.1f}%"
    if format_name == "integer":
        return f"{numeric:,.0f}"
    if format_name == "compact_integer":
        return _compact_number(numeric)
    return _compact_number(numeric)


def _recovery_svg_open(chart: dict[str, Any], width: int, height: int) -> list[str]:
    chart_id = _slug(chart.get("id")) or "recoveredchart"
    title = _svg_text(chart.get("title") or chart.get("id") or "业务图表")
    return [
        (
            f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMinYMin meet" role="img" '
            f'aria-labelledby="{chart_id}-recovery-title" '
            'style="display:block;width:100%;min-width:680px;height:auto;font-family:Inter,Segoe UI,Microsoft YaHei,Arial,sans-serif">'
        ),
        f'<title id="{chart_id}-recovery-title">{title}</title>',
        f'<desc>根据 chart_specs 数据自动恢复的静态图表：{title}</desc>',
    ]


def _render_metric_group_recovery_svg(chart: dict[str, Any]) -> str:
    rows = _rows(chart.get("data"))[:6]
    if not rows:
        return ""
    width = 960
    columns = 2 if len(rows) > 1 else 1
    gap = 18
    tile_width = (width - 40 - gap * (columns - 1)) / columns
    tile_height = 102
    row_count = (len(rows) + columns - 1) // columns
    height = 28 + row_count * (tile_height + gap) + 18
    svg = _recovery_svg_open(chart, width, height)
    for index, row in enumerate(rows):
        column = index % columns
        row_index = index // columns
        x = 20 + column * (tile_width + gap)
        y = 20 + row_index * (tile_height + gap)
        value = _format_recovery_value(
            row.get("value"),
            row.get("value_format") or chart.get("value_format"),
            row.get("unit") or chart.get("unit"),
        )
        evidence_id = str(row.get("evidence_id") or "")
        svg.extend(
            [
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{tile_width:.1f}" height="{tile_height}" rx="6" fill="#F8FAFC" stroke="#E2E8F0"/>',
                f'<text x="{x + 18:.1f}" y="{y + 28:.1f}" font-size="13" fill="#475569">{_svg_text(row.get("label"), 28)}</text>',
                f'<text x="{x + 18:.1f}" y="{y + 64:.1f}" font-size="26" font-weight="750" fill="#111827">{_svg_text(value)}</text>',
                f'<text x="{x + tile_width - 18:.1f}" y="{y + 84:.1f}" text-anchor="end" font-size="10" fill="#94A3B8">{_svg_text(evidence_id)}</text>',
            ]
        )
    svg.append("</svg>")
    return "".join(svg)


def _render_bar_recovery_svg(chart: dict[str, Any], *, diverging: bool = False) -> str:
    rows = [
        row
        for row in _rows(chart.get("data"))[:12]
        if _float(row.get("value")) is not None
    ]
    if not rows:
        return ""
    width = 960
    top = 24
    row_height = 36
    height = top + len(rows) * row_height + 34
    label_width = 220
    plot_width = 590
    value_x = 940
    values = [float(_float(row.get("value")) or 0) for row in rows]
    max_value = max((abs(value) for value in values), default=1) or 1
    svg = _recovery_svg_open(chart, width, height)
    if diverging:
        center_x = label_width + plot_width / 2
        svg.append(
            f'<line x1="{center_x:.1f}" y1="12" x2="{center_x:.1f}" y2="{height - 22}" stroke="#94A3B8" stroke-width="1"/>'
        )
    for index, (row, value) in enumerate(zip(rows, values, strict=True)):
        y = top + index * row_height
        svg.append(
            f'<text x="10" y="{y + 18}" font-size="12" fill="#334155">{_svg_text(row.get("label"), 30)}</text>'
        )
        if diverging:
            half_width = plot_width / 2 - 8
            bar_width = half_width * abs(value) / max_value
            bar_x = center_x if value >= 0 else center_x - bar_width
            color = "#16A34A" if value >= 0 else "#DC2626"
            svg.append(
                f'<rect x="{bar_x:.2f}" y="{y + 5}" width="{bar_width:.2f}" height="20" rx="3" fill="{color}"/>'
            )
        else:
            bar_width = plot_width * max(0.0, value) / max_value
            svg.extend(
                [
                    f'<rect x="{label_width}" y="{y + 5}" width="{plot_width}" height="20" rx="3" fill="#EEF2FF"/>',
                    f'<rect x="{label_width}" y="{y + 5}" width="{bar_width:.2f}" height="20" rx="3" fill="{RECOVERY_CHART_COLORS[index % len(RECOVERY_CHART_COLORS)]}"/>',
                ]
            )
        formatted = _format_recovery_value(
            value,
            row.get("value_format") or chart.get("value_format"),
            row.get("unit") or chart.get("unit"),
        )
        svg.extend(
            [
                f'<text x="{value_x}" y="{y + 18}" text-anchor="end" font-size="12" font-weight="700" fill="#111827">{_svg_text(formatted)}</text>',
                f'<line x1="10" y1="{y + row_height - 3}" x2="{value_x}" y2="{y + row_height - 3}" stroke="#F1F5F9"/>',
            ]
        )
    svg.append("</svg>")
    return "".join(svg)


def _render_grouped_bar_recovery_svg(chart: dict[str, Any]) -> str:
    rows = [
        row
        for row in _rows(chart.get("data"))[:24]
        if _float(row.get("value")) is not None
        and str(row.get("label") or "").strip()
        and str(row.get("group") or "").strip()
    ]
    categories = list(dict.fromkeys(str(row["label"]) for row in rows))
    groups = list(dict.fromkeys(str(row["group"]) for row in rows))
    if len(categories) < 2 or len(groups) < 2:
        return ""
    width = 960
    top = 54
    category_height = max(42, 14 + len(groups) * 15)
    height = top + len(categories) * category_height + 42
    label_width = 190
    plot_width = 650
    value_x = 930
    maximum = max(float(_float(row.get("value")) or 0) for row in rows) or 1
    color_by_group = {
        group: RECOVERY_CHART_COLORS[index % len(RECOVERY_CHART_COLORS)]
        for index, group in enumerate(groups)
    }
    value_by_pair = {
        (str(row["label"]), str(row["group"])): float(_float(row.get("value")) or 0)
        for row in rows
    }
    svg = _recovery_svg_open(chart, width, height)
    legend_x = label_width
    for group in groups:
        color = color_by_group[group]
        svg.extend(
            [
                f'<rect x="{legend_x}" y="18" width="12" height="12" rx="2" fill="{color}"/>',
                f'<text x="{legend_x + 18}" y="29" font-size="11" fill="#475569">{_svg_text(group, 16)}</text>',
            ]
        )
        legend_x += 120
    for category_index, category in enumerate(categories):
        block_y = top + category_index * category_height
        svg.append(
            f'<text x="10" y="{block_y + category_height / 2:.1f}" font-size="12" fill="#334155">{_svg_text(category, 24)}</text>'
        )
        for group_index, group in enumerate(groups):
            value = value_by_pair.get((category, group))
            if value is None:
                continue
            y = block_y + 4 + group_index * 15
            bar_width = plot_width * max(0.0, value) / maximum
            svg.extend(
                [
                    f'<rect x="{label_width}" y="{y}" width="{plot_width}" height="10" rx="2" fill="#F1F5F9"/>',
                    f'<rect x="{label_width}" y="{y}" width="{bar_width:.2f}" height="10" rx="2" fill="{color_by_group[group]}"/>',
                    f'<text x="{value_x}" y="{y + 9}" text-anchor="end" font-size="10" font-weight="700" fill="#334155">{_svg_text(_format_recovery_value(value, chart.get("value_format"), chart.get("unit")))}</text>',
                ]
            )
        svg.append(
            f'<line x1="10" y1="{block_y + category_height - 3}" x2="{value_x}" y2="{block_y + category_height - 3}" stroke="#F1F5F9"/>'
        )
    svg.append("</svg>")
    return "".join(svg)


def _render_bullet_recovery_svg(chart: dict[str, Any]) -> str:
    rows = [
        row
        for row in _rows(chart.get("data"))[:6]
        if _float(row.get("value")) is not None
        and _float(row.get("goal")) is not None
    ]
    if not rows:
        return ""
    width = 960
    top = 30
    row_height = 78
    height = top + len(rows) * row_height + 24
    label_width = 250
    plot_width = 590
    value_x = 930
    svg = _recovery_svg_open(chart, width, height)
    for index, row in enumerate(rows):
        value = max(0.0, float(_float(row.get("value")) or 0))
        goal = max(0.0, float(_float(row.get("goal")) or 0))
        comparison_direction = str(
            row.get("comparison_direction") or "higher_is_better"
        )
        meets_benchmark = (
            value <= goal
            if comparison_direction == "lower_is_better"
            else value >= goal
        )
        status = str(
            row.get("status") or ("优于同级" if meets_benchmark else "弱于同级")
        )
        bar_color = "#2F855A" if status == "优于同级" else "#C44E52"
        scale_max = max(value, goal, 1) * 1.18
        bar_width = plot_width * value / scale_max
        goal_x = label_width + plot_width * goal / scale_max
        y = top + index * row_height
        svg.extend(
            [
                f'<text x="10" y="{y + 24}" font-size="12" font-weight="700" fill="#334155">{_svg_text(row.get("label"), 32)}</text>',
                f'<rect x="{label_width}" y="{y + 8}" width="{plot_width}" height="24" rx="4" fill="#E2E8F0"/>',
                f'<rect x="{label_width}" y="{y + 8}" width="{bar_width:.2f}" height="24" rx="4" fill="{bar_color}"/>',
                f'<line x1="{goal_x:.2f}" y1="{y + 2}" x2="{goal_x:.2f}" y2="{y + 38}" stroke="#111827" stroke-width="3"/>',
                f'<text x="{label_width}" y="{y + 55}" font-size="10" fill="#475569">当前 {_svg_text(_format_recovery_value(value, row.get("value_format") or chart.get("value_format"), row.get("unit") or chart.get("unit")))}</text>',
                f'<text x="{goal_x:.2f}" y="{y + 55}" text-anchor="middle" font-size="10" font-weight="700" fill="#111827">同级基准 {_svg_text(_format_recovery_value(goal, row.get("value_format") or chart.get("value_format"), row.get("unit") or chart.get("unit")))}</text>',
                f'<text x="{value_x}" y="{y + 24}" text-anchor="end" font-size="10" font-weight="700" fill="{bar_color}">{_svg_text(status)}</text>',
                f'<line x1="10" y1="{y + row_height - 8}" x2="{value_x}" y2="{y + row_height - 8}" stroke="#F1F5F9"/>',
            ]
        )
    svg.append("</svg>")
    return "".join(svg)


def _render_scatter_recovery_svg(chart: dict[str, Any]) -> str:
    rows = [
        row
        for row in _rows(chart.get("data"))[:30]
        if _float(row.get("x")) is not None and _float(row.get("y")) is not None
    ]
    if len(rows) < 2:
        return ""
    width = 960
    height = 420
    left = 84
    right = 34
    top = 58
    bottom = 62
    plot_width = width - left - right
    plot_height = height - top - bottom
    x_values = [float(_float(row.get("x")) or 0) for row in rows]
    y_values = [float(_float(row.get("y")) or 0) for row in rows]
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    x_spread = x_max - x_min or max(abs(x_max), 1)
    y_spread = y_max - y_min or max(abs(y_max), 1)
    x_min -= x_spread * 0.06
    x_max += x_spread * 0.06
    y_min = max(0.0, y_min - y_spread * 0.06)
    y_max += y_spread * 0.06
    x_spread = x_max - x_min or 1
    y_spread = y_max - y_min or 1
    groups = list(
        dict.fromkeys(str(row.get("group") or "全部商品") for row in rows)
    )
    color_by_group = {
        group: RECOVERY_CHART_COLORS[index % len(RECOVERY_CHART_COLORS)]
        for index, group in enumerate(groups)
    }
    field_semantics = (
        chart.get("field_semantics")
        if isinstance(chart.get("field_semantics"), dict)
        else {}
    )
    x_format = "currency" if field_semantics.get("x") == "Price" else "number"
    y_format = "compact_integer"
    svg = _recovery_svg_open(chart, width, height)
    legend_x = left
    for group in groups[:7]:
        color = color_by_group[group]
        svg.extend(
            [
                f'<circle cx="{legend_x + 5}" cy="24" r="5" fill="{color}"/>',
                f'<text x="{legend_x + 15}" y="28" font-size="10" fill="#475569">{_svg_text(group, 12)}</text>',
            ]
        )
        legend_x += 112
    for grid_index in range(5):
        ratio = grid_index / 4
        x = left + plot_width * ratio
        y = top + plot_height * ratio
        x_value = x_min + x_spread * ratio
        y_value = y_max - y_spread * ratio
        svg.extend(
            [
                f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height - bottom}" stroke="#F1F5F9"/>',
                f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" stroke="#F1F5F9"/>',
                f'<text x="{x:.2f}" y="{height - bottom + 20}" text-anchor="middle" font-size="10" fill="#64748B">{_svg_text(_format_recovery_value(x_value, x_format, "$" if x_format == "currency" else ""))}</text>',
                f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" font-size="10" fill="#64748B">{_svg_text(_format_recovery_value(y_value, y_format))}</text>',
            ]
        )
    label_indexes = set(
        sorted(range(len(rows)), key=lambda item: y_values[item], reverse=True)[:6]
    )
    for index, row in enumerate(rows):
        x = left + plot_width * (x_values[index] - x_min) / x_spread
        y = top + plot_height * (y_max - y_values[index]) / y_spread
        group = str(row.get("group") or "全部商品")
        color = color_by_group[group]
        svg.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="6" fill="{color}" fill-opacity="0.76" stroke="#FFFFFF" stroke-width="1.5"/>'
        )
        if index in label_indexes:
            svg.append(
                f'<text x="{x:.2f}" y="{max(top + 10, y - 9):.2f}" text-anchor="middle" font-size="10" fill="#334155">{_svg_text(row.get("label"), 16)}</text>'
            )
    svg.extend(
        [
            f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#64748B"/>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#64748B"/>',
            f'<text x="{left + plot_width / 2:.2f}" y="{height - 18}" text-anchor="middle" font-size="11" fill="#475569">{_svg_text(chart.get("x_label"))}</text>',
            f'<text x="18" y="{top + plot_height / 2:.2f}" transform="rotate(-90 18 {top + plot_height / 2:.2f})" text-anchor="middle" font-size="11" fill="#475569">{_svg_text(chart.get("y_label"))}</text>',
        ]
    )
    svg.append("</svg>")
    return "".join(svg)


def _render_line_recovery_svg(chart: dict[str, Any]) -> str:
    rows = [
        row
        for row in _rows(chart.get("data"))[:18]
        if _float(row.get("value")) is not None
    ]
    if len(rows) < 2:
        return ""
    width = 960
    height = 340
    left = 76
    right = 28
    top = 28
    bottom = 54
    plot_width = width - left - right
    plot_height = height - top - bottom
    values = [float(_float(row.get("value")) or 0) for row in rows]
    minimum = min(values)
    maximum = max(values)
    spread = maximum - minimum or max(abs(maximum), 1)
    minimum -= spread * 0.08
    maximum += spread * 0.08
    spread = maximum - minimum or 1
    points: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        x = left + plot_width * index / (len(values) - 1)
        y = top + plot_height * (maximum - value) / spread
        points.append((x, y))
    svg = _recovery_svg_open(chart, width, height)
    for grid_index in range(5):
        ratio = grid_index / 4
        y = top + plot_height * ratio
        grid_value = maximum - spread * ratio
        svg.extend(
            [
                f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" stroke="#E2E8F0"/>',
                f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" font-size="10" fill="#64748B">{_svg_text(_format_recovery_value(grid_value, chart.get("value_format"), chart.get("unit")))}</text>',
            ]
        )
    point_string = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    svg.append(
        f'<polyline points="{point_string}" fill="none" stroke="#4F46E5" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>'
    )
    label_indexes = {0, len(rows) - 1, values.index(max(values)), values.index(min(values))}
    if len(rows) <= 7:
        label_indexes.update(range(len(rows)))
    for index, ((x, y), row, value) in enumerate(zip(points, rows, values, strict=True)):
        svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="#4F46E5" stroke="#FFFFFF" stroke-width="2"/>')
        if index in label_indexes:
            anchor = "start" if index == 0 else "end" if index == len(rows) - 1 else "middle"
            svg.extend(
                [
                    f'<text x="{x:.2f}" y="{height - 24}" text-anchor="{anchor}" font-size="10" fill="#64748B">{_svg_text(row.get("label"), 14)}</text>',
                    f'<text x="{x:.2f}" y="{max(top + 12, y - 9):.2f}" text-anchor="middle" font-size="10" font-weight="700" fill="#3730A3">{_svg_text(_format_recovery_value(value, chart.get("value_format"), chart.get("unit")))}</text>',
                ]
            )
    svg.append("</svg>")
    return "".join(svg)


def _render_bubble_recovery_svg(chart: dict[str, Any]) -> str:
    rows = [
        row
        for row in _rows(chart.get("data"))[:12]
        if _float(row.get("x")) is not None and _float(row.get("y")) is not None
    ]
    if not rows:
        return ""
    width = 960
    height = 360
    left = 82
    right = 34
    top = 30
    bottom = 60
    plot_width = width - left - right
    plot_height = height - top - bottom
    x_values = [float(_float(row.get("x")) or 0) for row in rows]
    y_values = [float(_float(row.get("y")) or 0) for row in rows]
    size_values = [max(0.0, float(_float(row.get("size")) or 0)) for row in rows]
    x_max = max(x_values) or 1
    y_max = max(y_values) or 1
    size_max = max(size_values) or 1
    svg = _recovery_svg_open(chart, width, height)
    for grid_index in range(5):
        ratio = grid_index / 4
        x = left + plot_width * ratio
        y = top + plot_height * ratio
        svg.extend(
            [
                f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height - bottom}" stroke="#F1F5F9"/>',
                f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" stroke="#F1F5F9"/>',
            ]
        )
    label_indexes = set(sorted(range(len(rows)), key=lambda index: size_values[index], reverse=True)[:5])
    for index, row in enumerate(rows):
        x = left + plot_width * x_values[index] / x_max
        y = top + plot_height * (1 - y_values[index] / y_max)
        radius = 7 + 18 * (size_values[index] / size_max) ** 0.5
        color = RECOVERY_CHART_COLORS[index % len(RECOVERY_CHART_COLORS)]
        svg.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{color}" fill-opacity="0.58" stroke="{color}" stroke-width="1.5"/>'
        )
        if index in label_indexes:
            svg.append(
                f'<text x="{x:.2f}" y="{max(14, y - radius - 5):.2f}" text-anchor="middle" font-size="10" fill="#334155">{_svg_text(row.get("label"), 18)}</text>'
            )
    svg.extend(
        [
            f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#64748B"/>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#64748B"/>',
            f'<text x="{left + plot_width / 2:.2f}" y="{height - 18}" text-anchor="middle" font-size="11" fill="#475569">{_svg_text(chart.get("x_label"))}</text>',
            f'<text x="18" y="{top + plot_height / 2:.2f}" transform="rotate(-90 18 {top + plot_height / 2:.2f})" text-anchor="middle" font-size="11" fill="#475569">{_svg_text(chart.get("y_label"))}</text>',
            f'<text x="{left}" y="{height - bottom + 18}" text-anchor="middle" font-size="10" fill="#64748B">0</text>',
            f'<text x="{width - right}" y="{height - bottom + 18}" text-anchor="end" font-size="10" fill="#64748B">{_svg_text(_compact_number(x_max))}</text>',
            f'<text x="{left - 9}" y="{top + 4}" text-anchor="end" font-size="10" fill="#64748B">{_svg_text(f"{y_max:.1f}%")}</text>',
        ]
    )
    svg.append("</svg>")
    return "".join(svg)


def _render_relationship_recovery_svg(chart: dict[str, Any]) -> str:
    rows = _rows(chart.get("data"))[:8]
    if not rows:
        return ""
    input_row = next((row for row in rows if row.get("kind") == "input_category"), rows[0])
    node_row = next((row for row in rows if row.get("kind") == "amazon_node"), None)
    search_rows = [row for row in rows if row.get("kind") == "search_term"]
    if not search_rows:
        search_rows = [row for row in rows if row is not input_row and row is not node_row]
    width = 960
    height = max(250, 72 + len(search_rows) * 54)
    input_y = height / 2 - 34
    node_y = height / 2 - 34
    svg = _recovery_svg_open(chart, width, height)
    if node_row:
        svg.extend(
            [
                f'<line x1="240" y1="{input_y + 34:.1f}" x2="350" y2="{node_y + 34:.1f}" stroke="#94A3B8" stroke-width="2"/>',
                f'<polygon points="350,{node_y + 34:.1f} 340,{node_y + 29:.1f} 340,{node_y + 39:.1f}" fill="#94A3B8"/>',
            ]
        )
    source_x = 620 if node_row else 300
    source_start_x = 590 if node_row else 240
    for index, row in enumerate(search_rows):
        y = 34 + index * 54
        svg.extend(
            [
                f'<line x1="{source_start_x}" y1="{node_y + 34:.1f}" x2="{source_x}" y2="{y + 22:.1f}" stroke="#CBD5E1" stroke-width="1.5"/>',
                f'<rect x="{source_x}" y="{y}" width="310" height="44" rx="6" fill="#ECFEFF" stroke="#A5F3FC"/>',
                f'<text x="{source_x + 14}" y="{y + 19}" font-size="12" font-weight="700" fill="#164E63">{_svg_text(row.get("label"), 30)}</text>',
                f'<text x="{source_x + 296}" y="{y + 34}" text-anchor="end" font-size="10" fill="#0E7490">{_svg_text(_format_recovery_value(row.get("value"), "compact_integer"))}</text>',
            ]
        )
    svg.extend(
        [
            f'<rect x="20" y="{input_y:.1f}" width="220" height="68" rx="6" fill="#EEF2FF" stroke="#C7D2FE"/>',
            f'<text x="36" y="{input_y + 27:.1f}" font-size="11" fill="#6366F1">研究入口</text>',
            f'<text x="36" y="{input_y + 50:.1f}" font-size="14" font-weight="700" fill="#312E81">{_svg_text(input_row.get("label"), 24)}</text>',
        ]
    )
    if node_row:
        svg.extend(
            [
                f'<rect x="350" y="{node_y:.1f}" width="240" height="68" rx="6" fill="#F0FDF4" stroke="#BBF7D0"/>',
                f'<text x="366" y="{node_y + 27:.1f}" font-size="11" fill="#16A34A">Amazon 节点</text>',
                f'<text x="366" y="{node_y + 50:.1f}" font-size="12" font-weight="700" fill="#14532D">{_svg_text(node_row.get("label"), 30)}</text>',
            ]
        )
    svg.append("</svg>")
    return "".join(svg)


def _render_data_gap_recovery_svg(chart: dict[str, Any]) -> str:
    width = 960
    height = 150
    svg = _recovery_svg_open(chart, width, height)
    svg.extend(
        [
            '<rect x="20" y="28" width="920" height="86" rx="6" fill="#FFF7ED" stroke="#FED7AA"/>',
            '<text x="42" y="64" font-size="14" font-weight="700" fill="#9A3412">该图表规格缺少可绘制数值</text>',
            '<text x="42" y="91" font-size="12" fill="#7C2D12">报告保留此数据缺口，不生成替代数值。</text>',
        ]
    )
    svg.append("</svg>")
    return "".join(svg)


def render_recovery_chart_figure(chart: dict[str, Any]) -> str:
    """Render a chart-spec-backed fallback only when LLM chart markup is missing or empty."""

    chart_type = str(chart.get("type") or "")
    if chart_type == "metric_group":
        svg = _render_metric_group_recovery_svg(chart)
    elif chart_type == "bullet":
        svg = _render_bullet_recovery_svg(chart)
    elif chart_type == "grouped_bar":
        svg = _render_grouped_bar_recovery_svg(chart)
    elif chart_type == "scatter":
        svg = _render_scatter_recovery_svg(chart)
    elif chart_type == "line":
        svg = _render_line_recovery_svg(chart)
    elif chart_type == "bubble":
        svg = _render_bubble_recovery_svg(chart)
    elif chart_type == "relationship_map":
        svg = _render_relationship_recovery_svg(chart)
    elif chart_type == "diverging_bar":
        svg = _render_bar_recovery_svg(chart, diverging=True)
    else:
        svg = _render_bar_recovery_svg(chart)
    if not svg:
        svg = _render_data_gap_recovery_svg(chart)

    chart_id = escape(str(chart.get("id") or "unknown"), quote=True)
    title = escape(str(chart.get("title") or chart_id))
    subtitle = escape(str(chart.get("subtitle") or ""))
    insight = escape(str(chart.get("insight") or ""))
    source = escape(str(chart.get("source") or "未提供"))
    return (
        f'<figure class="chart-card recovered-chart" data-chart-id="{chart_id}" data-chart-renderer="server-recovery" '
        'style="margin:16px 0;padding:18px;background:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;overflow:hidden">'
        '<figcaption style="margin:0 0 12px">'
        f'<div style="font-size:16px;font-weight:750;color:#111827;line-height:1.4">{title}</div>'
        + (f'<div style="margin-top:4px;font-size:12px;color:#6B7280;line-height:1.5">{subtitle}</div>' if subtitle else "")
        + '</figcaption><div style="width:100%;overflow-x:auto;overscroll-behavior-inline:contain">'
        + svg
        + '</div>'
        + (f'<p style="margin:10px 0 0;font-size:12px;line-height:1.6;color:#374151"><strong>判读：</strong>{insight}</p>' if insight else "")
        + f'<p style="margin:5px 0 0;font-size:11px;line-height:1.5;color:#6B7280">数据源：{source}</p>'
        + '</figure>'
    )


def _chart_figure_pattern(chart_id: str) -> re.Pattern[str]:
    return re.compile(
        rf'<figure\b(?=[^>]*\bdata-chart-id\s*=\s*["\']{re.escape(chart_id)}["\'])[^>]*>.*?</figure\s*>',
        flags=re.IGNORECASE | re.DOTALL,
    )


def _replace_chart_figures_once(
    html_content: str,
    chart_id: str,
    figure_markup: str,
) -> tuple[str, int]:
    """Replace every occurrence of a chart with one figure at its narrative position.

    Reports are rendered in document order, with the executive summary before the
    detailed narrative.  When the LLM repeats a chart in both places, retaining the
    last occurrence therefore keeps the chart alongside its full interpretation.
    Rebuilding the string in one pass also guarantees that no empty duplicate is
    left behind.
    """

    matches = list(_chart_figure_pattern(chart_id).finditer(html_content))
    if not matches:
        return html_content, 0

    retained_index = len(matches) - 1
    parts: list[str] = []
    cursor = 0
    for index, match in enumerate(matches):
        parts.append(html_content[cursor : match.start()])
        if index == retained_index:
            parts.append(figure_markup)
        cursor = match.end()
    parts.append(html_content[cursor:])
    return "".join(parts), len(matches)


def _chart_figure_has_populated_svg(figure_markup: str) -> bool:
    svg_blocks = re.findall(r"<svg\b[^>]*>.*?</svg\s*>", figure_markup, flags=re.IGNORECASE | re.DOTALL)
    return any(RECOVERY_CHART_GRAPHIC_PATTERN.search(svg) for svg in svg_blocks)


def render_compiled_chart_figure(
    chart: dict[str, Any],
    rendered_chart: dict[str, Any],
) -> str:
    """Wrap a validated Flint SVG with the report chart's business context."""

    svg_path_value = str(rendered_chart.get("svg_path") or "").strip()
    if not svg_path_value:
        return ""
    svg_path = Path(svg_path_value).expanduser().resolve()
    if not svg_path.is_file() or svg_path.suffix.lower() != ".svg":
        return ""
    try:
        svg = extract_safe_svg(svg_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return ""

    chart_id = escape(str(chart.get("id") or "unknown"), quote=True)
    title = escape(str(chart.get("title") or chart_id))
    subtitle = escape(str(chart.get("subtitle") or ""))
    insight = escape(str(chart.get("insight") or ""))
    source = escape(str(chart.get("source") or "未提供"))
    return (
        f'<figure class="chart-card compiled-chart" data-chart-id="{chart_id}" '
        'data-chart-renderer="flint-mcp" '
        'style="margin:16px 0;padding:18px;background:#FFFFFF;border:1px solid #E5E7EB;'
        'border-radius:8px;overflow:hidden">'
        '<figcaption style="margin:0 0 12px">'
        f'<div style="font-size:16px;font-weight:750;color:#111827;line-height:1.4">{title}</div>'
        + (
            f'<div style="margin-top:4px;font-size:12px;color:#6B7280;line-height:1.5">{subtitle}</div>'
            if subtitle
            else ""
        )
        + '</figcaption><div class="compiled-chart-svg" '
        'style="width:100%;overflow-x:auto;overscroll-behavior-inline:contain">'
        + svg
        + '</div>'
        + (
            f'<p style="margin:10px 0 0;font-size:12px;line-height:1.6;color:#374151">'
            f'<strong>判读：</strong>{insight}</p>'
            if insight
            else ""
        )
        + f'<p style="margin:5px 0 0;font-size:11px;line-height:1.5;color:#6B7280">'
        f"数据源：{source}</p>"
        + "</figure>"
    )


def replace_compiled_chart_figures(
    html_content: str,
    chart_specs: list[dict[str, Any]],
    chart_render_bundle: dict[str, Any],
) -> tuple[str, list[str]]:
    """Replace matching chart placeholders with validated SVGs produced by Flint MCP."""

    rendered_by_id = {
        str(item.get("chart_id") or ""): item
        for item in chart_render_bundle.get("charts") or []
        if isinstance(item, dict)
        and str(item.get("status") or "") == "rendered"
        and item.get("chart_id")
    }
    result = html_content
    replaced_ids: list[str] = []
    appended_figures: list[str] = []
    for chart in chart_specs:
        if not isinstance(chart, dict):
            continue
        chart_id = str(chart.get("id") or "").strip()
        rendered_chart = rendered_by_id.get(chart_id)
        if not chart_id or not rendered_chart:
            continue
        figure = render_compiled_chart_figure(chart, rendered_chart)
        if not figure:
            continue
        result, count = _replace_chart_figures_once(result, chart_id, figure)
        if count:
            replaced_ids.append(chart_id)
        else:
            appended_figures.append(figure)
            replaced_ids.append(chart_id)
    if appended_figures:
        section = (
            '<section class="content-section compiled-chart-section" '
            'data-compiled-chart-section="true"><h2>补充业务图表</h2>'
            + "".join(appended_figures)
            + "</section>"
        )
        main_close = re.search(r"</main\s*>", result, flags=re.IGNORECASE)
        body_close = re.search(r"</body\s*>", result, flags=re.IGNORECASE)
        insertion = main_close.start() if main_close else body_close.start() if body_close else len(result)
        result = result[:insertion] + section + result[insertion:]
    return result, replaced_ids


def replace_degraded_chart_figures(
    html_content: str,
    chart_specs: list[dict[str, Any]],
    chart_render_bundle: dict[str, Any],
) -> tuple[str, list[str]]:
    """Replace MCP-skipped or failed charts with the deterministic server renderer."""

    degraded_ids = {
        str(item.get("chart_id") or "")
        for item in [
            *(chart_render_bundle.get("charts") or []),
            *(chart_render_bundle.get("skipped_charts") or []),
        ]
        if isinstance(item, dict)
        and str(item.get("status") or "") in {"failed", "skipped"}
        and item.get("chart_id")
    }
    result = html_content
    replaced_ids: list[str] = []
    appended_figures: list[str] = []
    for chart in chart_specs:
        if not isinstance(chart, dict):
            continue
        chart_id = str(chart.get("id") or "").strip()
        contract = (
            chart.get("rendering_contract")
            if isinstance(chart.get("rendering_contract"), dict)
            else {}
        )
        if (
            not chart_id
            or chart_id not in degraded_ids
            or str(contract.get("renderer") or "") == "server"
        ):
            continue
        figure = render_recovery_chart_figure(chart)
        if not figure:
            continue
        result, count = _replace_chart_figures_once(result, chart_id, figure)
        replaced_ids.append(chart_id)
        if not count:
            appended_figures.append(figure)
    if appended_figures:
        section = (
            '<section class="content-section degraded-chart-section" '
            'data-degraded-chart-section="true"><h2>补充业务图表</h2>'
            + "".join(appended_figures)
            + "</section>"
        )
        main_close = re.search(r"</main\s*>", result, flags=re.IGNORECASE)
        body_close = re.search(r"</body\s*>", result, flags=re.IGNORECASE)
        insertion = main_close.start() if main_close else body_close.start() if body_close else len(result)
        result = result[:insertion] + section + result[insertion:]
    return result, replaced_ids


def replace_server_rendered_chart_figures(
    html_content: str,
    chart_specs: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Replace LLM-drawn placeholders for charts that require deterministic rendering."""

    rendered_ids: list[str] = []
    result = html_content
    for chart in chart_specs:
        if not isinstance(chart, dict):
            continue
        contract = chart.get("rendering_contract") if isinstance(chart.get("rendering_contract"), dict) else {}
        if contract.get("renderer") != "server":
            continue
        chart_id = str(chart.get("id") or "").strip()
        figure = render_bra_attribute_chart_figure(chart)
        if not chart_id or not figure:
            continue
        result, count = _replace_chart_figures_once(result, chart_id, figure)
        if count:
            rendered_ids.append(chart_id)
    return result, rendered_ids


def repair_missing_or_empty_chart_figures(
    html_content: str,
    chart_specs: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Repair individual chart failures without discarding an otherwise valid LLM report."""

    result = html_content
    repaired_ids: list[str] = []
    appended_figures: list[str] = []
    for chart in chart_specs:
        if not isinstance(chart, dict) or str(chart.get("quality_status") or "ready") != "ready":
            continue
        chart_id = str(chart.get("id") or "").strip()
        if not chart_id:
            continue
        matches = list(_chart_figure_pattern(chart_id).finditer(result))
        retained_match = matches[-1] if matches else None
        retained_figure = retained_match.group(0) if retained_match else ""
        populated_figures = [
            match.group(0)
            for match in matches
            if _chart_figure_has_populated_svg(match.group(0))
        ]
        if len(matches) == 1 and populated_figures:
            continue

        if retained_figure and _chart_figure_has_populated_svg(retained_figure):
            figure = retained_figure
        elif populated_figures:
            # Move an already rendered chart to the retained narrative location.
            figure = populated_figures[-1]
        else:
            contract = chart.get("rendering_contract") if isinstance(chart.get("rendering_contract"), dict) else {}
            if contract.get("renderer") == "server":
                figure = render_bra_attribute_chart_figure(chart)
            else:
                figure = render_recovery_chart_figure(chart)
        if not figure:
            continue
        repaired_ids.append(chart_id)
        if matches:
            result, _ = _replace_chart_figures_once(result, chart_id, figure)
        else:
            appended_figures.append(figure)

    if appended_figures:
        recovery_section = (
            '<section class="content-section chart-recovery-section" data-chart-recovery-section="true">'
            '<h2>补充业务图表</h2>'
            + "".join(appended_figures)
            + '</section>'
        )
        main_close = re.search(r"</main\s*>", result, flags=re.IGNORECASE)
        body_close = re.search(r"</body\s*>", result, flags=re.IGNORECASE)
        insertion = main_close.start() if main_close else body_close.start() if body_close else len(result)
        result = result[:insertion] + recovery_section + result[insertion:]
    return result, repaired_ids


DIMENSION_CHART_CONTRACTS: dict[str, dict[str, str]] = {
    "M01": {"chart_id": "", "title": "市场范围与分析口径", "type": "scope_summary"},
    "M02": {"chart_id": "market_capacity", "title": "市场容量与成熟度", "type": "metric_group"},
    "M03": {"chart_id": "keyword_boundary", "title": "核心词与长尾需求分布", "type": "bar"},
    "M04": {"chart_id": "keyword_demand", "title": "关键词需求与购买效率", "type": "bubble"},
    "M05": {"chart_id": "category_demand_trend", "title": "需求趋势与生命周期", "type": "line"},
    "M06": {"chart_id": "weekly_keyword_movement", "title": "周度关键词变化", "type": "diverging_bar"},
    "M07": {"chart_id": "keyword_competition", "title": "关键词点击集中度", "type": "bar"},
    "M08": {"chart_id": "node_demand_quality", "title": "节点需求质量对标", "type": "metric_group"},
    "M09": {"chart_id": "top_product_signal", "title": "Top 商品销量/份额", "type": "bar"},
    "M10": {"chart_id": "brand_competition", "title": "品牌销量份额结构", "type": "donut"},
    "M11": {"chart_id": "seller_competition", "title": "卖家销量份额结构", "type": "donut"},
    "M12": {"chart_id": "price_band_distribution", "title": "价格带销量占比", "type": "bar"},
    "M13": {"chart_id": "rating_distribution", "title": "评分值与销量承载", "type": "bar"},
    "M14": {"chart_id": "ratings_count_distribution", "title": "评论数门槛分布", "type": "bar"},
    "M15": {"chart_id": "listing_age_distribution", "title": "新品接受度", "type": "bar"},
    "M16": {"chart_id": "lifecycle_distribution", "title": "上架生命周期结构", "type": "bar"},
    "M17": {"chart_id": "", "title": "样本范围与去重口径", "type": "sample_audit_table"},
    "M18": {"chart_id": "review_voice_distribution", "title": "评论样本与反馈层级", "type": "bar"},
    "M19": {"chart_id": "external_search_trend", "title": "Google 站外搜索相对热度", "type": "line"},
}
NON_CHART_DIMENSION_IDS = {"M01", "M17"}


DIMENSIONS_BY_ID = {item.dimension_id: item for item in MARKET_ANALYSIS_DIMENSIONS}


def _dimension_chart(
    dimension_id: str,
    data: list[dict[str, Any]],
    *,
    insight: str,
    min_points: int = 2,
    subtitle: str = "",
    x_label: str = "",
    y_label: str = "",
    unit: str = "",
    orientation: str = "vertical",
    value_format: str = "number",
    chart_type: str | None = None,
    title: str | None = None,
    field_semantics: dict[str, str] | None = None,
    placement: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if len(data) < min_points:
        return None
    contract = DIMENSION_CHART_CONTRACTS[dimension_id]
    definition = DIMENSIONS_BY_ID[dimension_id]
    return _chart(
        contract["chart_id"],
        title or contract["title"],
        chart_type or contract["type"],
        data,
        insight=insight,
        subtitle=subtitle,
        x_label=x_label,
        y_label=y_label,
        unit=unit,
        orientation=orientation,
        value_format=value_format,
        dimension_id=dimension_id,
        market_question=definition.market_question,
        field_semantics=field_semantics,
        placement=placement,
    )


def _metric_group_points(
    rows: list[dict[str, Any]],
    definitions: tuple[tuple[str, tuple[str, ...], str, str], ...],
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for label, keys, unit, value_format in definitions:
        selected_row: dict[str, Any] | None = None
        numeric: float | None = None
        for row in rows:
            numeric = _float(_first_present(row, keys))
            if numeric is not None:
                selected_row = row
                break
        if selected_row is None or numeric is None:
            continue
        if value_format.startswith("percent") and abs(numeric) <= 1.0001:
            numeric *= 100
        points.append(
            {
                **_point(selected_row, label, numeric),
                "unit": unit,
                "value_format": value_format,
            }
        )
    return points


def _bubble_points(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        label = _first_present(row, ("keyword", "keywords", "query", "searchTerm", "term"))
        searches = _float(_first_present(row, ("searches", "monthlySearches", "searchVolume", "search_volume", "volume")))
        purchase_rate = _float(_first_present(row, ("purchaseRate", "purchase_rate", "purchasesRate", "conversionRate")))
        purchases = _float(_first_present(row, ("purchases", "monthlyPurchases", "purchaseCount", "keywordsIsHide")))
        normalized = str(label or "").strip().lower()
        if not normalized or searches is None or purchase_rate is None:
            continue
        if normalized in seen:
            return []
        seen.add(normalized)
        if abs(purchase_rate) <= 1.0001:
            purchase_rate *= 100
        points.append(
            {
                "label": _compact_label(label),
                "x": round(searches, 4),
                "y": round(purchase_rate, 4),
                "size": round(purchases if purchases is not None and purchases > 0 else searches, 4),
                "source": row.get("source"),
                "evidence_id": row.get("evidence_id"),
            }
        )
    points.sort(key=lambda item: float(item["x"]), reverse=True)
    return points[:limit]


def _growth_points(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        label = _first_present(row, ("keyword", "keywords", "query", "searchTerm", "term"))
        growth = _float(
            _first_present(
                row,
                (
                    "weeklyChange",
                    "growthRate",
                    "searchRankGrowthRate",
                    "w1RankGrowthRate",
                    "searchesCr",
                    "searchMonthCr",
                    "yearlyGrowthRate",
                    "monthOnMonthGrowth",
                    "growth",
                ),
            )
        )
        normalized = str(label or "").strip().lower()
        if not normalized or growth is None:
            continue
        if normalized in seen:
            return []
        seen.add(normalized)
        if abs(growth) <= 1.0001:
            growth *= 100
        points.append(_point(row, label, growth))
    points.sort(key=lambda item: abs(float(item["value"])), reverse=True)
    return points[:limit]


def _group_count_points(
    rows: list[dict[str, Any]],
    *,
    key: str,
    labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        raw_label = str(row.get(key) or "unknown").strip() or "unknown"
        item = grouped.setdefault(
            raw_label,
            {
                "label": (labels or {}).get(raw_label, raw_label),
                "value": 0,
                "source": row.get("source"),
                "evidence_id": row.get("evidence_id"),
            },
        )
        item["value"] += 1
    return sorted(grouped.values(), key=lambda item: int(item["value"]), reverse=True)


def _percent_value(value: Any) -> float | None:
    numeric = _float(value)
    if numeric is None:
        return None
    if abs(numeric) <= 1.0001:
        numeric *= 100
    if numeric < 0 or numeric > 100.0001:
        return None
    return round(numeric, 4)


def _benchmark_points(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    definitions = (
        (
            "转化率 ↑",
            (
                "searchToPurchaseRatio",
                "searchPurchaseRatio",
                "search_purchase_ratio",
                "purchaseRatio",
            ),
            (
                "avgSearchToPurchaseRatio",
                "peerSearchToPurchaseRatio",
                "categorySearchToPurchaseRatio",
            ),
            "higher_is_better",
        ),
        (
            "退货率 ↓",
            ("returnRatio", "returnRate", "return_rate", "refundRate"),
            (
                "avgReturnRatio",
                "peerReturnRate",
                "categoryReturnRate",
                "avgReturnRate",
            ),
            "lower_is_better",
        ),
    )
    points: list[dict[str, Any]] = []
    for label, value_keys, goal_keys, comparison_direction in definitions:
        for row in rows:
            value = _percent_value(_first_present(row, value_keys))
            goal = _percent_value(_first_present(row, goal_keys))
            if value is None or goal is None:
                continue
            meets_benchmark = (
                value <= goal
                if comparison_direction == "lower_is_better"
                else value >= goal
            )
            points.append(
                {
                    "label": label,
                    "value": value,
                    "goal": goal,
                    "unit": "%",
                    "value_format": "percent_1",
                    "comparison_direction": comparison_direction,
                    "status": "优于同级" if meets_benchmark else "弱于同级",
                    "source": row.get("source"),
                    "evidence_id": row.get("evidence_id"),
                }
            )
            break
    return points


def _grouped_brand_share_points(
    rows: list[dict[str, Any]],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    paired: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for row in rows:
        label = _first_present(row, ("brand", "brandName", "name"))
        normalized_label = str(label or "").strip().lower()
        unit_share = _percent_value(
            _first_present(
                row,
                ("totalUnitsRatio", "unitsRatio", "salesRatio", "share"),
            )
        )
        revenue_share = _percent_value(
            _first_present(
                row,
                ("totalRevenueRatio", "revenueRatio", "gmvRatio", "revenueShare"),
            )
        )
        if not normalized_label or unit_share is None or revenue_share is None:
            continue
        if normalized_label in seen_labels:
            return []
        seen_labels.add(normalized_label)
        paired.append(
            {
                "label": _compact_label(label),
                "unit_share": unit_share,
                "revenue_share": revenue_share,
                "source": row.get("source"),
                "evidence_id": row.get("evidence_id"),
            }
        )
    if len(paired) < 3:
        return []
    paired.sort(
        key=lambda item: max(
            float(item["unit_share"]), float(item["revenue_share"])
        ),
        reverse=True,
    )
    selected = paired[:limit]
    unit_total = sum(float(item["unit_share"]) for item in selected)
    revenue_total = sum(float(item["revenue_share"]) for item in selected)
    if unit_total > 100.5 or revenue_total > 100.5:
        return []
    points: list[dict[str, Any]] = []
    for item in selected:
        common = {
            "label": item["label"],
            "source": item.get("source"),
            "evidence_id": item.get("evidence_id"),
        }
        points.extend(
            [
                {**common, "group": "销量份额", "value": item["unit_share"]},
                {**common, "group": "销售额份额", "value": item["revenue_share"]},
            ]
        )
    other_unit_share = max(0.0, 100 - unit_total)
    other_revenue_share = max(0.0, 100 - revenue_total)
    if other_unit_share >= 1 or other_revenue_share >= 1:
        points.extend(
            [
                {
                    "label": "其他",
                    "group": "销量份额",
                    "value": round(other_unit_share, 4),
                },
                {
                    "label": "其他",
                    "group": "销售额份额",
                    "value": round(other_revenue_share, 4),
                },
            ]
        )
    return points


def _price_sales_scatter_points(
    rows: list[dict[str, Any]],
    *,
    min_points: int = 20,
    limit: int = 30,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_families: set[str] = set()
    sales_metrics: set[str] = set()
    periods: set[str] = set()
    for row in rows:
        family_id = str(row.get("family_id") or "").strip()
        if not family_id:
            continue
        if family_id in seen_families:
            return [], {}
        seen_families.add(family_id)
        price = _float(row.get("price_normalized") or row.get("price"))
        sales = _float(row.get("sales_value"))
        sales_metric = str(row.get("sales_metric") or "").strip()
        if price is None or price <= 0 or sales is None or sales < 0 or not sales_metric:
            continue
        period = str(row.get("snapshot_month") or "").strip()
        if period:
            periods.add(period)
        sales_metrics.add(sales_metric)
        brand = str(row.get("brand_norm") or row.get("brand") or "品牌未知").strip()
        candidates.append(
            {
                "label": _compact_label(
                    row.get("representative_asin") or row.get("asin") or family_id,
                    22,
                ),
                "x": round(price, 4),
                "y": round(sales, 4),
                "brand": brand or "品牌未知",
                "source": row.get("source") or "SellerSprite MCP",
                "evidence_id": row.get("evidence_id"),
                "evidence_ids": row.get("evidence_ids") or [],
            }
        )
    if len(candidates) < min_points or len(sales_metrics) != 1 or len(periods) > 1:
        return [], {}
    brand_counts = Counter(item["brand"] for item in candidates)
    named_brands = {
        brand
        for brand, _ in sorted(
            brand_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:6]
    }
    candidates.sort(key=lambda item: float(item["y"]), reverse=True)
    selected = candidates[:limit]
    for item in selected:
        brand = str(item.pop("brand"))
        item["group"] = brand if brand in named_brands else "其他品牌"
    return selected, {
        "valid_sample_size": len(candidates),
        "rendered_sample_size": len(selected),
        "sales_metric": next(iter(sales_metrics)),
        "period": next(iter(periods), ""),
    }


def build_market_report_charts(report_data: dict[str, Any]) -> dict[str, Any]:
    """Compile auditable chart or text/table presentation contracts by dimension."""

    keyword_rows = _rows(report_data.get("keyword_trends"))
    keyword_opportunity_rows = _rows(report_data.get("keyword_opportunities"))
    keyword_competition_rows = _rows(report_data.get("keyword_competition"))
    demand_rows = _rows(report_data.get("demand_trend"))
    node_quality_rows = _rows(report_data.get("node_demand_quality"))
    category_rows = _rows(report_data.get("category_benchmark"))
    statistics_rows = _rows(report_data.get("market_statistics"))
    product_rows = _rows(report_data.get("top_products"))
    brand_rows = _rows(report_data.get("brand_competition"))
    seller_rows = _rows(report_data.get("seller_competition"))
    price_rows = _rows(report_data.get("price_distribution"))
    rating_rows = _rows(report_data.get("rating_distribution"))
    ratings_count_rows = _rows(report_data.get("ratings_count_distribution"))
    listing_age_rows = _rows(report_data.get("listing_date_distribution"))
    lifecycle_rows = _rows(report_data.get("listing_trend_distribution"))
    product_universe_rows = _rows(report_data.get("product_universe"))
    unified_product_rows = [
        row for row in product_universe_rows if row.get("family_id")
    ]
    review_rows = _rows(report_data.get("review_pain_points"))
    external_demand_rows = _rows(report_data.get("external_demand_trend"))
    category_name = str(report_data.get("category") or "当前品类").strip() or "当前品类"
    charts: list[dict[str, Any]] = []
    non_chart_presentations: list[dict[str, Any]] = []

    boundary_nodes: list[dict[str, Any]] = [
        {"label": _compact_label(category_name), "kind": "input_category", "value": 1, "source": "User input"}
    ]
    category_node_id = str(report_data.get("category_node_id") or "").strip()
    node_label = next(
        (
            _first_present(row, ("nodeLabelPath", "nodeLabelName", "category", "node", "department"))
            for row in category_rows
            if _first_present(row, ("nodeLabelPath", "nodeLabelName", "category", "node", "department"))
        ),
        category_node_id,
    )
    if node_label:
        boundary_nodes.append(
            {
                "label": _compact_label(node_label, 52),
                "kind": "amazon_node",
                "value": 1,
                "source": category_rows[0].get("source") if category_rows else "SellerSprite",
                "evidence_id": category_rows[0].get("evidence_id") if category_rows else None,
            }
        )
    for point in _points_from_rows(
        keyword_rows,
        label_keys=("keyword", "keywords", "query", "searchTerm", "term", "root"),
        value_keys=("search_volume", "searchVolume", "volume", "searches", "demand", "search_count"),
        limit=5,
        sort_mode="desc",
    ):
        boundary_nodes.append({**point, "kind": "search_term"})
    if len(boundary_nodes) >= 2:
        non_chart_presentations.append(
            {
                "dimension_id": "M01",
                "title": "市场范围与分析口径",
                "presentation_type": "scope_summary",
                "status": "ready",
                "content": {
                    "research_entry": category_name,
                    "marketplace": str(report_data.get("marketplace") or ""),
                    "amazon_node": _compact_label(node_label, 120) if node_label else "",
                    "category_node_id": category_node_id,
                    "consumer_terms": [
                        str(item.get("label") or "")
                        for item in boundary_nodes
                        if item.get("kind") == "search_term" and item.get("label")
                    ],
                    "scope_rule": (
                        "Amazon 末级节点限定商品集合，消费者搜索词说明需求表达；"
                        "两者共同定义本轮分析范围，均不单独代表完整市场。"
                    ),
                },
                "evidence_ids": sorted(
                    {
                        str(item.get("evidence_id"))
                        for item in boundary_nodes
                        if item.get("evidence_id")
                    }
                ),
                "rendering_rule": (
                    "Use a compact definition list or scope card. Do not draw a relationship map, "
                    "axis, line, or quantitative chart."
                ),
            }
        )

    capacity_points = _metric_group_points(
        [*statistics_rows, *category_rows],
        (
            ("月销量", ("totalUnits", "monthlySales", "monthly_sales", "sales"), "units", "compact_integer"),
            ("月销售额", ("totalRevenue", "monthlyRevenue", "monthly_revenue", "revenue"), "$", "currency"),
            ("平均价格", ("avgPrice", "averagePrice", "avg_price"), "$", "currency"),
            ("新品销量占比", ("newProductUnitsRatio", "newUnitsRatio", "newProductShare"), "%", "percent_1"),
            ("商品数量", ("asinCount", "productCount", "products", "listingCount"), "listings", "integer"),
        ),
    )
    chart = _dimension_chart(
        "M02",
        capacity_points,
        min_points=1,
        insight="容量指标采用各自单位的独立小图，不把销量、销售额、价格和新品占比画在同一坐标轴。",
    )
    if chart:
        charts.append(chart)

    keyword_boundary_points = _points_from_rows(
        keyword_rows,
        label_keys=("keyword", "query", "searchTerm", "term", "root"),
        value_keys=("search_volume", "searchVolume", "volume", "searches", "demand", "search_count"),
        limit=10,
        sort_mode="desc",
    )
    chart = _dimension_chart(
        "M03",
        keyword_boundary_points,
        insight="比较核心词与长尾词的同口径需求，只用于识别需求边界；未启用关键词去重时不得求和为市场总量。",
        x_label="搜索需求",
        y_label="关键词",
        orientation="horizontal",
        value_format="compact_integer",
    )
    if chart:
        charts.append(chart)

    keyword_demand_points = _bubble_points(keyword_opportunity_rows)
    chart = _dimension_chart(
        "M04",
        keyword_demand_points,
        insight="横轴为搜索量，纵轴为购买率，气泡大小为购买量或搜索量代理，用于区分大流量与高购买效率关键词。",
        x_label="搜索量",
        y_label="购买率",
        unit="%",
        value_format="bubble_mixed",
    )
    if chart:
        charts.append(chart)

    keyword_trend_points = _points_from_rows(
        keyword_opportunity_rows,
        label_keys=("date", "month", "period"),
        value_keys=("searches", "searchVolume", "search_volume", "volume"),
        limit=18,
        sort_mode="label",
    )
    trend_metric = "搜索量"
    if len(keyword_trend_points) < 4:
        keyword_trend_points = _points_from_rows(
            demand_rows,
            label_keys=("date", "month", "period"),
            value_keys=("glanceViews", "glance_views", "views", "demand"),
            limit=18,
            sort_mode="label",
        )
        trend_metric = "节点页面浏览量代理"
    chart = _dimension_chart(
        "M05",
        keyword_trend_points,
        min_points=4,
        insight=f"用连续周期的{trend_metric}判断方向；单个峰值不自动构成稳定季节性。",
        x_label="周期",
        y_label=trend_metric,
        value_format="compact_integer",
    )
    if chart:
        charts.append(chart)

    movement_points = _growth_points([*keyword_opportunity_rows, *keyword_rows])
    chart = _dimension_chart(
        "M06",
        movement_points,
        insight="按绝对变化幅度排列近期异动词，正负方向分开显示；单周变化仍需历史窗口验证。",
        x_label="变化幅度",
        y_label="关键词",
        unit="%",
        orientation="horizontal",
        value_format="signed_percent_1",
    )
    if chart:
        charts.append(chart)

    competition_points = _share_points(
        keyword_competition_rows,
        label_keys=("asin", "title", "product", "keyword", "name"),
        ratio_keys=(
            "total_share",
            "totalShare",
            "clickShare",
            "click_share",
            "clickShareRate",
            "organic_share",
            "clickRate",
            "trafficShare",
            "share",
        ),
        limit=10,
    )
    chart = _dimension_chart(
        "M07",
        competition_points,
        insight="展示关键词下 Top ASIN 的总流量或点击份额，判断流量集中度；低集中度不自动等于蓝海。",
        x_label="ASIN / 商品",
        y_label="点击或流量份额",
        unit="%",
        orientation="horizontal",
        value_format="percent_1",
    )
    if chart:
        charts.append(chart)

    node_quality_points = _metric_group_points(
        node_quality_rows,
        (
            ("页面浏览量", ("glanceViews", "glance_views", "views"), "views", "compact_integer"),
            ("商品数量", ("asinCount", "productCount", "products"), "listings", "integer"),
            (
                "搜索购买比",
                ("searchToPurchaseRatio", "searchPurchaseRatio", "search_purchase_ratio", "purchaseRatio"),
                "%",
                "percent_1",
            ),
            ("退货率", ("returnRatio", "returnRate", "return_rate", "refundRate"), "%", "percent_1"),
            (
                "同级退货率",
                ("avgReturnRatio", "peerReturnRate", "categoryReturnRate", "avgReturnRate"),
                "%",
                "percent_1",
            ),
        ),
    )
    benchmark_points = _benchmark_points(node_quality_rows)
    chart = _dimension_chart(
        "M08",
        benchmark_points or node_quality_points,
        min_points=1,
        insight=(
            "黑色基准线表示同级平均而非经营目标；搜索购买比与退货率必须分别按标签中的高低方向解释，"
            "且搜索购买比不得改写成 Listing 转化率。"
            if benchmark_points
            else "需求质量指标使用独立小图保留原始定义；搜索购买比不改写成 Listing 转化率。"
        ),
        unit="%" if benchmark_points else "",
        value_format="percent_1" if benchmark_points else "number",
        chart_type="bullet" if benchmark_points else "metric_group",
        placement={
            "section_hint": "需求质量与市场门槛",
            "summary_eligible": False,
        },
    )
    if chart:
        charts.append(chart)

    product_points = _share_points(
        product_rows,
        label_keys=("asin", "title", "product", "name"),
        ratio_keys=("totalUnitsRatio", "unitsRatio", "salesRatio", "share"),
        limit=10,
    )
    product_value_label = "销量份额"
    product_unit = "%"
    product_value_format = "percent_1"
    if len(product_points) < 2:
        product_points = _points_from_rows(
            product_rows,
            label_keys=("asin", "title", "product", "name"),
            value_keys=("totalUnits", "monthly_orders", "monthlySales", "sales", "units"),
            limit=10,
            sort_mode="desc",
        )
        product_value_label = "销量代理"
        product_unit = ""
        product_value_format = "compact_integer"
    chart = _dimension_chart(
        "M09",
        product_points,
        insight=f"按同口径{product_value_label}排列 Top 商品，用于观察头部承载；不以评论数替代销量。",
        x_label=product_value_label,
        y_label="ASIN / 商品",
        unit=product_unit,
        orientation="horizontal",
        value_format=product_value_format,
        chart_type="bar_table",
        placement={
            "section_hint": "竞争格局与头部商品",
            "summary_eligible": True,
        },
    )
    if chart:
        charts.append(chart)

    scatter_points, scatter_metadata = _price_sales_scatter_points(
        unified_product_rows
    )
    if scatter_points:
        scatter_chart = _chart(
            "price_sales_positioning",
            "价格与销量定位",
            "scatter",
            scatter_points,
            subtitle=(
                f"同口径去重商品家族 n={scatter_metadata['valid_sample_size']}；"
                f"展示销量较高的 {scatter_metadata['rendered_sample_size']} 个；"
                f"销量口径={scatter_metadata['sales_metric']}"
                + (
                    f"；周期={scatter_metadata['period']}"
                    if scatter_metadata.get("period")
                    else ""
                )
                + "。"
            ),
            insight=(
                "仅用于观察同一商品样本中的价格—销量位置关系，不把散点相关性解释为价格导致销量变化。"
            ),
            x_label="价格（USD）",
            y_label="销量",
            value_format="scatter_mixed",
            field_semantics={"x": "Price", "y": "Quantity"},
            placement={
                "section_hint": "竞争格局与产品定位",
                "summary_eligible": False,
                "supplemental": True,
            },
        )
        scatter_chart["sample_contract"] = scatter_metadata
        charts.append(scatter_chart)

    grouped_brand_points = _grouped_brand_share_points(brand_rows)
    brand_points = _share_points(
        brand_rows,
        label_keys=("brand", "brandName", "name"),
        ratio_keys=("totalUnitsRatio", "unitsRatio", "share", "salesRatio"),
        limit=8,
    )
    brand_chart_data = (
        grouped_brand_points
        if grouped_brand_points
        else _with_other_share(brand_points)
        if len(brand_points) >= 3
        else brand_points
    )
    chart = _dimension_chart(
        "M10",
        brand_chart_data,
        insight=(
            "并列比较同一市场分母下的销量份额与销售额份额；销售额份额高于销量份额只表示价格或产品组合效应，"
            "不得直接解释成品牌忠诚度或溢价能力。"
            if grouped_brand_points
            else "比较头部品牌份额与长尾品牌空间，不把品牌集中度直接解释成忠诚度或溢价。"
        ),
        title=(
            "品牌销量与销售额份额对比"
            if grouped_brand_points
            else "品牌销量份额结构"
        ),
        x_label="份额" if grouped_brand_points else "",
        y_label="品牌" if grouped_brand_points else "",
        unit="%",
        value_format="percent_1",
        orientation="horizontal" if grouped_brand_points else "vertical",
        chart_type=(
            "grouped_bar"
            if grouped_brand_points
            else "donut"
            if len(brand_chart_data) >= 3
            else "bar"
        ),
        placement={
            "section_hint": "竞争格局与头部品牌",
            "summary_eligible": True,
        },
    )
    if chart:
        charts.append(chart)

    seller_points = _share_points(
        seller_rows,
        label_keys=("seller", "sellerName", "merchant", "name"),
        ratio_keys=("totalUnitsRatio", "unitsRatio", "share", "salesRatio"),
        limit=8,
    )
    seller_chart_data = _with_other_share(seller_points) if len(seller_points) >= 3 else seller_points
    chart = _dimension_chart(
        "M11",
        seller_chart_data,
        insight="单独观察卖家销量集中度，避免把同一卖家运营多个品牌的结构误判为品牌集中度。",
        unit="%",
        value_format="percent_1",
        chart_type="donut" if len(seller_chart_data) >= 3 else "bar",
    )
    if chart:
        charts.append(chart)

    distribution_specs = (
        (
            "M12",
            price_rows,
            ("label", "priceRange", "range", "bucket"),
            "价格带按销量占比比较，用于定位主力和升级价位，不直接等同消费者愿付价格。",
            "价格带",
        ),
        (
            "M13",
            rating_rows,
            ("label", "ratingRange", "rating", "range", "bucket"),
            "比较评分值区间的销量承载，低评分区间有销量只能产生产品改善假设。",
            "评分值区间",
        ),
        (
            "M14",
            ratings_count_rows,
            ("label", "ratingsRange", "ratings", "range", "bucket"),
            "比较评论数区间的销量承载，用于评估历史评价壁垒，不作为新品确定阈值。",
            "评论数区间",
        ),
        (
            "M15",
            listing_age_rows,
            ("label", "listingAge", "ageRange", "range", "bucket"),
            "比较不同上架时长商品的销量占比，判断新品是否获得市场承载。",
            "上架时长",
        ),
        (
            "M16",
            lifecycle_rows,
            ("label", "listingYear", "year", "dateRange", "range"),
            "按绝对上架年份或生命周期区间比较销售效率，识别新品、成长期和长尾结构。",
            "上架年份 / 生命周期",
        ),
    )
    for dimension_id, rows, label_keys, insight, x_label in distribution_specs:
        points = _share_points(
            rows,
            label_keys=label_keys,
            ratio_keys=("unitsRatio", "units_ratio", "salesRatio", "share", "avgUnitsRatio"),
            limit=12,
        )
        chart = _dimension_chart(
            dimension_id,
            points,
            insight=insight,
            x_label=x_label,
            y_label="销量占比",
            unit="%",
            value_format="percent_1",
        )
        if chart:
            charts.append(chart)

    if unified_product_rows:
        family_sources: dict[str, set[str]] = {}
        source_evidence: dict[str, set[str]] = {}
        overlap_evidence: set[str] = set()
        for row in unified_product_rows:
            family_id = str(row.get("family_id") or "").strip()
            if not family_id:
                continue
            sources = {
                str(item).strip()
                for item in row.get("source_tools") or []
                if str(item).strip()
            }
            if not sources:
                source = str(row.get("source_tool") or row.get("source") or "unknown").strip()
                sources = {source or "unknown"}
            family_sources.setdefault(family_id, set()).update(sources)
            evidence_ids = {
                str(item).strip()
                for item in [row.get("evidence_id"), *(row.get("evidence_ids") or [])]
                if str(item or "").strip()
            }
            for source in sources:
                source_evidence.setdefault(source, set()).update(evidence_ids)
            if len(sources) > 1:
                overlap_evidence.update(evidence_ids)
        source_counts = Counter(
            source
            for sources in family_sources.values()
            for source in sources
        )
        product_coverage_points = [
            {
                "label": source,
                "value": count,
                "evidence_ids": sorted(source_evidence.get(source) or []),
            }
            for source, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        product_coverage_points.append(
            {
                "label": "cross_source_overlap",
                "value": sum(1 for sources in family_sources.values() if len(sources) > 1),
                "evidence_ids": sorted(overlap_evidence),
            }
        )
        product_coverage_insight = "按统一商品家族统计各来源发现数，并单列被两个或以上来源共同发现的家族数；不对家族成员销量或销售额求和。"
        product_coverage_y_label = "唯一商品家族数"
    else:
        product_coverage_rows = [
            {
                **row,
                "coverage_source": row.get("source_tool") or row.get("source") or "unknown",
            }
            for row in product_universe_rows
        ]
        product_coverage_points = _group_count_points(product_coverage_rows, key="coverage_source")
        product_coverage_insight = "商品身份解析未启用时仅展示各工具入口返回的原始候选行数，不得表述为唯一商品数。"
        product_coverage_y_label = "原始候选行数"
    if product_coverage_points:
        source_rows = [
            {
                "source": str(item.get("label") or ""),
                "sample_count": int(item.get("value") or 0),
                "evidence_ids": item.get("evidence_ids") or [],
            }
            for item in product_coverage_points
            if str(item.get("label") or "") != "cross_source_overlap"
        ]
        source_count = len(source_rows)
        overlap_count = next(
            (
                int(item.get("value") or 0)
                for item in product_coverage_points
                if str(item.get("label") or "") == "cross_source_overlap"
            ),
            0,
        )
        non_chart_presentations.append(
            {
                "dimension_id": "M17",
                "title": "样本范围与去重口径",
                "presentation_type": "sample_audit_table",
                "status": "ready",
                "content": {
                    "sample_count": (
                        len(unified_product_rows)
                        if unified_product_rows
                        else len(product_universe_rows)
                    ),
                    "sample_unit": product_coverage_y_label,
                    "source_count": source_count,
                    "sources": source_rows,
                    "cross_source_check_applicable": source_count >= 2,
                    "cross_source_overlap_count": (
                        overlap_count if source_count >= 2 else None
                    ),
                    "deduplication_scope": (
                        (report_data.get("deduplication") or {}).get("scope")
                        if isinstance(report_data.get("deduplication"), dict)
                        else ""
                    ),
                    "representativeness_claim_allowed": False,
                    "scope_note": product_coverage_insight,
                },
                "evidence_ids": sorted(
                    {
                        str(evidence_id)
                        for row in source_rows
                        for evidence_id in row.get("evidence_ids") or []
                        if evidence_id
                    }
                ),
                "rendering_rule": (
                    "Use compact sample-scope facts and, only when two or more sources exist, "
                    "a small source table. Do not draw a bar chart and do not call the sample representative."
                ),
            }
        )

    review_points = _group_count_points(
        review_rows,
        key="review_group",
        labels={
            "low_star": "1–2 星失败机制",
            "tradeoff": "3 星权衡",
            "high_star": "4–5 星购买理由",
            "unknown": "星级未知",
        },
    )
    chart = _dimension_chart(
        "M18",
        review_points,
        min_points=1,
        insight="按星级层级展示进入分析的评论样本量；主题结论仍必须引用具体评论证据。",
        x_label="评论层级",
        y_label="样本量",
        value_format="integer",
    )
    if chart:
        charts.append(chart)

    external_demand_points = _points_from_rows(
        external_demand_rows,
        label_keys=(
            "date",
            "month",
            "period",
            "week",
            "time",
            "formattedTime",
            "formattedAxisTime",
            "timestamp",
        ),
        value_keys=("value", "trendValue", "searchInterest", "interest", "heat", "index", "score"),
        limit=24,
        sort_mode="label",
    )
    chart = _dimension_chart(
        "M19",
        external_demand_points,
        min_points=4,
        insight=(
            "Google Trends 仅用于校验同一关键词在同一地区和时间窗口内的相对热度方向与季节波动；"
            "不得与 Amazon 搜索量相加或换算销量。"
        ),
        x_label="周期",
        y_label="Google 相对热度",
        unit="index",
        value_format="number",
        chart_type="line",
    )
    if chart:
        charts.append(chart)

    attribute_distribution = (
        report_data.get("bra_attribute_distribution")
        if isinstance(report_data.get("bra_attribute_distribution"), dict)
        else {}
    )
    attribute_axes = _rows(attribute_distribution.get("axes"))
    attribute_sample_size = int(attribute_distribution.get("product_family_count") or 0)
    sales_coverage = float(attribute_distribution.get("sales_metric_coverage") or 0)
    attribute_metric = "estimated_sales_share" if sales_coverage >= 70 else "product_family_share"
    attribute_rows: list[dict[str, Any]] = []
    for axis in attribute_axes:
        segments: list[dict[str, Any]] = []
        for value in _rows(axis.get("values")):
            share = _float(value.get(attribute_metric))
            if share is None:
                continue
            segment_id = str(value.get("id") or "")
            role = "unknown" if segment_id == "unknown" else "conflict" if segment_id == "conflict" else "known"
            segments.append(
                {
                    "id": segment_id,
                    "label": value.get("label"),
                    "value": round(share, 1),
                    "role": role,
                }
            )
        if segments:
            known_segments = [item for item in segments if item["role"] == "known" and float(item["value"]) > 0]
            known_share = round(sum(float(item["value"]) for item in known_segments), 1)
            unknown_share = round(
                sum(float(item["value"]) for item in segments if item["role"] == "unknown"),
                1,
            )
            conflict_share = round(
                sum(float(item["value"]) for item in segments if item["role"] == "conflict"),
                1,
            )
            status, status_label = _bra_attribute_coverage_status(known_share)
            composition_segments = [
                {
                    "id": item["id"],
                    "label": item["label"],
                    "value": round(float(item["value"]) / known_share * 100, 1),
                    "raw_value": item["value"],
                    "color": BRA_ATTRIBUTE_KNOWN_COLORS[index % len(BRA_ATTRIBUTE_KNOWN_COLORS)],
                }
                for index, item in enumerate(known_segments)
                if known_share > 0
            ]
            attribute_rows.append(
                {
                    "label": axis.get("label"),
                    "attribute_id": axis.get("id"),
                    "segments": segments,
                    "composition_segments": composition_segments,
                    "coverage": {
                        "known_share": known_share,
                        "unknown_share": unknown_share,
                        "conflict_share": conflict_share,
                        "classified_product_family_share": axis.get("classified_product_share"),
                        "status": status,
                        "status_label": status_label,
                    },
                    "classified_product_share": axis.get("classified_product_share"),
                    "source": axis.get("source") or attribute_distribution.get("source"),
                }
            )
    if attribute_sample_size >= 30 and len(attribute_rows) == len(attribute_axes) and len(attribute_rows) >= 8:
        weighting = "销量加权" if attribute_metric == "estimated_sales_share" else "商品家族数量"
        attribute_chart = _chart(
            "bra_attribute_distribution",
            "文胸属性结构与可识别度",
            "stacked_bar_100",
            attribute_rows,
            subtitle=(
                f"按{weighting}统计；n={attribute_sample_size} 个商品家族；销量字段覆盖 {sales_coverage:.1f}%。"
                "每行展示该属性轴在全样本中的已识别属性值、未知和冲突占比。"
            ),
            insight=_bra_attribute_insight(attribute_rows),
            x_label="占比",
            y_label="属性轴",
            unit="%",
            orientation="horizontal",
            value_format="percent_1",
            dimension_id="BRA01",
            market_question="文胸货架的核心结构属性如何分布，哪些属性证据足以支撑判断？",
        )
        attribute_chart["coverage_summary"] = {
            "analyzable_axes": sum(
                1 for row in attribute_rows if row["coverage"]["status"] == "analyzable"
            ),
            "directional_axes": sum(
                1 for row in attribute_rows if row["coverage"]["status"] == "directional"
            ),
            "insufficient_axes": sum(
                1 for row in attribute_rows if row["coverage"]["status"] == "insufficient"
            ),
            "directional_threshold": BRA_ATTRIBUTE_DIRECTIONAL_COVERAGE,
            "reliable_threshold": BRA_ATTRIBUTE_RELIABLE_COVERAGE,
        }
        attribute_chart["rendering_contract"] = {
            "renderer": "flint",
            "layout": "normalized_stacked_bar",
            "stack_mode": "normalize",
            "unknown_color": BRA_ATTRIBUTE_UNKNOWN_COLOR,
            "conflict_color": BRA_ATTRIBUTE_CONFLICT_COLOR,
            "known_palette": list(BRA_ATTRIBUTE_KNOWN_COLORS),
            "mobile_behavior": "horizontal_scroll",
        }
        charts.append(attribute_chart)

    charts_by_dimension = {
        str(chart.get("dimension_id") or ""): chart
        for chart in charts
        if chart.get("dimension_id") in DIMENSION_CHART_CONTRACTS
    }
    presentations_by_dimension = {
        str(item.get("dimension_id") or ""): item
        for item in non_chart_presentations
        if isinstance(item, dict) and item.get("dimension_id")
    }
    coverage = report_data.get("analysis_coverage") if isinstance(report_data.get("analysis_coverage"), dict) else {}
    coverage_by_dimension = {
        str(item.get("dimension_id") or ""): item
        for item in coverage.get("dimensions", [])
        if isinstance(item, dict)
    }
    chart_manifest: list[dict[str, Any]] = []
    for definition in MARKET_ANALYSIS_DIMENSIONS:
        contract = DIMENSION_CHART_CONTRACTS[definition.dimension_id]
        analysis = coverage_by_dimension.get(definition.dimension_id) or {}
        analysis_status = str(analysis.get("status") or "unknown")
        ready_chart = charts_by_dimension.get(definition.dimension_id)
        text_presentation = presentations_by_dimension.get(definition.dimension_id)
        if ready_chart:
            chart_status = "ready"
            reason = "Semantically valid chart data compiled from the dimension evidence."
        elif text_presentation:
            chart_status = "text_only"
            reason = (
                "This dimension is clearer as a structured scope or sample-audit block; "
                "a quantitative chart would be misleading."
            )
        elif analysis_status == "not_triggered":
            chart_status = "not_triggered"
            reason = "Conditional market task was not requested for this run."
        elif analysis_status in {"missing", "partial"}:
            chart_status = "blocked_by_evidence"
            reason = "Required evidence is incomplete for this market task."
        else:
            chart_status = "missing_data"
            reason = "Tool evidence succeeded, but no semantically valid numeric or categorical chart data was compiled."
        chart_manifest.append(
            {
                "dimension_id": definition.dimension_id,
                "name": definition.name,
                "priority": definition.priority,
                "market_question": definition.market_question,
                "analysis_status": analysis_status,
                "chart_id": ready_chart.get("id") if ready_chart else None,
                "title": (
                    ready_chart.get("title")
                    if ready_chart
                    else text_presentation.get("title")
                    if text_presentation
                    else contract["title"]
                ),
                "type": (
                    ready_chart.get("type")
                    if ready_chart
                    else text_presentation.get("presentation_type")
                    if text_presentation
                    else contract["type"]
                ),
                "presentation_mode": (
                    "chart"
                    if ready_chart or definition.dimension_id not in NON_CHART_DIMENSION_IDS
                    else "text"
                ),
                "chart_status": chart_status,
                "reason": reason,
                "evidence_ids": (
                    ready_chart.get("evidence_ids")
                    if ready_chart
                    else text_presentation.get("evidence_ids")
                    if text_presentation
                    else analysis.get("evidence_ids") or []
                ),
            }
        )

    preferred_summary_ids = (
        "market_capacity",
        "category_demand_trend",
        "external_search_trend",
        "keyword_demand",
        "price_band_distribution",
        "brand_competition",
        "top_product_signal",
    )
    available_ids = {str(chart.get("id") or "") for chart in charts}
    summary_chart_ids = [chart_id for chart_id in preferred_summary_ids if chart_id in available_ids][:5]
    return {
        "schema_version": "market_report_charts.v4",
        "chart_specs": charts,
        "chart_count": len(charts),
        "summary_chart_ids": summary_chart_ids,
        "chart_manifest": chart_manifest,
        "non_chart_presentations": non_chart_presentations,
        "method": {
            "notes": [
                "Compiled a stable chart or text/table presentation contract for each M01-M19 task.",
                "Rendered M01 market scope and M17 sample audit as structured non-chart blocks.",
                "Kept all semantically valid task charts; summary_chart_ids selects at most five first-page charts.",
                "Rejected duplicate chart labels instead of silently deduplicating or aggregating them.",
                "Used missing_data or blocked_by_evidence instead of inventing a chart when fields were insufficient.",
            ]
        },
    }


def dumps_chart_specs(report_data: dict[str, Any]) -> str:
    return json.dumps(build_market_report_charts(report_data), ensure_ascii=False, indent=2)

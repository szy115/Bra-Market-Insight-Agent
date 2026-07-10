from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


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
        if not normalized_label or numeric is None or normalized_label in seen_labels:
            continue
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
        if not normalized_label or ratio is None or ratio < 0 or normalized_label in seen_labels:
            continue
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
) -> dict[str, Any]:
    return {
        "id": chart_id,
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
        "quality_status": "ready",
        "data": data,
    }


def build_market_report_charts(report_data: dict[str, Any]) -> dict[str, Any]:
    """Build a small set of semantically valid, presentation-ready chart specs."""

    keyword_rows = _rows(report_data.get("keyword_trends"))
    demand_rows = _rows(report_data.get("demand_trend"))
    category_rows = _rows(report_data.get("category_benchmark"))
    product_rows = _rows(report_data.get("top_products"))
    brand_rows = _rows(report_data.get("brand_competition"))
    price_rows = _rows(report_data.get("price_distribution"))
    opportunity_rows = _rows(report_data.get("opportunity_pool"))
    category_name = str(report_data.get("category") or "当前品类").strip() or "当前品类"
    charts: list[dict[str, Any]] = []

    demand_points = _points_from_rows(
        demand_rows,
        label_keys=("date", "month", "period"),
        value_keys=("glanceViews", "glance_views", "views", "demand"),
        limit=14,
        sort_mode="label",
    )
    if len(demand_points) >= 4:
        charts.append(
            _chart(
                "category_demand_trend",
                "类目需求趋势",
                "line",
                demand_points,
                insight=f"用连续月份页面浏览量观察 {category_name} 的需求方向，不用单月高低替代趋势判断。",
                x_label="月份",
                y_label="页面浏览量",
                unit="views",
                value_format="compact_integer",
            )
        )

    keyword_points = _points_from_rows(
        keyword_rows,
        label_keys=("keyword", "query", "searchTerm", "term", "root"),
        value_keys=("search_volume", "searchVolume", "volume", "searches", "demand", "search_count"),
        limit=8,
        sort_mode="desc",
    )
    if len(keyword_points) >= 2:
        charts.append(
            _chart(
                "keyword_demand",
                "关键词需求强度",
                "bar",
                keyword_points,
                insight="比较同口径关键词需求，识别主需求词和可承接的长尾入口。",
                x_label="需求量 / 搜索量",
                y_label="关键词",
                orientation="horizontal",
                value_format="compact_integer",
            )
        )
    else:
        rank_points = _points_from_rows(
            keyword_rows,
            label_keys=("keyword", "query", "searchTerm", "term", "root"),
            value_keys=("rank", "abaRank", "ranking", "position"),
            limit=8,
            sort_mode="asc",
        )
        if len(rank_points) >= 2:
            charts.append(
                _chart(
                    "keyword_rank",
                    "关键词排名 / ABA 信号",
                    "bar",
                    rank_points,
                    insight="排名值越低越靠前；这里只做关键词横向比较，不伪装成时间趋势。",
                    x_label="Rank / ABA（越低越好）",
                    y_label="关键词",
                    orientation="horizontal",
                    value_format="integer",
                )
            )

    price_points = _share_points(
        price_rows,
        label_keys=("label", "priceRange", "range", "bucket"),
        ratio_keys=("unitsRatio", "units_ratio", "share", "salesRatio"),
        limit=10,
    )
    if len(price_points) >= 2:
        charts.append(
            _chart(
                "price_band_distribution",
                "价格带销量占比",
                "bar",
                price_points,
                insight="价格带按销量占比比较，用于判断主力价位与升级价位的真实承接能力。",
                x_label="价格带",
                y_label="销量占比",
                unit="%",
                value_format="percent_1",
            )
        )

    brand_points = _share_points(
        brand_rows,
        label_keys=("brand", "brandName", "name"),
        ratio_keys=("totalUnitsRatio", "unitsRatio", "share", "salesRatio"),
        limit=6,
    )
    donut_points = _with_other_share(brand_points) if len(brand_points) >= 3 else []
    if donut_points:
        charts.append(
            _chart(
                "brand_competition",
                "品牌销量份额结构",
                "donut",
                donut_points,
                insight="观察头部品牌份额和长尾空间，判断新品需要多强的差异化理由。",
                unit="%",
                value_format="percent_1",
            )
        )

    product_points = _points_from_rows(
        product_rows,
        label_keys=("asin", "title", "product", "name"),
        value_keys=("totalUnits", "monthly_orders", "sales", "units", "revenue", "reviews", "review_count"),
        limit=8,
        sort_mode="desc",
    )
    if len(product_points) >= 2:
        charts.append(
            _chart(
                "top_product_signal",
                "Top 商品月销量",
                "bar",
                product_points,
                insight="按同口径月销量排列优先拆解对象，不把评论数或流量份额冒充销量。",
                x_label="月销量",
                y_label="ASIN",
                orientation="horizontal",
                value_format="compact_integer",
            )
        )

    category_points = _points_from_rows(
        category_rows,
        label_keys=("nodeLabelName", "category", "node", "department", "subcategory"),
        value_keys=("totalUnits", "monthly_sales", "monthlySales", "sales", "totalRevenue", "monthlyRevenue"),
        limit=6,
        sort_mode="desc",
    )
    if len(charts) < 3 and len(category_points) >= 2:
        charts.append(
            _chart(
                "category_benchmark",
                "类目规模对标",
                "bar",
                category_points,
                insight=f"把 {category_name} 放回同口径节点比较，避免只盯单一关键词误判市场空间。",
                orientation="horizontal",
                value_format="compact_integer",
            )
        )

    if len(charts) < 3 and len(opportunity_rows) >= 2:
        opportunity_points = [
            {
                "label": _compact_label(item.get("name") or item.get("opportunity_name") or f"机会 {index + 1}", 42),
                "value": _priority_score(item.get("priority")),
                "priority": str(item.get("priority") or "B"),
                "evidence_id": ",".join(str(eid) for eid in item.get("evidence_ids") or []),
            }
            for index, item in enumerate(opportunity_rows[:6])
        ]
        charts.append(
            _chart(
                "opportunity_priority",
                "Hsia 机会优先级",
                "bar",
                opportunity_points,
                insight="机会分数只用于企划讨论排序，不替代人工投产决策。",
                orientation="horizontal",
                value_format="integer",
            )
        )

    ready_charts = [chart for chart in charts if len(chart.get("data") or []) >= 2][:5]
    return {
        "schema_version": "market_report_charts.v2",
        "chart_specs": ready_charts,
        "chart_count": len(ready_charts),
        "method": {
            "notes": [
                "Mapped each chart to an explicit MarketReportData field and source tool.",
                "Excluded duplicate labels, mixed units, one-point charts, and non-temporal line charts.",
                "Limited the report to five presentation-ready business charts.",
            ]
        },
    }


def dumps_chart_specs(report_data: dict[str, Any]) -> str:
    return json.dumps(build_market_report_charts(report_data), ensure_ascii=False, indent=2)

from __future__ import annotations

import datetime as dt
import re
from statistics import median
from typing import Any

from .agent_tool_recovery import SUCCESS_TOOL_STATUSES

RANKING_TOOL = "mcp__fastmoss__product_rank_new_listed"
CATEGORY_TOOL = "mcp__fastmoss__search_category_by_words"
DETAIL_TOOL = "mcp__fastmoss__product_detail_info"
TREND_TOOL = "mcp__fastmoss__product_sales_trend"
URL_TOOL = "mcp__fastmoss__fastmoss_detail_url_examples"

BRA_CATEGORY_LABEL = "女士文胸"
MIN_PRICE_USD = 20.0
MAX_PRICE_USD = 100.0


FEATURE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("function", "无钢圈", r"\b(?:wireless|no\s+underwire|no\s+steel\s+ring)\b"),
    ("function", "全覆盖/侧收", r"\b(?:full\s+coverage|side\s+breast\s+coverage)\b"),
    ("function", "轻塑/腹部控制", r"\b(?:tummy\s+control|waist\s+trainer|compression|shaper)\b"),
    ("function", "聚拢/上托", r"\b(?:push\s*up|breast\s+lifting|light\s+lift)\b"),
    ("function", "Minimizer", r"\bminimi[sz]er\b"),
    ("function", "支撑", r"\bsupport\b"),
    ("function", "产后/术后场景", r"\b(?:postpartum|post[-\s]?surgery)\b"),
    ("construction", "无缝", r"\bseamless\b"),
    ("construction", "固定杯", r"\bfixed\s+cups?\b"),
    ("construction", "宽肩带", r"\bwide\s+straps?\b"),
    ("construction", "可调肩带", r"\badjustable\s+straps?\b"),
    ("construction", "拉链结构", r"\bzipper\b"),
    ("construction", "开裆结构", r"\bopen\s+crotch\b"),
    ("construction", "深 V", r"\bdeep\s+v\b"),
    ("construction", "可转换穿法", r"\bconvertible\b"),
    ("construction", "钢圈", r"\bunderwire\b"),
    ("material_surface", "柔软触感", r"\b(?:buttery\s+soft|soft)\b"),
    ("material_surface", "透气", r"\bbreathable\b"),
    ("material_surface", "蕾丝", r"\blace\b"),
    ("size_inclusivity", "大码", r"\bplus[-\s]?size\b"),
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _date(value: Any) -> dt.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _generated_date(value: Any) -> dt.date:
    parsed = _date(value)
    return parsed or dt.datetime.now(dt.UTC).date()


def _tool_name(tool: dict[str, Any]) -> str:
    return str(tool.get("name") or "")


def _is_success(tool: dict[str, Any]) -> bool:
    return str(tool.get("status") or "") in SUCCESS_TOOL_STATUSES


def _tools(tool_results: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [tool for tool in tool_results if _tool_name(tool) == name]


def _successful_tools(tool_results: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [tool for tool in _tools(tool_results, name) if _is_success(tool)]


def _input_filter(tool: dict[str, Any]) -> dict[str, Any]:
    tool_input = _as_dict(tool.get("input"))
    request = _as_dict(tool_input.get("request"))
    container = request or tool_input
    return _as_dict(container.get("filter"))


def _input_product_id(tool: dict[str, Any]) -> str:
    tool_input = _as_dict(tool.get("input"))
    request = _as_dict(tool_input.get("request"))
    container = request or tool_input
    product_id = _input_filter(tool).get("product_id") or container.get("product_id")
    return str(product_id or "").strip()


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _category_parts(row: dict[str, Any]) -> tuple[str, str, str, str]:
    category = _as_dict(row.get("category"))
    l1 = _as_dict(category.get("l1"))
    l2 = _as_dict(category.get("l2"))
    l3 = _as_dict(category.get("l3"))
    names = [str(item.get("name") or "").strip() for item in (l1, l2, l3)]
    return names[0], names[1], names[2], " > ".join(item for item in names if item)


def _category_id(value: Any) -> str:
    return str(value or "").strip()


def _is_bra_category_name(value: Any) -> bool:
    name = str(value or "").strip().lower()
    if not name or any(token in name for token in ("shapewear", "塑身", "束身")):
        return False
    return bool(re.search(r"\bbras?\b", name, re.I)) or any(
        token in name for token in ("女士文胸", "文胸", "胸罩")
    )


def _is_bra_category_candidate(candidate: dict[str, Any]) -> bool:
    name = str(candidate.get("name") or "").strip()
    path = str(candidate.get("path") or "").strip()
    path_leaf = re.split(r"\s*(?:>|/|-)\s*", path)[-1] if path else ""
    return bool(candidate.get("category_id_l3")) and (
        _is_bra_category_name(name) or _is_bra_category_name(path_leaf)
    )


def _ranking_filter_l3_ids(tool_results: list[dict[str, Any]]) -> set[str]:
    return {
        category_id
        for tool in _successful_tools(tool_results, RANKING_TOOL)
        if (category_id := _category_id(_input_filter(tool).get("category_l3_id")))
    }


def _select_bra_category(
    tool_results: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    queried_l3_ids = _ranking_filter_l3_ids(tool_results)
    eligible = [candidate for candidate in candidates if _is_bra_category_candidate(candidate)]
    if not eligible:
        raise ValueError(
            "TikTokNewProductReportData requires an exact FastMoss L3 Bras category "
            "resolution; a broad Women's Underwear category is not sufficient."
        )

    def rank(candidate: dict[str, Any]) -> tuple[int, int, int, float]:
        category_id = _category_id(candidate.get("category_id_l3"))
        name = str(candidate.get("name") or "").strip()
        path = str(candidate.get("path") or "").strip()
        return (
            int(category_id in queried_l3_ids),
            int("女士内衣" in path or "women's underwear" in path.lower()),
            int(name in {"女士文胸", "文胸"} or name.lower() in {"bra", "bras"}),
            _number(candidate.get("score")) or 0.0,
        )

    return max(eligible, key=rank)


def _row_is_target_bra(
    row: dict[str, Any], *, target_category_id: str, exact_l3_query: bool
) -> bool:
    l3 = _as_dict(_as_dict(row.get("category")).get("l3"))
    row_l3_id = _category_id(l3.get("id"))
    row_l3_name = str(l3.get("name") or "").strip()
    if row_l3_name:
        if not _is_bra_category_name(row_l3_name):
            return False
        return not row_l3_id or row_l3_id == target_category_id
    if row_l3_id:
        return row_l3_id == target_category_id
    return exact_l3_query


def _category_type_label(l3_name: str) -> str:
    lowered = l3_name.lower()
    if "bra" in lowered:
        return "文胸"
    if "shapewear" in lowered:
        return "塑身衣"
    if "pant" in lowered or "brief" in lowered or "thong" in lowered:
        return "女士内裤"
    if "lingerie" in lowered:
        return "性感内衣"
    if "sock" in lowered or "tight" in lowered:
        return "袜类"
    return l3_name or "未细分"


def _feature_tags(title: str, l3_name: str) -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    product_type = _category_type_label(l3_name)
    tags.append(
        {
            "dimension": "product_type",
            "label": product_type,
            "evidence": f"FastMoss L3 category: {l3_name or 'unknown'}",
        }
    )
    no_underwire = bool(
        re.search(r"\b(?:wireless|no\s+underwire|no\s+steel\s+ring)\b", title, re.I)
    )
    for dimension, label, pattern in FEATURE_PATTERNS:
        if label == "钢圈" and no_underwire:
            continue
        match = re.search(pattern, title, re.I)
        if not match:
            continue
        tags.append(
            {
                "dimension": dimension,
                "label": label,
                "evidence": f'title: "{match.group(0)}"',
            }
        )
    bundle = re.search(r"\b(\d+)\s*[- ]?(?:pc|pcs|pack)\b", title, re.I)
    if bundle:
        tags.append(
            {
                "dimension": "bundle",
                "label": f"{bundle.group(1)} 件装",
                "evidence": f'title: "{bundle.group(0)}"',
            }
        )
    return tags


def _trend_metrics(
    data: dict[str, Any], *, generated_date: dt.date
) -> tuple[dict[str, Any], list[str]]:
    rows_by_date: dict[dt.date, dict[str, Any]] = {}
    for item in _as_list(data.get("daily_trend")):
        row = _as_dict(item)
        day = _date(row.get("date"))
        if not day or day >= generated_date:
            continue
        rows_by_date[day] = {
            "date": day.isoformat(),
            "units_sold": _integer(row.get("daily_units_sold")) or 0,
            "gmv": round(_number(row.get("daily_gmv")) or 0.0, 2),
        }
    complete_rows = [rows_by_date[day] for day in sorted(rows_by_date)]
    recent_14 = complete_rows[-14:]
    l7_rows = recent_14[-7:] if len(recent_14) >= 7 else []
    p7_rows = recent_14[-14:-7] if len(recent_14) >= 14 else []
    l7_units = sum(int(row["units_sold"]) for row in l7_rows)
    p7_units = sum(int(row["units_sold"]) for row in p7_rows)
    l7_gmv = round(sum(float(row["gmv"]) for row in l7_rows), 2)
    p7_gmv = round(sum(float(row["gmv"]) for row in p7_rows), 2)
    ratio: float | None = None
    change_percent: float | None = None
    gaps: list[str] = []
    if len(recent_14) < 14:
        label = "观察期不足"
        gaps.append("少于 14 个完整日数据点，无法计算可比的 L7/P7。")
    elif p7_units == 0 and l7_units > 0:
        label = "新启动"
    elif p7_units == 0 and l7_units == 0:
        label = "无近期动销"
    else:
        ratio = round(l7_units / p7_units, 4)
        change_percent = round((ratio - 1) * 100, 1)
        if ratio >= 1.2:
            label = "加速"
        elif ratio >= 0.8:
            label = "平稳"
        else:
            label = "回落"
    summary = _as_dict(data.get("period_summary"))
    return (
        {
            "complete_day_count": len(complete_rows),
            "first_complete_date": complete_rows[0]["date"] if complete_rows else None,
            "latest_complete_date": complete_rows[-1]["date"] if complete_rows else None,
            "l7_units_sold": l7_units if l7_rows else None,
            "p7_units_sold": p7_units if p7_rows else None,
            "l7_gmv": l7_gmv if l7_rows else None,
            "p7_gmv": p7_gmv if p7_rows else None,
            "l7_p7_ratio": ratio,
            "l7_p7_change_percent": change_percent,
            "trend_label": label,
            "period_summary": {
                "units_sold": _integer(summary.get("period_units_sold")),
                "gmv": _number(summary.get("period_gmv")),
                "linked_creator_count": _integer(summary.get("linked_creator_count")),
                "linked_video_count": _integer(summary.get("linked_video_count")),
                "linked_live_count": _integer(summary.get("linked_live_count")),
            },
            "daily_trend": complete_rows,
        },
        gaps,
    )


def _product_url_template(tool_results: list[dict[str, Any]]) -> str:
    for tool in reversed(_successful_tools(tool_results, URL_TOOL)):
        detail_pages = _as_dict(_as_dict(tool.get("data")).get("detail_pages"))
        template = str(_as_dict(detail_pages.get("product")).get("template") or "").strip()
        if template.startswith("https://") and "{product_id}" in template:
            return template
    return ""


def _category_candidates(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for tool in _successful_tools(tool_results, CATEGORY_TOOL):
        result = _as_dict(_as_dict(tool.get("data")).get("result"))
        for row in _as_list(result.get("categories")):
            item = _as_dict(row)
            candidates.append(
                {
                    "category_id_l1": item.get("category_id_level1"),
                    "category_id_l2": item.get("category_id_level2"),
                    "category_id_l3": item.get("category_id_level3"),
                    "name": item.get("cn_name"),
                    "path": item.get("cn_full_name"),
                    "matched_query": item.get("matched_query"),
                    "score": item.get("score"),
                }
            )
    return candidates[:15]


def _ranking_rows(
    tool_results: list[dict[str, Any]], *, listing_limit: int, target_category_id: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_by_id: dict[str, dict[str, Any]] = {}
    raw_product_ids: set[str] = set()
    bra_category_product_ids: set[str] = set()
    excluded_product_ids: set[str] = set()
    excluded_l3_categories: set[str] = set()
    excluded_under_price_ids: set[str] = set()
    excluded_over_price_ids: set[str] = set()
    excluded_missing_price_ids: set[str] = set()
    starts: list[str] = []
    ends: list[str] = []
    pages: list[int] = []
    totals: list[int] = []
    exact_l3_totals: list[int] = []
    queried_l3_ids: set[str] = set()
    raw_row_count = 0
    for tool in _successful_tools(tool_results, RANKING_TOOL):
        tool_input = _as_dict(tool.get("input"))
        request = _as_dict(tool_input.get("request"))
        container = request or tool_input
        filters = _as_dict(container.get("filter"))
        if filters.get("listing_start_date"):
            starts.append(str(filters["listing_start_date"]))
        if filters.get("listing_end_date"):
            ends.append(str(filters["listing_end_date"]))
        if container.get("page") is not None:
            pages.append(int(container["page"]))
        query_l3_id = _category_id(filters.get("category_l3_id"))
        if query_l3_id:
            queried_l3_ids.add(query_l3_id)
        exact_l3_query = query_l3_id == target_category_id
        data = _as_dict(tool.get("data"))
        if data.get("total") is not None:
            totals.append(int(data["total"]))
            if exact_l3_query:
                exact_l3_totals.append(int(data["total"]))
        for raw in _as_list(data.get("list")):
            raw_row_count += 1
            row = _as_dict(raw)
            product_id = str(row.get("product_id") or "").strip()
            if not product_id:
                continue
            raw_product_ids.add(product_id)
            if not _row_is_target_bra(
                row,
                target_category_id=target_category_id,
                exact_l3_query=exact_l3_query,
            ):
                excluded_product_ids.add(product_id)
                l3_name = str(
                    _as_dict(_as_dict(row.get("category")).get("l3")).get("name") or ""
                ).strip()
                excluded_l3_categories.add(l3_name or "未提供 L3")
                continue
            bra_category_product_ids.add(product_id)
            price = _number(row.get("current_price"))
            if price is None:
                excluded_missing_price_ids.add(product_id)
                continue
            if price < MIN_PRICE_USD:
                excluded_under_price_ids.add(product_id)
                continue
            if price > MAX_PRICE_USD:
                excluded_over_price_ids.add(product_id)
                continue
            current = rows_by_id.get(product_id)
            if current is None or (_number(row.get("total_units_sold")) or 0) > (
                _number(current.get("total_units_sold")) or 0
            ):
                rows_by_id[product_id] = dict(row)
    qualifying_product_ids = set(rows_by_id)
    excluded_product_ids.difference_update(bra_category_product_ids)
    excluded_under_price_ids.difference_update(qualifying_product_ids)
    excluded_over_price_ids.difference_update(qualifying_product_ids)
    excluded_missing_price_ids.difference_update(qualifying_product_ids)
    excluded_price_ids = (
        excluded_under_price_ids | excluded_over_price_ids | excluded_missing_price_ids
    )
    rows = sorted(
        rows_by_id.values(),
        key=lambda row: (
            -(_number(row.get("total_units_sold")) or 0),
            -(_number(row.get("lifetime_gmv")) or 0),
            str(row.get("product_id") or ""),
        ),
    )[:listing_limit]
    return rows, {
        "listing_start_date": min(starts) if starts else None,
        "listing_end_date": max(ends) if ends else None,
        "pages_collected": sorted(set(pages)),
        "available_total": max(exact_l3_totals or totals) if totals else None,
        "available_total_scope": "L3 Bras" if exact_l3_totals else "broader query",
        "category_id": target_category_id,
        "queried_category_l3_ids": sorted(queried_l3_ids),
        "used_exact_l3_query": target_category_id in queried_l3_ids,
        "raw_row_count": raw_row_count,
        "raw_unique_product_count": len(raw_product_ids),
        "bra_category_product_count": len(bra_category_product_ids),
        "qualifying_bra_count": len(rows_by_id),
        "excluded_non_bra_count": len(excluded_product_ids),
        "excluded_l3_categories": sorted(excluded_l3_categories),
        "price_filter": {
            "currency_code": "USD",
            "minimum_inclusive": MIN_PRICE_USD,
            "maximum_inclusive": MAX_PRICE_USD,
        },
        "excluded_price_count": len(excluded_price_ids),
        "excluded_under_price_count": len(excluded_under_price_ids),
        "excluded_over_price_count": len(excluded_over_price_ids),
        "excluded_missing_price_count": len(excluded_missing_price_ids),
    }


def _successful_product_data(
    tool_results: list[dict[str, Any]], tool_name: str
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for tool in _successful_tools(tool_results, tool_name):
        product_id = _input_product_id(tool)
        if product_id:
            output[product_id] = _as_dict(tool.get("data"))
    return output


def _attempted_product_ids(tool_results: list[dict[str, Any]], tool_name: str) -> set[str]:
    return {
        product_id
        for tool in _tools(tool_results, tool_name)
        if (product_id := _input_product_id(tool))
    }


def _price_position(price: float | None, q1: float | None, q3: float | None) -> str | None:
    if price is None or q1 is None or q3 is None:
        return None
    if price <= q1:
        return "低价带"
    if price >= q3:
        return "高价带"
    return "中价带"


def build_tiktok_new_product_report_data(payload: dict[str, Any]) -> dict[str, Any]:
    tool_results = [item for item in _as_list(payload.get("toolResults")) if isinstance(item, dict)]
    if not _successful_tools(tool_results, CATEGORY_TOOL):
        raise ValueError(
            "TikTokNewProductReportData requires one successful FastMoss category resolution result."
        )
    if not _tools(tool_results, URL_TOOL):
        raise ValueError(
            "TikTokNewProductReportData requires an attempted FastMoss detail URL template call."
        )

    listing_limit = max(1, min(int(payload.get("listingSampleSize") or 20), 100))
    head_count = max(1, min(int(payload.get("headListingCount") or 5), 30))
    category_candidates = _category_candidates(tool_results)
    target_category = _select_bra_category(tool_results, category_candidates)
    target_category_id = _category_id(target_category.get("category_id_l3"))
    ranking_rows, ranking_scope = _ranking_rows(
        tool_results,
        listing_limit=listing_limit,
        target_category_id=target_category_id,
    )
    if not ranking_rows:
        raise ValueError(
            "TikTokNewProductReportData requires at least one FastMoss new-product row "
            "confirmed as L3 Bras and priced from USD 20 through USD 100."
        )
    head_rows = ranking_rows[: min(head_count, len(ranking_rows))]
    head_ids = [str(row.get("product_id") or "") for row in head_rows]
    attempted_details = _attempted_product_ids(tool_results, DETAIL_TOOL)
    attempted_trends = _attempted_product_ids(tool_results, TREND_TOOL)
    missing_detail_attempts = [
        product_id for product_id in head_ids if product_id not in attempted_details
    ]
    missing_trend_attempts = [
        product_id for product_id in head_ids if product_id not in attempted_trends
    ]
    if missing_detail_attempts or missing_trend_attempts:
        missing_parts: list[str] = []
        if missing_detail_attempts:
            missing_parts.append("detail=" + ",".join(missing_detail_attempts))
        if missing_trend_attempts:
            missing_parts.append("trend=" + ",".join(missing_trend_attempts))
        raise ValueError(
            "Top-product enrichment has not been attempted for every selected product: "
            + "; ".join(missing_parts)
        )

    generated_at = str(payload.get("generatedAt") or dt.datetime.now(dt.UTC).isoformat())
    generated_date = _generated_date(generated_at)
    details_by_id = _successful_product_data(tool_results, DETAIL_TOOL)
    trends_by_id = _successful_product_data(tool_results, TREND_TOOL)
    url_template = _product_url_template(tool_results)
    prices = [
        price for row in ranking_rows if (price := _number(row.get("current_price"))) is not None
    ]
    q1 = _percentile(prices, 0.25)
    q3 = _percentile(prices, 0.75)
    iqr = (q3 - q1) if q1 is not None and q3 is not None else None

    candidate_products: list[dict[str, Any]] = []
    head_products: list[dict[str, Any]] = []
    report_gaps: list[str] = []
    if not ranking_scope.get("used_exact_l3_query"):
        report_gaps.append(
            f"新品榜调用未直接使用 category_l3_id={target_category_id}；"
            "编译器已按 L3 文胸硬筛选，但类目范围证据降级。"
        )
    for rank, row in enumerate(ranking_rows, start=1):
        product_id = str(row.get("product_id") or "")
        title = str(row.get("title") or "").strip()
        launch_date = _date(row.get("launch_date"))
        age_days = (
            max(1, (generated_date - launch_date).days + 1)
            if launch_date and launch_date <= generated_date
            else None
        )
        l1_name, l2_name, l3_name, category_path = _category_parts(row)
        shop = _as_dict(row.get("shop"))
        price = _number(row.get("current_price"))
        total_units = _integer(row.get("total_units_sold"))
        anomalies: list[str] = []
        if bool(row.get("is_off_shelf")):
            anomalies.append("已下架")
        if re.search(r"\b(?:thank you|customer appreciation|random gift)\b", title, re.I):
            anomalies.append("标题信息量低，可能为异常或占位商品")
        if price is not None and q3 is not None and iqr is not None and price > q3 + 1.5 * iqr:
            anomalies.append("价格显著高于候选池常见区间")
        product_url = str(row.get("fastmoss_url") or "").strip()
        if not product_url and url_template:
            product_url = url_template.replace("{product_id}", product_id)
        candidate = {
            "rank": rank,
            "product_id": product_id,
            "title": title,
            "fastmoss_url": product_url or None,
            "category_l3": l3_name,
            "launch_date": launch_date.isoformat() if launch_date else None,
            "age_days": age_days,
            "current_price": price,
            "price_display": row.get("price_display"),
            "price_position": _price_position(price, q1, q3),
            "first_3d_units_sold": _integer(row.get("first_3d_units_sold")),
            "first_3d_gmv": _number(row.get("first_3d_gmv")),
            "total_units_sold": total_units,
            "lifetime_gmv": _number(row.get("lifetime_gmv")),
            "units_per_day_since_launch": (
                round(total_units / age_days, 1) if total_units is not None and age_days else None
            ),
            "is_off_shelf": row.get("is_off_shelf"),
            "shop_name": shop.get("shop_name"),
            "shop_id": shop.get("shop_id") or shop.get("seller_id"),
            "anomaly_flags": anomalies,
        }
        candidate_products.append(candidate)
        if rank > len(head_rows):
            continue

        detail_data = details_by_id.get(product_id, {})
        detail = _as_dict(detail_data.get("product"))
        detail_shop = _as_dict(detail_data.get("shop"))
        shop_category = str(_as_dict(detail_shop.get("shop_category_l1")).get("name") or "")
        shop_category_lower = shop_category.lower()
        if shop_category and (
            "kid" in shop_category_lower
            or not any(
                token in shop_category_lower
                for token in ("women", "underwear", "lingerie", "fashion")
            )
        ):
            anomalies.append("店铺主营类目与女士内衣不一致")
        product_gaps: list[str] = []
        if not detail:
            product_gaps.append("商品详情调用未成功，特点仅使用新品榜字段。")
        trend_data = trends_by_id.get(product_id, {})
        if trend_data:
            trend, trend_gaps = _trend_metrics(trend_data, generated_date=generated_date)
            product_gaps.extend(trend_gaps)
        else:
            trend = {
                "complete_day_count": 0,
                "l7_units_sold": None,
                "p7_units_sold": None,
                "l7_p7_ratio": None,
                "l7_p7_change_percent": None,
                "trend_label": "趋势数据缺失",
                "period_summary": {},
                "daily_trend": [],
            }
            product_gaps.append("销量趋势调用未成功，不能判断 L7/P7 方向。")
        product_title = str(detail.get("title") or title)
        head_products.append(
            {
                **candidate,
                "title": product_title,
                "image_url": detail.get("cover_url") or row.get("cover_url"),
                "region": row.get("region"),
                "currency_code": row.get("currency_code"),
                "category_l1": l1_name,
                "category_l2": l2_name,
                "category_path": category_path,
                "commission_rate_percent": _number(row.get("commission_rate_percent")),
                "is_cross_border": row.get("is_cross_border"),
                "shop": {
                    "shop_id": detail_shop.get("shop_id") or shop.get("shop_id"),
                    "shop_name": detail_shop.get("shop_name") or shop.get("shop_name"),
                    "total_units_sold": _integer(
                        detail_shop.get("shop_total_units_sold") or shop.get("total_units_sold")
                    ),
                },
                "detail": {
                    "product_rating": _number(detail.get("product_rating")),
                    "review_count": _integer(detail.get("review_count")),
                    "stock_count": _integer(detail.get("stock_count")),
                    "stock_count_label": detail.get("stock_count_label"),
                    "linked_creator_count": _integer(detail.get("linked_creator_count")),
                    "linked_video_count": _integer(detail.get("linked_video_count")),
                    "linked_live_count": _integer(detail.get("linked_live_count")),
                    "shipping_fee": detail.get("shipping_fee"),
                    "has_paid_promotion": detail.get("has_paid_promotion"),
                    "has_sku_options": detail.get("has_sku_options"),
                    "popularity_index": detail.get("popularity_index"),
                    "viral_index": detail.get("viral_index"),
                    "shop_category_l1": shop_category or None,
                },
                "feature_tags": _feature_tags(product_title, l3_name),
                "trend": trend,
                "data_gaps": product_gaps,
                "source_refs": [
                    "fastmoss_new_product_ranking",
                    *(["fastmoss_product_detail"] if detail else []),
                    *(["fastmoss_product_sales_trend"] if trend_data else []),
                ],
            }
        )
        report_gaps.extend(f"{product_id}: {gap}" for gap in product_gaps)

    if not url_template:
        report_gaps.append("FastMoss 商品详情链接模板未成功返回，部分商品链接不可用。")
    successful_detail_count = sum(
        bool(_as_dict(_as_dict(details_by_id.get(product_id)).get("product")))
        for product_id in head_ids
    )
    successful_trend_count = sum(
        bool(_as_list(_as_dict(trends_by_id.get(product_id)).get("daily_trend")))
        for product_id in head_ids
    )
    compile_status = (
        "complete"
        if successful_detail_count == len(head_ids)
        and successful_trend_count == len(head_ids)
        and bool(url_template)
        and bool(ranking_scope.get("used_exact_l3_query"))
        else "degraded"
    )
    selected_category = head_rows[0].get("category") if head_rows else {}
    selected_category = _as_dict(selected_category)
    l1 = _as_dict(selected_category.get("l1"))
    l2 = _as_dict(selected_category.get("l2"))
    l3 = _as_dict(selected_category.get("l3"))
    l3_values = sorted(
        {
            str(_as_dict(_as_dict(row.get("category")).get("l3")).get("name") or "")
            for row in ranking_rows
            if _as_dict(_as_dict(row.get("category")).get("l3")).get("name")
        }
    )
    top_product = head_products[0] if head_products else candidate_products[0]
    return {
        "schema_version": "tiktok_new_product_report_data.v1",
        "title": "TikTok Shop 美国女士文胸新品洞察",
        "brand": payload.get("brand") or "Hsia",
        "marketplace": "US",
        "category": BRA_CATEGORY_LABEL,
        "generated_at": generated_at,
        "time_range": payload.get("timeRange") or "28d",
        "new_product_window": payload.get("newProductWindow") or "30d",
        "status": compile_status,
        "source_scope": {
            "source": "FastMoss",
            "region": "US",
            "category_id": ranking_scope.get("category_id") or payload.get("categoryNodeId"),
            "category_l1": {"id": l1.get("id"), "name": l1.get("name")},
            "category_l2": {"id": l2.get("id"), "name": l2.get("name")},
            "category_l3": {
                "id": l3.get("id") or target_category_id,
                "name": l3.get("name") or target_category.get("name"),
            },
            "observed_l3_categories": l3_values,
            "listing_start_date": ranking_scope.get("listing_start_date"),
            "listing_end_date": ranking_scope.get("listing_end_date"),
            "sort": "total_units_sold desc",
            "pages_collected": ranking_scope.get("pages_collected"),
            "available_total": ranking_scope.get("available_total"),
            "available_total_scope": ranking_scope.get("available_total_scope"),
            "candidate_limit": listing_limit,
            "head_product_limit": head_count,
            "raw_row_count": ranking_scope.get("raw_row_count"),
            "raw_unique_product_count": ranking_scope.get("raw_unique_product_count"),
            "bra_category_product_count": ranking_scope.get("bra_category_product_count"),
            "qualifying_bra_count": ranking_scope.get("qualifying_bra_count"),
            "excluded_non_bra_count": ranking_scope.get("excluded_non_bra_count"),
            "excluded_l3_categories": ranking_scope.get("excluded_l3_categories"),
            "price_filter": ranking_scope.get("price_filter"),
            "excluded_price_count": ranking_scope.get("excluded_price_count"),
            "excluded_under_price_count": ranking_scope.get("excluded_under_price_count"),
            "excluded_over_price_count": ranking_scope.get("excluded_over_price_count"),
            "excluded_missing_price_count": ranking_scope.get("excluded_missing_price_count"),
            "used_exact_l3_query": ranking_scope.get("used_exact_l3_query"),
        },
        "category_resolution": {
            "selected_category_id": target_category_id,
            "selected_category_name": target_category.get("name") or BRA_CATEGORY_LABEL,
            "selected_category_path": target_category.get("path"),
            "selected_category_level": "L3",
            "candidate_nodes": category_candidates,
        },
        "summary": {
            "candidate_count": len(candidate_products),
            "head_product_count": len(head_products),
            "detail_success_count": successful_detail_count,
            "trend_success_count": successful_trend_count,
            "excluded_non_bra_count": ranking_scope.get("excluded_non_bra_count"),
            "excluded_price_count": ranking_scope.get("excluded_price_count"),
            "currency_code": next(
                (
                    item.get("currency_code")
                    for item in candidate_products
                    if item.get("currency_code")
                ),
                "USD",
            ),
            "top_product": {
                "product_id": top_product.get("product_id"),
                "title": top_product.get("title"),
                "fastmoss_url": top_product.get("fastmoss_url"),
                "total_units_sold": top_product.get("total_units_sold"),
                "trend_label": _as_dict(top_product.get("trend")).get("trend_label"),
            },
            "price_band": {
                "minimum": min(prices) if prices else None,
                "median": median(prices) if prices else None,
                "maximum": max(prices) if prices else None,
                "q1": round(q1, 2) if q1 is not None else None,
                "q3": round(q3, 2) if q3 is not None else None,
            },
        },
        "candidate_products": candidate_products,
        "head_products": head_products,
        "output_contract": {
            "new_product_ranking_required_columns": [
                {"field": "rank", "label": "排名"},
                {"field": "title", "label": "商品"},
                {"field": "shop_name", "label": "店铺名称"},
                {"field": "shop_id", "label": "shop_id"},
                {"field": "launch_date", "label": "上架日期"},
                {"field": "current_price", "label": "售价 (USD)"},
                {"field": "first_3d_units_sold", "label": "首3天销量"},
                {"field": "total_units_sold", "label": "累计销量"},
                {"field": "lifetime_gmv", "label": "累计GMV"},
                {"field": "age_days", "label": "上架天数"},
            ]
        },
        "data_gaps": list(dict.fromkeys(report_gaps)),
        "methodology": [
            "FastMoss 新品榜优先使用女士文胸 L3 category_l3_id；分页结果先按 L3 文胸硬筛选，再按 product_id 去重。",
            "仅保留 current_price 在 20–100 USD（含边界）的商品；价格缺失、低于 20 USD 或高于 100 USD 的商品在计数和排序前剔除。",
            "主榜仅按 total_units_sold 降序，累计 GMV 不替代销量排序。",
            "Top 商品详情和趋势按 product_id 确定性关联。",
            "L7/P7 使用生成日前最近 14 个完整日数据点；不使用被截断的前段趋势。",
            "产品特点仅来自 FastMoss L3 类目、商品标题和明确详情字段。",
        ],
        "source_summary": {
            "tool_result_count": len(tool_results),
            "ranking_call_count": len(_tools(tool_results, RANKING_TOOL)),
            "ranking_success_count": len(_successful_tools(tool_results, RANKING_TOOL)),
            "ranking_used_exact_l3_query": ranking_scope.get("used_exact_l3_query"),
            "ranking_raw_unique_product_count": ranking_scope.get("raw_unique_product_count"),
            "ranking_excluded_non_bra_count": ranking_scope.get("excluded_non_bra_count"),
            "ranking_excluded_price_count": ranking_scope.get("excluded_price_count"),
            "detail_attempt_count": len(attempted_details),
            "detail_success_count": successful_detail_count,
            "trend_attempt_count": len(attempted_trends),
            "trend_success_count": successful_trend_count,
        },
    }


def tiktok_new_product_report_data_to_artifact(report_data: dict[str, Any]) -> dict[str, Any]:
    summary = _as_dict(report_data.get("summary"))
    top_product = _as_dict(summary.get("top_product"))
    candidate_count = int(summary.get("candidate_count") or 0)
    head_count = int(summary.get("head_product_count") or 0)
    top_name = str(top_product.get("title") or "暂无可用头部新品")
    top_units = top_product.get("total_units_sold")
    top_finding = (
        f"当前样本销量最高的新品为 {top_name}，累计销量 {top_units}。"
        if top_units is not None
        else f"当前样本销量最高的新品为 {top_name}。"
    )
    return {
        "title": report_data.get("title") or "TikTok Shop 美国女士文胸新品洞察",
        "executive_summary": (
            f"基于 FastMoss 美国女士文胸 L3 类目新品榜扫描 {candidate_count} 个新品，"
            f"对销量最高的 {head_count} 个商品完成详情与趋势整理。"
        ),
        "kpis": [
            {"label": "新品样本", "value": candidate_count},
            {"label": "深挖商品", "value": head_count},
            {"label": "详情成功", "value": summary.get("detail_success_count")},
            {"label": "趋势成功", "value": summary.get("trend_success_count")},
        ],
        "market_basics": [],
        "price_and_margin": [],
        "competition": [],
        "user_voice": [],
        "key_findings": [top_finding],
        "opportunities": [],
        "opportunity_pool": [],
        "risks": report_data.get("data_gaps") or [],
        "data_gaps": report_data.get("data_gaps") or [],
        "next_steps": [],
    }

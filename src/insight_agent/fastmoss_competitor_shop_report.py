from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from statistics import median
from typing import Any

from .agent_tool_recovery import SUCCESS_TOOL_STATUSES

CATEGORY_TOOL = "mcp__fastmoss__search_category_by_words"
RANKING_TOOL = "mcp__fastmoss__shop_rank_top_selling"
BASE_TOOL = "mcp__fastmoss__shop_base_info"
PRODUCT_TOOL = "mcp__fastmoss__shop_product_analysis"
SALE_TOOL = "mcp__fastmoss__shop_sale_analysis"
TREND_TOOL = "mcp__fastmoss__shop_data_trends"
CREATOR_TOOL = "mcp__fastmoss__shop_creator_analysis"
URL_TOOL = "mcp__fastmoss__fastmoss_detail_url_examples"

STANDARD_SHOP_TOOLS = (BASE_TOOL, PRODUCT_TOOL, SALE_TOOL, TREND_TOOL, CREATOR_TOOL)
BRA_CATEGORY_LABEL = "女士文胸"
WOMENS_UNDERWEAR_CATEGORY_ID = "842888"
WOMENS_UNDERWEAR_CATEGORY_LABEL = "女士内衣"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
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
    return _date(value) or dt.datetime.now(dt.UTC).date()


def _tool_name(tool: dict[str, Any]) -> str:
    return str(tool.get("name") or "")


def _is_success(tool: dict[str, Any]) -> bool:
    return str(tool.get("status") or "").lower() in SUCCESS_TOOL_STATUSES


def _tools(tool_results: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [tool for tool in tool_results if _tool_name(tool) == name]


def _successful_tools(tool_results: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [tool for tool in _tools(tool_results, name) if _is_success(tool)]


def _input_filter(tool: dict[str, Any]) -> dict[str, Any]:
    tool_input = _as_dict(tool.get("input"))
    return _as_dict(tool_input.get("filter"))


def _input_seller_id(tool: dict[str, Any]) -> str:
    tool_input = _as_dict(tool.get("input"))
    filters = _as_dict(tool_input.get("filter"))
    return str(filters.get("seller_id") or tool_input.get("seller_id") or "").strip()


def _walk_dicts(value: Any, *, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 7:
        return []
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_dicts(child, depth=depth + 1))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_dicts(child, depth=depth + 1))
    return found


def _first_value(value: Any, keys: tuple[str, ...]) -> Any:
    for item in _walk_dicts(value):
        for key in keys:
            if key in item and item.get(key) not in (None, ""):
                return item.get(key)
    return None


def _first_number(value: Any, keys: tuple[str, ...]) -> float | None:
    return _number(_first_value(value, keys))


def _category_id(value: Any) -> str:
    number = _integer(value)
    return str(number) if number is not None else str(value or "").strip()


def _is_bra_category_name(value: Any) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return text in {"bras", "bra", "women's bras", "womens bras", "女士文胸", "文胸"}


def _is_bra_product_category_name(value: Any) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if not text:
        return False
    if any(
        excluded in text
        for excluded in ("accessory", "accessories", "配件", "bra insert", "胸垫")
    ):
        return False
    return bool(re.search(r"\bbras?\b", text) or "文胸" in text)


def _category_candidates(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for tool in _successful_tools(tool_results, CATEGORY_TOOL):
        for item in _walk_dicts(tool.get("data")):
            l3 = _as_dict(item.get("l3"))
            category_id = _category_id(
                item.get("category_id_level3")
                or item.get("category_id_l3")
                or item.get("category_l3_id")
                or l3.get("id")
            )
            name = str(
                item.get("category_name_level3")
                or item.get("category_name_l3")
                or item.get("cn_name")
                or item.get("name")
                or l3.get("name")
                or ""
            ).strip()
            path = str(
                item.get("category_path_zh")
                or item.get("category_path")
                or item.get("cn_full_name")
                or item.get("path")
                or ""
            ).strip()
            leaf = re.split(r"\s*(?:>|/|→|-)\s*", path)[-1] if path else name
            if not category_id or not (_is_bra_category_name(name) or _is_bra_category_name(leaf)):
                continue
            candidates[category_id] = {
                "category_id_l3": category_id,
                "name": name or leaf or BRA_CATEGORY_LABEL,
                "path": path or None,
                "level": "L3",
            }
    return list(candidates.values())


def _bra_product_category_candidates(
    tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for tool in _successful_tools(tool_results, CATEGORY_TOOL):
        for item in _walk_dicts(tool.get("data")):
            l3 = _as_dict(item.get("l3"))
            category_id = _category_id(
                item.get("category_id_level3")
                or item.get("category_id_l3")
                or item.get("category_l3_id")
                or l3.get("id")
            )
            name = str(
                item.get("category_name_level3")
                or item.get("category_name_l3")
                or item.get("cn_name")
                or item.get("name")
                or l3.get("name")
                or ""
            ).strip()
            path = str(
                item.get("category_path_zh")
                or item.get("category_path")
                or item.get("cn_full_name")
                or item.get("path")
                or ""
            ).strip()
            leaf = re.split(r"\s*(?:>|/|→|-)\s*", path)[-1] if path else name
            if not category_id or not (
                _is_bra_product_category_name(name)
                or _is_bra_product_category_name(leaf)
            ):
                continue
            candidates[category_id] = {
                "category_id_l3": category_id,
                "name": name or leaf or BRA_CATEGORY_LABEL,
                "path": path or None,
                "level": "L3",
            }
    return list(candidates.values())


def resolved_bra_category_ids(tool_results: list[dict[str, Any]]) -> set[str]:
    return {
        str(candidate.get("category_id_l3") or "")
        for candidate in _category_candidates(tool_results)
        if candidate.get("category_id_l3")
    }


def _select_bra_category(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = _category_candidates(tool_results)
    ranking_ids = {
        _category_id(_input_filter(tool).get("category_id"))
        for tool in _tools(tool_results, RANKING_TOOL)
        if _input_filter(tool).get("category_id") not in (None, "")
    }
    matching = [item for item in candidates if item["category_id_l3"] in ranking_ids]
    if len(matching) == 1:
        return matching[0]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(
            "TikTokBraCompetitorShopReportData requires a FastMoss category result whose L3 leaf is Bras."
        )
    raise ValueError(
        "FastMoss returned multiple L3 Bras category candidates; use one resolved category_id consistently."
    )


def _brand_tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", str(value or "").lower())
        if len(token) >= 3 or re.fullmatch(r"[\u4e00-\u9fff]+", token)
    }


def _is_subject_brand(shop: dict[str, Any], brand: str) -> bool:
    subject_tokens = _brand_tokens(brand)
    if not subject_tokens:
        return False
    shop_tokens = _brand_tokens(
        " ".join(
            str(value or "")
            for value in (shop.get("shop_name"), shop.get("brand_name"), shop.get("company_name"))
        )
    )
    return bool(subject_tokens & shop_tokens)


def _ranking_rows(
    tool_results: list[dict[str, Any]],
    *,
    target_category_id: str,
    candidate_limit: int,
    brand: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    ranking_tools = _tools(tool_results, RANKING_TOOL)
    preferred_attempts: list[dict[str, Any]] = []
    for tool in ranking_tools:
        filters = _input_filter(tool)
        if (
            str(filters.get("region") or "").upper() == "US"
            and _category_id(filters.get("category_id")) == target_category_id
            and str(filters.get("date_type") or "").lower() == "month"
        ):
            preferred_attempts.append(tool)
    if not preferred_attempts:
        raise ValueError(
            "TikTokBraCompetitorShopReportData requires an attempted US L3 Bras monthly shop ranking before any fallback."
        )

    selected_tools = [
        tool
        for tool in preferred_attempts
        if _is_success(tool) and bool(_as_list(_as_dict(tool.get("data")).get("list")))
    ]
    ranking_mode = "bras_l3_completed_month"
    ranking_category_id = target_category_id
    ranking_category_name = BRA_CATEGORY_LABEL
    date_type = "month"
    if not selected_tools:
        selected_tools = [
            tool
            for tool in ranking_tools
            if _is_success(tool)
            and str(_input_filter(tool).get("region") or "").upper() == "US"
            and _category_id(_input_filter(tool).get("category_id"))
            == WOMENS_UNDERWEAR_CATEGORY_ID
            and str(_input_filter(tool).get("date_type") or "").lower() == "week"
            and bool(_as_list(_as_dict(tool.get("data")).get("list")))
        ]
        ranking_mode = "womens_underwear_l2_completed_week_fallback"
        ranking_category_id = WOMENS_UNDERWEAR_CATEGORY_ID
        ranking_category_name = WOMENS_UNDERWEAR_CATEGORY_LABEL
        date_type = "week"
    if not selected_tools:
        raise ValueError(
            "TikTokBraCompetitorShopReportData requires either a non-empty US L3 Bras monthly ranking, "
            "or—after that scope was attempted and returned no rows—a non-empty US Women's Underwear L2 weekly ranking."
        )

    periods = [str(_input_filter(tool).get("date_value") or "") for tool in selected_tools]
    selected_period = max((period for period in periods if period), default="")
    if selected_period:
        selected_tools = [
            tool
            for tool in selected_tools
            if str(_input_filter(tool).get("date_value") or "") == selected_period
        ]

    raw_rows: list[tuple[int, int, dict[str, Any]]] = []
    available_total = 0
    for tool in selected_tools:
        tool_input = _as_dict(tool.get("input"))
        page = max(1, _integer(tool_input.get("page")) or 1)
        pagesize = max(1, _integer(tool_input.get("pagesize")) or 10)
        data = _as_dict(tool.get("data"))
        available_total = max(available_total, _integer(data.get("total")) or 0)
        for index, row in enumerate(_as_list(data.get("list"))):
            if isinstance(row, dict):
                raw_rows.append((page, (page - 1) * pagesize + index + 1, row))

    by_seller: dict[str, dict[str, Any]] = {}
    for _page, source_rank, row in sorted(raw_rows, key=lambda item: (item[0], item[1])):
        shop = _as_dict(row.get("shop"))
        metrics = _as_dict(row.get("ranking_metrics"))
        scope = _as_dict(row.get("ranking_scope"))
        seller_id = str(shop.get("seller_id") or row.get("seller_id") or "").strip()
        if not seller_id:
            continue
        candidate = {
            "source_rank": source_rank,
            "seller_id": seller_id,
            "shop_name": shop.get("shop_name") or row.get("shop_name"),
            "brand_name": shop.get("brand_name"),
            "company_name": shop.get("company_name"),
            "region": shop.get("region") or "US",
            "currency_code": shop.get("currency_code") or "USD",
            "shop_type_code": shop.get("shop_type_code"),
            "is_cross_border": shop.get("is_cross_border"),
            "is_fully_managed": shop.get("is_fully_managed"),
            "shop_rating": _number(shop.get("shop_rating")),
            "active_product_count_total": _integer(shop.get("active_product_count_total")),
            "main_category": _as_dict(shop.get("main_category")),
            "period_gmv": _number(
                metrics.get("period_gmv") or metrics.get("usd_gmv") or row.get("period_gmv")
            ),
            "period_units_sold": _integer(
                metrics.get("period_units_sold")
                or metrics.get("units_sold")
                or row.get("period_units_sold")
            ),
            "gmv_growth_rate_percent": _number(metrics.get("gmv_growth_rate_percent")),
            "units_sold_growth_rate_percent": _number(
                metrics.get("units_sold_growth_rate_percent")
            ),
            "linked_creator_count": _integer(metrics.get("linked_creator_count")),
            "products_with_sales_count": _integer(metrics.get("products_with_sales_count")),
            "ranking_category_id": _category_id(scope.get("ranked_category_id"))
            or ranking_category_id,
            "ranking_category_name": scope.get("ranked_category_name")
            or ranking_category_name,
        }
        previous = by_seller.get(seller_id)
        if previous is None or source_rank < int(previous.get("source_rank") or 10**9):
            by_seller[seller_id] = candidate

    ordered = sorted(
        by_seller.values(),
        key=lambda row: (
            int(row.get("source_rank") or 10**9),
            -float(row.get("period_gmv") or 0),
            str(row.get("seller_id") or ""),
        ),
    )
    subject_brand = [row for row in ordered if _is_subject_brand(row, brand)]
    competitors = [row for row in ordered if not _is_subject_brand(row, brand)][:candidate_limit]
    for rank, row in enumerate(competitors, start=1):
        row["competitor_rank"] = rank
    scope = {
        "mode": ranking_mode,
        "is_fallback": ranking_mode != "bras_l3_completed_month",
        "category_id": ranking_category_id,
        "category_name": ranking_category_name,
        "date_type": date_type,
        "date_value": selected_period or None,
        "sort": "usd_gmv desc",
        "pages_collected": sorted(
            {_integer(_as_dict(tool.get("input")).get("page")) or 1 for tool in selected_tools}
        ),
        "available_total": available_total or None,
        "raw_row_count": len(raw_rows),
        "unique_shop_count": len(ordered),
        "subject_brand_excluded_count": len(subject_brand),
    }
    return competitors, subject_brand, scope


def competitor_shop_ranking_preflight(
    tool_results: list[dict[str, Any]],
    *,
    candidate_limit: int = 50,
    brand: str = "Hsia",
) -> dict[str, Any]:
    """Return the accepted candidate universe used by runtime scope guards."""
    target_category = _select_bra_category(tool_results)
    candidates, subject_brand, scope = _ranking_rows(
        tool_results,
        target_category_id=str(target_category.get("category_id_l3") or ""),
        candidate_limit=candidate_limit,
        brand=brand,
    )
    return {
        "target_category": target_category,
        "candidates": candidates,
        "subject_brand_shops": subject_brand,
        "ranking_scope": scope,
    }


def _attempted_seller_ids(tool_results: list[dict[str, Any]], tool_name: str) -> set[str]:
    return {
        seller_id
        for tool in _tools(tool_results, tool_name)
        if (seller_id := _input_seller_id(tool))
    }


def _successful_data_by_seller(
    tool_results: list[dict[str, Any]], tool_name: str
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for tool in _successful_tools(tool_results, tool_name):
        seller_id = _input_seller_id(tool)
        data = _as_dict(tool.get("data"))
        if seller_id and data:
            output[seller_id] = data
    return output


def _successful_product_data_by_seller(
    tool_results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for tool in _successful_tools(tool_results, PRODUCT_TOOL):
        seller_id = _input_seller_id(tool)
        data = _as_dict(tool.get("data"))
        if not seller_id or not data:
            continue
        tool_input = _as_dict(tool.get("input"))
        output.setdefault(seller_id, {"calls": []})["calls"].append(
            {
                "page": max(1, _integer(tool_input.get("page")) or 1),
                "pagesize": max(1, _integer(tool_input.get("pagesize")) or 10),
                "filter": _as_dict(tool_input.get("filter")),
                "data": data,
            }
        )
    for merged in output.values():
        merged["calls"].sort(
            key=lambda item: (
                int(item.get("page") or 1),
                str(_as_dict(item.get("filter")).get("category_id") or ""),
            )
        )
    return output


def _bounded_scalars(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return None
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, child in list(value.items())[:24]:
            compact = _bounded_scalars(child, depth=depth + 1)
            if compact not in (None, {}, []):
                output[str(key)] = compact
        return output
    if isinstance(value, list):
        return [
            compact
            for child in value[:10]
            if (compact := _bounded_scalars(child, depth=depth + 1)) not in (None, {}, [])
        ]
    if isinstance(value, str):
        return value[:320]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:320]


def _find_rows(value: Any, identity: str) -> list[dict[str, Any]]:
    def score(row: dict[str, Any]) -> bool:
        if identity == "product":
            product = _as_dict(row.get("product"))
            return bool(
                row.get("product_id")
                or row.get("id")
                or product.get("product_id")
                or product.get("id")
            )
        if identity == "creator":
            creator = _as_dict(row.get("creator"))
            return bool(
                row.get("uid")
                or row.get("creator_uid")
                or creator.get("uid")
                or creator.get("creator_uid")
            )
        return bool(row.get("date") or row.get("stat_date") or row.get("data_date"))

    best: list[dict[str, Any]] = []
    for item in _walk_dicts(value):
        for child in item.values():
            rows = [row for row in _as_list(child) if isinstance(row, dict)]
            matched = [row for row in rows if score(row)]
            if len(matched) > len(best):
                best = matched
    return best


def _find_all_rows(value: Any, identity: str) -> list[dict[str, Any]]:
    def matches(row: dict[str, Any]) -> bool:
        if identity == "product":
            product = _as_dict(row.get("product"))
            return bool(
                row.get("product_id")
                or row.get("id")
                or product.get("product_id")
                or product.get("id")
            )
        return False

    rows: list[dict[str, Any]] = []
    for item in _walk_dicts(value):
        for child in item.values():
            rows.extend(
                row
                for row in _as_list(child)
                if isinstance(row, dict) and matches(row)
            )
    return rows


def _url_template(tool_results: list[dict[str, Any]], object_name: str) -> str:
    placeholders = {
        "shop": ("{seller_id}", "{shop_id}"),
        "creator": ("{uid}", "{creator_id}"),
        "product": ("{product_id}",),
    }.get(object_name, ("{" + object_name + "_id}",))
    for tool in _successful_tools(tool_results, URL_TOOL):
        for item in _walk_dicts(tool.get("data")):
            for value in item.values():
                if not isinstance(value, str):
                    continue
                text = str(value or "")
                if "fastmoss.com" in text and any(
                    placeholder in text for placeholder in placeholders
                ):
                    return text
    return ""


def _normalize_base(data: dict[str, Any], ranking: dict[str, Any]) -> dict[str, Any]:
    shop = _as_dict(data.get("shop"))
    if not shop:
        shop = next(
            (
                item
                for item in _walk_dicts(data)
                if str(item.get("seller_id") or "") == str(ranking.get("seller_id") or "")
            ),
            {},
        )
    return {
        "seller_id": shop.get("seller_id") or ranking.get("seller_id"),
        "shop_name": shop.get("shop_name") or ranking.get("shop_name"),
        "brand_name": shop.get("brand_name") or ranking.get("brand_name"),
        "company_name": shop.get("company_name") or ranking.get("company_name"),
        "shop_type_code": shop.get("shop_type_code") or ranking.get("shop_type_code"),
        "is_cross_border": shop.get("is_cross_border", ranking.get("is_cross_border")),
        "is_fully_managed": shop.get("is_fully_managed", ranking.get("is_fully_managed")),
        "shop_rating": _number(shop.get("shop_rating") or ranking.get("shop_rating")),
        "shop_age_days": _integer(
            _first_value(data, ("shop_age_days", "store_age_days", "days_since_open"))
        ),
        "cumulative_gmv": _first_number(data, ("cumulative_gmv", "total_gmv", "gmv")),
        "cumulative_units_sold": _integer(
            _first_value(data, ("cumulative_units_sold", "total_units_sold", "units_sold"))
        ),
        "active_product_count": _integer(
            _first_value(data, ("active_product_count", "active_product_count_total"))
        ),
        "linked_creator_count": _integer(
            _first_value(data, ("linked_creator_count", "creator_count"))
        ),
        "linked_video_count": _integer(
            _first_value(data, ("linked_video_count", "video_count"))
        ),
        "linked_live_count": _integer(
            _first_value(data, ("linked_live_count", "live_count"))
        ),
    }


def _product_id(row: dict[str, Any]) -> str:
    product = _as_dict(row.get("product"))
    return str(row.get("product_id") or product.get("product_id") or product.get("id") or "")


def _normalize_products(
    data: dict[str, Any],
    *,
    target_category_id: str,
    target_category_ids: set[str],
    generated_date: dt.date,
    new_product_days: int,
    product_url_template: str,
) -> dict[str, Any]:
    products_by_id: dict[str, dict[str, Any]] = {}
    excluded_category_count = 0
    excluded_unknown_category_count = 0
    raw_product_rows = _find_all_rows(data, "product")
    for row in raw_product_rows:
        product = {**row, **_as_dict(row.get("product"))}
        product_id = _product_id(row)
        if not product_id:
            continue
        category = _as_dict(product.get("category"))
        category_l3 = _as_dict(category.get("l3"))
        explicit_category_id = _category_id(
            product.get("category_id_level3")
            or product.get("category_l3_id")
            or product.get("category_id_l3")
            or category_l3.get("id")
        )
        explicit_category_name = str(
            product.get("category_name_level3")
            or product.get("category_l3_name")
            or category_l3.get("name")
            or ""
        ).strip()
        if not explicit_category_id:
            excluded_unknown_category_count += 1
            continue
        if explicit_category_id not in target_category_ids:
            excluded_category_count += 1
            continue
        launch_date = _date(
            _first_value(product, ("launch_date", "launch_time", "listing_date", "listed_at"))
        )
        age_days = (
            max(0, (generated_date - launch_date).days)
            if launch_date and launch_date <= generated_date
            else None
        )
        price = _first_number(
            product,
            ("current_price", "sale_price", "real_price", "price", "avg_price"),
        )
        fastmoss_url = str(_first_value(product, ("fastmoss_url",)) or "").strip()
        if not fastmoss_url and product_url_template:
            fastmoss_url = product_url_template.replace("{product_id}", product_id)
        normalized = {
            "product_id": product_id,
            "title": _first_value(product, ("title", "product_title", "name")),
            "fastmoss_url": fastmoss_url or None,
            "image_url": _first_value(
                product,
                ("cover_url", "cover", "image_url", "main_image", "product_image"),
            ),
            "category_l3_id": explicit_category_id or target_category_id,
            "category_l3_name": explicit_category_name or None,
            "launch_date": launch_date.isoformat() if launch_date else None,
            "age_days": age_days,
            "is_new_30d": age_days is not None and age_days <= new_product_days,
            "price": price,
            "currency_code": _first_value(product, ("currency_code", "currency")),
            "day28_gmv": _first_number(
                product, ("day28_gmv", "period_gmv", "sale_amount", "gmv")
            ),
            "day28_units_sold": _integer(
                _first_value(
                    product,
                    ("day28_units_sold", "period_units_sold", "sold_count", "units_sold"),
                )
            ),
            "total_gmv": _first_number(product, ("total_gmv", "lifetime_gmv")),
            "total_units_sold": _integer(
                _first_value(product, ("total_units_sold", "lifetime_units_sold"))
            ),
        }
        previous = products_by_id.get(product_id)
        if previous is None or (
            float(normalized.get("day28_gmv") or 0),
            float(normalized.get("day28_units_sold") or 0),
        ) > (
            float(previous.get("day28_gmv") or 0),
            float(previous.get("day28_units_sold") or 0),
        ):
            products_by_id[product_id] = normalized
    products = list(products_by_id.values())
    products.sort(
        key=lambda item: (
            -float(item.get("day28_gmv") or 0),
            -float(item.get("day28_units_sold") or 0),
            str(item.get("product_id") or ""),
        )
    )
    products = products[:30]
    gmv_values = [float(item["day28_gmv"]) for item in products if item.get("day28_gmv") is not None]
    observed_gmv = sum(gmv_values)

    def observed_share(top_n: int) -> float | None:
        if not observed_gmv:
            return None
        return round(sum(gmv_values[:top_n]) / observed_gmv * 100, 2)

    bands = Counter()
    for product in products:
        price = product.get("price")
        if price is None:
            bands["unknown"] += 1
        elif price < 20:
            bands["under_20"] += 1
        elif price < 40:
            bands["20_40"] += 1
        elif price < 60:
            bands["40_60"] += 1
        elif price <= 100:
            bands["60_100"] += 1
        else:
            bands["over_100"] += 1
    return {
        "scope": "seller product-list rows locally filtered to resolved Bras L3 category IDs",
        "resolved_bra_category_ids": sorted(target_category_ids),
        "sampled_page_count": len(_as_list(data.get("calls"))),
        "sampled_product_row_count": len(raw_product_rows),
        "observed_product_count": len(products),
        "new_product_count_30d": sum(bool(item.get("is_new_30d")) for item in products),
        "observed_top1_gmv_share_percent": observed_share(1),
        "observed_top3_gmv_share_percent": observed_share(3),
        "concentration_denominator": "sum of returned product rows with day28_gmv",
        "price_band_product_counts": dict(bands),
        "excluded_explicit_non_bra_count": excluded_category_count,
        "excluded_unknown_category_count": excluded_unknown_category_count,
        "top_products": products[:5],
    }


def _normalize_distribution(value: Any) -> list[dict[str, Any]]:
    return [
        _bounded_scalars(row)
        for row in _as_list(value)[:10]
        if isinstance(row, dict)
    ]


def _normalize_channels(data: dict[str, Any]) -> dict[str, Any]:
    content = _as_dict(data.get("content_type_distribution"))
    sales = _as_dict(data.get("sales_channel_distribution"))
    content_gmv = _normalize_distribution(content.get("by_gmv"))
    sales_gmv = _normalize_distribution(sales.get("by_gmv"))

    def share(row: dict[str, Any]) -> float:
        return float(_number(row.get("gmv_share_percent")) or 0)

    leading_content = max(content_gmv, key=share, default={})
    leading_sales = max(sales_gmv, key=share, default={})
    return {
        "scope": "whole shop for the requested 28-day window",
        "content_type_by_gmv": content_gmv,
        "content_type_by_units_sold": _normalize_distribution(content.get("by_units_sold")),
        "sales_channel_by_gmv": sales_gmv,
        "sales_channel_by_units_sold": _normalize_distribution(sales.get("by_units_sold")),
        "leading_content_type": leading_content.get("content_type_label"),
        "leading_content_share_percent": _number(leading_content.get("gmv_share_percent")),
        "leading_sales_channel": leading_sales.get("sales_channel_label"),
        "leading_sales_channel_share_percent": _number(
            leading_sales.get("gmv_share_percent")
        ),
    }


def _normalize_trend(data: dict[str, Any], generated_date: dt.date) -> dict[str, Any]:
    daily: list[dict[str, Any]] = []
    for row in _find_rows(data, "date"):
        day = _date(_first_value(row, ("date", "stat_date", "data_date")))
        if not day or day >= generated_date:
            continue
        daily.append(
            {
                "date": day.isoformat(),
                "gmv": _first_number(row, ("usd_gmv", "gmv", "sale_amount", "sales_amount")),
                "units_sold": _integer(
                    _first_value(row, ("units_sold", "sold_count", "sales_count"))
                ),
                "creator_count": _integer(
                    _first_value(row, ("creator_count", "linked_creator_count"))
                ),
                "video_count": _integer(
                    _first_value(row, ("video_count", "linked_video_count"))
                ),
                "active_product_count": _integer(
                    _first_value(row, ("active_product_count", "products_with_sales_count"))
                ),
            }
        )
    daily.sort(key=lambda row: str(row.get("date") or ""))
    daily = daily[-28:]
    latest_14 = daily[-14:]
    p7 = latest_14[:7] if len(latest_14) == 14 else []
    l7 = latest_14[7:] if len(latest_14) == 14 else []

    def total(rows: list[dict[str, Any]], field: str) -> float | None:
        values = [_number(row.get(field)) for row in rows]
        present = [value for value in values if value is not None]
        return round(sum(present), 2) if present else None

    p7_gmv = total(p7, "gmv")
    l7_gmv = total(l7, "gmv")
    p7_units = total(p7, "units_sold")
    l7_units = total(l7, "units_sold")
    primary_p7 = p7_gmv if p7_gmv is not None else p7_units
    primary_l7 = l7_gmv if l7_gmv is not None else l7_units
    ratio = (
        round(primary_l7 / primary_p7, 3)
        if primary_l7 is not None and primary_p7 not in (None, 0)
        else None
    )
    if len(latest_14) < 14:
        label = "观察期不足"
    elif primary_p7 == 0 and (primary_l7 or 0) > 0:
        label = "新启动"
    elif ratio is None:
        label = "趋势不可判断"
    elif ratio >= 1.2:
        label = "加速"
    elif ratio < 0.8:
        label = "回落"
    else:
        label = "平稳"
    return {
        "scope": "whole shop daily trend",
        "complete_day_count": len(daily),
        "p7_gmv": p7_gmv,
        "l7_gmv": l7_gmv,
        "p7_units_sold": int(p7_units) if p7_units is not None else None,
        "l7_units_sold": int(l7_units) if l7_units is not None else None,
        "l7_p7_ratio": ratio,
        "trend_label": label,
        "daily_trend": daily[-14:],
    }


def _creator_uid(row: dict[str, Any]) -> str:
    creator = _as_dict(row.get("creator"))
    return str(row.get("uid") or row.get("creator_uid") or creator.get("uid") or "")


def _normalize_creators(data: dict[str, Any], creator_url_template: str) -> dict[str, Any]:
    creators: list[dict[str, Any]] = []
    for row in _find_rows(data, "creator"):
        creator = {**row, **_as_dict(row.get("creator"))}
        uid = _creator_uid(row)
        if not uid:
            continue
        fastmoss_url = str(_first_value(creator, ("fastmoss_url",)) or "").strip()
        if not fastmoss_url and creator_url_template:
            fastmoss_url = creator_url_template.replace("{creator_id}", uid)
            fastmoss_url = fastmoss_url.replace("{uid}", uid)
        creators.append(
            {
                "uid": uid,
                "nickname": _first_value(
                    creator, ("nickname", "creator_name", "display_name", "unique_id")
                ),
                "fastmoss_url": fastmoss_url or None,
                "follower_count": _integer(
                    _first_value(creator, ("follower_count", "followers"))
                ),
                "sale_amount": _first_number(
                    creator, ("sale_amount", "gmv", "day28_gmv", "total_gmv")
                ),
                "sold_count": _integer(
                    _first_value(creator, ("sold_count", "units_sold", "day28_units_sold"))
                ),
                "video_count": _integer(
                    _first_value(creator, ("video_count", "linked_video_count"))
                ),
                "live_count": _integer(
                    _first_value(creator, ("live_count", "linked_live_count"))
                ),
            }
        )
    creators.sort(
        key=lambda item: (
            -float(item.get("sale_amount") or 0),
            -float(item.get("sold_count") or 0),
            str(item.get("uid") or ""),
        )
    )
    creators = creators[:10]
    gmv_values = [float(row["sale_amount"]) for row in creators if row.get("sale_amount") is not None]
    observed_gmv = sum(gmv_values)
    top3_share = (
        round(sum(gmv_values[:3]) / observed_gmv * 100, 2) if observed_gmv else None
    )
    return {
        "scope": "whole shop creators for the requested 28-day window",
        "observed_creator_count": len(creators),
        "observed_top3_creator_gmv_share_percent": top3_share,
        "concentration_denominator": "sum of returned creator rows with sale_amount",
        "top_creators": creators[:5],
        "source_distributions": {
            key: _bounded_scalars(data.get(key))
            for key in (
                "creator_distribution",
                "follower_distribution",
                "creator_tier_distribution",
                "author_product_type_distribution",
            )
            if data.get(key) is not None
        },
    }


def _median(values: list[Any]) -> float | None:
    numbers = [number for value in values if (number := _number(value)) is not None]
    return round(median(numbers), 2) if numbers else None


def build_tiktok_bra_competitor_shop_report_data(payload: dict[str, Any]) -> dict[str, Any]:
    tool_results = [item for item in _as_list(payload.get("toolResults")) if isinstance(item, dict)]
    if not _successful_tools(tool_results, CATEGORY_TOOL):
        raise ValueError(
            "TikTokBraCompetitorShopReportData requires one successful FastMoss category resolution result."
        )
    if not _tools(tool_results, URL_TOOL):
        raise ValueError(
            "TikTokBraCompetitorShopReportData requires an attempted FastMoss detail URL template call."
        )

    candidate_limit = max(10, min(int(payload.get("shopCandidateSize") or 50), 100))
    analysis_limit = max(1, min(int(payload.get("shopAnalysisCount") or 10), 30))
    brand = str(payload.get("brand") or "Hsia")
    generated_at = str(payload.get("generatedAt") or dt.datetime.now(dt.UTC).isoformat())
    generated_date = _generated_date(generated_at)
    new_product_days = max(
        1,
        min(
            _integer(str(payload.get("newProductWindow") or "30d").replace("d", "")) or 30,
            90,
        ),
    )
    ranking_preflight = competitor_shop_ranking_preflight(
        tool_results,
        candidate_limit=candidate_limit,
        brand=brand,
    )
    target_category = _as_dict(ranking_preflight.get("target_category"))
    target_category_id = str(target_category.get("category_id_l3") or "")
    product_category_candidates = _bra_product_category_candidates(tool_results)
    target_product_category_ids = {
        str(item.get("category_id_l3") or "")
        for item in product_category_candidates
        if item.get("category_id_l3")
    }
    target_product_category_ids.add(target_category_id)
    candidates = _as_list(ranking_preflight.get("candidates"))
    subject_brand_shops = _as_list(ranking_preflight.get("subject_brand_shops"))
    ranking_scope = _as_dict(ranking_preflight.get("ranking_scope"))
    if not candidates:
        raise ValueError(
            "TikTokBraCompetitorShopReportData requires at least one external competitor shop in the US L3 Bras ranking."
        )
    selected = candidates[: min(analysis_limit, len(candidates))]
    selected_ids = [str(row.get("seller_id") or "") for row in selected]
    missing_attempts: dict[str, list[str]] = {}
    for tool_name in STANDARD_SHOP_TOOLS:
        attempted = _attempted_seller_ids(tool_results, tool_name)
        missing = [seller_id for seller_id in selected_ids if seller_id not in attempted]
        if missing:
            missing_attempts[tool_name] = missing
    if missing_attempts:
        details = "; ".join(
            f"{tool_name.split('__')[-1]}=" + ",".join(seller_ids)
            for tool_name, seller_ids in missing_attempts.items()
        )
        raise ValueError(
            "Standard shop analysis has not been attempted for every selected seller_id: " + details
        )

    data_by_tool = {
        tool_name: _successful_data_by_seller(tool_results, tool_name)
        for tool_name in STANDARD_SHOP_TOOLS
        if tool_name != PRODUCT_TOOL
    }
    data_by_tool[PRODUCT_TOOL] = _successful_product_data_by_seller(tool_results)
    shop_url_template = _url_template(tool_results, "shop")
    product_url_template = _url_template(tool_results, "product")
    creator_url_template = _url_template(tool_results, "creator")
    if shop_url_template:
        for candidate in candidates:
            seller_id = str(candidate.get("seller_id") or "")
            candidate["fastmoss_url"] = shop_url_template.replace(
                "{seller_id}", seller_id
            ).replace("{shop_id}", seller_id)
    comparison: list[dict[str, Any]] = []
    report_gaps: list[str] = []
    for ranking in selected:
        seller_id = str(ranking.get("seller_id") or "")
        gaps: list[str] = []
        base_data = data_by_tool[BASE_TOOL].get(seller_id, {})
        product_data = data_by_tool[PRODUCT_TOOL].get(seller_id, {})
        sale_data = data_by_tool[SALE_TOOL].get(seller_id, {})
        trend_data = data_by_tool[TREND_TOOL].get(seller_id, {})
        creator_data = data_by_tool[CREATOR_TOOL].get(seller_id, {})
        for tool_name, data in (
            (BASE_TOOL, base_data),
            (PRODUCT_TOOL, product_data),
            (SALE_TOOL, sale_data),
            (TREND_TOOL, trend_data),
            (CREATOR_TOOL, creator_data),
        ):
            if not data:
                gaps.append(f"{tool_name.split('__')[-1]} 未成功返回数据。")

        shop_url = str(ranking.get("fastmoss_url") or "").strip()
        if not shop_url and shop_url_template:
            shop_url = shop_url_template.replace("{shop_id}", seller_id)
            shop_url = shop_url.replace("{seller_id}", seller_id)
        product_structure = (
            _normalize_products(
                product_data,
                target_category_id=target_category_id,
                target_category_ids=target_product_category_ids,
                generated_date=generated_date,
                new_product_days=new_product_days,
                product_url_template=product_url_template,
            )
            if product_data
            else {}
        )
        if product_data and not product_structure.get("observed_product_count"):
            gaps.append(
                "shop_product_analysis 已返回店铺商品页，但没有可识别为目标文胸 L3 的商品行。"
            )
        channel_structure = _normalize_channels(sale_data) if sale_data else {}
        trend = _normalize_trend(trend_data, generated_date) if trend_data else {}
        creator_structure = (
            _normalize_creators(creator_data, creator_url_template) if creator_data else {}
        )
        comparison.append(
            {
                "rank": ranking.get("competitor_rank"),
                "seller_id": seller_id,
                "shop_name": ranking.get("shop_name"),
                "fastmoss_url": shop_url or None,
                "ranking_snapshot": {
                    key: ranking.get(key)
                    for key in (
                        "period_gmv",
                        "period_units_sold",
                        "gmv_growth_rate_percent",
                        "units_sold_growth_rate_percent",
                        "linked_creator_count",
                        "products_with_sales_count",
                        "shop_type_code",
                        "is_cross_border",
                        "shop_rating",
                    )
                },
                "base_snapshot": _normalize_base(base_data, ranking) if base_data else {},
                "product_structure": product_structure,
                "channel_structure": channel_structure,
                "trend": trend,
                "creator_structure": creator_structure,
                "comparison_scope_notes": [
                    (
                        "ranking_snapshot is L3 Bras category-scoped for the completed monthly ranking period"
                        if not ranking_scope.get("is_fallback")
                        else "ranking_snapshot is a Women's Underwear L2 completed-week candidate-universe fallback; it is not a Top Bras shop claim"
                    ),
                    "product_structure is locally filtered by resolved Bras L3 IDs from seller-only product-list pages; product rows retain their returned 28-day metrics",
                    "base_snapshot, channel_structure, trend, and creator_structure are whole-shop metrics unless FastMoss explicitly labels a narrower scope",
                ],
                "data_gaps": gaps,
            }
        )
        report_gaps.extend(f"{seller_id}: {gap}" for gap in gaps)

    if not shop_url_template:
        report_gaps.append("FastMoss 店铺详情链接模板未成功返回，部分店铺链接不可用。")
    if ranking_scope.get("is_fallback"):
        report_gaps.append(
            "FastMoss 美国 Bras L3 月度店铺榜未返回可用行；候选池降级为女士内衣 L2 最近完整周榜。"
            "因此候选排名只能称为女士内衣店铺榜样本，不能称为文胸店铺 Top 排名；文胸判断仅来自后续 L3 商品分析。"
        )
    if len(candidates) < candidate_limit:
        report_gaps.append(
            f"外部竞品候选池仅取得 {len(candidates)}/{candidate_limit} 家；不得称为完整 Top {candidate_limit}。"
        )
    if len(comparison) < analysis_limit:
        report_gaps.append(
            f"标准分析对象仅取得 {len(comparison)}/{analysis_limit} 家，横向结论只适用于实际样本。"
        )

    successful_counts = {
        tool_name: sum(seller_id in data_by_tool[tool_name] for seller_id in selected_ids)
        for tool_name in STANDARD_SHOP_TOOLS
    }
    complete_shop_count = sum(not row.get("data_gaps") for row in comparison)
    status = (
        "complete"
        if not ranking_scope.get("is_fallback")
        and len(candidates) >= candidate_limit
        and len(comparison) >= analysis_limit
        and complete_shop_count == len(comparison)
        and bool(shop_url_template)
        else "degraded"
    )
    peer_benchmarks = {
        "period_gmv_median": _median(
            [row.get("ranking_snapshot", {}).get("period_gmv") for row in comparison]
        ),
        "period_units_sold_median": _median(
            [row.get("ranking_snapshot", {}).get("period_units_sold") for row in comparison]
        ),
        "gmv_growth_rate_percent_median": _median(
            [row.get("ranking_snapshot", {}).get("gmv_growth_rate_percent") for row in comparison]
        ),
        "observed_top1_product_gmv_share_percent_median": _median(
            [
                row.get("product_structure", {}).get("observed_top1_gmv_share_percent")
                for row in comparison
            ]
        ),
        "leading_channel_share_percent_median": _median(
            [
                row.get("channel_structure", {}).get("leading_sales_channel_share_percent")
                for row in comparison
            ]
        ),
        "observed_top3_creator_gmv_share_percent_median": _median(
            [
                row.get("creator_structure", {}).get(
                    "observed_top3_creator_gmv_share_percent"
                )
                for row in comparison
            ]
        ),
    }
    top_scale = max(
        comparison,
        key=lambda row: float(row.get("ranking_snapshot", {}).get("period_gmv") or 0),
        default={},
    )
    def growth_sort_value(row: dict[str, Any]) -> float:
        value = _number(_as_dict(row.get("ranking_snapshot")).get("gmv_growth_rate_percent"))
        return value if value is not None else float("-inf")

    fastest_growth = max(comparison, key=growth_sort_value, default={})
    return {
        "schema_version": "tiktok_bra_competitor_shop_report_data.v1",
        "title": "TikTok Shop 美国文胸竞品店铺分析",
        "brand": brand,
        "marketplace": "US",
        "category": BRA_CATEGORY_LABEL,
        "generated_at": generated_at,
        "time_range": payload.get("timeRange") or "28d",
        "new_product_window": payload.get("newProductWindow") or "30d",
        "status": status,
        "source_scope": {
            "source": "FastMoss",
            "region": "US",
            "category_id_l3": target_category_id,
            "category_name_l3": target_category.get("name") or BRA_CATEGORY_LABEL,
            "category_path": target_category.get("path"),
            "product_category_ids_l3": sorted(target_product_category_ids),
            "product_category_candidates_l3": product_category_candidates,
            "ranking_scope_mode": ranking_scope.get("mode"),
            "ranking_scope_is_fallback": bool(ranking_scope.get("is_fallback")),
            "ranking_category_id": ranking_scope.get("category_id"),
            "ranking_category_name": ranking_scope.get("category_name"),
            "ranking_period": ranking_scope.get("date_value"),
            "ranking_period_type": ranking_scope.get("date_type"),
            "ranking_sort": ranking_scope.get("sort"),
            "ranking_pages_collected": ranking_scope.get("pages_collected"),
            "candidate_limit": candidate_limit,
            "analysis_limit": analysis_limit,
            "subject_brand_excluded_count": ranking_scope.get(
                "subject_brand_excluded_count"
            ),
            "subject_brand_exclusions": subject_brand_shops[:10],
            "scope_boundary": (
                (
                    "Ranking rows are L3 Bras scoped, while seller product-list rows are locally filtered to resolved Bras L3 IDs; "
                    if not ranking_scope.get("is_fallback")
                    else "Ranking rows are Women's Underwear L2 candidate-universe evidence, while seller product-list rows are locally filtered to resolved Bras L3 IDs; "
                )
                + "base, channel, trend, and creator analysis are whole-shop unless their source explicitly says otherwise."
            ),
        },
        "summary": {
            "candidate_count": len(candidates),
            "analyzed_shop_count": len(comparison),
            "complete_shop_count": complete_shop_count,
            "top_scale_shop": {
                "shop_name": top_scale.get("shop_name"),
                "seller_id": top_scale.get("seller_id"),
                "period_gmv": _as_dict(top_scale.get("ranking_snapshot")).get("period_gmv"),
            },
            "fastest_growth_shop": {
                "shop_name": fastest_growth.get("shop_name"),
                "seller_id": fastest_growth.get("seller_id"),
                "gmv_growth_rate_percent": _as_dict(
                    fastest_growth.get("ranking_snapshot")
                ).get("gmv_growth_rate_percent"),
            },
        },
        "candidate_shops": candidates,
        "shop_comparison": comparison,
        "peer_benchmarks": peer_benchmarks,
        "output_contract": {
            "comparison_required_columns": [
                {"field": "rank", "label": "排名"},
                {"field": "shop_name", "label": "店铺"},
                {"field": "seller_id", "label": "seller_id"},
                {"field": "period_gmv", "label": "类目期GMV"},
                {"field": "period_units_sold", "label": "类目期销量"},
                {"field": "gmv_growth_rate_percent", "label": "GMV增长"},
                {"field": "shop_type_code", "label": "店铺类型"},
                {"field": "observed_product_count", "label": "文胸商品样本"},
                {"field": "trend_label", "label": "近期趋势"},
                {"field": "leading_sales_channel", "label": "主导渠道"},
                {"field": "observed_creator_count", "label": "达人样本"},
            ]
        },
        "report_quality": {
            "status": status,
            "candidate_target": candidate_limit,
            "candidate_actual": len(candidates),
            "analysis_target": analysis_limit,
            "analysis_actual": len(comparison),
            "complete_shop_count": complete_shop_count,
        },
        "data_gaps": list(dict.fromkeys(report_gaps)),
        "methodology": [
            "先解析 Bras/女士文胸 L3，优先用 US 已完成自然月、usd_gmv 降序的 L3 店铺榜建立候选池。",
            "仅当 L3 月榜已尝试且无可用行时，允许使用 US 女士内衣 L2 最近完整周榜作为候选宇宙；该降级排名不得表述为文胸店铺 Top 排名。",
            "按 seller_id 去重；与 brand 明确匹配的自有店铺从外部竞品候选中剔除。",
            "候选池最多 50 家，只对前 10 家外部竞品执行同口径标准分析。",
            "店铺商品先以 seller_id 获取，最多有限翻页三页；Builder 再按已解析的 Bras L3 category.l3.id 本地筛选并按 product_id 去重。",
            "店铺整体渠道、趋势和达人指标不得改写为文胸子集指标。",
            "商品与达人集中度若只基于返回列表，明确使用 observed 口径，不冒充全店真实集中度。",
        ],
        "source_summary": {
            "tool_result_count": len(tool_results),
            "ranking_call_count": len(_tools(tool_results, RANKING_TOOL)),
            "ranking_success_count": len(_successful_tools(tool_results, RANKING_TOOL)),
            "ranking_pages_collected": ranking_scope.get("pages_collected"),
            "candidate_count": len(candidates),
            "analysis_count": len(comparison),
            "successful_counts": successful_counts,
        },
    }


def tiktok_bra_competitor_shop_report_data_to_artifact(
    report_data: dict[str, Any],
) -> dict[str, Any]:
    summary = _as_dict(report_data.get("summary"))
    top_scale = _as_dict(summary.get("top_scale_shop"))
    fastest_growth = _as_dict(summary.get("fastest_growth_shop"))
    findings: list[str] = []
    if top_scale.get("shop_name"):
        findings.append(
            f"类目期规模领先店铺为 {top_scale.get('shop_name')}，期GMV {top_scale.get('period_gmv')}。"
        )
    if fastest_growth.get("shop_name"):
        findings.append(
            f"当前样本增长最快店铺为 {fastest_growth.get('shop_name')}，GMV增长率 {fastest_growth.get('gmv_growth_rate_percent')}%。"
        )
    return {
        "title": report_data.get("title") or "TikTok Shop 美国文胸竞品店铺分析",
        "executive_summary": (
            f"基于 FastMoss 美国女士文胸 L3 店铺榜建立 {summary.get('candidate_count', 0)} 家外部竞品候选，"
            f"对其中 {summary.get('analyzed_shop_count', 0)} 家执行同口径店铺标准分析。"
        ),
        "kpis": [
            {"label": "竞品候选", "value": summary.get("candidate_count")},
            {"label": "标准分析", "value": summary.get("analyzed_shop_count")},
            {"label": "完整店铺", "value": summary.get("complete_shop_count")},
        ],
        "market_basics": [],
        "price_and_margin": [],
        "competition": report_data.get("shop_comparison") or [],
        "user_voice": [],
        "key_findings": findings,
        "opportunities": [],
        "opportunity_pool": [],
        "risks": report_data.get("data_gaps") or [],
        "data_gaps": report_data.get("data_gaps") or [],
        "next_steps": [],
    }

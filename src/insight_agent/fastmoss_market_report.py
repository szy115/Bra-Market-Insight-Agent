from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Callable
from typing import Any

SUCCESS_STATUSES = {"ok", "partial_ok"}
FASTMOSS_PREFIX = "mcp__fastmoss__"


FASTMOSS_MARKET_TASKS: tuple[dict[str, Any], ...] = (
    {
        "dimension_id": "FM01",
        "name": "美国功能细分与查询边界",
        "priority": "P0",
        "market_question": "用户给出的功能词是否已转换成多个 TikTok Shop US 商品关键词入口？",
        "tool_mapping": ["product_search:keyword_recall"],
        "allowed_conclusion": "定义 FastMoss 关键词可识别的美国功能细分样本及查询边界。",
        "limitation": "关键词商品召回不是搜索量，也不能直接代表完整细分市场规模。",
    },
    {
        "dimension_id": "FM02",
        "name": "细分商品样本覆盖与质量",
        "priority": "P0",
        "market_question": "多关键词召回后是否有足够的去重商品支持细分分析和头部深挖？",
        "tool_mapping": ["product_search:multi_query_merge"],
        "allowed_conclusion": "描述关键词、排序、页码、去重商品数和实际样本覆盖。",
        "limitation": "样本少于深挖目标时报告降级；空结果只表示未取回数据，不表示市场为零。",
    },
    {
        "dimension_id": "FM03",
        "name": "代理父类目解析与披露",
        "priority": "P0",
        "market_question": "功能细分不存在独立类目时，哪个标准类目可作为市场背景？",
        "tool_mapping": ["search_category_by_words"],
        "allowed_conclusion": "记录标准类目路径、category_id 和其代理父类目角色。",
        "limitation": "代理父类目只能提供背景，绝不能写成功能细分的规模、份额或竞争结构。",
    },
    {
        "dimension_id": "FM04",
        "name": "代理父类目规模与趋势",
        "priority": "P0",
        "market_question": "代理父类目的规模、相对位置、销售结果和内容供给趋势如何？",
        "tool_mapping": [
            "market_category_ranking",
            "market_category_analysis:basic_metrics",
            "market_category_analysis:sales_trends",
        ],
        "allowed_conclusion": "描述代理父类目在上一完整周期的第三方估算规模和趋势。",
        "limitation": "父类目趋势不能直接归因到关键词定义的功能细分。",
    },
    {
        "dimension_id": "FM05",
        "name": "代理父类目价格与竞争背景",
        "priority": "P0",
        "market_question": "代理父类目的价格带、头部商品和店铺结构如何？",
        "tool_mapping": [
            "market_category_analysis:price_distribution",
            "shop_rank_top_selling",
            "product_rank_top_selling",
        ],
        "allowed_conclusion": "描述父类目价格和竞争背景，并与细分商品样本分栏展示。",
        "limitation": "不得用父类目头部商品或价格分布替代功能细分结构。",
    },
    {
        "dimension_id": "FM06",
        "name": "代理父类目达人生态",
        "priority": "P0",
        "market_question": "代理父类目的销售由哪些达人层级贡献，是否依赖少数头部达人？",
        "tool_mapping": ["market_category_author_sales_matrix", "creator_rank_top_ecommerce"],
        "allowed_conclusion": "描述父类目达人层级贡献和代表达人；粉丝量不等于带货能力。",
        "limitation": "只能作为父类目背景；缺少具体达人榜时不能判断头部达人依赖。",
    },
    {
        "dimension_id": "FM07",
        "name": "细分规模、销量与新品商品池",
        "priority": "P0",
        "market_question": "关键词细分中哪些商品代表 GMV、销量和新品三个候选池？",
        "tool_mapping": [
            "product_search:day28_gmv",
            "product_search:day28_units_sold",
            "product_search:is_new_listed",
        ],
        "allowed_conclusion": "按 product_id 建立关键词细分的规模池、销量池和新品池，并保留命中查询。",
        "limitation": "product_search 没有直接的关键词增长率或需求量；无 parent/variation 时不称唯一商品家族。",
    },
    {
        "dimension_id": "FM08",
        "name": "细分商品 Market Outcome",
        "priority": "P0",
        "market_question": "深挖商品最近观察窗口的 GMV、销量和日趋势是否兑现？",
        "tool_mapping": ["product_sales_trend"],
        "allowed_conclusion": "逐商品描述观察窗口内的成交结果与变化，不把累计 GMV当作当前动量。",
        "limitation": "未覆盖全部 head listings 时，只能对已完成商品下结论。",
    },
    {
        "dimension_id": "FM09",
        "name": "细分商品 Content Momentum",
        "priority": "P0",
        "market_question": "每个深挖商品由哪些达人和视频承接，广告与自然样本如何？",
        "tool_mapping": ["product_creator_analysis", "product_video_list"],
        "allowed_conclusion": "描述当前达人结构、视频样本、成交贡献和广告标记。",
        "limitation": "没有前一等长窗口时不得声称视频或达人正在增长，也不得输出确定生命周期。",
    },
    {
        "dimension_id": "FM10",
        "name": "细分渠道与广告归因",
        "priority": "P0",
        "market_question": "商品销售来自广告、自然、联盟、自营、短视频、直播还是商品卡？",
        "tool_mapping": ["product_overview", "shop_sale_analysis"],
        "allowed_conclusion": "仅根据渠道分布字段判断商品或店铺的渠道结构。",
        "limitation": "视频列表中的 is_ad 样本不能替代完整渠道分布。",
    },
    {
        "dimension_id": "FM11",
        "name": "Entry Timing",
        "priority": "P0",
        "market_question": "关键词细分样本的 Market Outcome 与 Content Momentum 是否支持入场窗口？",
        "tool_mapping": ["derived:FM01+FM02+FM08+FM09"],
        "allowed_conclusion": "输出窗口打开、优先验证、窗口收窄、窗口关闭或不可判断。",
        "limitation": "关键词召回、商品覆盖或等长内容窗口任一不足时，只能输出不可判断或低置信待验证。",
    },
    {
        "dimension_id": "FM12",
        "name": "产品可进入性与 Hsia Fit",
        "priority": "P0",
        "market_question": "候选产品能否通过竞争、内容、渠道、经济性、供应链和 Hsia right-to-win 门禁？",
        "tool_mapping": ["derived:FM07+FM08+FM09+FM10", "user_or_internal_hsia_facts"],
        "allowed_conclusion": "分别输出产品结论与 Hsia Fit；缺少内部事实时标记证据不足。",
        "limitation": "FastMoss 竞品数据不能替代 Hsia 成本、退货、供应链、尺码和内容产能事实。",
    },
)


def _parse_generated_at(value: Any) -> dt.datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        parsed = dt.datetime.now(dt.UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def _us_pacific_offset(instant: dt.datetime) -> dt.timedelta:
    """Return the US Pacific UTC offset without requiring host timezone data."""
    utc_instant = instant.astimezone(dt.UTC)
    year = utc_instant.year
    march_first = dt.date(year, 3, 1)
    second_sunday_march = 1 + ((6 - march_first.weekday()) % 7) + 7
    november_first = dt.date(year, 11, 1)
    first_sunday_november = 1 + ((6 - november_first.weekday()) % 7)
    dst_start_utc = dt.datetime(year, 3, second_sunday_march, 10, tzinfo=dt.UTC)
    dst_end_utc = dt.datetime(year, 11, first_sunday_november, 9, tzinfo=dt.UTC)
    return dt.timedelta(hours=-7 if dst_start_utc <= utc_instant < dst_end_utc else -8)


def completed_us_periods(generated_at: Any) -> dict[str, str]:
    # FastMoss US reports use completed natural periods. Calculate Pacific DST
    # locally because the packaged Windows runtime does not include IANA tzdata.
    generated = _parse_generated_at(generated_at)
    us_reference = generated.astimezone(dt.timezone(_us_pacific_offset(generated)))
    current_date = us_reference.date()
    yesterday = current_date - dt.timedelta(days=1)
    previous_week_start = current_date - dt.timedelta(days=current_date.weekday() + 7)
    iso_year, iso_week, _ = previous_week_start.isocalendar()
    current_month_start = current_date.replace(day=1)
    previous_month_end = current_month_start - dt.timedelta(days=1)
    return {
        "timezone": "US Pacific business date",
        "reference_date": current_date.isoformat(),
        "day": yesterday.isoformat(),
        "week": f"{iso_year}-W{iso_week:02d}",
        "month": previous_month_end.strftime("%Y-%m"),
    }


def _tool_input(tool: dict[str, Any]) -> dict[str, Any]:
    return tool.get("input") if isinstance(tool.get("input"), dict) else {}


def _tool_data(tool: dict[str, Any]) -> dict[str, Any]:
    return tool.get("data") if isinstance(tool.get("data"), dict) else {}


def _short_name(tool: dict[str, Any]) -> str:
    return str(tool.get("name") or "").removeprefix(FASTMOSS_PREFIX)


def _nested_filter(tool: dict[str, Any]) -> dict[str, Any]:
    value = _tool_input(tool).get("filter")
    return value if isinstance(value, dict) else {}


def _region(tool: dict[str, Any]) -> str:
    request = _tool_input(tool)
    data = _tool_data(tool)
    category = data.get("category") if isinstance(data.get("category"), dict) else {}
    ranking_scope = data.get("ranking_scope") if isinstance(data.get("ranking_scope"), dict) else {}
    shop = data.get("shop") if isinstance(data.get("shop"), dict) else {}
    return (
        str(
            _nested_filter(tool).get("region")
            or request.get("region")
            or data.get("region")
            or category.get("region")
            or ranking_scope.get("region")
            or shop.get("region")
            or ""
        )
        .strip()
        .upper()
    )


def _date_type(tool: dict[str, Any]) -> str:
    return (
        str(_nested_filter(tool).get("date_type") or _tool_input(tool).get("date_type") or "")
        .strip()
        .lower()
    )


def _date_value(tool: dict[str, Any]) -> str:
    return str(
        _nested_filter(tool).get("date_value") or _tool_input(tool).get("date_value") or ""
    ).strip()


def _analysis_type(tool: dict[str, Any]) -> str:
    return str(
        _tool_input(tool).get("analysis_type") or _tool_data(tool).get("analysis_type") or ""
    ).strip()


def _product_id(tool: dict[str, Any]) -> str:
    request = _tool_input(tool)
    data = _tool_data(tool)
    return str(
        _nested_filter(tool).get("product_id")
        or request.get("product_id")
        or data.get("product_id")
        or ""
    ).strip()


def _search_keywords(tool: dict[str, Any]) -> str:
    request = _tool_input(tool)
    return str(
        request.get("keywords")
        or request.get("keyword")
        or request.get("query")
        or ""
    ).strip()


def _orderby_fields(tool: dict[str, Any]) -> set[str]:
    value = _tool_input(tool).get("orderby")
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return set()
    return {
        str(item.get("field") or "").strip()
        for item in value
        if isinstance(item, dict) and str(item.get("field") or "").strip()
    }


def _product_search_source_rows(tool: dict[str, Any]) -> list[dict[str, Any]]:
    data = _tool_data(tool)
    containers: list[Any] = [data]
    if isinstance(data.get("result"), dict):
        containers.append(data["result"])
    elif isinstance(data.get("result"), list):
        return [row for row in data["result"] if isinstance(row, dict)]
    for container in containers:
        for key in ("list", "products", "items"):
            rows = container.get(key) if isinstance(container, dict) else None
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def _product_search_rows(
    tools: list[dict[str, Any]],
    evidence_by_object: dict[int, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tool in tools:
        evidence_id = evidence_by_object.get(id(tool), "")
        matched_query = _search_keywords(tool)
        orderby_fields = sorted(_orderby_fields(tool))
        is_new_listed = bool(_nested_filter(tool).get("is_new_listed"))
        for raw in _product_search_source_rows(tool):
            product = raw.get("product") if isinstance(raw.get("product"), dict) else {}
            sales = (
                raw.get("sales_summary")
                if isinstance(raw.get("sales_summary"), dict)
                else {}
            )
            normalized = {
                **product,
                **raw,
                "product_id": str(
                    raw.get("product_id")
                    or product.get("product_id")
                    or product.get("id")
                    or ""
                ).strip(),
                "title": str(
                    raw.get("title")
                    or raw.get("product_title")
                    or product.get("title")
                    or product.get("product_title")
                    or ""
                ).strip(),
                "matched_query": matched_query,
                "search_orderby_fields": orderby_fields,
                "search_is_new_listed": is_new_listed,
                "evidence_id": evidence_id,
                "source_tool": _short_name(tool),
            }
            for key in (
                "day7_gmv",
                "day7_units_sold",
                "day28_gmv",
                "day28_units_sold",
                "total_gmv",
                "total_units_sold",
                "creator_count",
            ):
                if normalized.get(key) is None and sales.get(key) is not None:
                    normalized[key] = sales[key]
            rows.append(normalized)
    return rows


def _tool_has_rows(tool: dict[str, Any], *keys: str) -> bool:
    data = _tool_data(tool)
    containers = [data]
    if isinstance(data.get("result"), dict):
        containers.append(data["result"])
    return any(
        isinstance(container.get(key), list) and bool(container[key])
        for container in containers
        for key in keys
        if isinstance(container, dict)
    )


def _category_search_has_results(tool: dict[str, Any]) -> bool:
    data = _tool_data(tool)
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    return any(
        isinstance(value, list) and bool(value)
        for value in (
            data.get("categories"),
            data.get("list"),
            result.get("categories"),
            result.get("list"),
        )
    )


def _basic_metrics_has_data(tool: dict[str, Any]) -> bool:
    data = _tool_data(tool)
    return any(
        isinstance(data.get(key), dict) and bool(data[key])
        for key in ("scale_metrics", "growth_metrics", "concentration_metrics")
    )


def _price_distribution_has_data(tool: dict[str, Any]) -> bool:
    data = _tool_data(tool)
    sales = (
        data.get("sales_price_distribution")
        if isinstance(data.get("sales_price_distribution"), dict)
        else {}
    )
    return any(
        isinstance(value, list) and bool(value)
        for value in (
            data.get("product_count_price_distribution"),
            sales.get("gmv_distribution"),
            sales.get("units_sold_distribution"),
        )
    )


def _product_trend_has_data(tool: dict[str, Any]) -> bool:
    data = _tool_data(tool)
    return bool(data.get("period_summary")) or bool(data.get("daily_trend"))


def _product_creator_has_data(tool: dict[str, Any]) -> bool:
    data = _tool_data(tool)
    linked = data.get("linked_creators")
    return bool(data.get("creator_summary")) or bool(linked)


def _product_video_has_data(tool: dict[str, Any]) -> bool:
    data = _tool_data(tool)
    return bool(data.get("videos")) or (_number(data.get("total")) or 0) > 0


def _product_overview_has_data(tool: dict[str, Any]) -> bool:
    data = _tool_data(tool)
    return any(
        bool(data.get(key))
        for key in (
            "period_summary",
            "ads_distribution",
            "channel_distribution",
            "content_distribution",
        )
    )


def _shop_channel_has_data(tool: dict[str, Any]) -> bool:
    data = _tool_data(tool)
    return any(
        bool(data.get(key))
        for key in (
            "period_summary",
            "sales_channel_distribution",
            "channel_distribution",
            "content_type_distribution",
            "content_distribution",
        )
    )


def _is_success(tool: dict[str, Any]) -> bool:
    return str(tool.get("status") or "") in SUCCESS_STATUSES


def _tools(
    tool_results: list[dict[str, Any]],
    name: str,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    return [
        tool
        for tool in tool_results
        if _is_success(tool)
        and _short_name(tool) == name
        and (predicate is None or predicate(tool))
    ]


def _unique_product_count(tools: list[dict[str, Any]]) -> int:
    return len({_product_id(tool) for tool in tools if _product_id(tool)})


def _tool_evidence_ids(
    tools: list[dict[str, Any]], evidence_by_object: dict[int, str]
) -> list[str]:
    return [evidence_by_object[id(tool)] for tool in tools if id(tool) in evidence_by_object]


def _period_is_expected(tool: dict[str, Any], periods: dict[str, str]) -> bool:
    value = _date_value(tool)
    if not value:
        return True
    kind = _date_type(tool)
    if not kind and _short_name(tool) == "market_category_author_sales_matrix":
        kind = "month"
    expected = periods.get(kind)
    return not expected or value == expected


def _is_us_or_unscoped(tool: dict[str, Any]) -> bool:
    return _region(tool) in {"", "US"}


def _status_from_requirements(requirements: list[tuple[str, bool]]) -> tuple[str, str]:
    missing = [label for label, passed in requirements if not passed]
    if not missing:
        return "covered", "All task completion criteria are satisfied."
    return "missing_data", "Missing task evidence: " + "; ".join(missing)


def _attach_source(
    rows: Any, evidence_id: str, source_tool: str, *, limit: int = 30
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    output: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        output.append({**row, "evidence_id": evidence_id, "source_tool": source_tool})
    return output


def _rows_from_tools(
    tools: list[dict[str, Any]],
    evidence_by_object: dict[int, str],
    keys: tuple[str, ...],
    *,
    limit_per_tool: int = 30,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for tool in tools:
        data = _tool_data(tool)
        evidence_id = evidence_by_object.get(id(tool), "")
        for key in keys:
            if isinstance(data.get(key), list):
                output.extend(
                    _attach_source(data[key], evidence_id, _short_name(tool), limit=limit_per_tool)
                )
                break
    return output


def _review_rows(tool: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    data = _tool_data(tool)
    containers = [data]
    for key in ("result", "data"):
        if isinstance(data.get(key), dict):
            containers.append(data[key])
    rows: list[Any] = []
    for container in containers:
        for key in ("reviews", "list", "items", "comments"):
            if isinstance(container.get(key), list):
                rows = container[key]
                break
        if rows:
            break

    product_id = _product_id(tool)
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        content = str(
            row.get("review_text")
            or row.get("content")
            or row.get("review_content")
            or row.get("comment")
            or row.get("text")
            or row.get("body")
            or ""
        ).strip()
        review_id = str(
            row.get("review_id")
            or row.get("comment_id")
            or row.get("id")
            or ""
        ).strip()
        dedupe_key = review_id or " ".join(content.casefold().split())
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        media = (
            row.get("media_urls")
            or row.get("image_urls")
            or row.get("images")
            or row.get("videos")
            or []
        )
        output.append(
            {
                "product_id": product_id,
                "review_id": review_id,
                "rating": row.get("rating")
                or row.get("star")
                or row.get("score")
                or row.get("rating_value"),
                "date": row.get("date")
                or row.get("review_date")
                or row.get("create_time")
                or row.get("published_at"),
                "content": content[:1200],
                "sku": row.get("sku_variant_text")
                or row.get("sku")
                or row.get("sku_name")
                or row.get("variant")
                or row.get("variation"),
                "like_count": (
                    row.get("like_count")
                    if row.get("like_count") is not None
                    else row.get("likes")
                ),
                "media_urls": media[:8] if isinstance(media, list) else [],
            }
        )
        if len(output) >= limit:
            break
    return output


def _aggregate_product_review_rows(
    tools: list[dict[str, Any]],
    *,
    evidence_by_object: dict[int, str],
    limit_per_product: int,
) -> list[dict[str, Any]]:
    """Merge paged review calls into one bounded, deduplicated block per product."""

    grouped: dict[str, dict[str, Any]] = {}
    for tool in tools:
        product_id = _product_id(tool)
        if not product_id:
            continue
        block = grouped.setdefault(
            product_id,
            {
                "product_id": product_id,
                "reviews": [],
                "evidence_ids": [],
                "retrieval_scopes": [],
                "source_tool": _short_name(tool),
                "_seen_ids": set(),
                "_seen_texts": set(),
                "total_review_count": None,
            },
        )
        evidence_id = evidence_by_object.get(id(tool), "")
        if evidence_id and evidence_id not in block["evidence_ids"]:
            block["evidence_ids"].append(evidence_id)
        tool_input = tool.get("input") if isinstance(tool.get("input"), dict) else {}
        tool_filter = tool_input.get("filter") if isinstance(tool_input.get("filter"), dict) else {}
        retrieval_scope = {
            "page": tool_input.get("page"),
            "time_range_days": tool_filter.get("time_range_days"),
            "evidence_id": evidence_id,
        }
        if retrieval_scope not in block["retrieval_scopes"]:
            block["retrieval_scopes"].append(retrieval_scope)
        total_review_count = _number(_tool_data(tool).get("total_review_count"))
        if total_review_count is not None:
            current_total = block.get("total_review_count")
            block["total_review_count"] = max(
                int(total_review_count),
                int(current_total) if current_total is not None else 0,
            )
        for review in _review_rows(tool, limit=limit_per_product):
            review_id = str(review.get("review_id") or "").strip()
            content_key = " ".join(str(review.get("content") or "").casefold().split())
            if not review_id and not content_key:
                continue
            if review_id and review_id in block["_seen_ids"]:
                continue
            if content_key and content_key in block["_seen_texts"]:
                continue
            if review_id:
                block["_seen_ids"].add(review_id)
            if content_key:
                block["_seen_texts"].add(content_key)
            if len(block["reviews"]) < limit_per_product:
                block["reviews"].append(
                    {
                        **review,
                        "evidence_id": evidence_id,
                        "source_page": tool_input.get("page"),
                        "time_range_days": tool_filter.get("time_range_days"),
                    }
                )

    output: list[dict[str, Any]] = []
    for block in grouped.values():
        reviews = block["reviews"]
        text_sample_size = sum(
            1 for review in reviews if str(review.get("content") or "").strip()
        )
        evidence_ids = block["evidence_ids"]
        output.append(
            {
                "product_id": block["product_id"],
                "sample_size": len(reviews),
                "text_sample_size": text_sample_size,
                "rating_only_sample_size": len(reviews) - text_sample_size,
                "total_review_count": block.get("total_review_count"),
                "reviews": reviews,
                "evidence_id": evidence_ids[0] if evidence_ids else "",
                "evidence_ids": evidence_ids,
                "retrieval_scopes": block["retrieval_scopes"],
                "source_tool": block["source_tool"],
            }
        )
    return output


def _dedupe_products(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    output: list[dict[str, Any]] = []
    for row in rows:
        product_id = str(row.get("product_id") or "").strip()
        key = product_id or str(row.get("title") or "").strip().casefold()
        if not key:
            continue
        matched_query = str(row.get("matched_query") or "").strip()
        evidence_id = str(row.get("evidence_id") or "").strip()
        orderby_fields = row.get("search_orderby_fields")
        if key in seen:
            existing = output[seen[key]]
            existing["matched_queries"] = list(
                dict.fromkeys(
                    [
                        *(existing.get("matched_queries") or []),
                        *([matched_query] if matched_query else []),
                    ]
                )
            )
            existing["evidence_ids"] = list(
                dict.fromkeys(
                    [
                        *(existing.get("evidence_ids") or []),
                        *([evidence_id] if evidence_id else []),
                    ]
                )
            )
            existing["search_orderby_fields"] = list(
                dict.fromkeys(
                    [
                        *(existing.get("search_orderby_fields") or []),
                        *(orderby_fields if isinstance(orderby_fields, list) else []),
                    ]
                )
            )
            existing["search_is_new_listed"] = bool(
                existing.get("search_is_new_listed") or row.get("search_is_new_listed")
            )
            continue
        seen[key] = len(output)
        output.append(
            {
                **row,
                "matched_queries": [matched_query] if matched_query else [],
                "evidence_ids": [evidence_id] if evidence_id else [],
            }
        )
    return output


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _row_metric(row: dict[str, Any], *keys: str) -> Any:
    sales = row.get("sales_summary") if isinstance(row.get("sales_summary"), dict) else {}
    for key in keys:
        if _number(row.get(key)) is not None:
            return row[key]
        if _number(sales.get(key)) is not None:
            return sales[key]
    return None


def _chart(
    *,
    chart_id: str,
    dimension_id: str,
    market_question: str,
    title: str,
    chart_type: str,
    data: list[dict[str, Any]],
    source: str,
    evidence_ids: list[str],
    unit: str = "",
    value_format: str = "number",
    insight: str = "",
) -> dict[str, Any] | None:
    usable = [
        item for item in data if isinstance(item, dict) and _number(item.get("value")) is not None
    ]
    if not usable:
        return None
    return {
        "id": chart_id,
        "dimension_id": dimension_id,
        "market_question": market_question,
        "title": title,
        "subtitle": "FastMoss 第三方估算，按报告内标注周期",
        "type": chart_type,
        "insight": insight,
        "x_label": "",
        "y_label": "",
        "unit": unit,
        "orientation": "horizontal" if chart_type == "bar" else "vertical",
        "value_format": value_format,
        "source": source,
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
        "quality_status": "ready",
        "data": usable[:10],
    }


def _build_charts(
    tasks: list[dict[str, Any]],
    datasets: dict[str, Any],
) -> list[dict[str, Any]]:
    task_by_id = {task["dimension_id"]: task for task in tasks}
    charts: list[dict[str, Any]] = []
    ranking_rows = datasets["category_benchmark"]
    chart = _chart(
        chart_id="fastmoss_category_scale",
        dimension_id="FM04",
        market_question=task_by_id["FM04"]["market_question"],
        title="美国代理父类目销量相对位置",
        chart_type="bar",
        data=[
            {
                "label": row.get("category_name"),
                "value": row.get("category_units_sold"),
                "evidence_id": row.get("evidence_id"),
            }
            for row in ranking_rows
        ],
        source="FastMoss · market_category_ranking",
        evidence_ids=[str(row.get("evidence_id") or "") for row in ranking_rows],
        unit="units",
        value_format="compact_integer",
        insight="只用于同父类目、同周期下的相对位置比较。",
    )
    if chart:
        charts.append(chart)

    trend_rows = datasets["category_trend"]
    chart = _chart(
        chart_id="fastmoss_content_momentum",
        dimension_id="FM04",
        market_question=task_by_id["FM04"]["market_question"],
        title="代理父类目带货视频供给趋势",
        chart_type="line",
        data=[
            {
                "label": row.get("period_label"),
                "value": row.get("selling_video_count"),
                "evidence_id": row.get("evidence_id"),
            }
            for row in trend_rows
        ],
        source="FastMoss · market_category_analysis(sales_trends)",
        evidence_ids=[str(row.get("evidence_id") or "") for row in trend_rows],
        unit="videos",
        value_format="compact_integer",
        insight="内容供给是领先指标，但必须与同周期销量方向分开解读。",
    )
    if chart and len(chart["data"]) >= 2:
        charts.append(chart)

    creator_rows = datasets["creator_matrix"]
    chart = _chart(
        chart_id="fastmoss_creator_mix",
        dimension_id="FM06",
        market_question=task_by_id["FM06"]["market_question"],
        title="达人层级 GMV 贡献",
        chart_type="bar",
        data=[
            {
                "label": row.get("follower_tier"),
                "value": row.get("gmv_share_percent"),
                "evidence_id": row.get("evidence_id"),
            }
            for row in creator_rows
        ],
        source="FastMoss · market_category_author_sales_matrix",
        evidence_ids=[str(row.get("evidence_id") or "") for row in creator_rows],
        unit="%",
        value_format="percent",
        insight="粉丝层级只描述贡献结构，不代表单个达人的合作价值。",
    )
    if chart:
        charts.append(chart)

    product_rows = datasets["top_products"]
    chart = _chart(
        chart_id="fastmoss_top_products",
        dimension_id="FM07",
        market_question=task_by_id["FM07"]["market_question"],
        title="代表商品周期 GMV",
        chart_type="bar",
        data=[
            {
                "label": str(row.get("title") or row.get("product_id") or "")[:64],
                "value": _row_metric(row, "day28_gmv", "period_gmv", "total_gmv"),
                "evidence_id": row.get("evidence_id"),
            }
            for row in product_rows
        ],
        source="FastMoss · product_search(keywords, region=US)",
        evidence_ids=[str(row.get("evidence_id") or "") for row in product_rows],
        unit="$",
        value_format="currency",
        insight="这是关键词可识别商品样本，不代表完整细分市场规模。",
    )
    if chart:
        charts.append(chart)

    shop_rows = datasets["top_shops"]
    chart = _chart(
        chart_id="fastmoss_top_shops",
        dimension_id="FM05",
        market_question=task_by_id["FM05"]["market_question"],
        title="头部店铺周期 GMV",
        chart_type="bar",
        data=[
            {
                "label": (
                    (row.get("shop") or {}).get("shop_name")
                    if isinstance(row.get("shop"), dict)
                    else ""
                ),
                "value": (
                    (row.get("ranking_metrics") or {}).get("period_gmv")
                    if isinstance(row.get("ranking_metrics"), dict)
                    else None
                ),
                "evidence_id": row.get("evidence_id"),
            }
            for row in shop_rows
        ],
        source="FastMoss · shop_rank_top_selling",
        evidence_ids=[str(row.get("evidence_id") or "") for row in shop_rows],
        unit="$",
        value_format="currency",
        insight="店铺集中度与商品集中度分别判断，不互相替代。",
    )
    if chart:
        charts.append(chart)
    return charts


def build_fastmoss_market_report_data(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    if not category:
        raise ValueError("category is required for FastMoss MarketReportData")
    brand = str(payload.get("brand") or "Hsia").strip() or "Hsia"
    marketplace = "US"
    time_range = str(payload.get("timeRange") or payload.get("time_range") or "28d")
    generated_at = str(payload.get("generatedAt") or dt.datetime.now(dt.UTC).isoformat())
    head_listing_count = max(
        1, int(payload.get("headListingCount") or payload.get("head_listing_count") or 5)
    )
    listing_sample_size = max(
        head_listing_count,
        int(payload.get("listingSampleSize") or payload.get("listing_sample_size") or 20),
    )
    review_sample_size = max(
        1, min(100, int(payload.get("reviewSampleSize") or payload.get("review_sample_size") or 30))
    )
    is_hot_product_workflow = (
        str(payload.get("skillId") or "") == "tiktok_us_hot_product_insight"
    )
    periods = completed_us_periods(generated_at)
    tool_results = [
        item
        for item in (
            payload.get("toolResults") if isinstance(payload.get("toolResults"), list) else []
        )
        if isinstance(item, dict) and str(item.get("name") or "").startswith(FASTMOSS_PREFIX)
    ]

    evidence_map: list[dict[str, Any]] = []
    evidence_by_object: dict[int, str] = {}
    for index, tool in enumerate(tool_results, start=1):
        evidence_id = f"FM-E{index:02d}"
        evidence_by_object[id(tool)] = evidence_id
        evidence_map.append(
            {
                "id": evidence_id,
                "tool": str(tool.get("name") or ""),
                "status": str(tool.get("status") or ""),
                "outcome": str(tool.get("outcome") or ""),
                "summary": str(tool.get("summary") or ""),
                "input": _tool_input(tool),
                "region": _region(tool),
                "date_type": _date_type(tool),
                "date_value": _date_value(tool),
                "analysis_type": _analysis_type(tool),
                "product_id": _product_id(tool),
                "keywords": _search_keywords(tool),
            }
        )

    product_searches = _tools(tool_results, "product_search")
    category_search = _tools(
        tool_results,
        "search_category_by_words",
        _category_search_has_results,
    )
    rankings = _tools(tool_results, "market_category_ranking")
    basic = _tools(
        tool_results,
        "market_category_analysis",
        lambda tool: _analysis_type(tool) == "basic_metrics",
    )
    sales_trends = _tools(
        tool_results,
        "market_category_analysis",
        lambda tool: _analysis_type(tool) == "sales_trends",
    )
    price = _tools(
        tool_results,
        "market_category_analysis",
        lambda tool: _analysis_type(tool) == "price_distribution",
    )
    creator_matrix = _tools(tool_results, "market_category_author_sales_matrix")
    top_creators = _tools(tool_results, "creator_rank_top_ecommerce")
    top_products = _tools(tool_results, "product_rank_top_selling")
    new_products = _tools(tool_results, "product_rank_new_listed")
    top_shops = _tools(tool_results, "shop_rank_top_selling")
    product_trends = _tools(tool_results, "product_sales_trend")
    product_creators = _tools(tool_results, "product_creator_analysis")
    product_videos = _tools(tool_results, "product_video_list")
    product_reviews = _tools(tool_results, "product_review_list")
    product_overviews = _tools(tool_results, "product_overview")
    shop_channels = _tools(tool_results, "shop_sale_analysis")

    dated_market_tools = [
        *rankings,
        *basic,
        *sales_trends,
        *price,
        *creator_matrix,
        *top_products,
        *new_products,
        *top_shops,
        *top_creators,
    ]
    stale_tools = [tool for tool in dated_market_tools if not _period_is_expected(tool, periods)]
    non_us_tools = [tool for tool in tool_results if _region(tool) and _region(tool) != "US"]

    scale_rankings = [
        tool
        for tool in rankings
        if _is_us_or_unscoped(tool)
        and _period_is_expected(tool, periods)
        and _tool_has_rows(tool, "ranked_categories", "list", "categories")
    ]
    valid_basic = [
        tool
        for tool in basic
        if _is_us_or_unscoped(tool)
        and _period_is_expected(tool, periods)
        and _basic_metrics_has_data(tool)
    ]
    valid_sales_trends = [
        tool
        for tool in sales_trends
        if _is_us_or_unscoped(tool)
        and _period_is_expected(tool, periods)
        and _tool_has_rows(tool, "trend_series")
    ]
    valid_price = [
        tool
        for tool in price
        if _is_us_or_unscoped(tool)
        and _period_is_expected(tool, periods)
        and _price_distribution_has_data(tool)
    ]
    valid_creator_matrix = [
        tool
        for tool in creator_matrix
        if _is_us_or_unscoped(tool)
        and _period_is_expected(tool, periods)
        and _tool_has_rows(tool, "list", "matrix")
    ]
    valid_top_creators = [
        tool
        for tool in top_creators
        if _is_us_or_unscoped(tool)
        and _period_is_expected(tool, periods)
        and _tool_has_rows(tool, "list", "creators")
    ]
    valid_top_products = [
        tool
        for tool in top_products
        if _is_us_or_unscoped(tool)
        and _period_is_expected(tool, periods)
        and _tool_has_rows(tool, "list", "products")
    ]
    valid_new_products = [
        tool
        for tool in new_products
        if _is_us_or_unscoped(tool)
        and _period_is_expected(tool, periods)
        and _tool_has_rows(tool, "list", "products")
    ]
    valid_top_shops = [
        tool
        for tool in top_shops
        if _is_us_or_unscoped(tool)
        and _period_is_expected(tool, periods)
        and _tool_has_rows(tool, "list", "shops")
    ]
    valid_product_searches = [
        tool for tool in product_searches if _is_us_or_unscoped(tool)
    ]
    valid_product_trends = [
        tool
        for tool in product_trends
        if _is_us_or_unscoped(tool) and _product_trend_has_data(tool)
    ]
    valid_product_creators = [
        tool
        for tool in product_creators
        if _is_us_or_unscoped(tool) and _product_creator_has_data(tool)
    ]
    valid_product_videos = [
        tool
        for tool in product_videos
        if _is_us_or_unscoped(tool) and _product_video_has_data(tool)
    ]
    valid_product_reviews = [
        tool
        for tool in product_reviews
        if _is_us_or_unscoped(tool) and bool(_review_rows(tool, limit=1))
    ]
    valid_product_overviews = [
        tool
        for tool in product_overviews
        if _is_us_or_unscoped(tool) and _product_overview_has_data(tool)
    ]
    valid_shop_channels = [
        tool
        for tool in shop_channels
        if _is_us_or_unscoped(tool) and _shop_channel_has_data(tool)
    ]

    trend_point_count = max(
        [len(_tool_data(tool).get("trend_series") or []) for tool in valid_sales_trends] or [0]
    )
    keyword_queries = sorted(
        {
            _search_keywords(tool).casefold()
            for tool in valid_product_searches
            if _search_keywords(tool)
        }
    )
    segment_product_rows = _dedupe_products(
        (
            _rows_from_tools(
                valid_top_products,
                evidence_by_object,
                ("list", "products"),
                limit_per_tool=listing_sample_size,
            )
            if is_hot_product_workflow
            else _product_search_rows(valid_product_searches, evidence_by_object)
        )
    )
    segment_product_count = len(segment_product_rows)
    segment_product_ids = {
        str(row.get("product_id") or "").strip()
        for row in segment_product_rows
        if str(row.get("product_id") or "").strip()
    }
    valid_product_trends = [
        tool for tool in valid_product_trends if _product_id(tool) in segment_product_ids
    ]
    valid_product_creators = [
        tool for tool in valid_product_creators if _product_id(tool) in segment_product_ids
    ]
    valid_product_videos = [
        tool for tool in valid_product_videos if _product_id(tool) in segment_product_ids
    ]
    valid_product_overviews = [
        tool for tool in valid_product_overviews if _product_id(tool) in segment_product_ids
    ]
    valid_product_reviews = [
        tool for tool in valid_product_reviews if _product_id(tool) in segment_product_ids
    ]
    trend_product_ids = {_product_id(tool) for tool in valid_product_trends if _product_id(tool)}
    creator_product_ids = {
        _product_id(tool) for tool in valid_product_creators if _product_id(tool)
    }
    video_product_ids = {_product_id(tool) for tool in valid_product_videos if _product_id(tool)}
    overview_product_ids = {
        _product_id(tool) for tool in valid_product_overviews if _product_id(tool)
    }
    content_product_ids = trend_product_ids & creator_product_ids & video_product_ids
    fully_aligned_product_ids = content_product_ids & overview_product_ids
    has_scale_search = any(
        _orderby_fields(tool) & {"day28_gmv", "total_gmv"}
        and bool(_product_search_source_rows(tool))
        for tool in valid_product_searches
    )
    has_volume_search = any(
        _orderby_fields(tool) & {"day28_units_sold", "total_units_sold"}
        and bool(_product_search_source_rows(tool))
        for tool in valid_product_searches
    )
    has_new_search = any(
        bool(_nested_filter(tool).get("is_new_listed"))
        and bool(_product_search_source_rows(tool))
        for tool in valid_product_searches
    )

    task_requirements: dict[str, list[tuple[str, bool]]] = {
        "FM01": [
            ("at least two distinct product_search keyword queries", len(keyword_queries) >= 2),
            ("all FastMoss evidence uses region=US or is explicitly unscoped", not non_us_tools),
        ],
        "FM02": [
            (
                f"at least {listing_sample_size} unique keyword-retrieved products",
                segment_product_count >= listing_sample_size,
            ),
        ],
        "FM03": [
            ("successful proxy category resolution", bool(category_search)),
        ],
        "FM04": [
            ("proxy category ranking for a completed period", bool(scale_rankings)),
            ("proxy category basic_metrics", bool(valid_basic)),
            ("proxy category sales_trends", bool(valid_sales_trends)),
            ("at least two comparable proxy trend points", trend_point_count >= 2),
        ],
        "FM05": [
            ("proxy category price_distribution", bool(valid_price)),
            ("top shop ranking", bool(valid_top_shops)),
            ("proxy category top product ranking", bool(valid_top_products)),
        ],
        "FM06": [
            ("creator tier sales matrix", bool(valid_creator_matrix)),
            ("specific top creator ranking", bool(valid_top_creators)),
        ],
        "FM07": [
            ("keyword product search sorted by GMV", has_scale_search),
            ("keyword product search sorted by units sold", has_volume_search),
            ("keyword product search filtered to new-listed products", has_new_search),
            (
                f"keyword product universe reaches {head_listing_count} deep-dive candidates",
                segment_product_count >= head_listing_count,
            ),
        ],
        "FM08": [
            (
                f"sales trend for {head_listing_count} head products",
                _unique_product_count(valid_product_trends) >= head_listing_count,
            )
        ],
        "FM09": [
            (
                f"sales, creator, and video evidence align on {head_listing_count} segment products",
                len(content_product_ids) >= head_listing_count,
            ),
        ],
        "FM10": [
            (
                f"outcome, content, and overview evidence align on {head_listing_count} segment products",
                len(fully_aligned_product_ids) >= head_listing_count,
            ),
            ("representative shop channel analysis", bool(valid_shop_channels)),
        ],
    }

    task_results: list[dict[str, Any]] = []
    task_tools: dict[str, list[dict[str, Any]]] = {
        "FM01": valid_product_searches,
        "FM02": valid_product_searches,
        "FM03": category_search,
        "FM04": [*scale_rankings, *valid_basic, *valid_sales_trends],
        "FM05": [*valid_price, *valid_top_shops, *valid_top_products],
        "FM06": [*valid_creator_matrix, *valid_top_creators],
        "FM07": valid_product_searches,
        "FM08": valid_product_trends,
        "FM09": [*valid_product_creators, *valid_product_videos],
        "FM10": [*valid_product_overviews, *valid_shop_channels],
    }
    for spec in FASTMOSS_MARKET_TASKS[:10]:
        status, reason = _status_from_requirements(task_requirements[spec["dimension_id"]])
        used = task_tools[spec["dimension_id"]]
        task_results.append(
            {
                **spec,
                "status": status,
                "analysis_status": status,
                "reason": reason,
                "used_tools": list(dict.fromkeys(str(tool.get("name") or "") for tool in used)),
                "evidence_ids": list(dict.fromkeys(_tool_evidence_ids(used, evidence_by_object))),
                "missing_requirements": [
                    label for label, passed in task_requirements[spec["dimension_id"]] if not passed
                ],
            }
        )

    covered_ids = {task["dimension_id"] for task in task_results if task["status"] == "covered"}
    derived_requirements = {
        "FM11": [
            ("FM01 functional segment boundary", "FM01" in covered_ids),
            ("FM02 segment sample coverage", "FM02" in covered_ids),
            ("FM08 segment market outcome", "FM08" in covered_ids),
            ("FM09 segment content momentum", "FM09" in covered_ids),
        ],
        "FM12": [
            ("FM07 product pools", "FM07" in covered_ids),
            ("FM08 product outcome", "FM08" in covered_ids),
            ("FM09 product content", "FM09" in covered_ids),
            ("FM10 channel attribution", "FM10" in covered_ids),
            (
                "Hsia internal cost/supply/return/content facts",
                bool(payload.get("hsiaFacts") or payload.get("brandFacts")),
            ),
        ],
    }
    for spec in FASTMOSS_MARKET_TASKS[10:]:
        status, reason = _status_from_requirements(derived_requirements[spec["dimension_id"]])
        prerequisite_ids = [
            label.split()[0]
            for label, _ in derived_requirements[spec["dimension_id"]]
            if label.startswith("FM")
        ]
        prerequisite_tasks = [
            task for task in task_results if task["dimension_id"] in prerequisite_ids
        ]
        task_results.append(
            {
                **spec,
                "status": status,
                "analysis_status": status,
                "reason": reason,
                "used_tools": list(
                    dict.fromkeys(
                        tool for task in prerequisite_tasks for tool in task["used_tools"]
                    )
                ),
                "evidence_ids": list(
                    dict.fromkeys(
                        evidence for task in prerequisite_tasks for evidence in task["evidence_ids"]
                    )
                ),
                "missing_requirements": [
                    label
                    for label, passed in derived_requirements[spec["dimension_id"]]
                    if not passed
                ],
            }
        )

    category_benchmark = _rows_from_tools(
        scale_rankings, evidence_by_object, ("ranked_categories",), limit_per_tool=10
    )
    category_trend = _rows_from_tools(
        valid_sales_trends, evidence_by_object, ("trend_series",), limit_per_tool=12
    )
    price_distribution: list[dict[str, Any]] = []
    for tool in valid_price:
        data = _tool_data(tool)
        evidence_id = evidence_by_object.get(id(tool), "")
        price_distribution.extend(
            _attach_source(
                data.get("product_count_price_distribution"), evidence_id, _short_name(tool)
            )
        )
        sales = (
            data.get("sales_price_distribution")
            if isinstance(data.get("sales_price_distribution"), dict)
            else {}
        )
        price_distribution.extend(
            _attach_source(sales.get("gmv_distribution"), evidence_id, _short_name(tool))
        )
        price_distribution.extend(
            _attach_source(sales.get("units_sold_distribution"), evidence_id, _short_name(tool))
        )
    creator_matrix_rows = _rows_from_tools(
        valid_creator_matrix, evidence_by_object, ("list",), limit_per_tool=20
    )
    top_creator_rows = _rows_from_tools(
        valid_top_creators, evidence_by_object, ("list", "creators"), limit_per_tool=20
    )
    proxy_product_rows = _dedupe_products(
        _rows_from_tools(
            [*valid_top_products, *valid_new_products],
            evidence_by_object,
            ("list", "products"),
            limit_per_tool=30,
        )
    )
    product_rows = segment_product_rows[:listing_sample_size]
    shop_rows = _rows_from_tools(
        valid_top_shops, evidence_by_object, ("list", "shops"), limit_per_tool=20
    )

    product_trend_rows = [
        {
            "product_id": _product_id(tool),
            "region": _region(tool),
            "period_summary": _tool_data(tool).get("period_summary") or {},
            "daily_trend": (_tool_data(tool).get("daily_trend") or [])[:62],
            "evidence_id": evidence_by_object.get(id(tool), ""),
            "source_tool": _short_name(tool),
        }
        for tool in valid_product_trends
    ]
    product_creator_rows = []
    for tool in valid_product_creators:
        linked = _tool_data(tool).get("linked_creators")
        if isinstance(linked, dict):
            linked_rows = linked.get("list") if isinstance(linked.get("list"), list) else []
            linked_total = linked.get("total")
        else:
            linked_rows = linked if isinstance(linked, list) else []
            linked_total = len(linked_rows)
        product_creator_rows.append(
            {
                "product_id": _product_id(tool),
                "creator_summary": _tool_data(tool).get("creator_summary") or {},
                "linked_creator_total": linked_total,
                "linked_creators": linked_rows[:10],
                "evidence_id": evidence_by_object.get(id(tool), ""),
                "source_tool": _short_name(tool),
            }
        )
    product_video_rows = [
        {
            "product_id": _product_id(tool),
            "time_range_days": _nested_filter(tool).get("time_range_days")
            or _tool_data(tool).get("time_range_days"),
            "total": _tool_data(tool).get("total"),
            "videos": (_tool_data(tool).get("videos") or [])[:10],
            "evidence_id": evidence_by_object.get(id(tool), ""),
            "source_tool": _short_name(tool),
        }
        for tool in valid_product_videos
    ]
    channel_rows = [
        {
            "object_id": _product_id(tool)
            or str((_tool_data(tool).get("shop") or {}).get("seller_id") or ""),
            "period_summary": _tool_data(tool).get("period_summary") or {},
            "ads_distribution": _tool_data(tool).get("ads_distribution") or {},
            "channel_distribution": _tool_data(tool).get("channel_distribution")
            or _tool_data(tool).get("sales_channel_distribution")
            or {},
            "content_distribution": _tool_data(tool).get("content_distribution")
            or _tool_data(tool).get("content_type_distribution")
            or {},
            "evidence_id": evidence_by_object.get(id(tool), ""),
            "source_tool": _short_name(tool),
        }
        for tool in [*valid_product_overviews, *valid_shop_channels]
    ]
    product_review_rows = _aggregate_product_review_rows(
        valid_product_reviews,
        evidence_by_object=evidence_by_object,
        limit_per_product=review_sample_size,
    )

    datasets = {
        "category_benchmark": category_benchmark,
        "category_trend": category_trend,
        "price_distribution": price_distribution,
        "creator_matrix": creator_matrix_rows,
        "top_creators": top_creator_rows,
        "top_products": product_rows,
        "top_shops": shop_rows,
        "product_trends": product_trend_rows,
        "product_creators": product_creator_rows,
        "product_videos": product_video_rows,
        "channel_attribution": channel_rows,
        "product_reviews": product_review_rows,
    }
    charts = _build_charts(task_results, datasets)
    chart_by_dimension = {chart["dimension_id"]: chart for chart in charts}
    chart_manifest: list[dict[str, Any]] = []
    dimension_results: list[dict[str, Any]] = []
    for task in task_results:
        chart = chart_by_dimension.get(task["dimension_id"])
        chart_manifest.append(
            {
                "dimension_id": task["dimension_id"],
                "name": task["name"],
                "priority": task["priority"],
                "market_question": task["market_question"],
                "analysis_status": task["status"],
                "chart_id": chart.get("id") if chart else "",
                "title": chart.get("title") if chart else "",
                "type": chart.get("type") if chart else "",
                "chart_status": "ready" if chart else "missing_data",
                "reason": "Task-backed chart data compiled." if chart else task["reason"],
                "evidence_ids": chart.get("evidence_ids") if chart else task["evidence_ids"],
            }
        )
        dimension_results.append(
            {
                "dimension_id": task["dimension_id"],
                "name": task["name"],
                "market_question": task["market_question"],
                "priority": task["priority"],
                "analysis_status": task["status"],
                "used_tools": task["used_tools"],
                "evidence_ids": task["evidence_ids"],
                "allowed_conclusion": task["allowed_conclusion"],
                "limitation": task["limitation"],
                "missing_requirements": task["missing_requirements"],
                "chart": {
                    "chart_id": chart.get("id") if chart else "",
                    "title": chart.get("title") if chart else "",
                    "type": chart.get("type") if chart else "",
                    "status": "ready" if chart else "missing_data",
                    "reason": "Task-backed chart data compiled." if chart else task["reason"],
                    "evidence_ids": chart.get("evidence_ids") if chart else task["evidence_ids"],
                },
            }
        )

    p0_tasks = [task for task in task_results if task["priority"] == "P0"]
    p0_covered = sum(1 for task in p0_tasks if task["status"] == "covered")
    failed_tools = [tool for tool in tool_results if not _is_success(tool)]
    data_gaps = [
        f"{task['dimension_id']} {task['name']}：{task['reason']}"
        for task in task_results
        if task["status"] != "covered"
    ]
    raw_segment_product_rows = sum(
        len(_product_search_source_rows(tool)) for tool in valid_product_searches
    )
    if valid_product_searches and not segment_product_rows:
        data_gaps.insert(
            0,
            "FastMoss product_search 已执行但未取回可用商品；这表示关键词数据未取回，不表示该细分市场销量为零。",
        )
    elif segment_product_count < listing_sample_size:
        data_gaps.insert(
            0,
            f"关键词细分样本仅取得 {segment_product_count}/{listing_sample_size} 个去重商品记录；"
            "所有细分结构结论仅限当前 FastMoss 可识别样本。",
        )
    if stale_tools:
        observed = sorted({_date_value(tool) for tool in stale_tools if _date_value(tool)})
        data_gaps.insert(
            0,
            "FastMoss 周期不一致：本次应使用 "
            f"month={periods['month']}、week={periods['week']}，但发现 {', '.join(observed)}。",
        )
    if non_us_tools:
        data_gaps.insert(0, "发现非 US FastMoss 证据，已从美国市场任务覆盖中排除。")
    for tool in failed_tools:
        data_gaps.append(
            f"{_short_name(tool)} 未成功：{tool.get('summary') or tool.get('outcome') or 'unknown error'}"
        )
    data_gaps = list(dict.fromkeys(data_gaps))[:30]

    inferred_category_ids: list[str] = []
    for tool in [*basic, *sales_trends, *price, *rankings, *top_products]:
        value = _nested_filter(tool).get("category_id")
        if value not in (None, ""):
            inferred_category_ids.append(str(value))
    category_node_id = str(
        payload.get("categoryNodeId") or payload.get("category_node_id") or ""
    ).strip()
    if not category_node_id and inferred_category_ids:
        category_node_id = Counter(inferred_category_ids).most_common(1)[0][0]

    market_kpis: list[dict[str, Any]] = []
    if valid_basic:
        data = _tool_data(valid_basic[-1])
        evidence_id = evidence_by_object.get(id(valid_basic[-1]), "")
        scale = data.get("scale_metrics") if isinstance(data.get("scale_metrics"), dict) else {}
        growth = data.get("growth_metrics") if isinstance(data.get("growth_metrics"), dict) else {}
        for label, key, unit in (
            ("代理父类目 GMV", "category_gmv", "$"),
            ("代理父类目销量", "category_units_sold", "units"),
            ("代理父类目活跃商品", "active_product_count", "products"),
            ("代理父类目带货视频", "selling_video_count", "videos"),
            ("代理父类目带货达人", "selling_creator_count", "creators"),
        ):
            if _number(scale.get(key)) is not None:
                market_kpis.append(
                    {"label": label, "value": scale[key], "unit": unit, "source": evidence_id}
                )
        if _number(growth.get("category_gmv_mom_percent")) is not None:
            market_kpis.append(
                {
                    "label": "GMV 环比",
                    "value": growth["category_gmv_mom_percent"],
                    "unit": "%",
                    "source": evidence_id,
                }
            )

    analysis_coverage = {
        "schema_version": "fastmoss_market_task_coverage.v1",
        "summary": {
            "task_total": len(task_results),
            "task_covered": sum(1 for task in task_results if task["status"] == "covered"),
            "p0_total": len(p0_tasks),
            "p0_covered": p0_covered,
        },
        "dimensions": task_results,
    }
    report_quality = {
        "schema_version": "fastmoss_market_report_quality.v1",
        "status": "ready" if p0_covered == len(p0_tasks) else "degraded",
        "p0_total": len(p0_tasks),
        "p0_covered": p0_covered,
        "ready_chart_count": len(charts),
        "gap_messages": data_gaps,
        "unavailable_dimensions": [
            task["dimension_id"] for task in task_results if task["status"] != "covered"
        ],
    }
    insights = [
        {
            "id": f"task_{task['dimension_id'].lower()}",
            "title": task["name"],
            "summary": (
                f"{task['dimension_id']} 已完成，可在“{task['allowed_conclusion']}”范围内形成结论。"
                if task["status"] == "covered"
                else f"{task['dimension_id']} 未完成：{task['reason']}"
            ),
            "evidence_ids": task["evidence_ids"],
        }
        for task in task_results
    ]
    report_data: dict[str, Any] = {
        "schema_version": "fastmoss_market_report_data.v1",
        "title": (
            f"{brand} TikTok Shop US {category} 爆款洞察报告"
            if is_hot_product_workflow
            else f"{brand} TikTok Shop US {category} 市场洞察报告"
        ),
        "brand": brand,
        "marketplace": marketplace,
        "category": category,
        "category_node_id": category_node_id,
        "time_range": time_range,
        "generated_at": generated_at,
        "period_contract": periods,
        "research_boundary": {
            "market": "TikTok Shop US",
            "segment_type": (
                "category_ranked_hot_product_sample"
                if is_hot_product_workflow
                else "keyword_defined_product_sample"
            ),
            "requested_segment": category,
            "keyword_queries": keyword_queries,
            "proxy_category_id": category_node_id,
            "proxy_category_role": "background_only",
            "segment_limitation": (
                "FastMoss product_search recall is a keyword-identifiable product sample, "
                "not search demand, total addressable market, or a complete census."
            ),
        },
        "segment_query_summary": {
            "successful_search_calls": len(valid_product_searches),
            "distinct_keyword_queries": len(keyword_queries),
            "keyword_queries": keyword_queries,
            "raw_product_rows": raw_segment_product_rows,
            "deduplicated_product_records": segment_product_count,
            "listing_sample_target": listing_sample_size,
            "deep_dive_target": head_listing_count,
            "sample_target_met": segment_product_count >= listing_sample_size,
            "deep_dive_target_met": segment_product_count >= head_listing_count,
            "status": (
                "ready"
                if segment_product_count >= listing_sample_size
                else "partial"
                if segment_product_count
                else "missing_data"
            ),
        },
        "source_summary": {
            "tool_count": len(tool_results),
            "successful_tool_count": sum(1 for tool in tool_results if _is_success(tool)),
            "failed_tool_count": len(failed_tools),
            "task_total": len(task_results),
            "task_covered": analysis_coverage["summary"]["task_covered"],
            "p0_task_total": len(p0_tasks),
            "p0_task_covered": p0_covered,
        },
        "market_kpis": market_kpis,
        "category_benchmark": category_benchmark,
        "market_statistics": [
            {
                **(_tool_data(tool).get("scale_metrics") or {}),
                **(_tool_data(tool).get("growth_metrics") or {}),
                **(_tool_data(tool).get("concentration_metrics") or {}),
                "evidence_id": evidence_by_object.get(id(tool), ""),
            }
            for tool in valid_basic
        ],
        "demand_trend": category_trend,
        "price_distribution": price_distribution,
        "top_products": product_rows,
        "seller_competition": shop_rows,
        "content_distribution": creator_matrix_rows,
        "product_universe": product_rows,
        "fastmoss_segment_products": product_rows,
        "fastmoss_proxy_category_products": proxy_product_rows,
        "fastmoss_task_results": task_results,
        "fastmoss_category_trend": category_trend,
        "fastmoss_creator_matrix": creator_matrix_rows,
        "fastmoss_top_creators": top_creator_rows,
        "fastmoss_top_shops": shop_rows,
        "fastmoss_product_trends": product_trend_rows,
        "fastmoss_product_creators": product_creator_rows,
        "fastmoss_product_videos": product_video_rows,
        "fastmoss_channel_attribution": channel_rows,
        "fastmoss_product_reviews": product_review_rows,
        "review_pain_points": product_review_rows,
        "analysis_coverage": analysis_coverage,
        "dimension_results": dimension_results,
        "chart_specs": charts,
        "summary_chart_ids": [chart["id"] for chart in charts[:5]],
        "chart_manifest": chart_manifest,
        "deduplication": {
            "schema_version": "fastmoss_product_identity.v1",
            "status": "partial" if product_rows else "deferred",
            "applied": bool(product_rows),
            "scope": "product_id_only",
            "raw_product_rows": raw_segment_product_rows,
            "deduplicated_product_records": len(product_rows),
            "limitation": (
                "Keyword recall is not a complete market census. No parent/variation evidence; "
                "counts are product_id records, not unique product families."
            ),
        },
        "report_quality": report_quality,
        "analysis_sections": task_results,
        "insights": insights,
        "opportunity_pool": [],
        "evidence_map": evidence_map,
        "data_gaps": data_gaps,
        "next_actions": [
            "先补齐未完成的 FM 任务，再更新 FastMossMarketReportData。",
            "关键词召回为空时扩展同义词并移除类目过滤重试；仍为空则只保留代理父类目背景。",
            "Entry Timing 仅在 FM01、FM02、FM08、FM09 全部完成后生成。",
            "Hsia Fit 缺少成本、退货、供应链、尺码或内容产能事实时保持证据不足。",
        ],
    }
    report_data["executive_summary"] = (
        f"FastMossMarketReportData 已按 FM01–FM12 编译："
        f"{analysis_coverage['summary']['task_covered']}/{analysis_coverage['summary']['task_total']} 个任务完成，"
        f"P0 覆盖 {p0_covered}/{len(p0_tasks)}；报告状态为 {report_quality['status']}。"
    )
    report_data["artifact"] = {
        "title": report_data["title"],
        "executive_summary": report_data["executive_summary"],
        "kpis": market_kpis,
        "market_basics": [item["summary"] for item in insights[:4]],
        "price_and_margin": [
            next((item["summary"] for item in insights if item["id"] == "task_fm05"), "FM05 未编译")
        ],
        "competition": [
            next((item["summary"] for item in insights if item["id"] == "task_fm05"), "FM05 未编译")
        ],
        "user_voice": [],
        "key_findings": [item["summary"] for item in insights if "已完成" in item["summary"]][:6],
        "opportunity_pool": [],
        "opportunities": [],
        "risks": data_gaps[:8],
        "data_gaps": data_gaps,
        "next_steps": report_data["next_actions"],
    }
    return report_data

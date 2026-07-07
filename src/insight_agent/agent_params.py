from __future__ import annotations

import re
from typing import Any

REDDIT_NATIVE_TIME_RANGES = {"day", "week", "month", "year", "all"}

AGENT_PARAM_ALIASES: dict[str, tuple[str, ...]] = {
    "brand": ("brand_name", "target_brand", "品牌"),
    "marketplace": (
        "market",
        "market_place",
        "marketplace_name",
        "platform",
        "site",
        "store",
        "channel",
        "region",
        "country",
        "电商市场",
        "平台",
        "市场",
        "站点",
    ),
    "category": (
        "product_category",
        "product_type",
        "subcategory",
        "niche",
        "keyword",
        "keywords",
        "品类",
        "类目",
        "关键词",
    ),
    "time_range": (
        "timeRange",
        "date_range",
        "time_period",
        "period",
        "window",
        "days",
        "duration",
        "时间范围",
        "时间",
        "周期",
    ),
    "listing_sample_size": (
        "amazonLimit",
        "amazon_product_limit",
        "product_limit",
        "listing_count",
        "sample_size",
        "样本数量",
        "商品样本数",
    ),
    "head_listing_count": (
        "headListingCount",
        "head_count",
        "top_listing_count",
        "头部商品数量",
    ),
    "new_product_window": ("newProductWindow", "new_product_period", "新品定义"),
    "reddit_post_limit": ("redditLimit", "reddit_limit", "reddit_posts", "reddit_post_count"),
    "reddit_detail_limit": ("redditDetailLimit", "reddit_detail_limit"),
    "reddit_comments_per_post": ("redditCommentsPerPost", "reddit_comments_per_post"),
    "tiktok_video_limit": ("tiktokLimit", "tiktok_limit", "tiktokVideoLimit"),
    "tiktok_comments_per_video": ("tiktokCommentsPerVideo", "tiktok_comments_per_video"),
    "article_query_limit": ("articleQueryLimit", "article_query_limit"),
    "article_results_per_query": ("articleResultsPerQuery", "article_results_per_query"),
    "article_candidate_limit": ("articleCandidateLimit", "article_candidate_limit"),
    "bypass_cache": ("bypassCache", "fresh", "force_refresh"),
}

ALIAS_TO_CANONICAL = {
    alias: canonical
    for canonical, aliases in AGENT_PARAM_ALIASES.items()
    for alias in (canonical, *aliases)
}


def has_value(value: Any) -> bool:
    return value is not None and value != ""


def bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


def normalize_agent_time_range(value: Any) -> str:
    raw_value = str(value or "").strip().lower()
    compact = re.sub(r"\s+", "", raw_value)
    if not compact:
        return ""

    if raw_value in REDDIT_NATIVE_TIME_RANGES:
        normalized_native = raw_value
    else:
        normalized_native = ""

    day_match = re.search(r"(\d{1,4})(?:天|日|days?|d\b)", compact)
    if day_match:
        return f"{max(1, int(day_match.group(1)))}d"

    week_match = re.search(r"(\d{1,3})(?:周|星期|weeks?|w\b)", compact)
    if week_match:
        return f"{max(1, int(week_match.group(1))) * 7}d"

    month_match = re.search(r"(\d{1,3})(?:个月|月|months?|mo\b)", compact)
    if month_match:
        return f"{max(1, int(month_match.group(1))) * 30}d"

    year_match = re.search(r"(\d{1,2})(?:年|years?|y\b)", compact)
    if year_match:
        return f"{max(1, int(year_match.group(1))) * 365}d"

    if any(token in compact for token in ("三个月", "quarter", "季度")):
        return "90d"
    if any(token in compact for token in ("半年", "半年度", "6个月", "sixmonths")):
        return "180d"
    if any(token in compact for token in ("一个月", "近一个月", "最近一个月")):
        return "month"
    if any(token in compact for token in ("一周", "week")):
        return "week"
    if any(token in compact for token in ("一天", "今日", "今天", "day")):
        return "day"
    if any(token in compact for token in ("一年", "12个月", "year")):
        return "year"
    if any(token in compact for token in ("全部", "alltime", "all")):
        return "all"
    return normalized_native


def normalize_agent_params(params: dict[str, Any] | None) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    if not isinstance(params, dict):
        return normalized

    for key, value in params.items():
        if not has_value(value):
            continue
        canonical = ALIAS_TO_CANONICAL.get(str(key), str(key))
        normalized[canonical] = value

    normalized_time_range = normalize_agent_time_range(normalized.get("time_range"))
    if normalized_time_range:
        normalized["time_range"] = normalized_time_range
    return normalized


def infer_agent_params_from_prompt(prompt: Any) -> dict[str, Any]:
    text = str(prompt or "").strip()
    if not text:
        return {}
    lower_text = text.lower()
    params: dict[str, Any] = {}

    brand_match = re.search(
        r"(?:品牌|brand|研究对象品牌)\s*[:：是为]?\s*([^，。,.;；\n]+)",
        text,
        flags=re.IGNORECASE,
    )
    if brand_match:
        brand = brand_match.group(1).strip(" :：是为")
        if brand:
            params["brand"] = brand
    elif "hsia" in lower_text:
        params["brand"] = "Hsia"

    if any(token in lower_text for token in ("amazon us", "amazon.com", "美国站", "亚马逊美国", "亚马逊美站")):
        params["marketplace"] = "Amazon US"
    elif "amazon" in lower_text and ("美国" in text or re.search(r"\bus\b", lower_text)):
        params["marketplace"] = "Amazon US"
    elif "美国" in text or re.search(r"\bus\b", lower_text):
        params["marketplace"] = "US"

    time_range = normalize_agent_time_range(text)
    if time_range:
        params["time_range"] = time_range

    if "minimizer bra" in lower_text:
        params["category"] = "minimizer bra"

    return normalize_agent_params(params)


def merge_agent_param_sources(*sources: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in sources:
        merged.update(normalize_agent_params(source))
    return merged


def payload_param_source(payload: dict[str, Any]) -> dict[str, Any]:
    source: dict[str, Any] = {}
    for key, value in payload.items():
        if str(key) in ALIAS_TO_CANONICAL and has_value(value):
            source[str(key)] = value
    return source


def resolve_canonical_agent_params(
    skill: dict[str, Any],
    payload: dict[str, Any],
    extracted_params: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    schema = skill.get("input_schema") or {}
    defaults = schema.get("defaults") if isinstance(schema.get("defaults"), dict) else {}
    payload_params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    params = merge_agent_param_sources(
        defaults,
        infer_agent_params_from_prompt(payload.get("prompt")),
        extracted_params,
        payload_params,
        payload_param_source(payload),
    )
    required = schema.get("required") or []
    required = [ALIAS_TO_CANONICAL.get(str(key), str(key)) for key in required]
    missing = [key for key in required if not has_value(params.get(key))]
    return params, missing


def agent_payload_from_params(payload: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    canonical = merge_agent_param_sources(
        infer_agent_params_from_prompt(payload.get("prompt")),
        payload_param_source(payload),
        payload.get("params") if isinstance(payload.get("params"), dict) else {},
        params,
    )
    mapped = dict(payload)
    mapped["params"] = canonical
    mapped["brand"] = canonical.get("brand") or payload.get("brand")
    mapped["marketplace"] = canonical.get("marketplace") or payload.get("marketplace")
    mapped["category"] = canonical.get("category") or payload.get("category")
    mapped["timeRange"] = canonical.get("time_range") or payload.get("timeRange")
    mapped["amazonLimit"] = canonical.get("listing_sample_size") or payload.get("amazonLimit")
    mapped["redditLimit"] = canonical.get("reddit_post_limit") or payload.get("redditLimit")
    mapped["redditDetailLimit"] = canonical.get("reddit_detail_limit") or payload.get("redditDetailLimit")
    mapped["redditCommentsPerPost"] = canonical.get("reddit_comments_per_post") or payload.get("redditCommentsPerPost")
    mapped["tiktokLimit"] = canonical.get("tiktok_video_limit") or payload.get("tiktokLimit")
    mapped["tiktokCommentsPerVideo"] = canonical.get("tiktok_comments_per_video") or payload.get("tiktokCommentsPerVideo")
    mapped["articleQueryLimit"] = canonical.get("article_query_limit") or payload.get("articleQueryLimit")
    mapped["articleResultsPerQuery"] = canonical.get("article_results_per_query") or payload.get("articleResultsPerQuery")
    mapped["articleCandidateLimit"] = canonical.get("article_candidate_limit") or payload.get("articleCandidateLimit")
    mapped["bypassCache"] = bool(canonical.get("bypass_cache") or payload.get("bypassCache"))
    return mapped


def adapt_agent_params_for_tool(tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
    canonical = merge_agent_param_sources(
        infer_agent_params_from_prompt(payload.get("prompt")),
        payload_param_source(payload),
        payload.get("params") if isinstance(payload.get("params"), dict) else {},
    )
    tool_category = str(canonical.get("category") or category)
    bypass_cache = bool(canonical.get("bypass_cache") or payload.get("bypassCache"))

    if tool_name == "reddit_voc":
        return {
            "category": tool_category,
            "timeRange": canonical.get("time_range") or "year",
            "limit": bounded_int(canonical.get("reddit_post_limit"), 30, 5, 120),
            "mode": payload.get("mode") or "auto",
            "useLlm": False,
            "redditDetailLimit": bounded_int(canonical.get("reddit_detail_limit"), 5, 0, 30),
            "redditCommentsPerPost": bounded_int(canonical.get("reddit_comments_per_post"), 10, 0, 80),
            "bypassCache": bypass_cache,
        }
    if tool_name == "amazon_shelf":
        return {
            "category": tool_category,
            "limit": bounded_int(canonical.get("listing_sample_size"), 30, 5, 80),
            "amazonKeywordLimit": bounded_int(canonical.get("amazon_keyword_limit") or payload.get("amazonKeywordLimit"), 6, 1, 12),
            "useLlm": False,
            "bypassCache": bypass_cache,
        }
    if tool_name == "media_rankings":
        return {
            "category": tool_category,
            "queryLimit": bounded_int(canonical.get("article_query_limit"), 4, 1, 10),
            "resultsPerQuery": bounded_int(canonical.get("article_results_per_query"), 5, 1, 10),
            "candidateLimit": bounded_int(canonical.get("article_candidate_limit"), 8, 1, 20),
            "includeIndustryReports": True,
            "bypassCache": bypass_cache,
        }
    if tool_name == "tiktok_social":
        return {
            "category": tool_category,
            "limit": bounded_int(canonical.get("tiktok_video_limit"), 6, 1, 12),
            "tiktokCommentsPerVideo": bounded_int(canonical.get("tiktok_comments_per_video"), 4, 1, 20),
            "bypassCache": bypass_cache,
        }
    return {"category": tool_category, "bypassCache": bypass_cache}

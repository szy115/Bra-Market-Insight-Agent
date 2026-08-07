from __future__ import annotations

import re
from typing import Any

from .tool_capabilities.local import normalize_reddit_voc_input

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
    "asin": (
        "ASIN",
        "product_asin",
        "competitor_asin",
        "target_asin",
        "商品ASIN",
        "竞品ASIN",
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
    "review_sample_size": (
        "reviewSampleSize",
        "review_limit",
        "reviews_per_product",
        "评论样本数",
        "每商品评论数",
    ),
    "new_product_window": ("newProductWindow", "new_product_period", "新品定义"),
    "shop_candidate_size": (
        "shopCandidateSize",
        "candidate_shop_count",
        "shop_candidate_count",
        "候选店铺数",
    ),
    "shop_analysis_count": (
        "shopAnalysisCount",
        "analyzed_shop_count",
        "competitor_shop_count",
        "标准分析店铺数",
    ),
    "category_node_id": (
        "categoryNodeId",
        "nodeIdPath",
        "node_id_path",
        "departmentNodeIdPath",
        "类目节点",
        "类目节点路径",
    ),
    "reddit_post_limit": ("redditLimit", "reddit_limit", "reddit_posts", "reddit_post_count"),
    "reddit_detail_limit": ("redditDetailLimit", "reddit_detail_limit"),
    "reddit_comments_per_post": ("redditCommentsPerPost", "reddit_comments_per_post"),
    "tiktok_video_limit": ("tiktokLimit", "tiktok_limit", "tiktokVideoLimit"),
    "tiktok_comments_per_video": ("tiktokCommentsPerVideo", "tiktok_comments_per_video"),
    "article_query_limit": ("articleQueryLimit", "article_query_limit"),
    "article_results_per_query": ("articleResultsPerQuery", "article_results_per_query"),
    "article_candidate_limit": ("articleCandidateLimit", "article_candidate_limit"),
    "report_image_limit": ("reportImageLimit", "report_image_count", "报告图片数"),
    "bypass_cache": ("bypassCache", "fresh", "force_refresh"),
    "design_goal": (
        "designGoal",
        "product_goal",
        "research_goal",
        "研发目标",
        "设计目标",
    ),
    "target_user": ("targetUser", "target_customer", "目标用户", "目标人群"),
    "brand_site_urls": (
        "brandSiteUrls",
        "brand_urls",
        "reference_urls",
        "独立站链接",
        "品牌站链接",
    ),
    "trend_context": ("trendContext", "trend_notes", "趋势背景", "趋势资料"),
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


def _category_tokens(value: Any) -> list[str]:
    words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", str(value or "").lower())
    normalized: list[str] = []
    for word in words:
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        normalized.append(word)
    return normalized


def category_supported_by_prompt(category: Any, prompt: Any) -> bool:
    category_text = str(category or "").strip()
    prompt_text = str(prompt or "").strip()
    if not category_text:
        return True
    if not prompt_text:
        return False
    if category_text.lower() in prompt_text.lower():
        return True

    category_tokens = _category_tokens(category_text)
    prompt_tokens = _category_tokens(prompt_text)
    if not category_tokens or not prompt_tokens:
        return False
    window = len(category_tokens)
    return any(
        prompt_tokens[index : index + window] == category_tokens
        for index in range(len(prompt_tokens) - window + 1)
    )


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

    if any(
        token in lower_text
        for token in ("amazon us", "amazon.com", "美国站", "亚马逊美国", "亚马逊美站")
    ):
        params["marketplace"] = "Amazon US"
    elif "amazon" in lower_text and ("美国" in text or re.search(r"\bus\b", lower_text)):
        params["marketplace"] = "Amazon US"
    elif "美国" in text or re.search(r"\bus\b", lower_text):
        params["marketplace"] = "US"

    asin_match = re.search(r"\bB[A-Z0-9]{9}\b", text.upper())
    if asin_match:
        params["asin"] = asin_match.group(0)

    time_range = normalize_agent_time_range(text)
    if time_range:
        params["time_range"] = time_range

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


def resolve_agent_tool_params(payload: dict[str, Any]) -> dict[str, Any]:
    return merge_agent_param_sources(
        infer_agent_params_from_prompt(payload.get("prompt")),
        payload_param_source(payload),
        payload.get("params") if isinstance(payload.get("params"), dict) else {},
    )


def resolve_canonical_agent_params(
    skill: dict[str, Any],
    payload: dict[str, Any],
    extracted_params: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    schema = skill.get("input_schema") or {}
    defaults = schema.get("defaults") if isinstance(schema.get("defaults"), dict) else {}
    payload_params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    prompt_params = infer_agent_params_from_prompt(payload.get("prompt"))
    extracted = normalize_agent_params(extracted_params)
    explicit_payload_params = merge_agent_param_sources(
        payload_params, payload_param_source(payload)
    )
    if (
        extracted.get("category")
        and not explicit_payload_params.get("category")
        and not category_supported_by_prompt(
            extracted.get("category"),
            payload.get("prompt"),
        )
    ):
        extracted.pop("category", None)
    params = merge_agent_param_sources(
        defaults,
        prompt_params,
        extracted,
        explicit_payload_params,
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
    mapped["asin"] = canonical.get("asin") or payload.get("asin")
    mapped["timeRange"] = canonical.get("time_range") or payload.get("timeRange")
    mapped["amazonLimit"] = canonical.get("listing_sample_size") or payload.get("amazonLimit")
    mapped["redditLimit"] = canonical.get("reddit_post_limit") or payload.get("redditLimit")
    mapped["redditDetailLimit"] = canonical.get("reddit_detail_limit") or payload.get(
        "redditDetailLimit"
    )
    mapped["redditCommentsPerPost"] = canonical.get("reddit_comments_per_post") or payload.get(
        "redditCommentsPerPost"
    )
    mapped["tiktokLimit"] = canonical.get("tiktok_video_limit") or payload.get("tiktokLimit")
    mapped["tiktokCommentsPerVideo"] = canonical.get("tiktok_comments_per_video") or payload.get(
        "tiktokCommentsPerVideo"
    )
    mapped["articleQueryLimit"] = canonical.get("article_query_limit") or payload.get(
        "articleQueryLimit"
    )
    mapped["articleResultsPerQuery"] = canonical.get("article_results_per_query") or payload.get(
        "articleResultsPerQuery"
    )
    mapped["articleCandidateLimit"] = canonical.get("article_candidate_limit") or payload.get(
        "articleCandidateLimit"
    )
    mapped["reportImageLimit"] = canonical.get("report_image_limit") or payload.get(
        "reportImageLimit"
    )
    mapped["head_listing_count"] = canonical.get("head_listing_count") or payload.get(
        "head_listing_count"
    )
    mapped["review_sample_size"] = canonical.get("review_sample_size") or payload.get(
        "review_sample_size"
    )
    mapped["new_product_window"] = canonical.get("new_product_window") or payload.get(
        "new_product_window"
    )
    mapped["shop_candidate_size"] = canonical.get("shop_candidate_size") or payload.get(
        "shop_candidate_size"
    )
    mapped["shop_analysis_count"] = canonical.get("shop_analysis_count") or payload.get(
        "shop_analysis_count"
    )
    mapped["category_node_id"] = canonical.get("category_node_id") or payload.get(
        "category_node_id"
    )
    mapped["bypassCache"] = bool(canonical.get("bypass_cache") or payload.get("bypassCache"))
    mapped["designGoal"] = canonical.get("design_goal") or payload.get("designGoal")
    mapped["targetUser"] = canonical.get("target_user") or payload.get("targetUser")
    mapped["brandSiteUrls"] = canonical.get("brand_site_urls") or payload.get("brandSiteUrls")
    mapped["trendContext"] = canonical.get("trend_context") or payload.get("trendContext")
    return mapped


def adapt_agent_params_for_tool(
    tool_name: str, category: str, payload: dict[str, Any]
) -> dict[str, Any]:
    canonical = resolve_agent_tool_params(payload)
    tool_category = str(canonical.get("category") or category)
    bypass_cache = bool(canonical.get("bypass_cache") or payload.get("bypassCache"))

    if tool_name == "reddit_voc":
        return normalize_reddit_voc_input(
            tool_category,
            payload,
            canonical,
            bounded_int,
        )
    if tool_name == "build_market_report_data":
        return {
            "skillId": payload.get("skillId"),
            "category": tool_category,
            "brand": canonical.get("brand") or payload.get("brand"),
            "marketplace": canonical.get("marketplace") or payload.get("marketplace"),
            "categoryNodeId": canonical.get("category_node_id")
            or payload.get("categoryNodeId")
            or payload.get("category_node_id"),
            "timeRange": canonical.get("time_range") or payload.get("timeRange") or "90d",
            "listingSampleSize": bounded_int(canonical.get("listing_sample_size"), 20, 5, 100),
            "headListingCount": bounded_int(canonical.get("head_listing_count"), 5, 1, 30),
            "reviewSampleSize": bounded_int(canonical.get("review_sample_size"), 30, 1, 100),
            "prompt": payload.get("prompt"),
            "mode": payload.get("agentMode") or payload.get("mode") or "market",
            "generatedAt": payload.get("generatedAt"),
            "toolResults": payload.get("toolResults")
            if isinstance(payload.get("toolResults"), list)
            else [],
            "evidenceGaps": payload.get("evidenceGaps")
            if isinstance(payload.get("evidenceGaps"), list)
            else [],
        }
    if tool_name == "build_tiktok_new_product_report_data":
        return {
            "skillId": payload.get("skillId"),
            "category": tool_category,
            "brand": canonical.get("brand") or payload.get("brand") or "Hsia",
            "marketplace": canonical.get("marketplace") or payload.get("marketplace") or "US",
            "categoryNodeId": canonical.get("category_node_id")
            or payload.get("categoryNodeId")
            or payload.get("category_node_id"),
            "timeRange": canonical.get("time_range") or payload.get("timeRange") or "28d",
            "newProductWindow": canonical.get("new_product_window")
            or payload.get("newProductWindow")
            or payload.get("new_product_window")
            or "30d",
            "listingSampleSize": bounded_int(canonical.get("listing_sample_size"), 20, 1, 100),
            "headListingCount": bounded_int(canonical.get("head_listing_count"), 5, 1, 30),
            "prompt": payload.get("prompt"),
            "mode": payload.get("agentMode") or payload.get("mode") or "market",
            "generatedAt": payload.get("generatedAt"),
            "toolResults": payload.get("toolResults")
            if isinstance(payload.get("toolResults"), list)
            else [],
            "evidenceGaps": payload.get("evidenceGaps")
            if isinstance(payload.get("evidenceGaps"), list)
            else [],
        }
    if tool_name == "build_tiktok_bra_competitor_shop_report_data":
        return {
            "skillId": payload.get("skillId"),
            "category": tool_category,
            "brand": canonical.get("brand") or payload.get("brand") or "Hsia",
            "marketplace": canonical.get("marketplace") or payload.get("marketplace") or "US",
            "categoryNodeId": canonical.get("category_node_id")
            or payload.get("categoryNodeId")
            or payload.get("category_node_id"),
            "timeRange": canonical.get("time_range") or payload.get("timeRange") or "28d",
            "newProductWindow": canonical.get("new_product_window")
            or payload.get("newProductWindow")
            or payload.get("new_product_window")
            or "30d",
            "shopCandidateSize": bounded_int(
                canonical.get("shop_candidate_size"), 50, 10, 100
            ),
            "shopAnalysisCount": bounded_int(
                canonical.get("shop_analysis_count"), 10, 1, 30
            ),
            "prompt": payload.get("prompt"),
            "mode": payload.get("agentMode") or payload.get("mode") or "competitor",
            "generatedAt": payload.get("generatedAt"),
            "toolResults": payload.get("toolResults")
            if isinstance(payload.get("toolResults"), list)
            else [],
            "evidenceGaps": payload.get("evidenceGaps")
            if isinstance(payload.get("evidenceGaps"), list)
            else [],
        }
    if tool_name == "build_trend_report_data":
        return {
            "category": tool_category,
            "marketplace": canonical.get("marketplace") or payload.get("marketplace") or "Global",
            "timeRange": canonical.get("time_range") or payload.get("timeRange") or "30d",
            "designGoal": canonical.get("design_goal") or payload.get("designGoal"),
            "targetUser": canonical.get("target_user") or payload.get("targetUser"),
            "reportImageLimit": bounded_int(
                canonical.get("report_image_limit") or payload.get("reportImageLimit"),
                36,
                1,
                36,
            ),
            "prompt": payload.get("prompt"),
            "mode": payload.get("agentMode") or payload.get("mode") or "market",
            "generatedAt": payload.get("generatedAt"),
            "toolResults": payload.get("toolResults")
            if isinstance(payload.get("toolResults"), list)
            else [],
            "evidenceGaps": payload.get("evidenceGaps")
            if isinstance(payload.get("evidenceGaps"), list)
            else [],
        }
    if tool_name in {
        "build_competitor_product_report_data",
        "build_hot_product_pain_report_data",
    }:
        return {
            "skillId": payload.get("skillId"),
            "category": tool_category,
            "asin": canonical.get("asin") or payload.get("asin"),
            "brand": canonical.get("brand") or payload.get("brand") or "Hsia / 遐",
            "marketplace": canonical.get("marketplace")
            or payload.get("marketplace")
            or "Amazon US",
            "timeRange": canonical.get("time_range") or payload.get("timeRange") or "180d",
            "headListingCount": bounded_int(canonical.get("head_listing_count"), 10, 1, 30),
            "reportImageLimit": bounded_int(
                canonical.get("report_image_limit") or payload.get("reportImageLimit"),
                60,
                1,
                120,
            ),
            "prompt": payload.get("prompt"),
            "mode": payload.get("agentMode") or payload.get("mode") or "competitor",
            "generatedAt": payload.get("generatedAt"),
            "toolResults": payload.get("toolResults")
            if isinstance(payload.get("toolResults"), list)
            else [],
            "evidenceGaps": payload.get("evidenceGaps")
            if isinstance(payload.get("evidenceGaps"), list)
            else [],
        }
    if tool_name == "build_product_design_brief_data":
        return {
            "category": tool_category,
            "brand": canonical.get("brand") or payload.get("brand") or "Hsia / 遐",
            "marketplace": canonical.get("marketplace")
            or payload.get("marketplace")
            or "Amazon US",
            "timeRange": canonical.get("time_range") or payload.get("timeRange") or "180d",
            "designGoal": canonical.get("design_goal") or payload.get("designGoal"),
            "targetUser": canonical.get("target_user") or payload.get("targetUser"),
            "brandSiteUrls": canonical.get("brand_site_urls") or payload.get("brandSiteUrls") or [],
            "trendContext": canonical.get("trend_context") or payload.get("trendContext"),
            "listingSampleSize": bounded_int(canonical.get("listing_sample_size"), 100, 10, 200),
            "headListingCount": bounded_int(canonical.get("head_listing_count"), 10, 5, 30),
            "reviewSampleSize": bounded_int(canonical.get("review_sample_size"), 60, 10, 100),
            "tiktokVideoLimit": bounded_int(canonical.get("tiktok_video_limit"), 12, 1, 12),
            "tiktokCommentsPerVideo": bounded_int(
                canonical.get("tiktok_comments_per_video"), 20, 1, 20
            ),
            "prompt": payload.get("prompt"),
            "generatedAt": payload.get("generatedAt"),
            "toolResults": payload.get("toolResults")
            if isinstance(payload.get("toolResults"), list)
            else [],
            "evidenceGaps": payload.get("evidenceGaps")
            if isinstance(payload.get("evidenceGaps"), list)
            else [],
        }
    if tool_name == "render_html_report":
        return {
            "category": tool_category,
            "brand": canonical.get("brand") or payload.get("brand"),
            "marketplace": canonical.get("marketplace") or payload.get("marketplace"),
            "timeRange": canonical.get("time_range") or payload.get("timeRange") or "90d",
            "prompt": payload.get("prompt"),
            "mode": payload.get("agentMode") or payload.get("mode") or "market",
            "generatedAt": payload.get("generatedAt"),
            "marketReportData": payload.get("marketReportData")
            if isinstance(payload.get("marketReportData"), dict)
            else {},
            "tiktokNewProductReportData": (
                payload.get("tiktokNewProductReportData")
                if isinstance(payload.get("tiktokNewProductReportData"), dict)
                else {}
            ),
            "tiktokCompetitorShopReportData": (
                payload.get("tiktokCompetitorShopReportData")
                if isinstance(payload.get("tiktokCompetitorShopReportData"), dict)
                else {}
            ),
            "trendReportData": payload.get("trendReportData")
            if isinstance(payload.get("trendReportData"), dict)
            else {},
            "competitorProductReportData": payload.get("competitorProductReportData")
            if isinstance(payload.get("competitorProductReportData"), dict)
            else {},
            "hotProductPainReportData": payload.get("hotProductPainReportData")
            if isinstance(payload.get("hotProductPainReportData"), dict)
            else {},
            "chartRenderBundle": payload.get("chartRenderBundle")
            if isinstance(payload.get("chartRenderBundle"), dict)
            else {},
            "toolResults": payload.get("toolResults")
            if isinstance(payload.get("toolResults"), list)
            else [],
            "evidenceGaps": payload.get("evidenceGaps")
            if isinstance(payload.get("evidenceGaps"), list)
            else [],
            "useLlm": bool(payload.get("useLlm")),
            "skillId": payload.get("skillId"),
            "skillMarkdown": payload.get("skillMarkdown"),
            "skillHtmlTemplate": payload.get("skillHtmlTemplate"),
            "reportImageLimit": bounded_int(
                canonical.get("report_image_limit") or payload.get("reportImageLimit"),
                60,
                1,
                120,
            ),
        }
    if tool_name == "render_markdown_report":
        return {
            "category": tool_category,
            "brand": canonical.get("brand") or payload.get("brand") or "Hsia / 遐",
            "marketplace": canonical.get("marketplace")
            or payload.get("marketplace")
            or "Amazon US",
            "timeRange": canonical.get("time_range") or payload.get("timeRange") or "180d",
            "designGoal": canonical.get("design_goal") or payload.get("designGoal"),
            "prompt": payload.get("prompt"),
            "generatedAt": payload.get("generatedAt"),
            "productDesignBriefData": (
                payload.get("productDesignBriefData")
                if isinstance(payload.get("productDesignBriefData"), dict)
                else {}
            ),
            "evidenceGaps": payload.get("evidenceGaps")
            if isinstance(payload.get("evidenceGaps"), list)
            else [],
            "useLlm": bool(payload.get("useLlm")),
            "skillId": payload.get("skillId"),
            "skillMarkdown": payload.get("skillMarkdown"),
        }
    return {"category": tool_category, "bypassCache": bypass_cache}

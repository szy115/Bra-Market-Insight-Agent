from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ._planner_shared import (
    BoundedInt,
    ResolveParams,
    input_schema,
    planner_capability,
    require_list,
    require_mapping_or_none,
)
from .registry import ToolCapability

TREND_MAX_IMAGES_PER_PLATFORM = 48
TREND_MAX_REPORT_IMAGES = 36

TREND_PLATFORMS_INPUT_SCHEMA = input_schema(
    {
        "category": {"type": "string", "description": "Target fashion or product category."},
        "marketplace": {"type": "string", "description": "Target market or region."},
        "timeRange": {"type": "string", "description": "Research time window."},
        "resultsPerQuery": {"type": "integer", "minimum": 1, "maximum": 20},
        "resultsPerPlatform": {"type": "integer", "minimum": 1, "maximum": 20},
        "pageReadLimit": {"type": "integer", "minimum": 1, "maximum": 50},
        "reportImageLimit": {"type": "integer", "minimum": 1, "maximum": 36},
        "bypassCache": {"type": "boolean"},
    },
    required=["category"],
)


def normalize_trend_platforms_input(
    category: str,
    payload: dict[str, Any],
    canonical: Mapping[str, Any],
    bounded_int: BoundedInt,
) -> dict[str, Any]:
    results_per_query = bounded_int(
        canonical.get("article_results_per_query")
        or payload.get("resultsPerQuery")
        or payload.get("resultsPerPlatform"),
        10,
        1,
        20,
    )
    return {
        "category": str(canonical.get("category") or category),
        "marketplace": canonical.get("marketplace") or payload.get("marketplace") or "Global",
        "timeRange": canonical.get("time_range") or payload.get("timeRange") or "30d",
        "designGoal": canonical.get("design_goal") or payload.get("designGoal"),
        "targetUser": canonical.get("target_user") or payload.get("targetUser"),
        "trendContext": canonical.get("trend_context") or payload.get("trendContext"),
        "resultsPerQuery": results_per_query,
        "resultsPerPlatform": results_per_query,
        "pageReadLimit": bounded_int(
            canonical.get("article_candidate_limit") or payload.get("pageReadLimit"), 30, 1, 50
        ),
        "reportImageLimit": bounded_int(
            canonical.get("report_image_limit") or payload.get("reportImageLimit"), 36, 1, 36
        ),
        "bypassCache": bool(canonical.get("bypass_cache") or payload.get("bypassCache")),
    }


def shape_trend_platforms_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": result.get("category"),
        "marketplace": result.get("marketplace"),
        "time_range": result.get("time_range"),
        "generated_at": result.get("generated_at"),
        "source_mode": result.get("source_mode"),
        "coverage": result.get("coverage"),
        "visual_evidence": result.get("visual_evidence", [])[:TREND_MAX_REPORT_IMAGES],
        "visual_coverage": result.get("visual_coverage"),
        "platforms": [
            {
                "platform_id": platform.get("platform_id"),
                "name": platform.get("name"),
                "official_domains": platform.get("official_domains"),
                "search_query": platform.get("search_query"),
                "search_queries": platform.get("search_queries", []),
                "query_runs": platform.get("query_runs", []),
                "query_count": platform.get("query_count"),
                "search_provider": platform.get("search_provider"),
                "raw_result_count": platform.get("raw_result_count"),
                "unique_candidate_count": platform.get("unique_candidate_count"),
                "search_result_count": platform.get("search_result_count"),
                "search_results": platform.get("search_results", [])[:120],
                "page_read_target": platform.get("page_read_target"),
                "page_attempt_count": platform.get("page_attempt_count"),
                "page_read_count": platform.get("page_read_count"),
                "pages": platform.get("pages", [])[:50],
                "qualified_page_count": platform.get("qualified_page_count"),
                "supporting_page_count": platform.get("supporting_page_count"),
                "recent_page_count": platform.get("recent_page_count"),
                "background_page_count": platform.get("background_page_count"),
                "undated_page_count": platform.get("undated_page_count"),
                "discarded_page_count": platform.get("discarded_page_count"),
                "visual_evidence": platform.get("visual_evidence", [])[
                    :TREND_MAX_IMAGES_PER_PLATFORM
                ],
                "visual_count": platform.get("visual_count"),
                "accessed": platform.get("accessed"),
                "access_status": platform.get("access_status"),
                "evidence_status": platform.get("evidence_status"),
                "evidence_snippets": platform.get("evidence_snippets", [])[:12],
                "warnings": platform.get("warnings", [])[:8],
            }
            for platform in result.get("platforms", [])
            if isinstance(platform, dict)
        ],
        "warnings": result.get("warnings", [])[:16],
        "method": result.get("method"),
    }


def summarize_trend_platforms_result(result: dict[str, Any]) -> str:
    coverage = result.get("coverage") if isinstance(result.get("coverage"), dict) else {}
    visual_coverage = (
        result.get("visual_coverage") if isinstance(result.get("visual_coverage"), dict) else {}
    )
    return (
        f"Accessed {coverage.get('accessed_platforms', 0)}/{coverage.get('required_platforms', 3)} "
        f"required trend platforms; read {coverage.get('readable_pages', 0)} effective public page(s), "
        f"including {coverage.get('recent_pages', 0)} within the requested window, and selected "
        f"{visual_coverage.get('selected_for_report', 0)} visual evidence item(s)."
    )


def validate_trend_platforms_result(result: Mapping[str, Any]) -> None:
    require_mapping_or_none(result, "coverage")
    require_mapping_or_none(result, "visual_coverage")
    require_mapping_or_none(result, "method")
    require_list(result, "visual_evidence")
    require_list(result, "platforms")
    require_list(result, "warnings")


def build_trend_platforms_capability(
    *,
    resolve_params: ResolveParams,
    bounded_int: BoundedInt,
    adapter: Callable[[dict[str, Any]], dict[str, Any]],
) -> ToolCapability:
    return planner_capability(
        capability_id="trend_platforms",
        label="WGSN / 蝶讯 / Pinterest trend crawler",
        description=(
            "Visit WGSN, 蝶讯, and Pinterest separately through domain-targeted web search and "
            "public-page reading; return color, fabric, silhouette, and style evidence with "
            "per-platform access status."
        ),
        schema=TREND_PLATFORMS_INPUT_SCHEMA,
        normalize_input=lambda category, payload: normalize_trend_platforms_input(
            category, payload, resolve_params(payload), bounded_int
        ),
        adapter=lambda invocation: adapter(invocation.tool_input),
        shape_result=shape_trend_platforms_result,
        summarize=summarize_trend_platforms_result,
        validate_result=validate_trend_platforms_result,
        catalog_metadata={"source": "agent_reach_crawler"},
    )

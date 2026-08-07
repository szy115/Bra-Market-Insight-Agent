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
from .registry import ToolCapability, ToolInvocation

MEDIA_RANKINGS_INPUT_SCHEMA = input_schema(
    {
        "category": {"type": "string"},
        "queryLimit": {"type": "integer", "minimum": 1, "maximum": 10},
        "resultsPerQuery": {"type": "integer", "minimum": 1, "maximum": 10},
        "candidateLimit": {"type": "integer", "minimum": 1, "maximum": 20},
        "urls": {"type": "array", "items": {"type": "string"}},
        "bypassCache": {"type": "boolean"},
    }
)


def normalize_media_rankings_input(
    category: str,
    payload: dict[str, Any],
    canonical: Mapping[str, Any],
    bounded_int: BoundedInt,
) -> dict[str, Any]:
    return {
        "category": str(canonical.get("category") or category),
        "queryLimit": bounded_int(canonical.get("article_query_limit"), 4, 1, 10),
        "resultsPerQuery": bounded_int(canonical.get("article_results_per_query"), 5, 1, 10),
        "candidateLimit": bounded_int(canonical.get("article_candidate_limit"), 8, 1, 20),
        "includeIndustryReports": True,
        "urls": canonical.get("brand_site_urls")
        or payload.get("brandSiteUrls")
        or payload.get("urls")
        or [],
        "bypassCache": bool(canonical.get("bypass_cache") or payload.get("bypassCache")),
    }


def shape_media_rankings_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": result.get("summary"),
        "articles": [
            {
                "title": article.get("title"),
                "domain": article.get("domain"),
                "url": article.get("url"),
                "source_type": article.get("source_type"),
                "authority_level": article.get("authority_level"),
                "product_signals": article.get("product_signals", [])[:5],
                "evidence_snippets": article.get("evidence_snippets", [])[:6],
                "cautions": article.get("cautions", [])[:4],
            }
            for article in result.get("articles", [])[:12]
        ],
        "data_volume": result.get("data_volume"),
        "warnings": result.get("warnings", [])[:8],
    }


def summarize_media_rankings_result(result: dict[str, Any]) -> str:
    return f"{(result.get('data_volume') or {}).get('collected_articles', 0)} readable articles."


def validate_media_rankings_result(result: Mapping[str, Any]) -> None:
    require_mapping_or_none(result, "summary")
    require_mapping_or_none(result, "data_volume")
    require_list(result, "articles")
    require_list(result, "warnings")


def build_media_rankings_capability(
    *,
    resolve_params: ResolveParams,
    bounded_int: BoundedInt,
    discover: Callable[[dict[str, Any]], dict[str, Any]],
    extract_urls: Callable[[dict[str, Any]], tuple[list[str], list[str]]],
    analyze: Callable[[dict[str, Any]], dict[str, Any]],
    now_iso: Callable[[], str],
) -> ToolCapability:
    def adapter(invocation: ToolInvocation) -> dict[str, Any]:
        tool_input = invocation.tool_input
        discovery = discover(tool_input)
        provided_urls, provided_warnings = extract_urls({"urls": tool_input.get("urls") or []})
        discovered_urls = [
            item.get("url") for item in discovery.get("candidates", []) if item.get("url")
        ]
        candidate_limit = max(1, min(int(tool_input.get("candidateLimit") or 8), 20))
        urls = list(dict.fromkeys([*provided_urls, *discovered_urls]))[:candidate_limit]
        result = (
            analyze(
                {
                    "category": invocation.requested_category,
                    "urls": urls,
                    "limit": len(urls),
                    "bypassCache": bool(tool_input.get("bypassCache")),
                }
            )
            if urls
            else {
                "category": invocation.requested_category,
                "generated_at": now_iso(),
                "summary": {"collected_articles": 0},
                "data_volume": {"collected_articles": 0},
                "articles": [],
                "warnings": discovery.get("warnings", [])
                + ["No article URLs were selected for reading."],
            }
        )
        result["discovery"] = discovery
        result["provided_urls"] = provided_urls
        result["warnings"] = list(
            dict.fromkeys([*(result.get("warnings") or []), *provided_warnings])
        )
        return result

    return planner_capability(
        capability_id="media_rankings",
        label="Media/ranking articles",
        description=(
            "Discover and read US media reviews, public rankings, and accessible report pages."
        ),
        schema=MEDIA_RANKINGS_INPUT_SCHEMA,
        normalize_input=lambda category, payload: normalize_media_rankings_input(
            category, payload, resolve_params(payload), bounded_int
        ),
        adapter=adapter,
        shape_result=shape_media_rankings_result,
        summarize=summarize_media_rankings_result,
        validate_result=validate_media_rankings_result,
    )

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from .registry import (
    InvocationScope,
    RecoveryTraits,
    ResultContract,
    ToolCapability,
)

DEFAULT_PLANNER_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {"type": "string"},
        "timeRange": {"type": "string"},
        "time_range": {"type": "string"},
        "limit": {"type": "integer"},
        "bypassCache": {"type": "boolean"},
    },
    "required": [],
    "additionalProperties": True,
}


def normalize_reddit_voc_input(
    category: str,
    payload: dict[str, Any],
    canonical: Mapping[str, Any],
    bounded_int: Callable[[Any, int, int, int], int],
) -> dict[str, Any]:
    return {
        "category": str(canonical.get("category") or category),
        "timeRange": canonical.get("time_range") or "year",
        "limit": bounded_int(canonical.get("reddit_post_limit"), 30, 5, 120),
        "mode": payload.get("mode") or "auto",
        "useLlm": False,
        "redditDetailLimit": bounded_int(canonical.get("reddit_detail_limit"), 5, 0, 30),
        "redditCommentsPerPost": bounded_int(
            canonical.get("reddit_comments_per_post"), 10, 0, 80
        ),
        "bypassCache": bool(canonical.get("bypass_cache") or payload.get("bypassCache")),
    }


def shape_reddit_voc_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "coverage": result.get("coverage"),
        "market_signal": result.get("market_signal"),
        "sentiment": result.get("sentiment"),
        "pain_points": result.get("pain_points", [])[:5],
        "brands": result.get("brands", [])[:8],
        "sizes": result.get("sizes", [])[:8],
        "posts": [
            {
                "id": post.get("id"),
                "title": post.get("title"),
                "url": post.get("url"),
                "subreddit": post.get("subreddit"),
                "score": post.get("score"),
                "comments": post.get("comments"),
                "comment_sample_count": len(_reddit_comment_items(post)),
                "comment_items": _reddit_comment_items(post),
                "excerpt": _compact_text(str(post.get("excerpt") or ""), 260),
            }
            for post in result.get("posts", [])
        ],
    }


def summarize_reddit_voc_result(result: dict[str, Any]) -> str:
    coverage = result.get("coverage") or {}
    data_volume = result.get("data_volume") or {}
    return (
        f"{coverage.get('posts', 0)} Reddit posts, "
        f"{data_volume.get('collected_comments', 0)} comments."
    )


def build_reddit_voc_capability(
    *,
    resolve_params: Callable[[dict[str, Any]], Mapping[str, Any]],
    bounded_int: Callable[[Any, int, int, int], int],
    adapter: Callable[[dict[str, Any]], dict[str, Any]],
) -> ToolCapability:
    return ToolCapability(
        capability_id="reddit_voc",
        label="Reddit VOC",
        description=(
            "Collect Reddit posts and comment samples for user pain points, language, "
            "and brand/size mentions."
        ),
        input_schema=DEFAULT_PLANNER_INPUT_SCHEMA,
        invocation_scope=InvocationScope.PLANNER,
        normalize_input=lambda category, payload: normalize_reddit_voc_input(
            category,
            payload,
            resolve_params(payload),
            bounded_int,
        ),
        adapter=lambda invocation: adapter(invocation.tool_input),
        shape_result=shape_reddit_voc_result,
        summarize=summarize_reddit_voc_result,
        result_contract=ResultContract(
            contract_id="reddit_voc_result.v1",
            validate=_validate_reddit_voc_result,
        ),
        recovery=RecoveryTraits(
            retryable=True,
            default_timeout_seconds=600,
            default_retry_attempts=2,
        ),
        output_kind="reddit_voc",
    )


def _validate_reddit_voc_result(result: Mapping[str, Any]) -> None:
    required_types = {
        "pain_points": list,
        "brands": list,
        "sizes": list,
        "posts": list,
    }
    for field_name, expected_type in required_types.items():
        if not isinstance(result.get(field_name), expected_type):
            raise ValueError(f"{field_name} must be a {expected_type.__name__}")


def _reddit_comment_items(post: dict[str, Any]) -> list[dict[str, Any]]:
    comments = post.get("comment_items", [])
    if not isinstance(comments, list):
        return []
    return [
        comment
        for comment in comments
        if isinstance(comment, dict) and str(comment.get("text", "")).strip()
    ]


def _compact_text(value: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized if len(normalized) <= limit else normalized[: limit - 1].rstrip() + "…"

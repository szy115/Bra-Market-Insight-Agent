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

TIKTOK_SOCIAL_INPUT_SCHEMA = input_schema(
    {
        "category": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 12},
        "tiktokCommentsPerVideo": {"type": "integer", "minimum": 1, "maximum": 20},
        "bypassCache": {"type": "boolean"},
    }
)


def normalize_tiktok_social_input(
    category: str,
    payload: dict[str, Any],
    canonical: Mapping[str, Any],
    bounded_int: BoundedInt,
) -> dict[str, Any]:
    return {
        "category": str(canonical.get("category") or category),
        "limit": bounded_int(canonical.get("tiktok_video_limit"), 6, 1, 12),
        "tiktokCommentsPerVideo": bounded_int(
            canonical.get("tiktok_comments_per_video"), 4, 1, 20
        ),
        "bypassCache": bool(canonical.get("bypass_cache") or payload.get("bypassCache")),
    }


def shape_tiktok_social_result(
    result: dict[str, Any],
    video_text: Callable[[dict[str, Any]], str],
    compact_text: Callable[[str, int], str],
) -> dict[str, Any]:
    return {
        "metrics": result.get("metrics"),
        "market_signal": result.get("market_signal"),
        "hashtags": result.get("hashtags", [])[:10],
        "pain_points": result.get("pain_points", [])[:5],
        "videos": [
            {
                "title": video.get("title") or video.get("caption"),
                "url": video.get("url"),
                "author": video.get("author"),
                "views": video.get("view_count"),
                "comments": len(video.get("comment_samples") or []),
                "comment_samples": video.get("comment_samples")
                if isinstance(video.get("comment_samples"), list)
                else [],
                "snippet": compact_text(video_text(video), 260),
            }
            for video in result.get("videos", [])[:12]
        ],
    }


def summarize_tiktok_social_result(result: dict[str, Any]) -> str:
    metrics = result.get("metrics") or {}
    data_volume = result.get("data_volume") or {}
    return (
        f"{metrics.get('videos', 0)} TikTok videos, "
        f"{data_volume.get('comment_samples', 0)} comment samples."
    )


def validate_tiktok_social_result(result: Mapping[str, Any]) -> None:
    require_mapping_or_none(result, "metrics")
    require_mapping_or_none(result, "market_signal")
    require_list(result, "hashtags")
    require_list(result, "pain_points")
    require_list(result, "videos")


def build_tiktok_social_capability(
    *,
    resolve_params: ResolveParams,
    bounded_int: BoundedInt,
    adapter: Callable[[dict[str, Any]], dict[str, Any]],
    video_text: Callable[[dict[str, Any]], str],
    compact_text: Callable[[str, int], str],
) -> ToolCapability:
    return planner_capability(
        capability_id="tiktok_social",
        label="TikTok social validation",
        description=(
            "Collect TikTok videos and detail-page comment samples for social visibility and "
            "creator/user language."
        ),
        schema=TIKTOK_SOCIAL_INPUT_SCHEMA,
        normalize_input=lambda category, payload: normalize_tiktok_social_input(
            category, payload, resolve_params(payload), bounded_int
        ),
        adapter=lambda invocation: adapter(invocation.tool_input),
        shape_result=lambda result: shape_tiktok_social_result(result, video_text, compact_text),
        summarize=summarize_tiktok_social_result,
        validate_result=validate_tiktok_social_result,
    )

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUCCESS_TOOL_STATUSES = {"ok", "partial_ok"}


@dataclass(frozen=True)
class ToolAssessment:
    status: str
    outcome: str
    retryable: bool
    reason: str
    suggested_next_actions: list[str]


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _error_assessment(summary: str) -> ToolAssessment:
    text = summary.lower()
    if any(token in text for token in ("timed out", "timeout")):
        return ToolAssessment(
            status="timeout",
            outcome="timeout",
            retryable=True,
            reason=summary or "Tool timed out.",
            suggested_next_actions=["Retry once with the same inputs.", "If it times out again, reduce sample size or continue with other evidence."],
        )
    if any(token in text for token in ("login", "captcha", "verification", "verify", "not authenticated", "authentication", "authorization", "unauthorized", "forbidden", "unsafe")):
        return ToolAssessment(
            status="needs_user_action",
            outcome="needs_user_action",
            retryable=False,
            reason=summary or "Tool needs user action before it can run.",
            suggested_next_actions=["Ask the user to refresh login state or resolve verification.", "Do not blindly retry this tool."],
        )
    if any(token in text for token in ("required", "invalid", "unknown agent tool", "not found", "missing")):
        return ToolAssessment(
            status="fatal_error",
            outcome="fatal_error",
            retryable=False,
            reason=summary or "Tool input is invalid.",
            suggested_next_actions=["Fix tool arguments before retrying.", "Ask the user only if required information is genuinely missing."],
        )
    if any(token in text for token in ("network", "connection", "temporar", "reset", "refused", "overloaded", "429", "529", "rate limit")):
        return ToolAssessment(
            status="retryable_error",
            outcome="retryable_error",
            retryable=True,
            reason=summary or "Transient tool error.",
            suggested_next_actions=["Retry with exponential backoff.", "If repeated, continue with other evidence and report the data gap."],
        )
    return ToolAssessment(
        status="retryable_error",
        outcome="retryable_error",
        retryable=True,
        reason=summary or "Tool failed.",
        suggested_next_actions=["Retry once before surfacing the failure to the model."],
    )


def assess_agent_tool_result(tool_name: str, result: dict[str, Any]) -> ToolAssessment:
    status = str(result.get("status") or "")
    summary = str(result.get("summary") or "")
    if status != "ok":
        return _error_assessment(summary)

    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if tool_name == "reddit_voc":
        coverage = data.get("coverage") if isinstance(data.get("coverage"), dict) else {}
        posts = _int_value(coverage.get("posts")) or len(data.get("posts") or [])
        comments = sum(_int_value(post.get("comment_sample_count")) for post in data.get("posts") or [] if isinstance(post, dict))
        if posts <= 0:
            return ToolAssessment(
                status="empty",
                outcome="empty_result",
                retryable=False,
                reason="Reddit returned 0 posts for this query.",
                suggested_next_actions=["Ask the model to broaden the query or expand the time range.", "Try adjacent terms such as full coverage bra or large bust bra."],
            )
        if comments <= 0:
            return ToolAssessment(
                status="partial_ok",
                outcome="partial_ok",
                retryable=False,
                reason="Reddit posts were collected, but no comment samples were available.",
                suggested_next_actions=["Use post text as evidence and mark comment evidence as a gap."],
            )
    elif tool_name == "amazon_shelf":
        metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
        products = _int_value(metrics.get("products")) or len(data.get("products") or [])
        reviews = _int_value(metrics.get("total_review_count"))
        if products <= 0:
            return ToolAssessment(
                status="empty",
                outcome="empty_result",
                retryable=False,
                reason="Amazon shelf returned 0 products for this query.",
                suggested_next_actions=["Ask the model to broaden category wording or remove overly narrow filters.", "Try adjacent keywords before synthesizing."],
            )
        if reviews <= 0:
            return ToolAssessment(
                status="partial_ok",
                outcome="partial_ok",
                retryable=False,
                reason="Amazon products were collected, but review/rating signal is empty.",
                suggested_next_actions=["Use shelf evidence, but mark review evidence as incomplete."],
            )
    elif tool_name == "media_rankings":
        articles = len(data.get("articles") or [])
        if articles <= 0:
            return ToolAssessment(
                status="empty",
                outcome="empty_result",
                retryable=False,
                reason="Media/ranking search found no readable articles.",
                suggested_next_actions=["Ask the model to try broader media queries.", "Proceed only if other tools provide enough evidence."],
            )
    elif tool_name == "tiktok_social":
        metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
        videos = _int_value(metrics.get("videos")) or len(data.get("videos") or [])
        comments = sum(_int_value(video.get("comments")) for video in data.get("videos") or [] if isinstance(video, dict))
        if videos <= 0:
            return ToolAssessment(
                status="empty",
                outcome="empty_result",
                retryable=False,
                reason="TikTok returned 0 videos for this query.",
                suggested_next_actions=["Ask the model to broaden social query terms.", "Mark TikTok validation as a data gap if Amazon evidence is still useful."],
            )
        if comments <= 0:
            return ToolAssessment(
                status="partial_ok",
                outcome="partial_ok",
                retryable=False,
                reason="TikTok videos were collected, but detail-page comment samples are empty.",
                suggested_next_actions=["Use video evidence and mark comment validation as incomplete."],
            )

    return ToolAssessment(
        status="ok",
        outcome="ok_with_data",
        retryable=False,
        reason=summary or "Tool returned usable evidence.",
        suggested_next_actions=[],
    )


def retry_limit_for_assessment(assessment: ToolAssessment, configured_retries: int) -> int:
    if not assessment.retryable:
        return 0
    if assessment.outcome == "timeout":
        return min(configured_retries, 1)
    return configured_retries


def retry_delay_seconds(attempt_index: int, base_delay_ms: int) -> float:
    delay_ms = max(0, base_delay_ms) * (2 ** max(0, attempt_index - 1))
    return min(delay_ms, 5000) / 1000


def compact_attempt_result(attempt: int, result: dict[str, Any], assessment: ToolAssessment) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "status": assessment.status,
        "outcome": assessment.outcome,
        "retryable": assessment.retryable,
        "summary": result.get("summary") or assessment.reason,
        "duration_ms": int(result.get("duration_ms") or 0),
    }


def final_status_after_exhaustion(assessment: ToolAssessment) -> str:
    if assessment.status == "timeout":
        return "timeout"
    if assessment.status == "retryable_error":
        return "retry_exhausted"
    return assessment.status

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUCCESS_TOOL_STATUSES = {"ok", "partial_ok"}
SEMANTIC_ERROR_KEYS = {"error", "errors", "exception", "traceback"}
SEMANTIC_CODE_KEYS = {"code", "errorcode", "error_code", "errcode", "err_code", "status"}
SEMANTIC_MESSAGE_KEYS = {"message", "msg", "detail", "details", "reason", "data", "error_description"}
SUCCESS_CODE_VALUES = {"0", "00", "ok", "success", "successful", "succeeded", "done", "completed", "true", "200"}
NEGATIVE_STATUS_VALUES = {
    "error",
    "failed",
    "failure",
    "fail",
    "invalid",
    "rejected",
    "denied",
    "unauthorized",
    "forbidden",
    "false",
}
ERROR_CODE_TOKENS = (
    "error",
    "err_",
    "err-",
    "failed",
    "failure",
    "invalid",
    "exception",
    "denied",
    "unauthorized",
    "forbidden",
    "temporary",
    "unavailable",
    "timeout",
    "busy",
    "rate_limit",
)


@dataclass(frozen=True)
class ToolAssessment:
    status: str
    outcome: str
    retryable: bool
    reason: str
    suggested_next_actions: list[str]


@dataclass(frozen=True)
class SemanticFailure:
    path: str
    code: str
    message: str


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _compact_value(value: Any, limit: int = 320) -> str:
    if isinstance(value, (dict, list)):
        text = str(value)
    else:
        text = str(value or "")
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def _is_non_empty_error_value(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() not in {"none", "null", "false", "0", "ok", "success"}
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _is_error_code_value(key: str, value: Any) -> bool:
    key_normalized = key.lower()
    if value is None:
        return False
    if isinstance(value, bool):
        return key_normalized == "status" and value is False
    if isinstance(value, (int, float)):
        return key_normalized in SEMANTIC_CODE_KEYS and int(value) >= 400
    text = str(value).strip()
    if not text:
        return False
    normalized = text.lower()
    if normalized in SUCCESS_CODE_VALUES:
        return False
    if key_normalized == "status" and normalized in NEGATIVE_STATUS_VALUES:
        return True
    if key_normalized in SEMANTIC_CODE_KEYS and any(token in normalized for token in ERROR_CODE_TOKENS):
        return True
    if key_normalized in SEMANTIC_CODE_KEYS and normalized.startswith(("4", "5")) and normalized.isdigit():
        return True
    return False


def _message_from_mapping(value: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, item in value.items():
        key_normalized = str(key).lower()
        if key_normalized in SEMANTIC_MESSAGE_KEYS or key_normalized in SEMANTIC_ERROR_KEYS:
            if isinstance(item, dict):
                nested = _message_from_mapping(item)
                if nested:
                    parts.append(nested)
            elif isinstance(item, list):
                list_text = "; ".join(_compact_value(entry, 120) for entry in item[:3])
                if list_text:
                    parts.append(list_text)
            else:
                text = _compact_value(item)
                if text:
                    parts.append(text)
    return "; ".join(dict.fromkeys(parts))


def _find_semantic_failure(value: Any, path: str = "data", depth: int = 0) -> SemanticFailure | None:
    if depth > 7:
        return None
    if isinstance(value, dict):
        code = ""
        message = _message_from_mapping(value)
        for raw_key, item in value.items():
            key = str(raw_key)
            key_normalized = key.lower()
            item_path = f"{path}.{key}" if path else key
            if key_normalized == "iserror" and item is True:
                return SemanticFailure(path=item_path, code="isError=true", message=message or "Tool payload marked isError=true.")
            if key_normalized == "success" and item is False:
                return SemanticFailure(path=item_path, code="success=false", message=message or "Tool payload marked success=false.")
            if key_normalized in SEMANTIC_ERROR_KEYS and _is_non_empty_error_value(item):
                error_message = message
                if isinstance(item, dict):
                    error_message = _message_from_mapping(item) or error_message
                elif not error_message:
                    error_message = _compact_value(item)
                return SemanticFailure(path=item_path, code=key, message=error_message or "Tool payload contains an error field.")
            if key_normalized in SEMANTIC_CODE_KEYS and _is_error_code_value(key_normalized, item):
                if key_normalized == "status" and depth > 1 and not message:
                    continue
                code = _compact_value(item, 120)
                return SemanticFailure(path=item_path, code=code, message=message or f"Tool payload returned error code {code}.")
        for raw_key, item in value.items():
            found = _find_semantic_failure(item, f"{path}.{raw_key}" if path else str(raw_key), depth + 1)
            if found:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value[:30]):
            found = _find_semantic_failure(item, f"{path}[{index}]", depth + 1)
            if found:
                return found
    return None


def _error_assessment(summary: str) -> ToolAssessment:
    text = summary.lower()
    if any(token in text for token in ("timed out", "timeout", "超时")):
        return ToolAssessment(
            status="timeout",
            outcome="timeout",
            retryable=True,
            reason=summary or "Tool timed out.",
            suggested_next_actions=["Retry once with the same inputs.", "If it times out again, reduce sample size or continue with other evidence."],
        )
    if any(token in text for token in ("login", "captcha", "verification", "verify", "not authenticated", "authentication", "authorization", "unauthorized", "forbidden", "unsafe", "credits exhausted", "credit balance", "insufficient credit", "out of credits", "recharge", "quota exhausted", "登录", "验证码", "验证", "鉴权", "授权", "未授权", "无权限", "权限", "余额", "额度", "积分不足", "充值")):
        return ToolAssessment(
            status="needs_user_action",
            outcome="needs_user_action",
            retryable=False,
            reason=summary or "Tool needs user action before it can run.",
            suggested_next_actions=["Ask the user to refresh login state or resolve verification.", "Do not blindly retry this tool."],
        )
    if any(token in text for token in ("required", "requires", "invalid", "unknown agent tool", "not found", "missing", "parameter", "argument", "schema", "bad request", "unsupported", "参数", "缺少", "必填", "无效", "格式错误", "不支持", "不存在")):
        return ToolAssessment(
            status="fatal_error",
            outcome="fatal_error",
            retryable=False,
            reason=summary or "Tool input is invalid.",
            suggested_next_actions=["Fix tool arguments before retrying.", "Ask the user only if required information is genuinely missing."],
        )
    if any(token in text for token in ("network", "connection", "temporar", "reset", "refused", "overloaded", "429", "529", "rate limit", "busy", "unavailable", "网络", "连接", "临时", "重置", "繁忙", "不可用", "限流", "频率")):
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


def _semantic_failure_assessment(failure: SemanticFailure) -> ToolAssessment:
    code = f" ({failure.code})" if failure.code else ""
    reason = f"Tool payload reported an error{code}: {failure.message or 'No message provided.'}"
    base = _error_assessment(reason)
    if base.status == "fatal_error":
        return ToolAssessment(
            status="fatal_error",
            outcome="semantic_error",
            retryable=False,
            reason=reason,
            suggested_next_actions=[
                "Fix or regenerate tool arguments before retrying.",
                "If the required parameter is not inferable from context, ask the user for it.",
            ],
        )
    if base.status == "needs_user_action":
        return ToolAssessment(
            status=base.status,
            outcome=base.outcome,
            retryable=False,
            reason=reason,
            suggested_next_actions=base.suggested_next_actions,
        )
    return ToolAssessment(
        status=base.status,
        outcome="semantic_error",
        retryable=base.retryable,
        reason=reason,
        suggested_next_actions=base.suggested_next_actions,
    )


def _seller_sprite_payload_container(data: dict[str, Any]) -> dict[str, Any]:
    candidates: list[Any] = []
    candidates.append(data.get("data"))
    parsed = data.get("parsed_content")
    if isinstance(parsed, dict):
        candidates.append(parsed.get("data"))
    for candidate in candidates:
        if isinstance(candidate, dict) and "items" in candidate:
            return candidate
    return {}


def _empty_sellersprite_assessment(tool_name: str, data: dict[str, Any]) -> ToolAssessment | None:
    if not tool_name.startswith("sellersprite_"):
        return None
    container = _seller_sprite_payload_container(data)
    items = container.get("items") if isinstance(container.get("items"), list) else None
    if items is None:
        return None
    total = _int_value(container.get("total"))
    if total <= 0 and len(items) <= 0:
        return ToolAssessment(
            status="empty",
            outcome="empty_result",
            retryable=False,
            reason=f"{tool_name} returned 0 items.",
            suggested_next_actions=[
                "Broaden or correct the SellerSprite query arguments before synthesizing.",
                "If this is a node-level tool, provide the required category node id/path.",
            ],
        )
    return None


def _sellersprite_product_node_assessment(tool_name: str, data: dict[str, Any]) -> ToolAssessment | None:
    if tool_name != "sellersprite_product_node":
        return None
    resolution = data.get("node_resolution") if isinstance(data.get("node_resolution"), dict) else {}
    resolution_status = str(resolution.get("status") or "")
    selected = resolution.get("selected") if isinstance(resolution.get("selected"), dict) else {}
    if resolution_status == "resolved" and selected.get("nodeIdPath"):
        return None
    return ToolAssessment(
        status="empty",
        outcome="category_node_unresolved",
        retryable=False,
        reason=f"SellerSprite product_node did not resolve a unique category node ({resolution_status or 'unknown'}).",
        suggested_next_actions=[
            "Retry with the official Amazon leaf category label.",
            "Do not run node-level product tools until category_node_id is resolved.",
        ],
    )


def _sif_payload(data: dict[str, Any]) -> dict[str, Any]:
    parsed = data.get("parsed_content")
    if isinstance(parsed, dict):
        return parsed
    return data


def _empty_sif_assessment(tool_name: str, data: dict[str, Any]) -> ToolAssessment | None:
    if tool_name != "sif_market_get_keyword_competition":
        return None
    payload = _sif_payload(data)
    competitors = payload.get("top_competitors")
    if isinstance(competitors, list) and not competitors:
        return ToolAssessment(
            status="empty",
            outcome="empty_result",
            retryable=False,
            reason="sif_market_get_keyword_competition returned 0 top competitors.",
            suggested_next_actions=[
                "Broaden the keyword or verify marketplace/country arguments.",
                "Do not infer top products from unrelated market trend fields.",
            ],
        )
    return None


def _completed_html_renderer_assessment(
    tool_name: str,
    result: dict[str, Any],
) -> ToolAssessment | None:
    if tool_name != "render_html_report" or str(result.get("status") or "") not in SUCCESS_TOOL_STATUSES:
        return None
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    html_analysis = data.get("html_analysis") if isinstance(data.get("html_analysis"), dict) else {}
    html = str(data.get("html") or "").strip()
    if (
        str(html_analysis.get("status") or "") == "ok"
        and html.casefold().startswith("<!doctype html")
        and html.casefold().endswith("</html>")
    ):
        return ToolAssessment(
            status="ok",
            outcome="ok_with_data",
            retryable=False,
            reason=str(result.get("summary") or "HTML report renderer returned a complete document."),
            suggested_next_actions=[],
        )
    return None


def assess_agent_tool_result(tool_name: str, result: dict[str, Any]) -> ToolAssessment:
    status = str(result.get("status") or "")
    summary = str(result.get("summary") or "")
    completed_renderer = _completed_html_renderer_assessment(tool_name, result)
    if completed_renderer:
        return completed_renderer
    semantic_failure = _find_semantic_failure(result.get("data"))
    if semantic_failure:
        return _semantic_failure_assessment(semantic_failure)
    if status == "empty":
        return ToolAssessment(
            status="empty",
            outcome="empty_result",
            retryable=False,
            reason=summary or f"{tool_name} returned no usable records.",
            suggested_next_actions=[
                "Adjust the completed period, category id, or query window before retrying.",
                "Treat this as missing evidence, not proof of zero market activity.",
            ],
        )
    if status not in SUCCESS_TOOL_STATUSES:
        return _error_assessment(summary)

    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    empty_assessment = (
        _sellersprite_product_node_assessment(tool_name, data)
        or _empty_sellersprite_assessment(tool_name, data)
        or _empty_sif_assessment(tool_name, data)
    )
    if empty_assessment:
        return empty_assessment

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
    elif tool_name == "trend_platforms":
        coverage = data.get("coverage") if isinstance(data.get("coverage"), dict) else {}
        required = _int_value(coverage.get("required_platforms")) or 3
        accessed = _int_value(coverage.get("accessed_platforms"))
        if accessed <= 0:
            return ToolAssessment(
                status="empty",
                outcome="empty_result",
                retryable=False,
                reason="WGSN, 蝶讯, and Pinterest all returned no usable public or indexed evidence.",
                suggested_next_actions=[
                    "Check the configured Agent Reach/Exa search route and public network access.",
                    "Retry with a broader category and bypassCache=true.",
                ],
            )
        if accessed < required:
            return ToolAssessment(
                status="partial_ok",
                outcome="partial_ok",
                retryable=False,
                reason=f"Trend crawler accessed {accessed}/{required} required platforms.",
                suggested_next_actions=[
                    "Use the available evidence, but name every missing platform in the report.",
                    "Do not substitute another source for WGSN, 蝶讯, or Pinterest.",
                ],
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
        status="partial_ok" if status == "partial_ok" else "ok",
        outcome="partial_ok" if status == "partial_ok" else "ok_with_data",
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

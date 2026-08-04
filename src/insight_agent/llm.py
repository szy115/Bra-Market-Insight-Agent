from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

from .settings import (
    DEFAULT_AMAZON_LLM_PRODUCT_LIMIT,
    DEFAULT_AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT,
    DEFAULT_LLM_COMMENT_SAMPLES_PER_POST,
    DEFAULT_LLM_EVIDENCE_POSTS,
    build_llm_settings_response,
    configured_secret,
    int_setting,
    read_settings_values,
    selected_provider,
)


class LLMUnavailable(RuntimeError):
    """Raised when LLM analysis is requested but not configured or fails."""


LLM_TRANSIENT_RETRY_COUNT = 2
LLM_TRANSIENT_RETRY_DELAY_SECONDS = 0.8


def is_transient_llm_transport_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ssl.SSLError, ConnectionError, ConnectionResetError, ConnectionAbortedError)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, BaseException):
            return is_transient_llm_transport_error(reason)
        text = str(reason).lower()
        return any(token in text for token in ("timeout", "eof", "ssl", "connection", "reset"))
    if isinstance(exc, OSError):
        text = str(exc).lower()
        return any(token in text for token in ("timeout", "eof", "ssl", "connection reset", "connection aborted"))
    return False


def llm_transport_error_hint(exc: BaseException) -> str:
    text = str(exc)
    if "UNEXPECTED_EOF_WHILE_READING" in text or "EOF occurred in violation of protocol" in text:
        return "LLM connection closed during TLS response reading; this is usually a transient network/provider/proxy issue, not an API-key validation failure."
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "LLM request timed out; the provider may be slow or the configured timeout may be too low."
    return "LLM transport failed; this is usually caused by a transient network/provider/proxy connection issue."


def compact_report_context(report: dict[str, Any]) -> dict[str, Any]:
    values = read_settings_values()
    evidence_post_limit = int_setting(values, "INSIGHT_LLM_EVIDENCE_POSTS", DEFAULT_LLM_EVIDENCE_POSTS, 1, 100)
    comment_sample_limit = int_setting(
        values,
        "INSIGHT_LLM_COMMENT_SAMPLES_PER_POST",
        DEFAULT_LLM_COMMENT_SAMPLES_PER_POST,
        0,
        50,
    )
    return {
        "category": report.get("category"),
        "coverage": report.get("coverage"),
        "data_volume": report.get("data_volume"),
        "market_signal": report.get("market_signal"),
        "sentiment": report.get("sentiment"),
        "pain_points": [
            {
                "topic": item.get("topic"),
                "count": item.get("count"),
                "share": item.get("share"),
                "examples": [
                    {
                        "title": example.get("title"),
                        "subreddit": example.get("subreddit"),
                        "url": example.get("url"),
                        "snippet": example.get("snippet"),
                    }
                    for example in item.get("examples", [])[:2]
                ],
            }
            for item in report.get("pain_points", [])[:6]
        ],
        "brands": report.get("brands", [])[:8],
        "sizes": report.get("sizes", [])[:8],
        "trend": report.get("trend", [])[-12:],
        "evidence_posts": [
            {
                "title": post.get("title"),
                "subreddit": post.get("subreddit"),
                "url": post.get("url"),
                "score": post.get("score"),
                "comments": post.get("comments"),
                "excerpt": str(post.get("excerpt", ""))[:900],
                "comment_samples": [
                    {
                        "text": str(comment.get("text", ""))[:500],
                        "score": comment.get("score"),
                    }
                    for comment in post.get("comment_items", [])[:comment_sample_limit]
                    if str(comment.get("text", "")).strip()
                ],
            }
            for post in report.get("posts", [])[:evidence_post_limit]
        ],
        "opportunities": report.get("opportunities", [])[:5],
        "method": report.get("method"),
    }


def build_prompt(report: dict[str, Any]) -> list[dict[str, str]]:
    context = compact_report_context(report)
    system = (
        "You are a senior US intimate-apparel market research analyst. "
        "Use only the provided Reddit-derived evidence. Do not invent sales volume, demographics, "
        "or platform-wide market size. Return strict JSON only."
    )
    user = {
        "task": "Analyze this bra subcategory Reddit signal for product decision-making.",
        "requirements": [
            "Write concise executive_summary in English.",
            "List 3-5 strategic_takeaways.",
            "List opportunity_areas with rationale and evidence_urls.",
            "List data_gaps and what source would close each gap.",
            "Include confidence as High, Medium, Low, or Demo only.",
            "Every claim that depends on Reddit evidence must cite URLs from the input.",
        ],
        "schema": {
            "executive_summary": "string",
            "strategic_takeaways": ["string"],
            "opportunity_areas": [
                {
                    "title": "string",
                    "rationale": "string",
                    "confidence": "High|Medium|Low|Demo only",
                    "evidence_urls": ["string"],
                }
            ],
            "evidence_audit": ["string"],
            "data_gaps": ["string"],
        },
        "context": context,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def compact_amazon_report_context(report: dict[str, Any]) -> dict[str, Any]:
    values = read_settings_values()
    product_limit = int_setting(values, "AMAZON_LLM_PRODUCT_LIMIT", DEFAULT_AMAZON_LLM_PRODUCT_LIMIT, 1, 100)
    review_sample_limit = int_setting(
        values,
        "AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT",
        DEFAULT_AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT,
        0,
        50,
    )
    products = report.get("products", [])[:product_limit]
    return {
        "category": report.get("category"),
        "query": report.get("query"),
        "queries": report.get("queries"),
        "metrics": report.get("metrics"),
        "data_volume": report.get("data_volume"),
        "price_bands": report.get("price_bands"),
        "brands": report.get("brands", [])[:12],
        "products": [
            {
                "asin": product.get("asin"),
                "rank": product.get("rank"),
                "title": product.get("title"),
                "brand": product.get("brand"),
                "price_text": product.get("price_text"),
                "price_value": product.get("price_value"),
                "rating_value": product.get("rating_value"),
                "review_count": product.get("review_count"),
                "badges": product.get("badges"),
                "is_sponsored": product.get("is_sponsored"),
                "product_url": product.get("product_url"),
                "bullet_points": product.get("bullet_points", [])[:5],
                "review_samples": [
                    {
                        "title": review.get("title"),
                        "body": str(review.get("body", ""))[:500],
                        "rating_value": review.get("rating_value"),
                        "verified_purchase": review.get("verified_purchase"),
                    }
                    for review in product.get("review_samples", [])[:review_sample_limit]
                ],
            }
            for product in products
        ],
        "method": report.get("method"),
    }


def build_amazon_prompt(report: dict[str, Any]) -> list[dict[str, str]]:
    context = compact_amazon_report_context(report)
    system = (
        "You are a senior US intimate-apparel ecommerce market research analyst. "
        "Use only the provided Amazon-derived product and review-sample evidence. "
        "Do not invent true sales volume; treat rank, review count, badges, and review growth proxies as directional signals. "
        "Return strict JSON only."
    )
    user = {
        "task": "Analyze this Amazon category shelf for product and R&D decision-making.",
        "requirements": [
            "Write concise executive_summary in English.",
            "List 3-5 strategic_takeaways about price, competition, claims, and product gaps.",
            "List opportunity_areas with rationale and evidence_urls.",
            "List data_gaps and what source would close each gap.",
            "Include confidence as High, Medium, Low, or Demo only.",
            "Every claim that depends on Amazon evidence must cite product URLs from the input.",
        ],
        "schema": {
            "executive_summary": "string",
            "strategic_takeaways": ["string"],
            "opportunity_areas": [
                {
                    "title": "string",
                    "rationale": "string",
                    "confidence": "High|Medium|Low|Demo only",
                    "evidence_urls": ["string"],
                }
            ],
            "evidence_audit": ["string"],
            "data_gaps": ["string"],
        },
        "context": context,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def build_combined_insight_prompt(context: dict[str, Any], locale: str = "zh") -> list[dict[str, str]]:
    language = "Chinese" if locale == "zh" else "English"
    system = (
        "You are a senior US intimate-apparel market insight strategist. "
        "Use only the provided Reddit and Amazon evidence pool. "
        "Every conclusion must cite at least one citation_id from the evidence pool. "
        "Do not invent market size, sales volume, demographics, or trend direction beyond the evidence. "
        "Return strict JSON only."
    )
    user = {
        "task": f"Create a concise integrated insight report in {language}.",
        "hard_requirements": [
            "verdict must be one sentence and cite at least one citation_id.",
            "Return exactly 3 opportunities.",
            "Return exactly 3 risks.",
            "Return 2-4 R&D recommendations.",
            "Return 2-4 brand communication recommendations.",
            "Return 4-8 evidence_chain items.",
            "Return 2-4 data_gaps.",
            "Every item in verdict, opportunities, risks, rd_recommendations, brand_communication, and data_gaps must include citation_ids.",
            "Only use citation_ids that exist in context.evidence_pool.",
        ],
        "schema": {
            "verdict": {"text": "string", "citation_ids": ["R1|A1|A1R1"]},
            "opportunities": [
                {"title": "string", "detail": "string", "citation_ids": ["string"]}
            ],
            "risks": [
                {"title": "string", "detail": "string", "citation_ids": ["string"]}
            ],
            "rd_recommendations": [
                {"title": "string", "detail": "string", "citation_ids": ["string"]}
            ],
            "brand_communication": [
                {"title": "string", "detail": "string", "citation_ids": ["string"]}
            ],
            "evidence_chain": [
                {"claim": "string", "detail": "string", "citation_ids": ["string"]}
            ],
            "data_gaps": [
                {"title": "string", "detail": "string", "citation_ids": ["string"]}
            ],
        },
        "context": context,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def build_competitor_deep_dive_prompt(context: dict[str, Any], locale: str = "zh") -> list[dict[str, str]]:
    language = "Chinese" if locale == "zh" else "English"
    compact_context = {
        "category": context.get("category"),
        "product": context.get("product"),
        "amazon": {
            "review_samples_collected": (context.get("amazon") or {}).get("review_samples_collected"),
            "review_samples": (context.get("amazon") or {}).get("review_samples", [])[:40],
        },
        "reddit": context.get("reddit"),
        "web": context.get("web"),
        "sales_proxy": context.get("sales_proxy"),
        "evidence_pool": [
            {
                "id": item.get("id"),
                "source": item.get("source"),
                "kind": item.get("kind"),
                "title": item.get("title"),
                "url": item.get("url"),
                "excerpt": str(item.get("excerpt") or "")[:900],
                "reference": item.get("reference"),
            }
            for item in context.get("evidence_pool", [])[:90]
            if isinstance(item, dict)
        ],
    }
    system = (
        "You are a senior US intimate-apparel competitor intelligence analyst. "
        "Use only the provided Amazon, Reddit, and web evidence. "
        "Do not invent true sales, revenue, demographics, BSR history, or trend direction. "
        "Every conclusion must cite at least one citation_id from context.evidence_pool. "
        "Return strict JSON only."
    )
    user = {
        "task": f"Create a competitor deep-dive / breakout-product teardown report in {language}.",
        "hard_requirements": [
            "verdict must be one sentence and cite at least one citation_id.",
            "Return exactly 3 breakout_assessment items.",
            "Return 2-4 why_it_sells items.",
            "Return 2-4 user_love items.",
            "Return 2-4 user_complaints items.",
            "Return 2-4 rd_teardown items.",
            "Return 2-4 brand_communication items.",
            "Return 1-3 sales_proxy_interpretation items and clearly say proxies are not true sales.",
            "Return exactly 3 risks.",
            "Return 5-8 evidence_chain items.",
            "Return exactly 3 data_gaps.",
            "Only cite citation_ids that exist in context.evidence_pool.",
        ],
        "schema": {
            "verdict": {"text": "string", "citation_ids": ["A1|A1R1|R1|R1C1|W1"]},
            "breakout_assessment": [{"title": "string", "detail": "string", "citation_ids": ["string"]}],
            "why_it_sells": [{"title": "string", "detail": "string", "citation_ids": ["string"]}],
            "user_love": [{"title": "string", "detail": "string", "citation_ids": ["string"]}],
            "user_complaints": [{"title": "string", "detail": "string", "citation_ids": ["string"]}],
            "rd_teardown": [{"title": "string", "detail": "string", "citation_ids": ["string"]}],
            "brand_communication": [{"title": "string", "detail": "string", "citation_ids": ["string"]}],
            "sales_proxy_interpretation": [{"title": "string", "detail": "string", "citation_ids": ["string"]}],
            "risks": [{"title": "string", "detail": "string", "citation_ids": ["string"]}],
            "evidence_chain": [{"claim": "string", "detail": "string", "citation_ids": ["string"]}],
            "data_gaps": [{"title": "string", "detail": "string", "citation_ids": ["string"]}],
        },
        "context": compact_context,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end >= start:
        stripped = stripped[start : end + 1]
    return json.loads(stripped)


def call_openai_compatible_chat(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    values = read_settings_values()
    provider = selected_provider(values)
    settings = build_llm_settings_response(values)
    api_key = values.get(provider.api_key_env or "", "") if provider.api_key_env else "ollama"
    if provider.api_key_required and not configured_secret(api_key):
        raise LLMUnavailable(f"{provider.label} API key is not configured.")

    base_url = settings["base_url"].rstrip("/")
    url = f"{base_url}/chat/completions"
    body = {
        "model": settings["model_name"],
        "messages": messages,
        "temperature": settings["temperature"],
    }
    if max_tokens is not None:
        body["max_tokens"] = max(1, int(max_tokens))
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice
    headers = {"Content-Type": "application/json"}
    if provider.api_key_env:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    max_attempts = LLM_TRANSIENT_RETRY_COUNT + 1
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=int(settings["timeout_seconds"])) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:500]
            raise LLMUnavailable(f"LLM HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # noqa: BLE001
            if attempt < max_attempts and is_transient_llm_transport_error(exc):
                time.sleep(LLM_TRANSIENT_RETRY_DELAY_SECONDS * attempt)
                continue
            hint = llm_transport_error_hint(exc) if is_transient_llm_transport_error(exc) else "LLM request failed."
            raise LLMUnavailable(f"LLM request failed after {attempt} attempt(s): {exc}. {hint}") from exc

    choice = payload.get("choices", [{}])[0]
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    return {
        "provider": provider.name,
        "model": settings["model_name"],
        "message": message,
        "finish_reason": choice.get("finish_reason"),
        "usage": payload.get("usage") or {},
        "raw": payload,
    }


def call_openai_compatible(messages: list[dict[str, str]]) -> dict[str, Any]:
    chat = call_openai_compatible_chat(messages)
    content = chat.get("message", {}).get("content", "")
    if not content:
        raise LLMUnavailable("LLM returned an empty response.")
    try:
        parsed = extract_json(content)
    except json.JSONDecodeError as exc:
        raise LLMUnavailable("LLM response was not valid JSON.") from exc
    return {
        "provider": chat.get("provider"),
        "model": chat.get("model"),
        "result": parsed,
        "usage": chat.get("usage") or {},
    }


def enhance_report_with_llm(report: dict[str, Any]) -> dict[str, Any]:
    previous_provider = os.environ.get("INSIGHT_LLM_PROVIDER")
    messages = build_prompt(report)
    enhanced = call_openai_compatible(messages)
    if previous_provider:
        os.environ["INSIGHT_LLM_PROVIDER"] = previous_provider
    return enhanced


def enhance_amazon_report_with_llm(report: dict[str, Any]) -> dict[str, Any]:
    previous_provider = os.environ.get("INSIGHT_LLM_PROVIDER")
    messages = build_amazon_prompt(report)
    enhanced = call_openai_compatible(messages)
    if previous_provider:
        os.environ["INSIGHT_LLM_PROVIDER"] = previous_provider
    return enhanced


def enhance_combined_insight_with_llm(context: dict[str, Any], locale: str = "zh") -> dict[str, Any]:
    previous_provider = os.environ.get("INSIGHT_LLM_PROVIDER")
    messages = build_combined_insight_prompt(context, locale)
    enhanced = call_openai_compatible(messages)
    if previous_provider:
        os.environ["INSIGHT_LLM_PROVIDER"] = previous_provider
    return enhanced


def enhance_competitor_deep_dive_with_llm(context: dict[str, Any], locale: str = "zh") -> dict[str, Any]:
    previous_provider = os.environ.get("INSIGHT_LLM_PROVIDER")
    messages = build_competitor_deep_dive_prompt(context, locale)
    enhanced = call_openai_compatible(messages)
    if previous_provider:
        os.environ["INSIGHT_LLM_PROVIDER"] = previous_provider
    return enhanced

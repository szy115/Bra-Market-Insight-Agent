from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .fastmoss_market_report import completed_us_periods
from .mcp_result_cache import execute_with_mcp_result_cache

FASTMOSS_AGENT_TOOL_PREFIX = "mcp__fastmoss__"
DEFAULT_FASTMOSS_MCP_URL = "https://mcp.fastmoss.com/mcp"
FASTMOSS_AUTH_ENV_NAMES = ["FASTMOSS_MCP_API_KEY", "FASTMOSS_MCP_KEY", "FASTMOSS_API_KEY"]
FASTMOSS_REGION_ALIASES = {
    "MEXICO": "MX",
    "MÉXICO": "MX",
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "USA": "US",
}
FASTMOSS_EMPTY_CONTEXT_KEYS = {
    "analysis_type",
    "category",
    "currency_code",
    "date",
    "date_type",
    "date_value",
    "filter",
    "lang",
    "normalized_period_key",
    "page",
    "pagesize",
    "params",
    "query",
    "ranking_context",
    "ranking_scope",
    "region",
    "stat_date",
    "tool_id",
    "total",
}

# Keep the default catalog focused on the TikTok Shop market-insight workflow.
# Set FASTMOSS_MCP_TOOLS=* to expose every tool returned by tools/list.
DEFAULT_FASTMOSS_AGENT_TOOLS = {
    "search_category_by_words",
    "market_category_ranking",
    "market_category_analysis",
    "market_category_author_sales_matrix",
    "product_search",
    "product_rank_top_selling",
    "product_rank_new_listed",
    "product_overview",
    "product_sales_trend",
    "product_creator_analysis",
    "product_video_list",
    "product_detail_info",
    "product_sku",
    "product_investment",
    "product_review_list",
    "shop_search",
    "shop_rank_top_selling",
    "shop_base_info",
    "shop_product_analysis",
    "shop_sale_analysis",
    "shop_creator_analysis",
    "shop_data_trends",
    "creator_rank_top_ecommerce",
    "creator_profile_overview",
    "creator_fans_distribution",
    "video_script_info",
    "fastmoss_detail_url_examples",
    "search_fastmoss_documents",
}


class FastMossMcpError(RuntimeError):
    pass


class FastMossMcpAuthError(FastMossMcpError):
    pass


class FastMossMcpCreditsError(FastMossMcpError):
    pass


def compact_text(value: Any, limit: int = 720) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def is_fastmoss_agent_tool(tool_name: str) -> bool:
    return str(tool_name or "").startswith(FASTMOSS_AGENT_TOOL_PREFIX)


def fastmoss_mcp_tool_name(agent_tool_name: str) -> str:
    if is_fastmoss_agent_tool(agent_tool_name):
        return agent_tool_name[len(FASTMOSS_AGENT_TOOL_PREFIX):]
    return agent_tool_name


def fastmoss_agent_tool_name(mcp_tool_name: str) -> str:
    return f"{FASTMOSS_AGENT_TOOL_PREFIX}{str(mcp_tool_name or '').strip()}"


def fastmoss_enabled_tool_names() -> set[str]:
    configured = os.getenv("FASTMOSS_MCP_TOOLS", "").strip()
    if not configured:
        return set(DEFAULT_FASTMOSS_AGENT_TOOLS)
    if configured.lower() in {"*", "all"}:
        return {"*"}
    return {item.strip() for item in configured.split(",") if item.strip()}


def _configured_fastmoss_url() -> str:
    return os.getenv("FASTMOSS_MCP_URL", DEFAULT_FASTMOSS_MCP_URL).strip() or DEFAULT_FASTMOSS_MCP_URL


def _usable_api_key(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized.casefold() in {"", "xxxxxx", "your_api_key", "your-api-key", "<api_key>"}:
        return ""
    return normalized


def fastmoss_api_key() -> str:
    for env_name in FASTMOSS_AUTH_ENV_NAMES:
        value = _usable_api_key(os.getenv(env_name, ""))
        if value:
            return value
    query = dict(parse_qsl(urlsplit(_configured_fastmoss_url()).query, keep_blank_values=True))
    return _usable_api_key(query.get("api_key"))


def fastmoss_mcp_url() -> str:
    configured = _configured_fastmoss_url()
    parts = urlsplit(configured)
    query_items = parse_qsl(parts.query, keep_blank_values=True)
    query = {key: value for key, value in query_items if key != "api_key"}
    api_key = fastmoss_api_key()
    if not api_key:
        raise FastMossMcpAuthError(
            "FastMoss MCP requires authentication. Set FASTMOSS_MCP_API_KEY in the environment."
        )
    query["api_key"] = api_key
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _safe_remote_message(value: Any) -> str:
    message = compact_text(value, 520)
    api_key = fastmoss_api_key()
    if api_key:
        message = message.replace(api_key, "***")
    return re.sub(r"(?i)(api_key=)[^&\s\"']+", r"\1***", message)


def _parse_sse_or_json_response(raw: str) -> dict[str, Any]:
    stripped = raw.strip()
    if not stripped:
        return {}
    if stripped.startswith("{") or stripped.startswith("["):
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    data_chunks: list[str] = []
    events: list[str] = []
    for line in stripped.splitlines():
        if line.startswith("data:"):
            data_chunks.append(line.split(":", 1)[1].strip())
        elif not line.strip() and data_chunks:
            events.append("\n".join(data_chunks))
            data_chunks = []
    if data_chunks:
        events.append("\n".join(data_chunks))
    for event in events:
        if not event or event == "[DONE]":
            continue
        parsed = json.loads(event)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _http_error(exc: urllib.error.HTTPError) -> FastMossMcpError:
    message = _safe_remote_message(exc.read().decode("utf-8", errors="replace"))
    suffix = f" {message}" if message else ""
    if exc.code in {401, 403}:
        return FastMossMcpAuthError(f"FastMoss MCP authorization failed ({exc.code}).{suffix}")
    if exc.code == 402:
        return FastMossMcpCreditsError(f"FastMoss MCP credits are insufficient (402).{suffix}")
    return FastMossMcpError(f"FastMoss MCP HTTP {exc.code}.{suffix}")


def _post_json_rpc(
    method: str,
    params: dict[str, Any],
    request_id: int | str,
    session_id: str | None = None,
    *,
    timeout: int = 60,
) -> tuple[dict[str, Any], str | None]:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "User-Agent": "InsightAgent/0.1",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    request = urllib.request.Request(fastmoss_mcp_url(), data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            next_session = (
                response.headers.get("Mcp-Session-Id")
                or response.headers.get("mcp-session-id")
                or session_id
            )
            return _parse_sse_or_json_response(raw), next_session
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except urllib.error.URLError as exc:
        raise FastMossMcpError(f"FastMoss MCP connection failed: {_safe_remote_message(exc.reason)}") from exc


def _post_json_rpc_notification(
    method: str,
    params: dict[str, Any],
    session_id: str | None = None,
) -> None:
    body = json.dumps(
        {"jsonrpc": "2.0", "method": method, "params": params},
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "User-Agent": "InsightAgent/0.1",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    request = urllib.request.Request(fastmoss_mcp_url(), data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc


def _initialize_session() -> str | None:
    init, session_id = _post_json_rpc(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "insight-agent", "version": "0.1"},
        },
        1,
        timeout=20,
    )
    if init.get("error"):
        raise FastMossMcpError(_safe_remote_message(json.dumps(init["error"], ensure_ascii=False)))
    try:
        _post_json_rpc_notification("notifications/initialized", {}, session_id)
    except Exception:
        # Some Streamable HTTP servers do not require or acknowledge this notification.
        pass
    return session_id


def call_fastmoss_mcp_method(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    session_id = _initialize_session()
    response, _ = _post_json_rpc(method, params or {}, 2, session_id)
    if response.get("error"):
        error = response["error"]
        code = error.get("code") if isinstance(error, dict) else None
        message = _safe_remote_message(json.dumps(error, ensure_ascii=False))
        if code in {401, 403}:
            raise FastMossMcpAuthError(message)
        if code == 402:
            raise FastMossMcpCreditsError(message)
        raise FastMossMcpError(message)
    result = response.get("result")
    return result if isinstance(result, dict) else {"result": result}


def fetch_fastmoss_tool_schema() -> list[dict[str, Any]]:
    if not fastmoss_api_key():
        return []
    try:
        result = call_fastmoss_mcp_method("tools/list", {})
    except Exception:
        return []
    tools = result.get("tools")
    return tools if isinstance(tools, list) else []


def build_fastmoss_tool_catalog(schema_tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    enabled = fastmoss_enabled_tool_names()
    include_all = "*" in enabled
    catalog: dict[str, dict[str, Any]] = {}
    for tool in schema_tools:
        if not isinstance(tool, dict):
            continue
        mcp_name = str(tool.get("name") or "").strip()
        if not mcp_name or (not include_all and mcp_name not in enabled):
            continue
        input_schema = (
            tool.get("inputSchema")
            if isinstance(tool.get("inputSchema"), dict)
            else {"type": "object", "properties": {}}
        )
        agent_name = fastmoss_agent_tool_name(mcp_name)
        catalog[agent_name] = {
            "label": f"FastMoss: {mcp_name}",
            "description": compact_text(tool.get("description"), 720),
            "input_schema": input_schema,
            "source": "fastmoss_mcp",
            "mcp_tool": mcp_name,
            "auth_env_names": FASTMOSS_AUTH_ENV_NAMES,
        }
    return catalog


@lru_cache(maxsize=4)
def _get_fastmoss_tool_catalog_for_config(config_fingerprint: str) -> dict[str, dict[str, Any]]:
    if not config_fingerprint:
        return {}
    return build_fastmoss_tool_catalog(fetch_fastmoss_tool_schema())


def get_fastmoss_tool_catalog() -> dict[str, dict[str, Any]]:
    api_key = fastmoss_api_key()
    if not api_key:
        return {}
    parts = urlsplit(_configured_fastmoss_url())
    endpoint = urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
    enabled = ",".join(sorted(fastmoss_enabled_tool_names()))
    fingerprint = hashlib.sha256(f"{endpoint}\0{api_key}\0{enabled}".encode()).hexdigest()
    return _get_fastmoss_tool_catalog_for_config(fingerprint)


def _payload_value(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value is not None and value != "":
        return value
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    return params.get(key)


def _normalize_fastmoss_region(value: Any) -> str:
    normalized = " ".join(str(value or "").strip().upper().split())
    if not normalized:
        return ""
    if (
        "NORTH AMERICA" in normalized
        or "北美" in normalized
        or re.search(r"\bUS\s*(?:\+|/|&|AND)\s*MX\b", normalized)
        or re.search(r"\bMX\s*(?:\+|/|&|AND)\s*US\b", normalized)
    ):
        return ""
    if "墨西哥" in normalized:
        return "MX"
    if "美国" in normalized:
        return "US"
    alias = FASTMOSS_REGION_ALIASES.get(normalized)
    if alias:
        return alias
    return normalized if re.fullmatch(r"[A-Z]{2}", normalized) else ""


def _region_from_payload(payload: dict[str, Any]) -> str:
    saw_region_value = False
    for key in ("region", "marketplace", "market", "country", "locale_market"):
        value = _payload_value(payload, key)
        if value is None or str(value).strip() == "":
            continue
        saw_region_value = True
        return _normalize_fastmoss_region(value)
    return "" if saw_region_value else "US"


def _schema_properties(schema: Any) -> dict[str, Any]:
    return schema.get("properties") if isinstance(schema, dict) and isinstance(schema.get("properties"), dict) else {}


def _sanitized_fastmoss_filter(value: Any, filter_schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = set(_schema_properties(filter_schema))
    filtered = {str(key): item for key, item in value.items() if not allowed or key in allowed}
    if "region" in filtered:
        normalized_region = _normalize_fastmoss_region(filtered.get("region"))
        if normalized_region:
            filtered["region"] = normalized_region
        else:
            filtered.pop("region", None)
    return filtered


def _prompt_requests_explicit_historical_period(payload: dict[str, Any]) -> bool:
    prompt = str(payload.get("prompt") or "")
    return bool(
        re.search(r"\b20\d{2}[-年](?:0?[1-9]|1[0-2])\b", prompt)
        or re.search(r"\b20\d{2}-W\d{1,2}\b", prompt, flags=re.IGNORECASE)
        or re.search(r"\b20\d{2}\b", prompt)
    )


def _apply_tiktok_us_completed_period(
    agent_tool_name: str,
    output: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    if str(payload.get("skillId") or "") != "tiktok_us_market_insight":
        return
    if _prompt_requests_explicit_historical_period(payload):
        return
    filter_payload = output.get("filter") if isinstance(output.get("filter"), dict) else None
    if filter_payload is None:
        return
    periods = completed_us_periods(payload.get("generatedAt"))
    date_type = str(filter_payload.get("date_type") or "").strip().lower()
    if not date_type and fastmoss_mcp_tool_name(agent_tool_name) == "market_category_author_sales_matrix":
        date_type = "month"
    if date_type in {"day", "week", "month"} and "date_value" in filter_payload:
        filter_payload["date_value"] = periods[date_type]


def build_fastmoss_input_payload(
    agent_tool_name: str,
    category: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    meta = get_fastmoss_tool_catalog().get(agent_tool_name) or {}
    schema = meta.get("input_schema") if isinstance(meta.get("input_schema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    allowed_keys = set(properties)
    output: dict[str, Any] = {}
    for key in allowed_keys:
        value = _payload_value(payload, key)
        if value is None or value == "":
            continue
        if key == "filter":
            output[key] = _sanitized_fastmoss_filter(value, properties.get("filter") or {})
        elif key in {"region", "country", "market"}:
            normalized_region = _normalize_fastmoss_region(value)
            if normalized_region:
                output[key] = normalized_region
        else:
            output[key] = value

    category_value = str(_payload_value(payload, "category") or category or "").strip()
    for key in ("query", "keyword", "keywords", "category_name", "category_words"):
        if key in allowed_keys and not output.get(key) and category_value:
            output[key] = category_value

    region = _region_from_payload(payload)
    for key in ("region", "country", "market"):
        if key in allowed_keys and not output.get(key):
            output[key] = region

    category_id = str(
        _payload_value(payload, "category_id")
        or _payload_value(payload, "category_node_id")
        or _payload_value(payload, "categoryNodeId")
        or ""
    ).strip()
    for key in ("category_id", "categoryId"):
        if key in allowed_keys and not output.get(key) and category_id:
            output[key] = category_id

    if "filter" in allowed_keys:
        filter_payload = dict(output.get("filter")) if isinstance(output.get("filter"), dict) else {}
        filter_schema = properties.get("filter") if isinstance(properties.get("filter"), dict) else {}
        filter_properties = _schema_properties(filter_schema)
        filter_is_open = not filter_properties
        if region and (filter_is_open or "region" in filter_properties) and not filter_payload.get("region"):
            filter_payload["region"] = region
        if (
            category_id
            and (filter_is_open or "category_id" in filter_properties)
            and not filter_payload.get("category_id")
        ):
            filter_payload["category_id"] = category_id
        if filter_payload:
            output["filter"] = filter_payload
    _apply_tiktok_us_completed_period(agent_tool_name, output, payload)
    return output


def _fastmoss_region_input_error(meta: dict[str, Any], input_payload: dict[str, Any]) -> str:
    schema = meta.get("input_schema") if isinstance(meta.get("input_schema"), dict) else {}
    properties = _schema_properties(schema)
    filter_schema = properties.get("filter") if isinstance(properties.get("filter"), dict) else {}
    filter_properties = _schema_properties(filter_schema)
    region_location = ""
    region_value: Any = None
    if "region" in filter_properties:
        region_location = "filter.region"
        filter_payload = input_payload.get("filter") if isinstance(input_payload.get("filter"), dict) else {}
        region_value = filter_payload.get("region")
    elif "region" in properties:
        region_location = "region"
        region_value = input_payload.get("region")
    if not region_location:
        return ""
    if _normalize_fastmoss_region(region_value):
        return ""
    return (
        f"FastMoss market-scoped tool requires an explicit two-letter `{region_location}`. "
        "North America is a market group; call US and MX separately."
    )


def call_fastmoss_mcp_tool(mcp_tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return call_fastmoss_mcp_method(
        "tools/call",
        {"name": mcp_tool_name, "arguments": arguments},
    )


def _fastmoss_has_meaningful_value(value: Any, *, key: str = "", depth: int = 0) -> bool:
    if depth > 12 or key.casefold() in FASTMOSS_EMPTY_CONTEXT_KEYS:
        return False
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_fastmoss_has_meaningful_value(item, depth=depth + 1) for item in value)
    if isinstance(value, dict):
        return any(
            _fastmoss_has_meaningful_value(item, key=str(item_key), depth=depth + 1)
            for item_key, item in value.items()
        )
    return True


def fastmoss_data_is_empty(data: dict[str, Any]) -> bool:
    return not _fastmoss_has_meaningful_value(data)


FASTMOSS_CREDIT_EXHAUSTED_MARKERS = (
    "credits exhausted",
    "credit exhausted",
    "credit balance is 0",
    "credit balance: 0",
    "credits are used up",
    "insufficient credits",
    "insufficient credit",
    "out of credits",
    "recharge your fastmoss",
    "fastmoss 余额不足",
    "fastmoss余额不足",
    "额度不足",
    "积分不足",
    "余额为 0",
    "余额为0",
    "请充值",
)


def fastmoss_user_action_reason(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str).lower()
    except (TypeError, ValueError):
        text = str(value or "").lower()
    if any(marker in text for marker in FASTMOSS_CREDIT_EXHAUSTED_MARKERS):
        return (
            "FastMoss credits are exhausted or the credit balance is 0. "
            "Recharge FastMoss, then continue this task from its saved checkpoint."
        )
    return ""


def normalize_fastmoss_result(result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    data: dict[str, Any] = {}
    status = "error" if result.get("isError") else "ok"
    if isinstance(result.get("structuredContent"), dict):
        data.update(result["structuredContent"])
    content = result.get("content")
    if isinstance(content, list):
        text_items: list[str] = []
        parsed_items: list[Any] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "")
            if not text:
                continue
            text_items.append(text)
            try:
                parsed_items.append(json.loads(text))
            except json.JSONDecodeError:
                pass
        if parsed_items:
            if len(parsed_items) == 1 and isinstance(parsed_items[0], dict):
                data.update(parsed_items[0])
            else:
                data["parsed_content"] = parsed_items[0] if len(parsed_items) == 1 else parsed_items
        elif text_items:
            data["text"] = text_items
    elif result:
        data.update({key: value for key, value in result.items() if key not in {"content", "isError"}})
    if not data:
        data["raw"] = result
    if status == "ok":
        if fastmoss_user_action_reason(data):
            status = "needs_user_action"
        elif fastmoss_data_is_empty(data):
            status = "empty"
    return status, data


def summarize_fastmoss_data(agent_tool_name: str, data: dict[str, Any]) -> str:
    if fastmoss_data_is_empty(data):
        return "FastMoss returned no usable market records; treat this as missing data, not zero market activity."
    for key, value in data.items():
        if key in {"raw", "text", "parsed_content"}:
            continue
        if isinstance(value, list):
            return f"FastMoss returned {len(value)} item(s) in `{key}`."
        if isinstance(value, dict):
            return f"FastMoss returned structured evidence in `{key}`."
    return f"FastMoss MCP tool {agent_tool_name} completed."


def _execute_fastmoss_agent_tool_uncached(
    agent_tool_name: str,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    started = time.time()
    meta = get_fastmoss_tool_catalog().get(agent_tool_name) or {}
    label = str(meta.get("label") or agent_tool_name)
    try:
        input_error = _fastmoss_region_input_error(meta, input_payload)
        if input_error:
            return {
                "name": agent_tool_name,
                "label": label,
                "status": "error",
                "summary": input_error,
                "duration_ms": int((time.time() - started) * 1000),
                "input": input_payload,
                "data": {},
            }
        mcp_tool_name = str(meta.get("mcp_tool") or fastmoss_mcp_tool_name(agent_tool_name))
        raw = call_fastmoss_mcp_tool(mcp_tool_name, input_payload)
        status, data = normalize_fastmoss_result(raw)
        user_action_reason = fastmoss_user_action_reason(data)
        return {
            "name": agent_tool_name,
            "label": label,
            "status": status,
            "summary": user_action_reason or summarize_fastmoss_data(agent_tool_name, data),
            "duration_ms": int((time.time() - started) * 1000),
            "input": input_payload,
            "data": data,
        }
    except (FastMossMcpAuthError, FastMossMcpCreditsError) as exc:
        return {
            "name": agent_tool_name,
            "label": label,
            "status": "needs_user_action",
            "summary": str(exc),
            "duration_ms": int((time.time() - started) * 1000),
            "input": input_payload,
            "data": {},
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": agent_tool_name,
            "label": label,
            "status": "error",
            "summary": _safe_remote_message(exc),
            "duration_ms": int((time.time() - started) * 1000),
            "input": input_payload,
            "data": {},
        }


def execute_fastmoss_agent_tool(
    agent_tool_name: str,
    input_payload: dict[str, Any],
    *,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    result = execute_with_mcp_result_cache(
        "fastmoss",
        agent_tool_name,
        input_payload,
        lambda: _execute_fastmoss_agent_tool_uncached(agent_tool_name, input_payload),
        bypass_cache=bypass_cache,
    )
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if str(result.get("status") or "") in {"ok", "partial_ok"} and fastmoss_data_is_empty(data):
        result = {
            **result,
            "status": "empty",
            "summary": (
                "MCP cache hit. " if (result.get("cache") or {}).get("hit") else ""
            ) + "FastMoss returned no usable market records; treat this as missing data, not zero market activity.",
        }
    return result

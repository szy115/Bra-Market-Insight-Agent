from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Any

SIF_AGENT_TOOL_PREFIX = "sif_"
SIF_SCHEMA_URL = os.getenv("SIF_MCP_SCHEMA_URL", "https://mcp.sif.com/mcp-api/tool-schema.json")
SIF_MCP_URL = os.getenv("SIF_MCP_URL", "https://mcp.sif.com/mcp")

DEFAULT_SIF_AGENT_TOOLS = {
    "market_get_keyword_demand",
    "market_get_keyword_history",
    "market_get_keyword_root_trend",
    "market_get_keyword_competition",
    "market_get_asin_keyword_signals",
    "ops_get_asin_sales_list",
    "ops_get_asin_sales_trend",
}


class SifMcpError(RuntimeError):
    pass


class SifMcpAuthError(SifMcpError):
    pass


def compact_text(value: Any, limit: int = 420) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def is_sif_agent_tool(tool_name: str) -> bool:
    return tool_name.startswith(SIF_AGENT_TOOL_PREFIX)


def sif_mcp_tool_name(agent_tool_name: str) -> str:
    return agent_tool_name[len(SIF_AGENT_TOOL_PREFIX):] if is_sif_agent_tool(agent_tool_name) else agent_tool_name


def sif_agent_tool_name(mcp_tool_name: str) -> str:
    return f"{SIF_AGENT_TOOL_PREFIX}{mcp_tool_name}"


def sif_enabled_tool_names() -> set[str]:
    configured = os.getenv("SIF_MCP_TOOLS", "").strip()
    if not configured:
        return set(DEFAULT_SIF_AGENT_TOOLS)
    if configured.lower() in {"*", "all"}:
        return {"*"}
    return {item.strip() for item in configured.split(",") if item.strip()}


def _request_json(url: str, *, timeout: int = 10) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "InsightAgent/0.1"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


@lru_cache(maxsize=1)
def fetch_sif_tool_schema() -> list[dict[str, Any]]:
    try:
        data = _request_json(SIF_SCHEMA_URL)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def build_sif_tool_catalog(schema_tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    enabled = sif_enabled_tool_names()
    include_all = "*" in enabled
    catalog: dict[str, dict[str, Any]] = {}
    for tool in schema_tools:
        if not isinstance(tool, dict):
            continue
        mcp_name = str(tool.get("name") or "").strip()
        if not mcp_name or mcp_name == "ping":
            continue
        if not include_all and mcp_name not in enabled:
            continue
        input_schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {"type": "object", "properties": {}}
        agent_name = sif_agent_tool_name(mcp_name)
        catalog[agent_name] = {
            "label": f"Sif: {mcp_name}",
            "description": compact_text(tool.get("description"), 520),
            "input_schema": input_schema,
            "source": "sif_mcp",
            "mcp_tool": mcp_name,
            "auth_env_names": ["SIF_MCP_TOKEN", "SIF_API_KEY", "SIF_TOKEN"],
        }
    return catalog


@lru_cache(maxsize=1)
def get_sif_tool_catalog() -> dict[str, dict[str, Any]]:
    return build_sif_tool_catalog(fetch_sif_tool_schema())


def sif_country_from_payload(payload: dict[str, Any]) -> str:
    for key in ("country", "marketplace", "market", "locale_market"):
        value = str(payload.get(key) or "").strip().upper()
        if not value:
            continue
        if "US" in value or "美国" in value or "AMAZON" in value:
            return "US"
        if value in {"UK", "DE", "CA", "JP", "FR", "ES", "IT", "MX", "AU", "AE", "BR", "SA"}:
            return value
    return "US"


def _previous_complete_month_start(value: dt.date | None = None) -> str:
    current = value or dt.date.today()
    first_day_this_month = current.replace(day=1)
    previous_month = first_day_this_month - dt.timedelta(days=1)
    return previous_month.replace(day=1).strftime("%Y-%m-%d")


def _latest_sunday(value: dt.date | None = None) -> str:
    current = value or dt.date.today()
    days_since_sunday = (current.weekday() + 1) % 7
    return (current - dt.timedelta(days=days_since_sunday)).strftime("%Y-%m-%d")


def build_sif_input_payload(agent_tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
    meta = get_sif_tool_catalog().get(agent_tool_name) or {}
    schema = meta.get("input_schema") if isinstance(meta.get("input_schema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    allowed_keys = set(properties.keys())
    output: dict[str, Any] = {}
    for key in allowed_keys:
        value = payload.get(key)
        if value is None or value == "":
            continue
        output[key] = value
    if "country" in allowed_keys and not output.get("country"):
        output["country"] = sif_country_from_payload(payload)
    if "granularity" in allowed_keys and not output.get("granularity"):
        output["granularity"] = "week"
    if "keyword" in allowed_keys and not output.get("keyword"):
        output["keyword"] = str(payload.get("keyword") or payload.get("category") or category)
    if "keywords" in allowed_keys and not output.get("keywords"):
        keywords = payload.get("keywords")
        if isinstance(keywords, str):
            output["keywords"] = [keywords]
        elif isinstance(keywords, list) and keywords:
            output["keywords"] = keywords
        else:
            output["keywords"] = [str(payload.get("keyword") or payload.get("category") or category)]
    if "asins" in allowed_keys and isinstance(output.get("asins"), str):
        output["asins"] = [output["asins"]]
    if agent_tool_name == "sif_ops_get_asin_sales_list" and str(payload.get("skillId") or "") == "hot_product_pain_analysis":
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        reviewed_asins = params.get("reviewed_product_asins") if isinstance(params.get("reviewed_product_asins"), list) else []
        reviewed_asins = [
            str(asin).strip().upper()
            for asin in reviewed_asins
            if str(asin).strip()
        ]
        if reviewed_asins and "asins" in allowed_keys:
            output["asins"] = list(dict.fromkeys(reviewed_asins))
        defaults = {
            "dimension": "asin",
            "sortBy": "boughtInPastMonth",
            "desc": True,
            "pageNum": 1,
            "pageSize": min(100, max(20, len(reviewed_asins))),
            "timePieceType": "latelyDay",
            "timePieceValue": "30",
        }
        for key, value in defaults.items():
            if key in allowed_keys:
                output[key] = value
    if "time_type" in allowed_keys and "time_value" in allowed_keys and output.get("time_type") and not output.get("time_value"):
        time_type = str(output.get("time_type") or "").strip().lower()
        if time_type == "month":
            output["time_value"] = _previous_complete_month_start()
        elif time_type == "week":
            output["time_value"] = _latest_sunday()
    return output


def _auth_headers() -> dict[str, str]:
    token = (
        os.getenv("SIF_MCP_TOKEN")
        or os.getenv("SIF_API_KEY")
        or os.getenv("SIF_TOKEN")
        or ""
    ).strip()
    if not token:
        raise SifMcpAuthError(
            "Sif MCP requires authentication. Set SIF_MCP_TOKEN or SIF_API_KEY in the environment."
        )
    header_name = os.getenv("SIF_MCP_AUTH_HEADER", "Authorization").strip() or "Authorization"
    if header_name.lower() == "authorization" and not token.lower().startswith(("bearer ", "basic ")):
        scheme = os.getenv("SIF_MCP_AUTH_SCHEME", "Bearer").strip() or "Bearer"
        token = f"{scheme} {token}"
    return {header_name: token}


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


def _post_json_rpc(method: str, params: dict[str, Any], request_id: int, session_id: str | None = None) -> tuple[dict[str, Any], str | None]:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "User-Agent": "InsightAgent/0.1",
        **_auth_headers(),
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    request = urllib.request.Request(SIF_MCP_URL, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8", errors="replace")
            next_session = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id") or session_id
            return _parse_sse_or_json_response(raw), next_session
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        if exc.code in {401, 403}:
            raise SifMcpAuthError(f"Sif MCP authorization failed ({exc.code}). {message}") from exc
        raise SifMcpError(f"Sif MCP HTTP {exc.code}: {message}") from exc


def call_sif_mcp_tool(mcp_tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    init, session_id = _post_json_rpc(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "insight-agent", "version": "0.1"},
        },
        1,
    )
    if init.get("error"):
        raise SifMcpError(json.dumps(init["error"], ensure_ascii=False))
    response, _ = _post_json_rpc(
        "tools/call",
        {"name": mcp_tool_name, "arguments": arguments},
        2,
        session_id,
    )
    if response.get("error"):
        raise SifMcpError(json.dumps(response["error"], ensure_ascii=False))
    result = response.get("result")
    return result if isinstance(result, dict) else {"result": result}


def normalize_sif_result(result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    data: dict[str, Any] = {}
    status = "ok"
    if result.get("isError"):
        status = "error"
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
            if text:
                text_items.append(text)
                try:
                    parsed_items.append(json.loads(text))
                except json.JSONDecodeError:
                    pass
        if parsed_items:
            if isinstance(parsed_items[0], dict):
                data.update(parsed_items[0])
            else:
                data["parsed_content"] = parsed_items[0] if len(parsed_items) == 1 else parsed_items
        elif text_items:
            data["text"] = text_items
    elif result:
        data.update({key: value for key, value in result.items() if key not in {"content", "isError"}})
    if not data:
        data["raw"] = result
    return status, data


def summarize_sif_data(agent_tool_name: str, data: dict[str, Any]) -> str:
    footer = data.get("render_footer")
    if isinstance(data.get("keywords"), list):
        return f"Sif returned keyword evidence for {len(data['keywords'])} keyword(s)."
    if isinstance(data.get("trend"), list):
        return f"Sif returned {len(data['trend'])} trend data point(s)."
    if isinstance(data.get("asins"), list):
        return f"Sif returned ASIN evidence for {len(data['asins'])} ASIN(s)."
    if isinstance(footer, str) and footer.strip():
        return "Sif MCP returned evidence with verification footer."
    return f"Sif MCP tool {agent_tool_name} completed."


def execute_sif_agent_tool(agent_tool_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    catalog = get_sif_tool_catalog()
    meta = catalog.get(agent_tool_name) or {}
    label = str(meta.get("label") or agent_tool_name)
    try:
        mcp_tool_name = str(meta.get("mcp_tool") or sif_mcp_tool_name(agent_tool_name))
        raw = call_sif_mcp_tool(mcp_tool_name, input_payload)
        status, data = normalize_sif_result(raw)
        return {
            "name": agent_tool_name,
            "label": label,
            "status": status,
            "summary": summarize_sif_data(agent_tool_name, data),
            "duration_ms": int((time.time() - started) * 1000),
            "input": input_payload,
            "data": data,
        }
    except SifMcpAuthError as exc:
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
            "summary": str(exc),
            "duration_ms": int((time.time() - started) * 1000),
            "input": input_payload,
            "data": {},
        }

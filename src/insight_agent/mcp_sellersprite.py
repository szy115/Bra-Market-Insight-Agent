from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import hashlib
from functools import lru_cache
from typing import Any


SELLERSPRITE_AGENT_TOOL_PREFIX = "sellersprite_"
SELLERSPRITE_MCP_URL = os.getenv("SELLERSPRITE_MCP_URL", "https://mcp.sellersprite.com/mcp")
SELLERSPRITE_AUTH_ENV_NAMES = ["SELLERSPRITE_MCP_SECRET_KEY", "SELLERSPRITE_SECRET_KEY", "SELLERSPRITE_API_KEY"]


class SellerSpriteMcpError(RuntimeError):
    pass


class SellerSpriteMcpAuthError(SellerSpriteMcpError):
    pass


def compact_text(value: Any, limit: int = 520) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def is_sellersprite_agent_tool(tool_name: str) -> bool:
    return tool_name.startswith(SELLERSPRITE_AGENT_TOOL_PREFIX)


def sellersprite_mcp_tool_name(agent_tool_name: str) -> str:
    if is_sellersprite_agent_tool(agent_tool_name):
        return agent_tool_name[len(SELLERSPRITE_AGENT_TOOL_PREFIX):]
    return agent_tool_name


def sellersprite_agent_tool_name(mcp_tool_name: str) -> str:
    normalized = str(mcp_tool_name or "").strip()
    return f"{SELLERSPRITE_AGENT_TOOL_PREFIX}{normalized}"


def sellersprite_enabled_tool_names() -> set[str]:
    configured = os.getenv("SELLERSPRITE_MCP_TOOLS", "").strip()
    if not configured:
        return {"*"}
    if configured.lower() in {"*", "all"}:
        return {"*"}
    return {item.strip() for item in configured.split(",") if item.strip()}


def sellersprite_secret_key() -> str:
    for env_name in SELLERSPRITE_AUTH_ENV_NAMES:
        value = os.getenv(env_name, "").strip()
        if value:
            return value
    return ""


def _auth_headers() -> dict[str, str]:
    secret = sellersprite_secret_key()
    if not secret:
        raise SellerSpriteMcpAuthError(
            "SellerSprite MCP requires authentication. Set SELLERSPRITE_MCP_SECRET_KEY in the environment."
        )
    header_name = os.getenv("SELLERSPRITE_MCP_AUTH_HEADER", "secret-key").strip() or "secret-key"
    return {header_name: secret}


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
        **_auth_headers(),
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    request = urllib.request.Request(SELLERSPRITE_MCP_URL, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            next_session = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id") or session_id
            return _parse_sse_or_json_response(raw), next_session
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        if exc.code in {401, 403}:
            raise SellerSpriteMcpAuthError(f"SellerSprite MCP authorization failed ({exc.code}). {message}") from exc
        raise SellerSpriteMcpError(f"SellerSprite MCP HTTP {exc.code}: {message}") from exc


def _post_json_rpc_notification(method: str, params: dict[str, Any], session_id: str | None = None) -> None:
    body = json.dumps(
        {"jsonrpc": "2.0", "method": method, "params": params},
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
    request = urllib.request.Request(SELLERSPRITE_MCP_URL, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


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
        raise SellerSpriteMcpError(json.dumps(init["error"], ensure_ascii=False))
    try:
        _post_json_rpc_notification("notifications/initialized", {}, session_id)
    except Exception:
        pass
    return session_id


def call_sellersprite_mcp_method(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    session_id = _initialize_session()
    response, _ = _post_json_rpc(method, params or {}, 2, session_id)
    if response.get("error"):
        raise SellerSpriteMcpError(json.dumps(response["error"], ensure_ascii=False))
    result = response.get("result")
    return result if isinstance(result, dict) else {"result": result}


def fetch_sellersprite_tool_schema() -> list[dict[str, Any]]:
    if not sellersprite_secret_key():
        return []
    try:
        result = call_sellersprite_mcp_method("tools/list", {})
    except Exception:
        return []
    tools = result.get("tools")
    return tools if isinstance(tools, list) else []


def build_sellersprite_tool_catalog(schema_tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    enabled = sellersprite_enabled_tool_names()
    include_all = "*" in enabled
    catalog: dict[str, dict[str, Any]] = {}
    for tool in schema_tools:
        if not isinstance(tool, dict):
            continue
        mcp_name = str(tool.get("name") or "").strip()
        if not mcp_name:
            continue
        if not include_all and mcp_name not in enabled:
            continue
        input_schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {"type": "object", "properties": {}}
        agent_name = sellersprite_agent_tool_name(mcp_name)
        catalog[agent_name] = {
            "label": f"SellerSprite: {mcp_name}",
            "description": compact_text(tool.get("description"), 720),
            "input_schema": input_schema,
            "source": "sellersprite_mcp",
            "mcp_tool": mcp_name,
            "auth_env_names": SELLERSPRITE_AUTH_ENV_NAMES,
        }
    return catalog


@lru_cache(maxsize=4)
def _get_sellersprite_tool_catalog_for_secret(secret_fingerprint: str) -> dict[str, dict[str, Any]]:
    if not secret_fingerprint:
        return {}
    return build_sellersprite_tool_catalog(fetch_sellersprite_tool_schema())


def get_sellersprite_tool_catalog() -> dict[str, dict[str, Any]]:
    secret = sellersprite_secret_key()
    if not secret:
        return {}
    fingerprint = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return _get_sellersprite_tool_catalog_for_secret(fingerprint)


def _market_from_payload(payload: dict[str, Any]) -> str:
    for key in ("marketplace", "market", "country", "locale_market"):
        value = str(payload.get(key) or "").strip()
        if value:
            if "美国" in value or "US" in value.upper() or "AMAZON" in value.upper():
                return "US"
            return value
    return "US"


def build_sellersprite_input_payload(agent_tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
    meta = get_sellersprite_tool_catalog().get(agent_tool_name) or {}
    schema = meta.get("input_schema") if isinstance(meta.get("input_schema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    allowed_keys = set(properties.keys())
    output: dict[str, Any] = {}
    for key in allowed_keys:
        value = payload.get(key)
        if value is None or value == "":
            continue
        output[key] = value

    category_value = str(payload.get("keyword") or payload.get("category") or category or "").strip()
    market_value = _market_from_payload(payload)
    asin_value = str(payload.get("asin") or payload.get("product_asin") or payload.get("ASIN") or "").strip()

    for key in ("keyword", "query", "searchTerm", "search_term"):
        if key in allowed_keys and not output.get(key) and category_value:
            output[key] = category_value
    if "keywords" in allowed_keys and not output.get("keywords") and category_value:
        output["keywords"] = [category_value]
    for key in ("marketplace", "market", "country", "site", "locale"):
        if key in allowed_keys and not output.get(key):
            output[key] = market_value
    for key in ("asin", "product_asin", "ASIN"):
        if key in allowed_keys and not output.get(key) and asin_value:
            output[key] = asin_value
    if "asins" in allowed_keys and not output.get("asins") and asin_value:
        output["asins"] = [asin_value]
    return output


def call_sellersprite_mcp_tool(mcp_tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    session_id = _initialize_session()
    response, _ = _post_json_rpc(
        "tools/call",
        {"name": mcp_tool_name, "arguments": arguments},
        2,
        session_id,
    )
    if response.get("error"):
        raise SellerSpriteMcpError(json.dumps(response["error"], ensure_ascii=False))
    result = response.get("result")
    return result if isinstance(result, dict) else {"result": result}


def normalize_sellersprite_result(result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    data: dict[str, Any] = {"raw": result}
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
        if text_items:
            data["text"] = text_items
        if parsed_items:
            data["parsed_content"] = parsed_items[0] if len(parsed_items) == 1 else parsed_items
            if isinstance(parsed_items[0], dict):
                data.update(parsed_items[0])
    elif result:
        data.update(result)
    return status, data


def summarize_sellersprite_data(agent_tool_name: str, data: dict[str, Any]) -> str:
    for key, value in data.items():
        if key in {"raw", "text", "parsed_content"}:
            continue
        if isinstance(value, list):
            return f"SellerSprite returned {len(value)} item(s) in `{key}`."
        if isinstance(value, dict):
            return f"SellerSprite returned structured evidence in `{key}`."
    return f"SellerSprite MCP tool {agent_tool_name} completed."


def execute_sellersprite_agent_tool(agent_tool_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    catalog = get_sellersprite_tool_catalog()
    meta = catalog.get(agent_tool_name) or {}
    label = str(meta.get("label") or agent_tool_name)
    try:
        if not sellersprite_secret_key():
            raise SellerSpriteMcpAuthError(
                "SellerSprite MCP requires authentication. Set SELLERSPRITE_MCP_SECRET_KEY in the environment."
            )
        mcp_tool_name = str(meta.get("mcp_tool") or sellersprite_mcp_tool_name(agent_tool_name))
        raw = call_sellersprite_mcp_tool(mcp_tool_name, input_payload)
        status, data = normalize_sellersprite_result(raw)
        return {
            "name": agent_tool_name,
            "label": label,
            "status": status,
            "summary": summarize_sellersprite_data(agent_tool_name, data),
            "duration_ms": int((time.time() - started) * 1000),
            "input": input_payload,
            "data": data,
        }
    except SellerSpriteMcpAuthError as exc:
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

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Any

from .mcp_result_cache import (
    cacheable_mcp_result,
    execute_with_mcp_result_cache,
    mcp_result_cache_lock,
    read_mcp_result_cache,
    with_mcp_cache_metadata,
    write_mcp_result_cache,
)

SELLERSPRITE_AGENT_TOOL_PREFIX = "sellersprite_"
SELLERSPRITE_MCP_URL = os.getenv("SELLERSPRITE_MCP_URL", "https://mcp.sellersprite.com/mcp")
SELLERSPRITE_AUTH_ENV_NAMES = ["SELLERSPRITE_MCP_SECRET_KEY", "SELLERSPRITE_SECRET_KEY", "SELLERSPRITE_API_KEY"]
INSIGHT_CONTEXT_KEY = "__insight_context"
HOT_PRODUCT_SKILL_ID = "hot_product_pain_analysis"
WEEKLY_MARKET_SKILL_ID = "weekly_market_insight"
PRODUCT_DESIGN_SKILL_ID = "product_design_research"
COMPETITOR_DEEP_DIVE_SKILL_ID = "competitor_product_deep_dive"
CATEGORY_REVIEW_SKILL_IDS = {HOT_PRODUCT_SKILL_ID, PRODUCT_DESIGN_SKILL_ID, WEEKLY_MARKET_SKILL_ID}
MAX_EXHAUSTIVE_REVIEW_PAGES = 100
MAX_EXHAUSTIVE_REVIEW_TARGET = 500
SELLERSPRITE_REVIEW_ASIN_CACHE_TOOL = "sellersprite_review_by_asin_v1"
MARKET_RESEARCH_GENERIC_QUERY_TOKENS = {
    "a",
    "an",
    "amazon",
    "and",
    "bra",
    "bras",
    "female",
    "for",
    "in",
    "ladies",
    "lady",
    "male",
    "man",
    "men",
    "mens",
    "of",
    "on",
    "or",
    "product",
    "products",
    "s",
    "the",
    "us",
    "with",
    "woman",
    "women",
    "womens",
}

PRODUCT_MATCH_GENERIC_TOKENS = {
    "a",
    "amazon",
    "and",
    "bra",
    "bras",
    "for",
    "the",
    "woman",
    "women",
    "womens",
}


class SellerSpriteMcpError(RuntimeError):
    pass


class SellerSpriteMcpAuthError(SellerSpriteMcpError):
    pass


def compact_text(value: Any, limit: int = 520) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def _payload_value(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value is not None and value != "":
        return value
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    return params.get(key)


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


def _review_time_bounds(value: Any, now: dt.datetime | None = None) -> tuple[int, int] | None:
    normalized = str(value or "").strip().lower()
    if not normalized or normalized == "all":
        return None
    day_aliases = {"day": 1, "week": 7, "month": 30, "year": 365}
    days = day_aliases.get(normalized)
    if days is None:
        match = re.fullmatch(r"(\d{1,4})d", normalized)
        if not match:
            return None
        days = max(1, int(match.group(1)))
    end = now or dt.datetime.now(dt.UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=dt.UTC)
    start = end - dt.timedelta(days=days)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _sellersprite_mcp_arguments(input_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in input_payload.items()
        if key != INSIGHT_CONTEXT_KEY
    }


def _sellersprite_cache_params(input_payload: dict[str, Any]) -> dict[str, Any]:
    params = dict(input_payload)
    insight_context = (
        dict(params.get(INSIGHT_CONTEXT_KEY))
        if isinstance(params.get(INSIGHT_CONTEXT_KEY), dict)
        else {}
    )
    if insight_context.get("cache_time_range"):
        params.pop("startTimestamp", None)
        params.pop("endTimestamp", None)
    return params


def _sellersprite_review_asin_cache_params(input_payload: dict[str, Any]) -> dict[str, Any]:
    public_input = _sellersprite_mcp_arguments(input_payload)
    return {
        "marketplace": _market_from_payload(public_input),
        "asin": str(public_input.get("asin") or "").strip().upper(),
    }


def _cached_exhaustive_review_satisfies(
    result: dict[str, Any],
    input_payload: dict[str, Any],
) -> bool:
    if str(result.get("status") or "") not in {"ok", "partial_ok"}:
        return False
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    sampling = data.get("review_sampling") if isinstance(data.get("review_sampling"), dict) else {}
    if sampling.get("mode") != "exhaustive_balanced_pagination":
        return False
    buckets = sampling.get("buckets") if isinstance(sampling.get("buckets"), dict) else {}
    if not all(isinstance(buckets.get(name), dict) for name in ("low_star", "high_star")):
        return False
    insight_context = input_payload.get(INSIGHT_CONTEXT_KEY)
    requested_target = _bounded_int(
        insight_context.get("review_target") if isinstance(insight_context, dict) else None,
        MAX_EXHAUSTIVE_REVIEW_TARGET,
        10,
        MAX_EXHAUSTIVE_REVIEW_TARGET,
    )
    cached_target = _bounded_int(
        sampling.get("review_target_per_bucket"),
        MAX_EXHAUSTIVE_REVIEW_TARGET,
        10,
        MAX_EXHAUSTIVE_REVIEW_TARGET,
    )
    for bucket in buckets.values():
        if bucket.get("complete"):
            continue
        if str(bucket.get("stop_reason") or "") == "page_error":
            return False
        if cached_target < requested_target:
            return False
    return True


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


def _latest_saturday(value: dt.date | None = None) -> str:
    current = value or dt.date.today()
    days_since_saturday = (current.weekday() - 5) % 7
    saturday = current - dt.timedelta(days=days_since_saturday)
    return saturday.strftime("%Y%m%d")


def _previous_complete_week_saturday(value: dt.date | None = None) -> str:
    latest_saturday = dt.datetime.strptime(_latest_saturday(value), "%Y%m%d").date()
    return (latest_saturday - dt.timedelta(days=7)).strftime("%Y%m%d")


def _request_month(value: dt.date | None = None) -> str:
    current = value or dt.date.today()
    first_day_this_month = current.replace(day=1)
    previous_month = first_day_this_month - dt.timedelta(days=1)
    return previous_month.strftime("%Y%m")


def _normalize_month_value(value: Any) -> str:
    compact = "".join(str(value or "").strip().split())
    match = re.fullmatch(r"((?:19|20)\d{2})(?:[-/.年]?)(0?[1-9]|1[0-2])月?", compact)
    if not match:
        return ""
    return f"{match.group(1)}{int(match.group(2)):02d}"


def _months_mentioned_in_prompt(prompt: Any) -> list[str]:
    compact = "".join(str(prompt or "").split())
    if not compact:
        return []
    seen: set[str] = set()
    months: list[str] = []
    for pattern in (
        r"(?<!\d)((?:19|20)\d{2})(0[1-9]|1[0-2])(?!\d)",
        r"(?<!\d)((?:19|20)\d{2})[-/.年](0?[1-9]|1[0-2])月?",
    ):
        for match in re.finditer(pattern, compact):
            month = f"{match.group(1)}{int(match.group(2)):02d}"
            if month not in seen:
                seen.add(month)
                months.append(month)
    return months


def _resolved_request_month(payload: dict[str, Any], requested_value: Any = None) -> str:
    prompt_months = _months_mentioned_in_prompt(payload.get("prompt"))
    requested_month = _normalize_month_value(requested_value)
    if prompt_months:
        if requested_month in prompt_months:
            return requested_month
        return prompt_months[-1]
    return _request_month()


def _new_product_months(payload: dict[str, Any]) -> int:
    raw = str(payload.get("new_product_window") or payload.get("newProduct") or "").strip().lower()
    if raw.endswith("d"):
        try:
            return max(1, round(int(raw[:-1]) / 30))
        except ValueError:
            return 6
    if raw.endswith("m"):
        try:
            return max(1, int(raw[:-1]))
        except ValueError:
            return 6
    try:
        return max(1, int(raw))
    except ValueError:
        return 6


def _node_id_path_from_payload(payload: dict[str, Any]) -> str:
    for key in ("nodeIdPath", "category_node_id", "categoryNodeId", "node_id_path", "departmentNodeIdPath"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _schema_keyword_value(property_schema: dict[str, Any], category_value: str) -> str | list[str]:
    return [category_value] if property_schema.get("type") == "array" else category_value


_NODE_MATCH_GENERIC_TOKENS = {
    "amazon",
    "bra",
    "category",
    "clothing",
    "jewelry",
    "men",
    "product",
    "shoe",
    "women",
}

_PRODUCT_NODE_BRA_TERMS = {
    "bra",
    "bralette",
    "minimizer",
}

_PRODUCT_NODE_OFFICIAL_BRA_ALIASES = {
    "adhesive bra": ("Adhesive Bras",),
    "mastectomy bra": ("Mastectomy Bras",),
    "maternity bra": ("Nursing & Maternity Bras",),
    "minimizer": ("Minimizers",),
    "minimizer bra": ("Minimizers",),
    "nursing bra": ("Nursing & Maternity Bras",),
    "sport bra": ("Sports Bras",),
}

_PRODUCT_NODE_EVERYDAY_BRA_PROXY_TERMS = {
    "back smoothing",
    "convertible",
    "full coverage",
    "lightly lined",
    "molded",
    "push up",
    "seamless",
    "side support",
    "spacer",
    "strapless",
    "t shirt",
    "underwire",
    "unlined",
    "wireless",
}


def _node_match_tokens(value: Any) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", str(value or "").lower().replace("'s", ""))
    normalized: list[str] = []
    for token in tokens:
        if len(token) > 3 and token.endswith("s") and not token.endswith(("is", "ss", "us")):
            token = token[:-1]
        normalized.append(token)
    return normalized


def _normalized_node_query(value: Any) -> str:
    return " ".join(_node_match_tokens(value))


def _product_node_alias_key(value: Any) -> str:
    noise = {"amazon", "female", "for", "lady", "us", "woman", "women", "womens"}
    return " ".join(token for token in _node_match_tokens(value) if token not in noise)


def _is_bra_node_query(query: str) -> bool:
    normalized = _normalized_node_query(query)
    tokens = set(normalized.split())
    return bool(tokens & _PRODUCT_NODE_BRA_TERMS) or _product_node_alias_key(query) in _PRODUCT_NODE_OFFICIAL_BRA_ALIASES


def _node_context_score(query: str, node_label_path: str) -> tuple[float, bool]:
    if not _is_bra_node_query(query):
        return 0.0, True

    query_tokens = set(_node_match_tokens(query))
    path_tokens = set(_node_match_tokens(node_label_path))
    if not path_tokens & {"bra", "bralette"}:
        return -1.0, False

    normalized_path = str(node_label_path or "").casefold()
    score = 0.0
    asks_for_girls = bool(query_tokens & {"girl", "junior", "teen"})
    asks_for_maternity = bool(query_tokens & {"maternity", "nursing"})
    if asks_for_girls:
        score += 0.20 if ":girls:" in f":{normalized_path}:" else -0.18
    elif asks_for_maternity:
        score += 0.20 if ":maternity:" in f":{normalized_path}:" else -0.12
    else:
        if ":women:" in f":{normalized_path}:":
            score += 0.18
        if ":girls:" in f":{normalized_path}:" or ":men:" in f":{normalized_path}:":
            score -= 0.18

    if "lingerie" in normalized_path:
        score += 0.04
    if "novelty" in normalized_path or "exotic apparel" in normalized_path:
        score -= 0.28
    if "protective sports bras" in normalized_path and "protective" not in query_tokens:
        score -= 0.16
    return score, True


def _node_match_score(query: str, node_id_path: str, node_label_path: str) -> float:
    query_text = str(query or "").strip()
    if not query_text:
        return 0.0
    if query_text.isdigit() and node_id_path.split(":")[-1] == query_text:
        return 1.0

    leaf_label = re.split(r"[:>/|]", node_label_path)[-1].strip()
    query_tokens = set(_node_match_tokens(query_text))
    leaf_tokens = set(_node_match_tokens(leaf_label))
    if not query_tokens or not leaf_tokens:
        return 0.0
    if query_tokens == leaf_tokens:
        return 1.0

    query_specific = query_tokens - _NODE_MATCH_GENERIC_TOKENS
    leaf_specific = leaf_tokens - _NODE_MATCH_GENERIC_TOKENS
    if leaf_specific and leaf_specific.issubset(query_specific):
        if len(node_id_path.split(":")) <= 2 and len(query_tokens) > 1:
            return 0.0
        return 0.94
    if query_specific and query_specific.issubset(leaf_specific):
        return 0.92
    union = query_specific | leaf_specific
    overlap = query_specific & leaf_specific
    if union and len(overlap) / len(union) >= 0.75:
        return 0.88
    return 0.0


def _collect_product_node_candidates(value: Any, candidates: dict[str, dict[str, Any]], *, depth: int = 0) -> None:
    if depth > 10:
        return
    if isinstance(value, dict):
        node_id_path = str(value.get("nodeIdPath") or "").strip()
        node_label_path = str(value.get("nodeLabelPath") or "").strip()
        if node_id_path and node_label_path:
            candidate = candidates.setdefault(
                node_id_path,
                {
                    "nodeIdPath": node_id_path,
                    "nodeLabelPath": node_label_path,
                },
            )
            for key in ("nodeId", "products", "productCount", "count"):
                if value.get(key) not in (None, ""):
                    candidate[key] = value.get(key)
        for child in value.values():
            _collect_product_node_candidates(child, candidates, depth=depth + 1)
        return
    if isinstance(value, list):
        for child in value:
            _collect_product_node_candidates(child, candidates, depth=depth + 1)
        return
    if isinstance(value, str) and value.strip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return
        _collect_product_node_candidates(parsed, candidates, depth=depth + 1)


def resolve_sellersprite_product_node(
    data: dict[str, Any],
    query: str,
    *,
    context_query: str | None = None,
) -> dict[str, Any]:
    candidates_by_path: dict[str, dict[str, Any]] = {}
    _collect_product_node_candidates(data, candidates_by_path)
    candidates: list[dict[str, Any]] = []
    for candidate in candidates_by_path.values():
        scored = dict(candidate)
        scored["match_score"] = _node_match_score(
            query,
            str(candidate.get("nodeIdPath") or ""),
            str(candidate.get("nodeLabelPath") or ""),
        )
        context_score, context_eligible = _node_context_score(
            context_query or query,
            str(candidate.get("nodeLabelPath") or ""),
        )
        scored["context_score"] = round(context_score, 4)
        scored["selection_score"] = round(float(scored["match_score"]) + context_score, 4)
        scored["context_eligible"] = context_eligible
        candidates.append(scored)
    candidates.sort(
        key=lambda item: (
            -float(item.get("selection_score") or 0),
            -int(item.get("products") or 0),
            str(item.get("nodeLabelPath") or ""),
        )
    )

    high_confidence = [
        item
        for item in candidates
        if item.get("context_eligible") is not False and float(item.get("match_score") or 0) >= 0.88
    ]
    if len(high_confidence) == 1:
        selected = high_confidence[0]
        return {
            "status": "resolved",
            "query": query,
            "selected": selected,
            "candidates": candidates[:12],
        }
    if len(high_confidence) > 1:
        top = high_confidence[0]
        runner_up = high_confidence[1]
        score_gap = float(top.get("selection_score") or 0) - float(runner_up.get("selection_score") or 0)
        if score_gap >= 0.08:
            return {
                "status": "resolved",
                "query": query,
                "selected": top,
                "candidates": candidates[:12],
                "disambiguation": {
                    "method": "taxonomy_context",
                    "score_gap": round(score_gap, 4),
                },
            }
        return {
            "status": "ambiguous",
            "query": query,
            "selected": None,
            "candidates": candidates[:12],
        }
    return {
        "status": "no_match" if candidates else "empty",
        "query": query,
        "selected": None,
        "candidates": candidates[:12],
    }


def _build_sellersprite_request(
    request_schema: dict[str, Any],
    category: str,
    payload: dict[str, Any],
    *,
    agent_tool_name: str = "",
) -> dict[str, Any]:
    properties = request_schema.get("properties") if isinstance(request_schema.get("properties"), dict) else {}
    allowed_keys = set(properties.keys())
    request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    request: dict[str, Any] = {}
    for key in allowed_keys:
        value = request_payload.get(key) if isinstance(request_payload, dict) else None
        if value is None or value == "":
            value = payload.get(key)
        if value is not None and value != "":
            request[key] = value

    category_value = str(payload.get("keyword") or payload.get("category") or category or "").strip()
    market_value = _market_from_payload(payload)
    asin_value = str(payload.get("asin") or payload.get("product_asin") or payload.get("ASIN") or "").strip()
    node_id_path = _node_id_path_from_payload(payload)
    top_n = _payload_value(payload, "head_listing_count") or payload.get("topN") or payload.get("topNum") or 10

    if "marketplace" in allowed_keys and not request.get("marketplace"):
        request["marketplace"] = market_value
    elif "marketplace" in request:
        request["marketplace"] = _market_from_payload({"marketplace": request.get("marketplace")})
    if "country" in allowed_keys and not request.get("country"):
        request["country"] = market_value
    elif "country" in request:
        request["country"] = _market_from_payload({"country": request.get("country")})
    if "departmentKeyword" in allowed_keys and not request.get("departmentKeyword") and category_value:
        request["departmentKeyword"] = category_value
    if "includeKeywords" in allowed_keys and not request.get("includeKeywords") and category_value:
        request["includeKeywords"] = category_value
    if "keyword" in allowed_keys and not request.get("keyword") and category_value:
        request["keyword"] = category_value
    if "keywords" in allowed_keys and not request.get("keywords") and category_value:
        request["keywords"] = _schema_keyword_value(properties.get("keywords") or {}, category_value)
    if "asin" in allowed_keys and not request.get("asin") and asin_value:
        request["asin"] = asin_value
    if "asins" in allowed_keys and not request.get("asins") and asin_value:
        request["asins"] = [asin_value]
    if "nodeIdPath" in allowed_keys and not request.get("nodeIdPath") and node_id_path:
        request["nodeIdPath"] = node_id_path
    if "month" in allowed_keys:
        request["month"] = _resolved_request_month(payload, request.get("month"))
    if "date" in allowed_keys and not request.get("date"):
        request["date"] = _latest_saturday()
    if "newProduct" in allowed_keys and not request.get("newProduct"):
        request["newProduct"] = _new_product_months(payload)
    if "topN" in allowed_keys and not request.get("topN"):
        request["topN"] = top_n
    if "topNum" in allowed_keys and not request.get("topNum"):
        request["topNum"] = top_n
    if "page" in allowed_keys and not request.get("page"):
        request["page"] = 1
    if "size" in allowed_keys and not request.get("size"):
        request["size"] = payload.get("listing_sample_size") or payload.get("amazonLimit") or 100
    if agent_tool_name == "sellersprite_aba_research_weekly":
        if "date" in allowed_keys:
            request["date"] = _previous_complete_week_saturday()
        request.pop("departments", None)
        if "searchModel" in allowed_keys:
            request["searchModel"] = 1
        if "size" in allowed_keys:
            request["size"] = min(_bounded_int(request.get("size"), 20, 1, 100), 50)
    if agent_tool_name == "sellersprite_google_trend":
        if "googleProp" in allowed_keys and not request.get("googleProp"):
            request["googleProp"] = "web"
        if "monthly" in allowed_keys and (
            str(payload.get("skillId") or "") == WEEKLY_MARKET_SKILL_ID
            or request.get("monthly") is None
        ):
            request["monthly"] = True
    skill_id = str(payload.get("skillId") or "")
    if agent_tool_name == "sellersprite_market_product_concentration" and skill_id in CATEGORY_REVIEW_SKILL_IDS and "topN" in allowed_keys:
        head_count = _bounded_int(_payload_value(payload, "head_listing_count"), 10, 1, 50)
        large_pool_skill_ids = {PRODUCT_DESIGN_SKILL_ID, WEEKLY_MARKET_SKILL_ID}
        maximum = 100 if skill_id in large_pool_skill_ids else 50
        default_sample_size = 100 if skill_id in large_pool_skill_ids else 20
        listing_sample_size = _bounded_int(
            _payload_value(payload, "listing_sample_size"),
            default_sample_size,
            1,
            maximum,
        )
        buffered_count = min(maximum, max(listing_sample_size, head_count + 5, (head_count * 3 + 1) // 2))
        request["topN"] = buffered_count
    return request


def build_sellersprite_input_payload(agent_tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
    meta = get_sellersprite_tool_catalog().get(agent_tool_name) or {}
    schema = meta.get("input_schema") if isinstance(meta.get("input_schema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    allowed_keys = set(properties.keys())
    output: dict[str, Any] = {}
    if "request" in allowed_keys and isinstance(properties.get("request"), dict):
        request = _build_sellersprite_request(
            properties["request"],
            category,
            payload,
            agent_tool_name=agent_tool_name,
        )
        if agent_tool_name == "sellersprite_market_product_demand_trend":
            # This endpoint returns its own rolling series. Optional market filters
            # produce an empty payload for otherwise valid category nodes.
            for key in ("month", "newProduct", "topN"):
                request.pop(key, None)
        output["request"] = request
        if agent_tool_name == "sellersprite_market_product_concentration" and str(payload.get("skillId") or "") in CATEGORY_REVIEW_SKILL_IDS:
            output[INSIGHT_CONTEXT_KEY] = {
                "category": str(_payload_value(payload, "category") or category or "").strip(),
                "head_listing_count": _bounded_int(_payload_value(payload, "head_listing_count"), 10, 1, 50),
            }
        return output

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
        output["keywords"] = _schema_keyword_value(properties.get("keywords") or {}, category_value)
    for key in ("marketplace", "market", "country", "site", "locale"):
        if key in allowed_keys and not output.get(key):
            output[key] = market_value
        elif key in {"marketplace", "market", "country"} and key in allowed_keys and output.get(key):
            output[key] = _market_from_payload({key: output.get(key)})
    for key in ("asin", "product_asin", "ASIN"):
        if key in allowed_keys and not output.get(key) and asin_value:
            output[key] = asin_value
    if "asins" in allowed_keys and not output.get("asins") and asin_value:
        output["asins"] = [asin_value]
    if "month" in allowed_keys:
        output["month"] = _resolved_request_month(payload, output.get("month"))
    if agent_tool_name == "sellersprite_review":
        skill_id = str(payload.get("skillId") or "")
        balanced_category_review = skill_id in CATEGORY_REVIEW_SKILL_IDS
        exhaustive_competitor_review = skill_id == COMPETITOR_DEEP_DIVE_SKILL_ID
        review_context: dict[str, Any] = {}
        if balanced_category_review:
            output.pop("starList", None)
            output.pop("typeList", None)
        review_target = _bounded_int(
            _payload_value(payload, "review_sample_size"),
            MAX_EXHAUSTIVE_REVIEW_TARGET if exhaustive_competitor_review else 30,
            10,
            MAX_EXHAUSTIVE_REVIEW_TARGET if exhaustive_competitor_review else 100,
        )
        if "size" in allowed_keys:
            # SellerSprite may return fewer records than requested on one page.
            # Keep the public page-size request within the endpoint's normal range;
            # the single-ASIN deep-dive executor uses review_target across pages.
            output["size"] = min(review_target, 100)
        if "page" in allowed_keys and not output.get("page"):
            output["page"] = 1
        if exhaustive_competitor_review:
            # The deep-dive Skill's time_range belongs to Reddit VOC. Amazon
            # reviews intentionally use the provider's full available history.
            # One public tool call fans out into exhaustive low/high-star buckets
            # so the Evidence Contract can keep ASIN-level deduplication intact.
            output.pop("starList", None)
            output.pop("typeList", None)
            output.pop("startTimestamp", None)
            output.pop("endTimestamp", None)
            review_context["exhaustive_review"] = True
            review_context["review_target"] = review_target
        else:
            time_range = _payload_value(payload, "time_range") or payload.get("timeRange")
            bounds = _review_time_bounds(time_range)
            if bounds:
                start_timestamp, end_timestamp = bounds
                if "startTimestamp" in allowed_keys:
                    output["startTimestamp"] = start_timestamp
                if "endTimestamp" in allowed_keys:
                    output["endTimestamp"] = end_timestamp
                review_context["cache_time_range"] = str(time_range)
        if balanced_category_review:
            review_context["balanced_review"] = True
        if review_context:
            output[INSIGHT_CONTEXT_KEY] = review_context
    if agent_tool_name == "sellersprite_asin_detail" and category_value:
        output[INSIGHT_CONTEXT_KEY] = {
            "category": category_value,
            "resolve_category_node": str(payload.get("skillId") or "") in {
                WEEKLY_MARKET_SKILL_ID,
                PRODUCT_DESIGN_SKILL_ID,
            },
        }
    return output


def _missing_required_sellersprite_fields(meta: dict[str, Any], input_payload: dict[str, Any]) -> list[str]:
    schema = meta.get("input_schema") if isinstance(meta.get("input_schema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    missing: list[str] = []
    for key in schema.get("required") or []:
        value = input_payload.get(str(key))
        if value is None or value == "":
            missing.append(str(key))

    request_schema = properties.get("request") if isinstance(properties.get("request"), dict) else {}
    if request_schema:
        request_payload = input_payload.get("request") if isinstance(input_payload.get("request"), dict) else {}
        for key in request_schema.get("required") or []:
            value = request_payload.get(str(key))
            if value is None or value == "":
                missing.append(f"request.{key}")
    return list(dict.fromkeys(missing))


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


def summarize_sellersprite_data(agent_tool_name: str, data: dict[str, Any]) -> str:
    for key, value in data.items():
        if key in {"raw", "text", "parsed_content"}:
            continue
        if isinstance(value, list):
            return f"SellerSprite returned {len(value)} item(s) in `{key}`."
        if isinstance(value, dict):
            return f"SellerSprite returned structured evidence in `{key}`."
    return f"SellerSprite MCP tool {agent_tool_name} completed."


def _aba_weekly_date_error(data: dict[str, Any]) -> bool:
    serialized = json.dumps(data, ensure_ascii=False, default=str).casefold()
    return "日期参数错误" in serialized or "只能查询上一周" in serialized or (
        "error_param" in serialized and "date" in serialized
    )


def _previous_aba_date(value: Any) -> str:
    try:
        parsed = dt.datetime.strptime(str(value or ""), "%Y%m%d").date()
    except ValueError:
        return _previous_complete_week_saturday()
    return (parsed - dt.timedelta(days=7)).strftime("%Y%m%d")


def _sellersprite_items_container(data: dict[str, Any]) -> dict[str, Any]:
    candidates: list[Any] = [data.get("data")]
    parsed = data.get("parsed_content")
    if isinstance(parsed, dict):
        candidates.append(parsed.get("data"))
    for candidate in candidates:
        if isinstance(candidate, dict) and isinstance(candidate.get("items"), list):
            return candidate
    return {}


def _market_research_result_is_empty(data: dict[str, Any]) -> bool:
    container = _sellersprite_items_container(data)
    items = container.get("items") if isinstance(container.get("items"), list) else None
    if items is None or items:
        return False
    try:
        total = int(container.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    return total <= 0


def _market_research_keyword_candidates(keyword: str) -> list[str]:
    original = " ".join(str(keyword or "").split())
    if not original:
        return []
    candidates = [original]
    tokens = re.findall(r"[a-z0-9]+", original.casefold())
    core_tokens = [token for token in tokens if token not in MARKET_RESEARCH_GENERIC_QUERY_TOKENS]
    core_keyword = " ".join(core_tokens)
    if (
        core_keyword
        and core_keyword.casefold() != original.casefold()
        and any(len(token) >= 4 for token in core_tokens)
    ):
        candidates.append(core_keyword)
    return list(dict.fromkeys(candidates))


def _product_node_query_candidates(query: str) -> list[str]:
    return [item["query"] for item in _product_node_query_plan(query)]


def _product_node_query_plan(query: str) -> list[dict[str, str]]:
    original = " ".join(str(query or "").split())
    if not original:
        return []
    candidates: list[dict[str, str]] = [{"query": original, "mode": "requested"}]
    normalized = _normalized_node_query(original)
    alias_key = _product_node_alias_key(original)
    for alias in _PRODUCT_NODE_OFFICIAL_BRA_ALIASES.get(alias_key, ()):
        candidates.append({"query": alias, "mode": "official_alias"})

    tokens = re.findall(r"[a-z0-9]+", original.casefold())
    core_tokens = [token for token in tokens if token not in MARKET_RESEARCH_GENERIC_QUERY_TOKENS]
    core = " ".join(core_tokens)
    broad_core_terms = {"sport", "sports", "bra", "bras", "clothing", "men", "women"}
    if not _is_bra_node_query(original):
        if core and core.casefold() != original.casefold() and core.casefold() not in broad_core_terms:
            candidates.append({"query": core, "mode": "normalized_alias"})
        if len(core_tokens) == 1 and len(core_tokens[0]) >= 4 and not core_tokens[0].endswith("s"):
            candidates.append({"query": f"{core_tokens[0]}s".title(), "mode": "normalized_alias"})
    elif normalized.endswith(" bra") and alias_key not in _PRODUCT_NODE_OFFICIAL_BRA_ALIASES:
        plural_query = re.sub(r"\bbras?\b\s*$", "Bras", original, flags=re.IGNORECASE)
        candidates.append({"query": plural_query, "mode": "official_alias"})

    if _is_bra_node_query(original) and any(term in normalized for term in _PRODUCT_NODE_EVERYDAY_BRA_PROXY_TERMS):
        candidates.append({"query": "Everyday Bras", "mode": "proxy"})

    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate["query"].casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _market_research_attempt(keyword: str, status: str, data: dict[str, Any]) -> dict[str, Any]:
    container = _sellersprite_items_container(data)
    items = container.get("items") if isinstance(container.get("items"), list) else []
    return {
        "keyword": keyword,
        "outcome": "empty" if status == "ok" and _market_research_result_is_empty(data) else status,
        "item_count": len(items),
    }


def _product_match_tokens(value: Any) -> set[str]:
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", str(value or "").casefold()):
        if len(token) > 4 and token.endswith("s"):
            token = token[:-1]
        if len(token) >= 2:
            tokens.add(token)
    return tokens


def _hot_product_candidate_selection(data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    payload = data.get("data")
    candidates = [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    category = str(context.get("category") or "").strip()
    head_count = _bounded_int(context.get("head_listing_count"), 10, 1, 50)
    category_tokens = _product_match_tokens(category)
    specific_tokens = category_tokens - PRODUCT_MATCH_GENERIC_TOKENS
    selected: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen_families: set[str] = set()
    for index, item in enumerate(candidates, start=1):
        asin = str(item.get("asin") or "").strip().upper()
        title = str(item.get("title") or "").strip()
        title_tokens = _product_match_tokens(title)
        matched_tokens = sorted(specific_tokens & title_tokens)
        required_matches = len(specific_tokens) if len(specific_tokens) <= 2 else max(2, (len(specific_tokens) + 1) // 2)
        relevant = bool(asin and title) and (not specific_tokens or len(matched_tokens) >= required_matches)
        compact_item = {
            key: item.get(key)
            for key in (
                "ranking",
                "asin",
                "asinUrl",
                "imageUrl",
                "brand",
                "title",
                "price",
                "rating",
                "ratings",
                "reviews",
                "totalUnits",
                "totalRevenue",
                "parent",
                "parentAsin",
                "parent_asin",
            )
            if item.get(key) not in (None, "")
        }
        compact_item["candidate_order"] = index
        compact_item["matched_category_tokens"] = matched_tokens
        family_asin = str(
            item.get("parentAsin")
            or item.get("parent_asin")
            or item.get("parent")
            or asin
        ).strip().upper()
        compact_item["family_asin"] = family_asin
        duplicate_family = bool(family_asin and family_asin in seen_families)
        if relevant and not duplicate_family:
            seen_families.add(family_asin)
            eligible.append(compact_item)
            if len(selected) < head_count:
                selected.append(compact_item)
        else:
            excluded.append(
                {
                    **compact_item,
                    "exclusion_reason": (
                        "ASIN/title missing"
                        if not asin or not title
                        else f"Duplicate parent/variation family: {family_asin}"
                        if duplicate_family
                        else f"Title does not match category token(s): {', '.join(sorted(specific_tokens))}"
                    ),
                }
            )
    return {
        "category": category,
        "requested_product_count": head_count,
        "candidate_count": len(candidates),
        "eligible_count": len(eligible),
        "selected_count": len(selected),
        "missing_count": max(0, head_count - len(selected)),
        "selected": selected,
        "eligible_candidates": eligible,
        "excluded": excluded,
    }


def _review_total(data: dict[str, Any]) -> int:
    container = _sellersprite_items_container(data)
    try:
        return int(container.get("total") or 0)
    except (TypeError, ValueError):
        return 0


def _review_identity(item: dict[str, Any]) -> str:
    for key in ("id", "reviewId", "review_id"):
        value = str(item.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
    return json.dumps(
        [item.get("author"), item.get("title"), item.get("date"), item.get("content")],
        ensure_ascii=False,
        default=str,
    )


def _interleave_review_items(low_items: list[dict[str, Any]], high_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index in range(max(len(low_items), len(high_items))):
        for source in (low_items, high_items):
            if index >= len(source):
                continue
            item = source[index]
            identity = _review_identity(item)
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(item)
    return merged


def _review_items_in_window(items: list[dict[str, Any]], start_timestamp: Any, end_timestamp: Any) -> list[dict[str, Any]]:
    try:
        start_value = int(start_timestamp) if start_timestamp not in (None, "") else None
        end_value = int(end_timestamp) if end_timestamp not in (None, "") else None
    except (TypeError, ValueError):
        return items
    if start_value is None and end_value is None:
        return items
    filtered: list[dict[str, Any]] = []
    for item in items:
        try:
            timestamp = int(item.get("date"))
        except (TypeError, ValueError):
            continue
        if timestamp < 100_000_000_000:
            timestamp *= 1000
        if start_value is not None and timestamp < start_value:
            continue
        if end_value is not None and timestamp > end_value:
            continue
        filtered.append(item)
    return filtered


def _balanced_review_sample(
    mcp_tool_name: str,
    base_input: dict[str, Any],
    asin: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    target_size = _bounded_int(base_input.get("size"), 30, 10, 100)
    low_size = max(1, (target_size * 3 + 4) // 5)
    high_size = max(1, target_size - low_size)
    bucket_specs = [
        ("low_star", [1, 2, 3], low_size),
        ("high_star", [4, 5], high_size),
    ]
    bucket_results: dict[str, dict[str, Any]] = {}
    bucket_statuses: list[str] = []
    for bucket_name, stars, size in bucket_specs:
        request = {
            **base_input,
            "asin": asin,
            "starList": stars,
            "size": size,
            "page": 1,
        }
        raw = call_sellersprite_mcp_tool(mcp_tool_name, request)
        bucket_status, bucket_data = normalize_sellersprite_result(raw)
        bucket_statuses.append(bucket_status)
        container = _sellersprite_items_container(bucket_data)
        raw_items = [item for item in container.get("items") or [] if isinstance(item, dict)]
        window_items = _review_items_in_window(
            raw_items,
            base_input.get("startTimestamp"),
            base_input.get("endTimestamp"),
        )
        bucket_results[bucket_name] = {
            "status": bucket_status,
            "source_total": _review_total(bucket_data),
            "source_sample_count": len(raw_items),
            "items": window_items,
        }
    low = bucket_results["low_star"]
    high = bucket_results["high_star"]
    items = _interleave_review_items(low["items"], high["items"])
    if items:
        status = "partial_ok" if "error" in bucket_statuses or not low["items"] or not high["items"] else "ok"
    else:
        status = "error" if "error" in bucket_statuses else "ok"
    merged_data = {
        "code": "OK" if status != "error" else "ERROR",
        "message": "Balanced recent review sample",
        "data": {
            "page": 1,
            "size": target_size,
            "total": len(items),
            "items": items,
        },
    }
    attempt = {
        "asin": asin,
        "outcome": "empty" if status == "ok" and not items else status,
        "low_star_source_total": low["source_total"],
        "low_star_source_sample_count": low["source_sample_count"],
        "low_star_sample_count": len(low["items"]),
        "high_star_source_total": high["source_total"],
        "high_star_source_sample_count": high["source_sample_count"],
        "high_star_sample_count": len(high["items"]),
        "sample_count": len(items),
    }
    return status, merged_data, attempt


def _review_family_candidates(marketplace: str, asin: str) -> tuple[list[str], dict[str, Any]]:
    raw = call_sellersprite_mcp_tool("asin_detail", {"marketplace": marketplace, "asin": asin})
    status, data = normalize_sellersprite_result(raw)
    detail = data.get("data") if isinstance(data.get("data"), dict) else {}
    candidates: list[str] = []
    parent = str(detail.get("parent") or "").strip().upper()
    if re.fullmatch(r"[A-Z0-9]{10}", parent) and parent != asin:
        candidates.append(parent)
    for variation in detail.get("variationList") or []:
        if not isinstance(variation, dict):
            continue
        variation_asin = str(variation.get("asin") or "").strip().upper()
        if re.fullmatch(r"[A-Z0-9]{10}", variation_asin) and variation_asin != asin and variation_asin not in candidates:
            candidates.append(variation_asin)
        if len(candidates) >= 4:
            break
    return candidates, {
        "status": status,
        "parent_asin": parent or None,
        "candidate_count": len(candidates),
    }


def _execute_balanced_review(
    mcp_tool_name: str,
    input_payload: dict[str, Any],
) -> tuple[str, dict[str, Any], str]:
    requested_asin = str(input_payload.get("asin") or "").strip().upper()
    marketplace = str(input_payload.get("marketplace") or "US").strip().upper()
    attempts: list[dict[str, Any]] = []
    status, data, attempt = _balanced_review_sample(mcp_tool_name, input_payload, requested_asin)
    attempts.append(attempt)
    selected_asin = requested_asin if _sellersprite_items_container(data).get("items") else ""
    family_lookup: dict[str, Any] = {"status": "not_needed"}
    if not selected_asin and status != "error":
        family_candidates, family_lookup = _review_family_candidates(marketplace, requested_asin)
        for candidate in family_candidates:
            status, data, attempt = _balanced_review_sample(mcp_tool_name, input_payload, candidate)
            attempts.append(attempt)
            if _sellersprite_items_container(data).get("items"):
                selected_asin = candidate
                break
            if status == "error":
                break
    final_items = [
        item
        for item in _sellersprite_items_container(data).get("items") or []
        if isinstance(item, dict)
    ]
    media_evidence = [
        {
            "star": item.get("star"),
            "title": item.get("title"),
            "content": item.get("content"),
            "date": item.get("date"),
            "images": item.get("images"),
            "videos": item.get("videos"),
        }
        for item in final_items
        if item.get("images") or item.get("videos")
    ][:6]
    data["review_sampling"] = {
        "requested_asin": requested_asin,
        "selected_review_asin": selected_asin or None,
        "scope": (
            "exact_asin"
            if selected_asin == requested_asin
            else "variation_family"
            if selected_asin
            else "unavailable"
        ),
        "start_timestamp": input_payload.get("startTimestamp"),
        "end_timestamp": input_payload.get("endTimestamp"),
        "family_lookup": family_lookup,
        "attempt_count": len(attempts),
        "attempts": attempts,
        "media_evidence_count": len(media_evidence),
        "media_evidence": media_evidence,
    }
    sample_count = len(final_items)
    if selected_asin:
        scope_note = "" if selected_asin == requested_asin else f" via family variant `{selected_asin}`"
        summary = f"SellerSprite collected {sample_count} balanced recent review sample(s) for `{requested_asin}`{scope_note}."
    elif status == "error":
        summary = f"SellerSprite review sampling failed for `{requested_asin}`."
    else:
        summary = f"SellerSprite returned 0 recent reviews for `{requested_asin}` and checked family variants."
    return status, data, summary


def _execute_exhaustive_review_bucket(
    mcp_tool_name: str,
    input_payload: dict[str, Any],
    *,
    review_target: Any,
) -> tuple[str, dict[str, Any], str]:
    """Collect distinct review pages for one explicit star bucket.

    SellerSprite can return materially fewer rows than the requested `size`.
    Treat `size` as a page-size hint, follow `page`, and stop only at a
    provider total, the Skill safety target, an empty/repeated page, an error,
    or the hard page guard.
    """

    target = _bounded_int(review_target, MAX_EXHAUSTIVE_REVIEW_TARGET, 10, MAX_EXHAUSTIVE_REVIEW_TARGET)
    page_size = _bounded_int(input_payload.get("size"), 100, 1, 100)
    start_page = _bounded_int(input_payload.get("page"), 1, 1, 100_000)
    merged_items: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_attempts: list[dict[str, Any]] = []
    source_total = 0
    merged_data: dict[str, Any] = {}
    stop_reason = "max_pages_reached"
    page_error = ""

    for offset in range(MAX_EXHAUSTIVE_REVIEW_PAGES):
        page = start_page + offset
        request = {**input_payload, "page": page, "size": page_size}
        try:
            raw = call_sellersprite_mcp_tool(mcp_tool_name, request)
            page_status, page_data = normalize_sellersprite_result(raw)
        except Exception as exc:  # noqa: BLE001
            page_error = str(exc)
            page_attempts.append(
                {
                    "page": page,
                    "status": "error",
                    "source_sample_count": 0,
                    "new_unique_count": 0,
                    "error": page_error,
                }
            )
            stop_reason = "page_error"
            break

        if not merged_data:
            merged_data = page_data
        page_container = _sellersprite_items_container(page_data)
        page_items = [item for item in page_container.get("items") or [] if isinstance(item, dict)]
        page_items = _review_items_in_window(
            page_items,
            input_payload.get("startTimestamp"),
            input_payload.get("endTimestamp"),
        )
        source_total = max(source_total, _review_total(page_data))
        new_unique_count = 0
        for item in page_items:
            identity = _review_identity(item)
            if identity in seen:
                continue
            seen.add(identity)
            merged_items.append(item)
            new_unique_count += 1
            if len(merged_items) >= target:
                break
        page_attempts.append(
            {
                "page": page,
                "status": page_status,
                "source_total": _review_total(page_data),
                "source_sample_count": len(page_items),
                "new_unique_count": new_unique_count,
            }
        )

        if page_status == "error":
            stop_reason = "page_error"
            break
        if not page_items:
            stop_reason = "empty_page"
            break
        if new_unique_count == 0:
            stop_reason = "no_new_unique_reviews"
            break
        if source_total and len(merged_items) >= source_total:
            stop_reason = "source_total_reached"
            break
        if len(merged_items) >= target:
            stop_reason = "review_target_reached"
            break

    merged_items = merged_items[:target]
    if not merged_data:
        merged_data = {
            "code": "ERROR" if page_error else "OK",
            "message": page_error or "SellerSprite review pagination returned no data",
            "data": {"page": start_page, "size": page_size, "total": source_total, "items": []},
        }
    merged_container = _sellersprite_items_container(merged_data)
    if not merged_container:
        merged_data["data"] = {
            "page": start_page,
            "size": page_size,
            "total": source_total,
            "items": merged_items,
        }
        merged_container = merged_data["data"]
    else:
        merged_container["page"] = start_page
        merged_container["size"] = page_size
        merged_container["total"] = source_total
        merged_container["items"] = merged_items

    collected = len(merged_items)
    complete = (
        (source_total > 0 and collected >= source_total)
        or (source_total == 0 and stop_reason == "empty_page")
    )
    if page_error and not collected:
        status = "error"
    elif complete:
        status = "ok"
    else:
        status = "partial_ok"
    coverage_rate = round(collected / source_total, 4) if source_total else None
    merged_data["review_sampling"] = {
        "mode": "exhaustive_pagination",
        "requested_asin": str(input_payload.get("asin") or "").strip().upper(),
        "star_list": input_payload.get("starList") or [],
        "source_total": source_total,
        "review_target": target,
        "collected_unique_count": collected,
        "coverage_rate": coverage_rate,
        "complete": complete,
        "page_count": len(page_attempts),
        "stop_reason": stop_reason,
        "page_attempts": page_attempts,
    }
    if complete:
        summary = f"SellerSprite read all {collected} available review(s) in this star bucket across {len(page_attempts)} page(s)."
    else:
        total_label = str(source_total) if source_total else "an unknown total"
        summary = (
            f"SellerSprite read {collected} of {total_label} available review(s) in this star bucket "
            f"across {len(page_attempts)} page(s); stopped because {stop_reason}."
        )
    return status, merged_data, summary


def _combine_exhaustive_review_buckets(
    input_payload: dict[str, Any],
    bucket_outputs: dict[str, tuple[str, dict[str, Any], str]],
    *,
    review_target: Any,
) -> tuple[str, dict[str, Any], str]:
    bucket_results: dict[str, dict[str, Any]] = {}
    low_items: list[dict[str, Any]] = []
    high_items: list[dict[str, Any]] = []
    statuses: list[str] = []

    for bucket_name in ("low_star", "high_star"):
        bucket_status, bucket_data, bucket_summary = bucket_outputs[bucket_name]
        statuses.append(bucket_status)
        sampling = bucket_data.get("review_sampling") if isinstance(bucket_data.get("review_sampling"), dict) else {}
        items = [
            item
            for item in _sellersprite_items_container(bucket_data).get("items") or []
            if isinstance(item, dict)
        ]
        if bucket_name == "low_star":
            low_items = items
        else:
            high_items = items
        bucket_results[bucket_name] = {
            **sampling,
            "status": bucket_status,
            "summary": bucket_summary,
        }

    items = _interleave_review_items(low_items, high_items)
    source_total = sum(int(bucket.get("source_total") or 0) for bucket in bucket_results.values())
    page_count = sum(int(bucket.get("page_count") or 0) for bucket in bucket_results.values())
    complete = all(bool(bucket.get("complete")) for bucket in bucket_results.values())
    collected = len(items)
    coverage_rate = round(collected / source_total, 4) if source_total else None
    stop_reasons = list(
        dict.fromkeys(
            str(bucket.get("stop_reason") or "unknown")
            for bucket in bucket_results.values()
            if not bucket.get("complete")
        )
    )
    if complete:
        status = "ok"
    elif items:
        status = "partial_ok"
    else:
        status = "error" if "error" in statuses else "partial_ok"
    data = {
        "code": "OK" if status != "error" else "ERROR",
        "message": "Exhaustive low/high-star review pagination",
        "data": {
            "page": 1,
            "size": _bounded_int(input_payload.get("size"), 100, 1, 100),
            "total": source_total,
            "items": items,
        },
        "review_sampling": {
            "mode": "exhaustive_balanced_pagination",
            "requested_asin": str(input_payload.get("asin") or "").strip().upper(),
            "star_list": [1, 2, 3, 4, 5],
            "source_total": source_total,
            "review_target_per_bucket": _bounded_int(
                review_target,
                MAX_EXHAUSTIVE_REVIEW_TARGET,
                10,
                MAX_EXHAUSTIVE_REVIEW_TARGET,
            ),
            "collected_unique_count": collected,
            "coverage_rate": coverage_rate,
            "complete": complete,
            "page_count": page_count,
            "stop_reason": "complete" if complete else ",".join(stop_reasons) or "incomplete",
            "buckets": bucket_results,
        },
    }
    if complete:
        summary = (
            f"SellerSprite read all {collected} available review(s) across low/high-star buckets "
            f"in {page_count} page(s)."
        )
    else:
        total_label = str(source_total) if source_total else "an unknown total"
        summary = (
            f"SellerSprite read {collected} of {total_label} available review(s) across low/high-star buckets "
            f"in {page_count} page(s); incomplete bucket reason(s): {','.join(stop_reasons) or 'unknown'}."
        )
    return status, data, summary


def _execute_exhaustive_review(
    mcp_tool_name: str,
    input_payload: dict[str, Any],
    *,
    review_target: Any,
) -> tuple[str, dict[str, Any], str]:
    bucket_outputs: dict[str, tuple[str, dict[str, Any], str]] = {}
    for bucket_name, stars in (
        ("low_star", [1, 2, 3]),
        ("high_star", [4, 5]),
    ):
        bucket_outputs[bucket_name] = _execute_exhaustive_review_bucket(
            mcp_tool_name,
            {
                **input_payload,
                "page": 1,
                "starList": stars,
            },
            review_target=review_target,
        )
    return _combine_exhaustive_review_buckets(
        input_payload,
        bucket_outputs,
        review_target=review_target,
    )


def _execute_sellersprite_agent_tool_uncached(agent_tool_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    catalog = get_sellersprite_tool_catalog()
    meta = catalog.get(agent_tool_name) or {}
    label = str(meta.get("label") or agent_tool_name)
    public_input_payload = _sellersprite_mcp_arguments(input_payload)
    try:
        if not sellersprite_secret_key():
            raise SellerSpriteMcpAuthError(
                "SellerSprite MCP requires authentication. Set SELLERSPRITE_MCP_SECRET_KEY in the environment."
            )
        missing_required = _missing_required_sellersprite_fields(meta, public_input_payload)
        if missing_required:
            return {
                "name": agent_tool_name,
                "label": label,
                "status": "needs_user_action",
                "summary": (
                    "Missing required SellerSprite parameter(s): "
                    + ", ".join(missing_required)
                    + ". Provide the required value or skip this SellerSprite node-level tool."
                ),
                "duration_ms": int((time.time() - started) * 1000),
                "input": public_input_payload,
                "data": {"missing_required": missing_required},
            }
        mcp_tool_name = str(meta.get("mcp_tool") or sellersprite_mcp_tool_name(agent_tool_name))
        effective_input_payload = public_input_payload
        insight_context = input_payload.get(INSIGHT_CONTEXT_KEY)
        balanced_review = isinstance(insight_context, dict) and bool(insight_context.get("balanced_review"))
        exhaustive_review = isinstance(insight_context, dict) and bool(insight_context.get("exhaustive_review"))
        if agent_tool_name == "sellersprite_review" and balanced_review:
            status, data, summary = _execute_balanced_review(mcp_tool_name, public_input_payload)
        elif agent_tool_name == "sellersprite_review" and exhaustive_review:
            status, data, summary = _execute_exhaustive_review(
                mcp_tool_name,
                public_input_payload,
                review_target=insight_context.get("review_target"),
            )
        elif agent_tool_name == "sellersprite_aba_research_weekly":
            aba_attempts: list[dict[str, Any]] = []
            for attempt_index in range(2):
                raw = call_sellersprite_mcp_tool(mcp_tool_name, effective_input_payload)
                status, data = normalize_sellersprite_result(raw)
                date_error = _aba_weekly_date_error(data)
                request = (
                    effective_input_payload.get("request")
                    if isinstance(effective_input_payload.get("request"), dict)
                    else {}
                )
                aba_attempts.append(
                    {
                        "date": request.get("date"),
                        "status": status,
                        "date_error": date_error,
                    }
                )
                if date_error and attempt_index == 0:
                    effective_input_payload = {
                        **effective_input_payload,
                        "request": {**request, "date": _previous_aba_date(request.get("date"))},
                    }
                    continue
                break
            summary = summarize_sellersprite_data(agent_tool_name, data)
            if len(aba_attempts) > 1 and not _aba_weekly_date_error(data):
                selected_request = (
                    effective_input_payload.get("request")
                    if isinstance(effective_input_payload.get("request"), dict)
                    else {}
                )
                data["query_resolution"] = {
                    "date_policy": "previous_complete_week",
                    "selected_date": selected_request.get("date"),
                    "attempts": aba_attempts,
                }
                summary = f"SellerSprite ABA weekly recovered with published week `{selected_request.get('date')}`."
        else:
            raw = call_sellersprite_mcp_tool(mcp_tool_name, effective_input_payload)
            status, data = normalize_sellersprite_result(raw)
            summary = summarize_sellersprite_data(agent_tool_name, data)
        query_resolution: dict[str, Any] | None = None
        if agent_tool_name == "sellersprite_market_research" and status == "ok" and _market_research_result_is_empty(data):
            request = public_input_payload.get("request") if isinstance(public_input_payload.get("request"), dict) else {}
            original_keyword = str(request.get("departmentKeyword") or "").strip()
            keyword_candidates = _market_research_keyword_candidates(original_keyword)
            attempts = [_market_research_attempt(original_keyword, status, data)]
            for candidate in keyword_candidates[1:2]:
                effective_input_payload = {
                    **public_input_payload,
                    "request": {**request, "departmentKeyword": candidate},
                }
                raw = call_sellersprite_mcp_tool(mcp_tool_name, effective_input_payload)
                status, data = normalize_sellersprite_result(raw)
                attempts.append(_market_research_attempt(candidate, status, data))
                if status != "ok" or not _market_research_result_is_empty(data):
                    break
            selected_keyword = ""
            if status == "ok" and not _market_research_result_is_empty(data):
                selected_request = (
                    effective_input_payload.get("request")
                    if isinstance(effective_input_payload.get("request"), dict)
                    else {}
                )
                selected_keyword = str(selected_request.get("departmentKeyword") or "").strip()
            query_resolution = {
                "original_keyword": original_keyword,
                "selected_keyword": selected_keyword or None,
                "attempt_count": len(attempts),
                "attempts": attempts,
            }
            data["query_resolution"] = query_resolution
        if query_resolution:
            selected_keyword = str(query_resolution.get("selected_keyword") or "").strip()
            original_keyword = str(query_resolution.get("original_keyword") or "").strip()
            if selected_keyword:
                summary = (
                    f"SellerSprite market_research recovered with departmentKeyword `{selected_keyword}` "
                    f"after `{original_keyword}` returned 0 items."
                )
            elif status == "ok":
                attempted_keywords = ", ".join(
                    f"`{attempt.get('keyword')}`"
                    for attempt in query_resolution.get("attempts") or []
                    if isinstance(attempt, dict) and attempt.get("keyword")
                )
                summary = f"SellerSprite market_research returned 0 items for {attempted_keywords}."
        if agent_tool_name == "sellersprite_asin_detail" and status in {"ok", "partial_ok"}:
            insight_context = input_payload.get(INSIGHT_CONTEXT_KEY)
            if isinstance(insight_context, dict) and insight_context.get("resolve_category_node"):
                category_query = str(insight_context.get("category") or "").strip()
                resolution = resolve_sellersprite_product_node(data, category_query)
                data["node_resolution"] = resolution
                selected = resolution.get("selected") if isinstance(resolution.get("selected"), dict) else {}
                node_id_path = str(selected.get("nodeIdPath") or "").strip()
                if resolution.get("status") == "resolved" and node_id_path:
                    data["resolved_params"] = {
                        "category_node_id": node_id_path,
                        "category_node_label_path": str(selected.get("nodeLabelPath") or "").strip(),
                    }
                    summary = (
                        f"SellerSprite ASIN detail resolved category node `{node_id_path}` "
                        f"({selected.get('nodeLabelPath')})."
                    )
        if agent_tool_name == "sellersprite_market_product_concentration" and status in {"ok", "partial_ok"}:
            insight_context = input_payload.get(INSIGHT_CONTEXT_KEY)
            if isinstance(insight_context, dict):
                product_selection = _hot_product_candidate_selection(data, insight_context)
                data["product_selection"] = product_selection
                selected_asins = [
                    str(item.get("asin") or "").strip().upper()
                    for item in product_selection.get("selected") or []
                    if isinstance(item, dict) and item.get("asin")
                ]
                candidate_asins = [
                    str(item.get("asin") or "").strip().upper()
                    for item in product_selection.get("eligible_candidates") or []
                    if isinstance(item, dict) and item.get("asin")
                ]
                data["resolved_params"] = {
                    "selected_product_asins": selected_asins,
                    "candidate_product_asins": candidate_asins,
                }
                missing_count = int(product_selection.get("missing_count") or 0)
                if missing_count:
                    status = "partial_ok"
                    summary = (
                        f"SellerSprite returned {product_selection.get('candidate_count')} candidate(s), but only "
                        f"{product_selection.get('selected_count')} matched `{product_selection.get('category')}`; "
                        f"{missing_count} more relevant product(s) are required."
                    )
                else:
                    summary = (
                        f"SellerSprite selected {product_selection.get('selected_count')} relevant head product(s) "
                        f"from {product_selection.get('candidate_count')} candidates and excluded "
                        f"{len(product_selection.get('excluded') or [])} category mismatch(es)."
                    )
        if agent_tool_name == "sellersprite_product_node" and status == "ok":
            request = public_input_payload.get("request") if isinstance(public_input_payload.get("request"), dict) else {}
            query = str(request.get("keyword") or request.get("nodeIdPath") or "").strip()
            resolution = resolve_sellersprite_product_node(data, query)
            resolution_mode = "requested"
            attempts = [
                {
                    "query": query,
                    "mode": resolution_mode,
                    "resolution_status": resolution.get("status"),
                    "candidate_count": len(resolution.get("candidates") or []),
                }
            ]
            if resolution.get("status") != "resolved" and request.get("keyword"):
                for fallback in _product_node_query_plan(query)[1:5]:
                    fallback_query = fallback["query"]
                    effective_input_payload = {
                        **public_input_payload,
                        "request": {**request, "keyword": fallback_query},
                    }
                    raw = call_sellersprite_mcp_tool(mcp_tool_name, effective_input_payload)
                    status, data = normalize_sellersprite_result(raw)
                    if status != "ok":
                        attempts.append(
                            {
                                "query": fallback_query,
                                "mode": fallback["mode"],
                                "resolution_status": status,
                                "candidate_count": 0,
                            }
                        )
                        break
                    resolution = resolve_sellersprite_product_node(
                        data,
                        fallback_query,
                        context_query=str(request.get("keyword") or query).strip(),
                    )
                    attempts.append(
                        {
                            "query": fallback_query,
                            "mode": fallback["mode"],
                            "resolution_status": resolution.get("status"),
                            "candidate_count": len(resolution.get("candidates") or []),
                        }
                    )
                    if resolution.get("status") == "resolved":
                        query = fallback_query
                        resolution_mode = fallback["mode"]
                        break
            resolution["resolution_mode"] = resolution_mode
            resolution["requested_query"] = str(request.get("keyword") or query).strip()
            if resolution_mode == "proxy":
                resolution["proxy_reason"] = (
                    "The requested functional bra segment is not an Amazon leaf category; "
                    "Everyday Bras is used only as a broad taxonomy proxy."
                )
            data["node_resolution"] = resolution
            data["node_query_resolution"] = {
                "original_query": str(request.get("keyword") or query).strip(),
                "selected_query": query if resolution.get("status") == "resolved" else None,
                "resolution_mode": resolution_mode if resolution.get("status") == "resolved" else None,
                "attempt_count": len(attempts),
                "attempts": attempts,
            }
            selected = resolution.get("selected") if isinstance(resolution.get("selected"), dict) else {}
            node_id_path = str(selected.get("nodeIdPath") or "").strip()
            if resolution.get("status") == "resolved" and node_id_path:
                data["resolved_params"] = {
                    "category_node_id": node_id_path,
                    "category_node_label_path": str(selected.get("nodeLabelPath") or "").strip(),
                    "category_node_resolution_mode": resolution_mode,
                    "category_node_is_proxy": resolution_mode == "proxy",
                    "category_node_requested_query": str(request.get("keyword") or query).strip(),
                }
                recovery_note = "" if len(attempts) == 1 else f" after {len(attempts)} controlled query variants"
                if resolution_mode == "proxy":
                    summary = (
                        f"SellerSprite resolved broad proxy node `{node_id_path}` ({selected.get('nodeLabelPath')})"
                        f"{recovery_note}; use node-level metrics as category context, not as the exact functional segment."
                    )
                else:
                    summary = (
                        f"SellerSprite resolved category node `{node_id_path}` "
                        f"({selected.get('nodeLabelPath')}){recovery_note}."
                    )
            elif resolution.get("status") == "ambiguous":
                summary = "SellerSprite returned multiple plausible category nodes; retry with a more exact category label or ask the user to choose."
            else:
                summary = "SellerSprite returned no high-confidence category node; retry with a shorter official leaf category label before asking the user."
        return {
            "name": agent_tool_name,
            "label": label,
            "status": status,
            "summary": summary,
            "duration_ms": int((time.time() - started) * 1000),
            "input": effective_input_payload,
            "data": data,
        }
    except SellerSpriteMcpAuthError as exc:
        return {
            "name": agent_tool_name,
            "label": label,
            "status": "needs_user_action",
            "summary": str(exc),
            "duration_ms": int((time.time() - started) * 1000),
            "input": public_input_payload,
            "data": {},
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": agent_tool_name,
            "label": label,
            "status": "error",
            "summary": str(exc),
            "duration_ms": int((time.time() - started) * 1000),
            "input": public_input_payload,
            "data": {},
        }


def _execute_exhaustive_review_with_asin_cache(
    input_payload: dict[str, Any],
    *,
    bypass_cache: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    cache_params = _sellersprite_review_asin_cache_params(input_payload)
    with mcp_result_cache_lock("sellersprite", SELLERSPRITE_REVIEW_ASIN_CACHE_TOOL, cache_params):
        if not bypass_cache:
            cached = read_mcp_result_cache(
                "sellersprite",
                SELLERSPRITE_REVIEW_ASIN_CACHE_TOOL,
                cache_params,
            )
            if cached is not None and _cached_exhaustive_review_satisfies(cached.result, input_payload):
                cached_result = dict(cached.result)
                cached_result["input"] = _sellersprite_mcp_arguments(input_payload)
                metadata = {
                    **cached.metadata,
                    "cache_tool": SELLERSPRITE_REVIEW_ASIN_CACHE_TOOL,
                    "tool": "sellersprite_review",
                    "scope": "marketplace_asin",
                }
                return with_mcp_cache_metadata(
                    cached_result,
                    metadata,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )

        result = _execute_sellersprite_agent_tool_uncached("sellersprite_review", input_payload)
        if cacheable_mcp_result(result):
            metadata = write_mcp_result_cache(
                "sellersprite",
                SELLERSPRITE_REVIEW_ASIN_CACHE_TOOL,
                cache_params,
                result,
            )
        else:
            metadata = {
                "hit": False,
                "stored": False,
                "provider": "sellersprite",
                "tool": "sellersprite_review",
                "cache_tool": SELLERSPRITE_REVIEW_ASIN_CACHE_TOOL,
                "scope": "marketplace_asin",
                "reason": "result_status_not_cacheable",
            }
        metadata = {
            **metadata,
            "cache_tool": SELLERSPRITE_REVIEW_ASIN_CACHE_TOOL,
            "tool": "sellersprite_review",
            "scope": "marketplace_asin",
        }
        if bypass_cache:
            metadata["bypassed"] = True
            metadata["refreshed"] = bool(metadata.get("stored"))
        return with_mcp_cache_metadata(
            result,
            metadata,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


def execute_sellersprite_agent_tool(
    agent_tool_name: str,
    input_payload: dict[str, Any],
    *,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    insight_context = input_payload.get(INSIGHT_CONTEXT_KEY)
    exhaustive_review = isinstance(insight_context, dict) and bool(insight_context.get("exhaustive_review"))
    asin = str(_sellersprite_mcp_arguments(input_payload).get("asin") or "").strip()
    if agent_tool_name == "sellersprite_review" and exhaustive_review and asin:
        return _execute_exhaustive_review_with_asin_cache(
            input_payload,
            bypass_cache=bypass_cache,
        )
    cache_params = _sellersprite_cache_params(input_payload)
    return execute_with_mcp_result_cache(
        "sellersprite",
        agent_tool_name,
        cache_params,
        lambda: _execute_sellersprite_agent_tool_uncached(agent_tool_name, input_payload),
        bypass_cache=bypass_cache,
    )

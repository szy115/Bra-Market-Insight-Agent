from __future__ import annotations

from insight_agent import mcp_sellersprite
from insight_agent import server as server_module
from insight_agent.sellersprite_manifest import (
    SELLERSPRITE_MARKET_ABA_DISTRIBUTION_BATCH,
    SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_BATCH,
    load_sellersprite_manifest,
    sellersprite_specs_for_batch,
)
from insight_agent.tool_capabilities import InvocationScope
from insight_agent.tool_capabilities.sellersprite_product_keyword import (
    SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_CAPABILITY_IDS,
    build_sellersprite_product_keyword_traffic_capabilities,
)


def test_sellersprite_manifest_partitions_all_provider_tools() -> None:
    manifest = load_sellersprite_manifest()
    selected = sellersprite_specs_for_batch(SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_BATCH)
    remaining = sellersprite_specs_for_batch(SELLERSPRITE_MARKET_ABA_DISTRIBUTION_BATCH)

    assert len(manifest) == 44
    assert len(selected) == 21
    assert len(remaining) == 23
    assert {item["name"] for item in selected}.isdisjoint(
        {item["name"] for item in remaining}
    )
    assert {item["name"] for item in manifest} == {
        item["name"] for item in (*selected, *remaining)
    }


def test_sellersprite_product_keyword_traffic_capabilities_are_registered() -> None:
    registry = server_module.AGENT_TOOL_CAPABILITY_REGISTRY
    planner_catalog = registry.catalog(InvocationScope.PLANNER)

    assert SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_CAPABILITY_IDS.issubset(
        registry.capabilities
    )
    assert SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_CAPABILITY_IDS.issubset(planner_catalog)
    for capability_id in SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_CAPABILITY_IDS:
        metadata = planner_catalog[capability_id]
        assert metadata["source"] == "sellersprite_mcp"
        assert metadata["mcp_tool"] == capability_id.removeprefix("sellersprite_")
        assert metadata["result_contract"] == "sellersprite_result.v1"
        assert metadata["output_kind"] == "generic_json"
        assert metadata["recovery"] == {
            "retryable": True,
            "default_timeout_seconds": 600,
            "default_retry_attempts": 2,
        }


def test_sellersprite_registry_composition_does_not_touch_provider_runtime() -> None:
    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("composition must not call provider runtime")

    capabilities = build_sellersprite_product_keyword_traffic_capabilities(
        normalize_input=unexpected_call,
        adapter=unexpected_call,
    )

    assert {item.capability_id for item in capabilities} == (
        SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_CAPABILITY_IDS
    )


def test_sellersprite_review_normalizes_market_asin_paging_and_filters() -> None:
    capability = server_module.AGENT_TOOL_CAPABILITY_REGISTRY.get("sellersprite_review")

    tool_input = capability.normalize_input(
        "",
        {
            "marketplace": "Amazon US",
            "product_asin": "B000000001",
            "page": 2,
            "size": 50,
            "starList": [1, 2, 3],
            "typeList": [3],
            "unsupported": "drop-me",
        },
    )

    assert tool_input == {
        "marketplace": "US",
        "asin": "B000000001",
        "page": 2,
        "size": 30,
        "starList": [1, 2, 3],
        "typeList": [3],
    }


def test_sellersprite_keyword_trend_normalizes_keyword_market_and_month(
    monkeypatch,
) -> None:
    class FixedDate(mcp_sellersprite.dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 9)

    monkeypatch.setattr(mcp_sellersprite.dt, "date", FixedDate)
    capability = server_module.AGENT_TOOL_CAPABILITY_REGISTRY.get(
        "sellersprite_keyword_research_trends"
    )

    tool_input = capability.normalize_input(
        "minimizer bra",
        {"marketplace": "Amazon US", "prompt": "drop-me"},
    )

    assert tool_input == {
        "marketplace": "US",
        "keyword": "minimizer bra",
        "month": "202606",
    }


def test_sellersprite_success_and_bypass_execute_through_registry(monkeypatch) -> None:
    calls: list[dict] = []

    def execute(capability_id, tool_input, *, bypass_cache=False, tool_meta=None):
        calls.append(
            {
                "capability_id": capability_id,
                "tool_input": tool_input,
                "bypass_cache": bypass_cache,
                "mcp_tool": tool_meta["mcp_tool"],
            }
        )
        return {
            "name": capability_id,
            "label": tool_meta["label"],
            "status": "ok",
            "summary": "SellerSprite returned 1 item(s).",
            "duration_ms": 43,
            "input": tool_input,
            "data": {"items": [{"keyword": "minimizer bra"}]},
            "cache": {"hit": False},
        }

    monkeypatch.setattr(server_module, "execute_sellersprite_agent_tool", execute)

    result = server_module.execute_agent_tool(
        "sellersprite_traffic_keyword_stat",
        "",
        {
            "bypassCache": True,
            "marketplace": "Amazon US",
            "asin": "B000000001",
        },
    )

    assert result["status"] == "ok"
    assert result["duration_ms"] == 43
    assert result["input"]["marketplace"] == "US"
    assert result["input"]["asin"] == "B000000001"
    assert result["data"] == {"items": [{"keyword": "minimizer bra"}]}
    assert result["cache"] == {"hit": False}
    assert calls[0]["bypass_cache"] is True
    assert calls[0]["mcp_tool"] == "traffic_keyword_stat"


def test_sellersprite_adapter_public_input_hides_internal_context(monkeypatch) -> None:
    captured: dict = {}

    def execute(capability_id, tool_input, *, bypass_cache=False, tool_meta=None):
        captured.update(tool_input)
        return {
            "name": capability_id,
            "label": tool_meta["label"],
            "status": "ok",
            "summary": "SellerSprite returned ASIN evidence.",
            "input": {"marketplace": "US", "asin": "B000000001"},
            "data": {"asin": "B000000001"},
        }

    monkeypatch.setattr(server_module, "execute_sellersprite_agent_tool", execute)

    result = server_module.execute_agent_tool(
        "sellersprite_asin_detail",
        "minimizer bra",
        {"marketplace": "Amazon US", "asin": "B000000001"},
    )

    assert "__insight_context" in captured
    assert result["input"] == {"marketplace": "US", "asin": "B000000001"}


def test_sellersprite_missing_credentials_is_runtime_outcome(monkeypatch) -> None:
    for env_name in (
        "SELLERSPRITE_MCP_SECRET_KEY",
        "SELLERSPRITE_SECRET_KEY",
        "SELLERSPRITE_API_KEY",
    ):
        monkeypatch.delenv(env_name, raising=False)

    result = server_module.execute_agent_tool(
        "sellersprite_traffic_keyword_stat",
        "",
        {
            "bypassCache": True,
            "marketplace": "Amazon US",
            "asin": "B000000001",
        },
    )

    assert result["status"] == "needs_user_action"
    assert "authentication" in result["summary"].lower()
    assert result["input"]["marketplace"] == "US"
    assert result["input"]["asin"] == "B000000001"
    assert result["data"] == {}


def test_sellersprite_provider_error_envelope_is_preserved(monkeypatch) -> None:
    def execute(capability_id, tool_input, *, bypass_cache=False, tool_meta=None):
        return {
            "name": capability_id,
            "label": tool_meta["label"],
            "status": "error",
            "summary": "SellerSprite MCP HTTP 503: fixture unavailable",
            "duration_ms": 59,
            "input": tool_input,
            "data": {},
            "cache": {"hit": False},
        }

    monkeypatch.setattr(server_module, "execute_sellersprite_agent_tool", execute)

    result = server_module.execute_agent_tool(
        "sellersprite_keyword_research_trends",
        "minimizer bra",
        {"marketplace": "Amazon US"},
    )

    assert result["status"] == "error"
    assert result["summary"] == "SellerSprite MCP HTTP 503: fixture unavailable"
    assert result["duration_ms"] == 59
    assert result["cache"] == {"hit": False}
    assert result["data"] == {}

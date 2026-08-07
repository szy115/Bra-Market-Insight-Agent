from __future__ import annotations

from insight_agent import server as server_module
from insight_agent.tool_capabilities import InvocationScope
from insight_agent.tool_capabilities.sif import (
    SIF_CAPABILITY_IDS,
    build_sif_capabilities,
)


def test_sif_capabilities_are_explicitly_registered() -> None:
    registry = server_module.AGENT_TOOL_CAPABILITY_REGISTRY
    planner_catalog = registry.catalog(InvocationScope.PLANNER)

    assert SIF_CAPABILITY_IDS.issubset(registry.capabilities)
    assert SIF_CAPABILITY_IDS.issubset(planner_catalog)
    for capability_id in SIF_CAPABILITY_IDS:
        metadata = planner_catalog[capability_id]
        assert metadata["source"] == "sif_mcp"
        assert metadata["mcp_tool"] == capability_id.removeprefix("sif_")
        assert metadata["result_contract"] == "sif_result.v1"
        assert metadata["output_kind"] == "generic_json"
        assert metadata["recovery"] == {
            "retryable": True,
            "default_timeout_seconds": 600,
            "default_retry_attempts": 2,
        }


def test_sif_registry_composition_does_not_touch_provider_runtime() -> None:
    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("composition must not call provider runtime")

    capabilities = build_sif_capabilities(
        normalize_input=unexpected_call,
        adapter=unexpected_call,
    )

    assert {item.capability_id for item in capabilities} == SIF_CAPABILITY_IDS


def test_dynamic_sif_catalog_cannot_override_migrated_capabilities(monkeypatch) -> None:
    migrated_id = "sif_market_get_keyword_demand"
    legacy_id = "sif_market_discover_competitors"
    monkeypatch.setattr(
        server_module,
        "get_sif_tool_catalog",
        lambda: {
            migrated_id: {"label": "dynamic duplicate"},
            legacy_id: {"label": "Sif: market_discover_competitors"},
        },
    )

    catalog = server_module.planner_agent_tool_catalog()

    assert catalog[migrated_id]["label"] == "Sif: market_get_keyword_demand"
    assert catalog[migrated_id]["result_contract"] == "sif_result.v1"
    assert catalog[legacy_id] == {"label": "Sif: market_discover_competitors"}


def test_sif_keyword_history_normalizes_static_schema_input() -> None:
    capability = server_module.AGENT_TOOL_CAPABILITY_REGISTRY.get(
        "sif_market_get_keyword_history"
    )

    tool_input = capability.normalize_input(
        "minimizer bra",
        {
            "marketplace": "Amazon US",
            "prompt": "drop-me",
            "bypassCache": True,
        },
    )

    assert tool_input == {
        "country": "US",
        "granularity": "week",
        "keywords": ["minimizer bra"],
    }


def test_sif_sales_list_keeps_hot_product_defaults() -> None:
    capability = server_module.AGENT_TOOL_CAPABILITY_REGISTRY.get(
        "sif_ops_get_asin_sales_list"
    )

    tool_input = capability.normalize_input(
        "minimizer bra",
        {
            "skillId": "hot_product_pain_analysis",
            "marketplace": "Amazon US",
            "asins": ["B000IGNORED"],
            "timePieceType": "month",
            "timePieceValue": "2025-02-01",
            "params": {
                "reviewed_product_asins": [
                    "B000000001",
                    "B000000002",
                    "B000000001",
                ]
            },
        },
    )

    assert tool_input == {
        "asins": ["B000000001", "B000000002"],
        "country": "US",
        "dimension": "asin",
        "sortBy": "boughtInPastMonth",
        "desc": True,
        "pageNum": 1,
        "pageSize": 20,
        "timePieceType": "latelyDay",
        "timePieceValue": "30",
    }


def test_sif_success_envelope_and_bypass_execute_through_registry(monkeypatch) -> None:
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
            "summary": "Sif returned keyword evidence for 1 keyword(s).",
            "duration_ms": 31,
            "input": tool_input,
            "data": {"keywords": [{"keyword": "minimizer bra"}]},
            "cache": {"hit": False},
        }

    monkeypatch.setattr(server_module, "execute_sif_agent_tool", execute)
    monkeypatch.setattr(
        server_module,
        "is_sif_agent_tool",
        lambda _tool_name: (_ for _ in ()).throw(
            AssertionError("migrated capability reached legacy family dispatch")
        ),
    )

    result = server_module.execute_agent_tool(
        "sif_market_get_keyword_demand",
        "minimizer bra",
        {"bypassCache": True, "marketplace": "Amazon US"},
    )

    assert result == {
        "name": "sif_market_get_keyword_demand",
        "label": "Sif: market_get_keyword_demand",
        "status": "ok",
        "summary": "Sif returned keyword evidence for 1 keyword(s).",
        "duration_ms": 31,
        "input": {"keywords": ["minimizer bra"], "country": "US"},
        "data": {"keywords": [{"keyword": "minimizer bra"}]},
        "cache": {"hit": False},
    }
    assert calls == [
        {
            "capability_id": "sif_market_get_keyword_demand",
            "tool_input": result["input"],
            "bypass_cache": True,
            "mcp_tool": "market_get_keyword_demand",
        }
    ]


def test_sif_missing_credentials_remains_execution_time_outcome(monkeypatch) -> None:
    for env_name in ("SIF_MCP_TOKEN", "SIF_API_KEY", "SIF_TOKEN"):
        monkeypatch.delenv(env_name, raising=False)

    result = server_module.execute_agent_tool(
        "sif_market_get_asin_keyword_signals",
        "",
        {"bypassCache": True, "asin": "B000000001", "marketplace": "Amazon US"},
    )

    assert result["status"] == "needs_user_action"
    assert "authentication" in result["summary"].lower()
    assert result["input"] == {"asin": "B000000001", "country": "US"}
    assert result["data"] == {}


def test_sif_provider_error_envelope_is_preserved_by_registry(monkeypatch) -> None:
    def execute(capability_id, tool_input, *, bypass_cache=False, tool_meta=None):
        return {
            "name": capability_id,
            "label": tool_meta["label"],
            "status": "error",
            "summary": "Sif MCP HTTP 503: fixture unavailable",
            "duration_ms": 47,
            "input": tool_input,
            "data": {},
            "cache": {"hit": False},
        }

    monkeypatch.setattr(server_module, "execute_sif_agent_tool", execute)

    result = server_module.execute_agent_tool(
        "sif_ops_get_asin_sales_trend",
        "",
        {"asin": "B000000001", "marketplace": "Amazon US"},
    )

    assert result["status"] == "error"
    assert result["summary"] == "Sif MCP HTTP 503: fixture unavailable"
    assert result["duration_ms"] == 47
    assert result["cache"] == {"hit": False}
    assert result["data"] == {}

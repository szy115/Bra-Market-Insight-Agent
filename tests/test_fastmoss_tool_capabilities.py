from __future__ import annotations

from insight_agent import server as server_module
from insight_agent.tool_capabilities import InvocationScope
from insight_agent.tool_capabilities.fastmoss_market import (
    FASTMOSS_MARKET_PRODUCT_CAPABILITY_IDS,
    build_fastmoss_market_product_capabilities,
)


def test_fastmoss_market_product_capabilities_are_explicitly_registered() -> None:
    registry = server_module.AGENT_TOOL_CAPABILITY_REGISTRY
    planner_catalog = registry.catalog(InvocationScope.PLANNER)

    assert FASTMOSS_MARKET_PRODUCT_CAPABILITY_IDS.issubset(registry.capabilities)
    assert FASTMOSS_MARKET_PRODUCT_CAPABILITY_IDS.issubset(planner_catalog)
    for capability_id in FASTMOSS_MARKET_PRODUCT_CAPABILITY_IDS:
        metadata = planner_catalog[capability_id]
        assert metadata["source"] == "fastmoss_mcp"
        assert metadata["mcp_tool"] == capability_id.removeprefix("mcp__fastmoss__")
        assert metadata["checkpoint_reuse"] is True
        assert metadata["result_contract"] == "fastmoss_result.v1"
        assert metadata["output_kind"] == "generic_json"
        assert metadata["recovery"] == {
            "retryable": True,
            "default_timeout_seconds": 600,
            "default_retry_attempts": 2,
        }


def test_fastmoss_registry_composition_does_not_touch_provider_runtime() -> None:
    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("composition must not call provider runtime")

    capabilities = build_fastmoss_market_product_capabilities(
        normalize_input=unexpected_call,
        adapter=unexpected_call,
    )

    assert {item.capability_id for item in capabilities} == (
        FASTMOSS_MARKET_PRODUCT_CAPABILITY_IDS
    )


def test_dynamic_fastmoss_catalog_cannot_override_migrated_capabilities(monkeypatch) -> None:
    migrated_id = "mcp__fastmoss__product_search"
    legacy_id = "mcp__fastmoss__video_search"
    monkeypatch.setattr(
        server_module,
        "get_fastmoss_tool_catalog",
        lambda: {
            migrated_id: {"label": "dynamic duplicate"},
            legacy_id: {"label": "FastMoss: video_search"},
        },
    )

    catalog = server_module.planner_agent_tool_catalog()

    assert catalog[migrated_id]["label"] == "FastMoss: product_search"
    assert catalog[migrated_id]["result_contract"] == "fastmoss_result.v1"
    assert catalog[legacy_id] == {"label": "FastMoss: video_search"}


def test_fastmoss_capability_normalizes_provider_input_from_static_schema() -> None:
    capability = server_module.AGENT_TOOL_CAPABILITY_REGISTRY.get(
        "mcp__fastmoss__market_category_analysis"
    )

    tool_input = capability.normalize_input(
        "minimizer bra",
        {
            "marketplace": "United States",
            "params": {"category_node_id": "601262"},
            "filter": {
                "date_type": "month",
                "date_value": "2026-06",
                "region": "North America (US+MX)",
                "unsupported": "drop-me",
            },
            "analysis_type": "sales_trends",
        },
    )

    assert tool_input == {
        "analysis_type": "sales_trends",
        "filter": {
            "date_type": "month",
            "date_value": "2026-06",
            "category_id": "601262",
            "region": "US",
        },
    }


def test_fastmoss_success_envelope_and_bypass_execute_through_registry(monkeypatch) -> None:
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
            "summary": "FastMoss returned 1 item(s) in `list`.",
            "duration_ms": 37,
            "input": tool_input,
            "data": {"list": [{"product_id": "p1"}]},
            "cache": {"hit": False},
        }

    monkeypatch.setattr(server_module, "execute_fastmoss_agent_tool", execute)
    monkeypatch.setattr(
        server_module,
        "is_fastmoss_agent_tool",
        lambda _tool_name: (_ for _ in ()).throw(
            AssertionError("migrated capability reached legacy family dispatch")
        ),
    )

    result = server_module.execute_agent_tool(
        "mcp__fastmoss__product_rank_top_selling",
        "minimizer bra",
        {
            "bypassCache": True,
            "filter": {
                "region": "US",
                "date_type": "week",
                "date_value": "2026-W30",
            },
        },
    )

    assert result == {
        "name": "mcp__fastmoss__product_rank_top_selling",
        "label": "FastMoss: product_rank_top_selling",
        "status": "ok",
        "summary": "FastMoss returned 1 item(s) in `list`.",
        "duration_ms": 37,
        "input": {
            "filter": {
                "region": "US",
                "date_type": "week",
                "date_value": "2026-W30",
            }
        },
        "data": {"list": [{"product_id": "p1"}]},
        "cache": {"hit": False},
    }
    assert calls == [
        {
            "capability_id": "mcp__fastmoss__product_rank_top_selling",
            "tool_input": result["input"],
            "bypass_cache": True,
            "mcp_tool": "product_rank_top_selling",
        }
    ]


def test_fastmoss_missing_credentials_remains_execution_time_outcome(monkeypatch) -> None:
    for env_name in (
        "FASTMOSS_MCP_API_KEY",
        "FASTMOSS_MCP_KEY",
        "FASTMOSS_API_KEY",
    ):
        monkeypatch.delenv(env_name, raising=False)

    result = server_module.execute_agent_tool(
        "mcp__fastmoss__product_detail_info",
        "",
        {
            "bypassCache": True,
            "filter": {"product_id": "fixture-product"},
        },
    )

    assert result["status"] == "needs_user_action"
    assert "authentication" in result["summary"].lower()
    assert result["input"] == {"filter": {"product_id": "fixture-product"}}
    assert result["data"] == {}


def test_fastmoss_provider_error_envelope_is_preserved_by_registry(monkeypatch) -> None:
    def execute(capability_id, tool_input, *, bypass_cache=False, tool_meta=None):
        return {
            "name": capability_id,
            "label": tool_meta["label"],
            "status": "error",
            "summary": "FastMoss MCP connection failed: fixture timeout",
            "duration_ms": 53,
            "input": tool_input,
            "data": {},
            "cache": {"hit": False},
        }

    monkeypatch.setattr(server_module, "execute_fastmoss_agent_tool", execute)

    result = server_module.execute_agent_tool(
        "mcp__fastmoss__product_review_list",
        "",
        {"filter": {"product_id": "fixture-product"}},
    )

    assert result["status"] == "error"
    assert result["summary"] == "FastMoss MCP connection failed: fixture timeout"
    assert result["duration_ms"] == 53
    assert result["cache"] == {"hit": False}
    assert result["data"] == {}

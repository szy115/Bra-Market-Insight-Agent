from __future__ import annotations

from insight_agent import server as server_module
from insight_agent.tool_capabilities import InvocationScope
from insight_agent.tool_capabilities.fastmoss_shop_creator import (
    FASTMOSS_SHOP_CREATOR_CAPABILITY_IDS,
    build_fastmoss_shop_creator_capabilities,
)


def test_fastmoss_shop_creator_capabilities_are_explicitly_registered() -> None:
    registry = server_module.AGENT_TOOL_CAPABILITY_REGISTRY
    planner_catalog = registry.catalog(InvocationScope.PLANNER)

    assert FASTMOSS_SHOP_CREATOR_CAPABILITY_IDS.issubset(registry.capabilities)
    for capability_id in FASTMOSS_SHOP_CREATOR_CAPABILITY_IDS:
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


def test_fastmoss_shop_creator_composition_does_not_touch_provider_runtime() -> None:
    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("composition must not call provider runtime")

    capabilities = build_fastmoss_shop_creator_capabilities(
        normalize_input=unexpected_call,
        adapter=unexpected_call,
    )

    assert {item.capability_id for item in capabilities} == (
        FASTMOSS_SHOP_CREATOR_CAPABILITY_IDS
    )


def test_fastmoss_shop_ranking_normalizes_provider_input() -> None:
    capability = server_module.AGENT_TOOL_CAPABILITY_REGISTRY.get(
        "mcp__fastmoss__shop_rank_top_selling"
    )

    tool_input = capability.normalize_input(
        "womens bra",
        {
            "marketplace": "United States",
            "params": {"category_node_id": "601262"},
            "filter": {
                "date_type": "month",
                "date_value": "2026-06",
                "region": "North America (US+MX)",
                "unsupported": "drop-me",
            },
            "page": 2,
            "pagesize": 10,
        },
    )

    assert tool_input == {
        "filter": {
            "date_type": "month",
            "date_value": "2026-06",
            "category_id": "601262",
            "region": "US",
        },
        "page": 2,
        "pagesize": 10,
    }


def test_fastmoss_shop_success_envelope_executes_through_registry(monkeypatch) -> None:
    calls: list[dict] = []

    def execute(capability_id, tool_input, *, bypass_cache=False, tool_meta=None):
        calls.append(
            {
                "capability_id": capability_id,
                "tool_input": tool_input,
                "bypass_cache": bypass_cache,
            }
        )
        return {
            "name": capability_id,
            "label": tool_meta["label"],
            "status": "ok",
            "summary": "FastMoss returned 1 item(s) in `list`.",
            "duration_ms": 29,
            "input": tool_input,
            "data": {"list": [{"seller_id": "seller-1"}]},
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
        "mcp__fastmoss__shop_search",
        "womens bra",
        {
            "bypassCache": True,
            "marketplace": "US",
            "filter": {"shop_name": "fixture shop"},
        },
    )

    assert result["status"] == "ok"
    assert result["duration_ms"] == 29
    assert result["data"] == {"list": [{"seller_id": "seller-1"}]}
    assert result["cache"] == {"hit": False}
    assert calls == [
        {
            "capability_id": "mcp__fastmoss__shop_search",
            "tool_input": {
                "filter": {"shop_name": "fixture shop", "region": "US"},
                "keywords": "womens bra",
            },
            "bypass_cache": True,
        }
    ]


def test_fastmoss_creator_missing_credentials_is_runtime_outcome(monkeypatch) -> None:
    for env_name in (
        "FASTMOSS_MCP_API_KEY",
        "FASTMOSS_MCP_KEY",
        "FASTMOSS_API_KEY",
    ):
        monkeypatch.delenv(env_name, raising=False)

    result = server_module.execute_agent_tool(
        "mcp__fastmoss__creator_profile_overview",
        "",
        {"bypassCache": True, "filter": {"uid": "fixture-creator"}},
    )

    assert result["status"] == "needs_user_action"
    assert "authentication" in result["summary"].lower()
    assert result["input"] == {"filter": {"uid": "fixture-creator"}}
    assert result["data"] == {}

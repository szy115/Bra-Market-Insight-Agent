from __future__ import annotations

from insight_agent import mcp_sellersprite
from insight_agent import server as server_module
from insight_agent.sellersprite_manifest import load_sellersprite_manifest
from insight_agent.tool_capabilities import InvocationScope
from insight_agent.tool_capabilities.sellersprite_market import (
    SELLERSPRITE_MARKET_ABA_DISTRIBUTION_CAPABILITY_IDS,
    build_sellersprite_market_aba_distribution_capabilities,
)
from insight_agent.tool_capabilities.sellersprite_product_keyword import (
    SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_CAPABILITY_IDS,
)


def test_all_sellersprite_capabilities_are_registered_from_static_manifest() -> None:
    registry = server_module.AGENT_TOOL_CAPABILITY_REGISTRY
    planner_catalog = registry.catalog(InvocationScope.PLANNER)
    manifest_ids = {f"sellersprite_{item['name']}" for item in load_sellersprite_manifest()}

    assert len(SELLERSPRITE_MARKET_ABA_DISTRIBUTION_CAPABILITY_IDS) == 23
    assert manifest_ids == (
        SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_CAPABILITY_IDS
        | SELLERSPRITE_MARKET_ABA_DISTRIBUTION_CAPABILITY_IDS
    )
    assert manifest_ids.issubset(registry.capabilities)
    assert manifest_ids.issubset(planner_catalog)
    for capability_id in SELLERSPRITE_MARKET_ABA_DISTRIBUTION_CAPABILITY_IDS:
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


def test_second_batch_registry_composition_is_offline() -> None:
    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("composition must not call provider runtime")

    capabilities = build_sellersprite_market_aba_distribution_capabilities(
        normalize_input=unexpected_call,
        adapter=unexpected_call,
    )

    assert {item.capability_id for item in capabilities} == (
        SELLERSPRITE_MARKET_ABA_DISTRIBUTION_CAPABILITY_IDS
    )


def test_catalogs_no_longer_depend_on_dynamic_sellersprite_discovery() -> None:
    public_catalog = server_module.agent_tool_catalog()
    planner_catalog = server_module.planner_agent_tool_catalog()

    assert SELLERSPRITE_MARKET_ABA_DISTRIBUTION_CAPABILITY_IDS.issubset(public_catalog)
    assert SELLERSPRITE_MARKET_ABA_DISTRIBUTION_CAPABILITY_IDS.issubset(planner_catalog)
    assert not hasattr(mcp_sellersprite, "get_sellersprite_tool_catalog")
    assert not hasattr(server_module, "get_sellersprite_tool_catalog")
    assert not hasattr(server_module, "is_sellersprite_agent_tool")


def test_aba_weekly_preserves_market_date_paging_and_keyword_normalization(
    monkeypatch,
) -> None:
    class FixedDate(mcp_sellersprite.dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 13)

    monkeypatch.setattr(mcp_sellersprite.dt, "date", FixedDate)
    capability = server_module.AGENT_TOOL_CAPABILITY_REGISTRY.get(
        "sellersprite_aba_research_weekly"
    )

    tool_input = capability.normalize_input(
        "sports bra",
        {
            "marketplace": "Amazon US",
            "request": {
                "marketplace": "US",
                "includeKeywords": "sports bra",
                "departments": ["sports bra"],
                "date": "20260711",
                "page": 2,
                "size": 50,
            },
        },
    )

    assert tool_input == {
        "request": {
            "marketplace": "US",
            "includeKeywords": "sports bra",
            "searchModel": 1,
            "date": "20260704",
            "page": 2,
            "size": 50,
        }
    }


def test_market_research_preserves_category_node_month_and_paging(monkeypatch) -> None:
    class FixedDate(mcp_sellersprite.dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 9)

    monkeypatch.setattr(mcp_sellersprite.dt, "date", FixedDate)
    capability = server_module.AGENT_TOOL_CAPABILITY_REGISTRY.get(
        "sellersprite_market_research"
    )

    tool_input = capability.normalize_input(
        "minimizer bra",
        {
            "marketplace": "Amazon US",
            "categoryNodeId": "2619525011:3741271",
            "month": "202606",
            "page": 3,
            "size": 40,
            "unsupported": "drop-me",
        },
    )

    assert tool_input == {
        "request": {
            "departmentKeyword": "minimizer bra",
            "marketplace": "US",
            "month": "202606",
            "nodeIdPath": "2619525011:3741271",
            "page": 3,
            "size": 40,
            "newProduct": 6,
            "topNum": 10,
        }
    }


def test_trademark_inputs_preserve_country_brand_and_paging() -> None:
    list_capability = server_module.AGENT_TOOL_CAPABILITY_REGISTRY.get(
        "sellersprite_trademark_list"
    )
    detail_capability = server_module.AGENT_TOOL_CAPABILITY_REGISTRY.get(
        "sellersprite_trademark_detail"
    )

    list_input = list_capability.normalize_input(
        "",
        {
            "request": {
                "text": "Example Brand",
                "office": ["US"],
                "page": 2,
                "size": 25,
            }
        },
    )
    detail_input = detail_capability.normalize_input(
        "",
        {"office": "US", "brandId": "SERIAL-1", "unsupported": "drop-me"},
    )

    assert list_input == {
        "request": {
            "text": "Example Brand",
            "office": ["US"],
            "page": 2,
            "size": 25,
        }
    }
    assert detail_input == {"office": "US", "brandId": "SERIAL-1"}


def test_second_batch_success_executes_through_registry(monkeypatch) -> None:
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
            "summary": "SellerSprite returned market evidence.",
            "duration_ms": 41,
            "input": tool_input,
            "data": {"items": [{"brand": "Example Brand"}]},
            "cache": {"hit": False},
        }

    monkeypatch.setattr(server_module, "execute_sellersprite_agent_tool", execute)

    result = server_module.execute_agent_tool(
        "sellersprite_trademark_list",
        "",
        {
            "bypassCache": True,
            "request": {"text": "Example Brand", "office": ["US"]},
        },
    )

    assert result["status"] == "ok"
    assert result["duration_ms"] == 41
    assert result["data"] == {"items": [{"brand": "Example Brand"}]}
    assert result["cache"] == {"hit": False}
    assert calls == [
        {
            "capability_id": "sellersprite_trademark_list",
            "tool_input": {
                "request": {
                    "text": "Example Brand",
                    "office": ["US"],
                    "page": 1,
                    "size": 100,
                }
            },
            "bypass_cache": True,
            "mcp_tool": "trademark_list",
        }
    ]


def test_second_batch_missing_credentials_and_provider_error_envelopes(
    monkeypatch,
) -> None:
    for env_name in (
        "SELLERSPRITE_MCP_SECRET_KEY",
        "SELLERSPRITE_SECRET_KEY",
        "SELLERSPRITE_API_KEY",
    ):
        monkeypatch.delenv(env_name, raising=False)

    missing_credentials = server_module.execute_agent_tool(
        "sellersprite_keepa_info",
        "",
        {"marketplace": "Amazon US", "asin": "B000000001", "bypassCache": True},
    )
    assert missing_credentials["status"] == "needs_user_action"
    assert "authentication" in missing_credentials["summary"].lower()
    assert missing_credentials["data"] == {}

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
    provider_error = server_module.execute_agent_tool(
        "sellersprite_market_rating_distribution",
        "",
        {"request": {"marketplace": "US", "nodeIdPath": "1:2"}},
    )
    assert provider_error["status"] == "error"
    assert provider_error["summary"] == "SellerSprite MCP HTTP 503: fixture unavailable"
    assert provider_error["duration_ms"] == 59
    assert provider_error["cache"] == {"hit": False}
    assert provider_error["data"] == {}

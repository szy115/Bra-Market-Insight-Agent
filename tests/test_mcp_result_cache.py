from __future__ import annotations

import json

from insight_agent import mcp_fastmoss, mcp_result_cache, mcp_sellersprite, mcp_sif, server


def test_mcp_cache_key_is_stable_across_dict_order() -> None:
    first = mcp_result_cache.mcp_result_cache_identity(
        "sif",
        "sif_market_get_keyword_demand",
        {"keywords": ["minimizer bra"], "country": "US"},
    )
    second = mcp_result_cache.mcp_result_cache_identity(
        "sif",
        "sif_market_get_keyword_demand",
        {"country": "US", "keywords": ["minimizer bra"]},
    )

    assert first == second
    assert mcp_result_cache.mcp_result_cache_ttl_seconds() == 7 * 24 * 60 * 60


def test_sellersprite_review_cache_uses_logical_time_range_for_derived_timestamps() -> None:
    first = {
        "marketplace": "US",
        "asin": "B000000001",
        "startTimestamp": 1_000,
        "endTimestamp": 2_000,
        mcp_sellersprite.INSIGHT_CONTEXT_KEY: {"balanced_review": True, "cache_time_range": "180d"},
    }
    second = {**first, "startTimestamp": 3_000, "endTimestamp": 4_000}

    first_key = mcp_result_cache.mcp_result_cache_identity(
        "sellersprite",
        "sellersprite_review",
        mcp_sellersprite._sellersprite_cache_params(first),
    )
    second_key = mcp_result_cache.mcp_result_cache_identity(
        "sellersprite",
        "sellersprite_review",
        mcp_sellersprite._sellersprite_cache_params(second),
    )

    assert first_key == second_key


def test_mcp_cache_expires_after_ttl(monkeypatch) -> None:
    now = [1_000_000.0]
    monkeypatch.setattr(mcp_result_cache.time, "time", lambda: now[0])
    params = {"country": "US", "keyword": "minimizer bra"}
    result = {"name": "tool", "status": "ok", "data": {"value": 1}}

    mcp_result_cache.write_mcp_result_cache("sif", "tool", params, result, ttl_seconds=60)
    assert mcp_result_cache.read_mcp_result_cache("sif", "tool", params, ttl_seconds=60) is not None

    path = mcp_result_cache.mcp_result_cache_path("sif", "tool", params)
    now[0] += 61

    assert mcp_result_cache.read_mcp_result_cache("sif", "tool", params, ttl_seconds=60) is None
    assert not path.exists()


def test_empty_mcp_result_is_not_cached() -> None:
    calls = {"count": 0}

    def execute() -> dict:
        calls["count"] += 1
        return {"name": "tool", "status": "empty", "data": {"list": [], "total": 0}}

    first = mcp_result_cache.execute_with_mcp_result_cache(
        "fastmoss", "ranking", {"page": 1}, execute
    )
    second = mcp_result_cache.execute_with_mcp_result_cache(
        "fastmoss", "ranking", {"page": 1}, execute
    )

    assert calls["count"] == 2
    assert first["cache"]["stored"] is False
    assert second["cache"]["hit"] is False


def test_sif_reuses_cached_result_and_bypass_refreshes(monkeypatch) -> None:
    agent_tool_name = "sif_market_get_keyword_demand"
    monkeypatch.setattr(
        mcp_sif,
        "get_sif_tool_catalog",
        lambda: {
            agent_tool_name: {
                "label": "Sif keyword demand",
                "mcp_tool": "market_get_keyword_demand",
            }
        },
    )
    calls: list[dict] = []

    def fake_call(_tool_name, arguments):
        calls.append(arguments)
        value = len(calls)
        return {"content": [{"type": "text", "text": f'{{"keywords":[{{"volume":{value}}}]}}'}]}

    monkeypatch.setattr(mcp_sif, "call_sif_mcp_tool", fake_call)
    params = {"keywords": ["minimizer bra"], "country": "US"}

    first = mcp_sif.execute_sif_agent_tool(agent_tool_name, params)
    cached = mcp_sif.execute_sif_agent_tool(
        agent_tool_name,
        {"country": "US", "keywords": ["minimizer bra"]},
    )
    refreshed = mcp_sif.execute_sif_agent_tool(agent_tool_name, params, bypass_cache=True)
    cached_refresh = mcp_sif.execute_sif_agent_tool(agent_tool_name, params)

    assert len(calls) == 2
    assert first["cache"]["stored"] is True
    assert cached["cache"]["hit"] is True
    assert refreshed["cache"]["bypassed"] is True
    assert refreshed["cache"]["refreshed"] is True
    assert cached_refresh["cache"]["hit"] is True
    assert cached_refresh["data"]["keywords"][0]["volume"] == 2


def test_fastmoss_reuses_cached_result_and_bypass_refreshes(monkeypatch) -> None:
    agent_tool_name = "mcp__fastmoss__market_category_analysis"
    monkeypatch.setenv("FASTMOSS_MCP_API_KEY", "test-fastmoss-key")
    monkeypatch.setattr(
        mcp_fastmoss,
        "get_fastmoss_tool_catalog",
        lambda: {
            agent_tool_name: {
                "label": "FastMoss category analysis",
                "mcp_tool": "market_category_analysis",
                "input_schema": {
                    "type": "object",
                    "properties": {"filter": {"type": "object"}, "analysis_type": {"type": "string"}},
                },
            }
        },
    )
    calls: list[dict] = []

    def fake_call(_tool_name, arguments):
        calls.append(arguments)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"data": {"gmv": len(calls)}}),
                }
            ]
        }

    monkeypatch.setattr(mcp_fastmoss, "call_fastmoss_mcp_tool", fake_call)
    params = {"analysis_type": "basic_metrics", "filter": {"category_id": "123", "region": "US"}}

    first = mcp_fastmoss.execute_fastmoss_agent_tool(agent_tool_name, params)
    cached = mcp_fastmoss.execute_fastmoss_agent_tool(
        agent_tool_name,
        {"filter": {"region": "US", "category_id": "123"}, "analysis_type": "basic_metrics"},
    )
    refreshed = mcp_fastmoss.execute_fastmoss_agent_tool(agent_tool_name, params, bypass_cache=True)
    cached_refresh = mcp_fastmoss.execute_fastmoss_agent_tool(agent_tool_name, params)

    assert len(calls) == 2
    assert first["cache"]["stored"] is True
    assert cached["cache"]["hit"] is True
    assert refreshed["cache"]["bypassed"] is True
    assert refreshed["cache"]["refreshed"] is True
    assert cached_refresh["cache"]["hit"] is True
    assert cached_refresh["data"]["data"]["gmv"] == 2


def test_fastmoss_plain_text_credit_exhaustion_requires_user_action_and_is_not_cached(
    monkeypatch,
) -> None:
    agent_tool_name = "mcp__fastmoss__shop_creator_analysis"
    calls = {"count": 0}
    monkeypatch.setattr(
        mcp_fastmoss,
        "get_fastmoss_tool_catalog",
        lambda: {
            agent_tool_name: {
                "label": "FastMoss creator analysis",
                "mcp_tool": "shop_creator_analysis",
            }
        },
    )

    def fake_call(_tool_name, _arguments):
        calls["count"] += 1
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        "ACTION REQUIRED — FastMoss credits exhausted. "
                        "Your credit balance is 0. Please recharge your FastMoss account."
                    ),
                }
            ]
        }

    monkeypatch.setattr(mcp_fastmoss, "call_fastmoss_mcp_tool", fake_call)
    params = {"filter": {"seller_id": "seller-01", "time_range_days": 28}}

    first = mcp_fastmoss.execute_fastmoss_agent_tool(agent_tool_name, params)
    second = mcp_fastmoss.execute_fastmoss_agent_tool(agent_tool_name, params)

    assert calls["count"] == 2
    assert first["status"] == "needs_user_action"
    assert "credits are exhausted" in first["summary"]
    assert first["cache"]["stored"] is False
    assert second["cache"]["hit"] is False


def test_fastmoss_catalog_and_input_use_exact_skill_tool_name(monkeypatch) -> None:
    monkeypatch.delenv("FASTMOSS_MCP_TOOLS", raising=False)
    catalog = mcp_fastmoss.build_fastmoss_tool_catalog(
        [
            {
                "name": "market_category_analysis",
                "description": "Analyze a TikTok Shop category.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"filter": {"type": "object"}, "analysis_type": {"type": "string"}},
                },
            },
            {"name": "unrelated_admin_tool", "inputSchema": {"type": "object", "properties": {}}},
        ]
    )
    agent_tool_name = "mcp__fastmoss__market_category_analysis"
    monkeypatch.setattr(mcp_fastmoss, "get_fastmoss_tool_catalog", lambda: catalog)

    payload = mcp_fastmoss.build_fastmoss_input_payload(
        agent_tool_name,
        "minimizer bra",
        {
            "marketplace": "MX",
            "params": {"category_node_id": "987"},
            "analysis_type": "sales_trends",
        },
    )

    assert set(catalog) == {agent_tool_name}
    assert payload == {
        "analysis_type": "sales_trends",
        "filter": {"region": "MX", "category_id": "987"},
    }


def test_fastmoss_input_drops_composite_region_and_schema_extras(monkeypatch) -> None:
    agent_tool_name = "mcp__fastmoss__product_overview"
    monkeypatch.setattr(
        mcp_fastmoss,
        "get_fastmoss_tool_catalog",
        lambda: {
            agent_tool_name: {
                "mcp_tool": "product_overview",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filter": {
                            "type": "object",
                            "properties": {
                                "product_id": {"type": "string"},
                                "time_range_days": {"type": "integer"},
                            },
                        }
                    },
                },
            }
        },
    )

    payload = mcp_fastmoss.build_fastmoss_input_payload(
        agent_tool_name,
        "minimizer bra",
        {
            "marketplace": "North America (US+MX)",
            "params": {"category_node_id": "601262"},
            "filter": {
                "product_id": "1730000000000000000",
                "time_range_days": 28,
                "region": "North America (US+MX)",
                "category_id": 601262,
            },
        },
    )

    assert payload == {
        "filter": {
            "product_id": "1730000000000000000",
            "time_range_days": 28,
        }
    }


def test_fastmoss_market_tool_rejects_missing_explicit_region(monkeypatch) -> None:
    agent_tool_name = "mcp__fastmoss__market_category_analysis"
    calls: list[dict] = []
    monkeypatch.setattr(
        mcp_fastmoss,
        "get_fastmoss_tool_catalog",
        lambda: {
            agent_tool_name: {
                "label": "FastMoss category analysis",
                "mcp_tool": "market_category_analysis",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "analysis_type": {"type": "string"},
                        "filter": {
                            "type": "object",
                            "properties": {
                                "category_id": {"type": "integer"},
                                "region": {"type": "string"},
                            },
                        },
                    },
                },
            }
        },
    )
    monkeypatch.setattr(
        mcp_fastmoss,
        "call_fastmoss_mcp_tool",
        lambda _tool_name, arguments: calls.append(arguments) or {},
    )
    input_payload = mcp_fastmoss.build_fastmoss_input_payload(
        agent_tool_name,
        "minimizer bra",
        {
            "marketplace": "North America (US+MX)",
            "analysis_type": "basic_metrics",
            "filter": {"category_id": 601262},
        },
    )

    result = mcp_fastmoss._execute_fastmoss_agent_tool_uncached(agent_tool_name, input_payload)

    assert input_payload["filter"] == {"category_id": 601262}
    assert result["status"] == "error"
    assert "call US and MX separately" in result["summary"]
    assert calls == []


def test_fastmoss_normalizer_marks_empty_records_as_missing_evidence() -> None:
    list_status, list_data = mcp_fastmoss.normalize_fastmoss_result(
        {"content": [{"type": "text", "text": '{"list":[],"total":0}'}]}
    )
    metrics_status, metrics_data = mcp_fastmoss.normalize_fastmoss_result(
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "analysis_type": "basic_metrics",
                            "category": {"category_id": 601262, "category_name": "Bras", "region": "US"},
                            "scale_metrics": {"category_gmv": 0, "category_units_sold": 0},
                            "top_products_summary": [],
                        }
                    ),
                }
            ]
        }
    )
    usable_status, _ = mcp_fastmoss.normalize_fastmoss_result(
        {"content": [{"type": "text", "text": '{"list":[],"total":0,"gmv":1250}'}]}
    )

    assert list_status == "empty"
    assert metrics_status == "empty"
    assert usable_status == "ok"
    assert "missing data" in mcp_fastmoss.summarize_fastmoss_data(agent_tool_name="tool", data=list_data)
    assert "missing data" in mcp_fastmoss.summarize_fastmoss_data(agent_tool_name="tool", data=metrics_data)


def test_fastmoss_reclassifies_legacy_cached_empty_result(monkeypatch) -> None:
    monkeypatch.setattr(
        mcp_fastmoss,
        "execute_with_mcp_result_cache",
        lambda *_args, **_kwargs: {
            "name": "mcp__fastmoss__product_rank_new_listed",
            "status": "ok",
            "summary": "MCP cache hit. FastMoss returned 0 item(s) in `list`.",
            "data": {"list": [], "total": 0},
            "cache": {"hit": True},
        },
    )

    result = mcp_fastmoss.execute_fastmoss_agent_tool(
        "mcp__fastmoss__product_rank_new_listed",
        {"filter": {"region": "US"}},
    )

    assert result["status"] == "empty"
    assert result["cache"]["hit"] is True
    assert result["summary"].startswith("MCP cache hit.")


def test_sellersprite_reuses_cached_result(monkeypatch) -> None:
    agent_tool_name = "sellersprite_asin_detail"
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")
    monkeypatch.setattr(
        mcp_sellersprite,
        "get_sellersprite_tool_catalog",
        lambda: {
            agent_tool_name: {
                "label": "SellerSprite ASIN detail",
                "mcp_tool": "asin_detail",
                "input_schema": {
                    "type": "object",
                    "properties": {"marketplace": {"type": "string"}, "asin": {"type": "string"}},
                    "required": ["marketplace", "asin"],
                },
            }
        },
    )
    calls: list[dict] = []

    def fake_call(_tool_name, arguments):
        calls.append(arguments)
        return {"content": [{"type": "text", "text": '{"data":{"asin":"B000000001"}}'}]}

    monkeypatch.setattr(mcp_sellersprite, "call_sellersprite_mcp_tool", fake_call)
    params = {"marketplace": "US", "asin": "B000000001"}

    first = mcp_sellersprite.execute_sellersprite_agent_tool(agent_tool_name, params)
    cached = mcp_sellersprite.execute_sellersprite_agent_tool(agent_tool_name, dict(reversed(list(params.items()))))

    assert len(calls) == 1
    assert first["cache"]["stored"] is True
    assert cached["cache"]["hit"] is True
    assert cached["data"]["data"]["asin"] == "B000000001"


def test_competitor_review_cache_reuses_same_marketplace_asin_across_request_shapes(monkeypatch) -> None:
    agent_tool_name = "sellersprite_review"
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")
    monkeypatch.setattr(
        mcp_sellersprite,
        "get_sellersprite_tool_catalog",
        lambda: {
            agent_tool_name: {
                "label": "SellerSprite reviews",
                "mcp_tool": "review",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "marketplace": {"type": "string"},
                        "asin": {"type": "string"},
                        "starList": {"type": "array"},
                        "page": {"type": "integer"},
                        "size": {"type": "integer"},
                    },
                    "required": ["marketplace", "asin"],
                },
            }
        },
    )
    calls: list[dict] = []

    def fake_call(_tool_name, arguments):
        calls.append(dict(arguments))
        stars = arguments["starList"]
        payload = {
            "code": "OK",
            "data": {
                "page": arguments["page"],
                "total": 1,
                "items": [
                    {
                        "id": f"R-{stars[0]}",
                        "star": stars[-1],
                        "title": f"Bucket {stars}",
                        "content": "Cached review",
                    }
                ],
            },
        }
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    monkeypatch.setattr(mcp_sellersprite, "call_sellersprite_mcp_tool", fake_call)
    context = {
        mcp_sellersprite.INSIGHT_CONTEXT_KEY: {
            "exhaustive_review": True,
            "review_target": 500,
        }
    }
    first = mcp_sellersprite.execute_sellersprite_agent_tool(
        agent_tool_name,
        {"marketplace": "US", "asin": "B000000001", "page": 1, "size": 20, **context},
    )
    cached = mcp_sellersprite.execute_sellersprite_agent_tool(
        agent_tool_name,
        {"size": 100, "page": 9, "asin": "B000000001", "marketplace": "US", **context},
    )

    assert len(calls) == 2
    assert first["cache"]["stored"] is True
    assert first["cache"]["scope"] == "marketplace_asin"
    assert cached["cache"]["hit"] is True
    assert cached["cache"]["scope"] == "marketplace_asin"
    assert cached["cache"]["cache_tool"] == mcp_sellersprite.SELLERSPRITE_REVIEW_ASIN_CACHE_TOOL
    assert len(cached["data"]["data"]["items"]) == 2


def test_failed_mcp_result_is_not_cached(monkeypatch) -> None:
    agent_tool_name = "sif_market_get_keyword_demand"
    monkeypatch.setattr(
        mcp_sif,
        "get_sif_tool_catalog",
        lambda: {agent_tool_name: {"label": "Sif keyword demand", "mcp_tool": "keyword_demand"}},
    )
    calls = [0]

    def fake_call(_tool_name, _arguments):
        calls[0] += 1
        raise RuntimeError("temporary MCP failure")

    monkeypatch.setattr(mcp_sif, "call_sif_mcp_tool", fake_call)
    params = {"keywords": ["minimizer bra"], "country": "US"}

    first = mcp_sif.execute_sif_agent_tool(agent_tool_name, params)
    second = mcp_sif.execute_sif_agent_tool(agent_tool_name, params)

    assert calls[0] == 2
    assert first["status"] == "error"
    assert first["cache"]["stored"] is False
    assert second["cache"]["hit"] is False


def test_server_forwards_bypass_cache_to_mcp_adapter(monkeypatch) -> None:
    captured: dict = {}

    def fake_execute(tool_name, tool_input, *, bypass_cache=False):
        captured.update({"tool_name": tool_name, "tool_input": tool_input, "bypass_cache": bypass_cache})
        return {"name": tool_name, "status": "ok", "data": {}}

    monkeypatch.setattr(server, "agent_tool_catalog", lambda: {})
    monkeypatch.setattr(server, "agent_tool_input_payload", lambda _name, _category, _payload: {"keyword": "bra"})
    monkeypatch.setattr(server, "execute_sif_agent_tool", fake_execute)

    server.execute_agent_tool(
        "sif_market_get_keyword_demand",
        "minimizer bra",
        {"bypassCache": True},
    )

    assert captured == {
        "tool_name": "sif_market_get_keyword_demand",
        "tool_input": {"keyword": "bra"},
        "bypass_cache": True,
    }


def test_server_forwards_bypass_cache_to_fastmoss_adapter(monkeypatch) -> None:
    captured: dict = {}

    def fake_execute(tool_name, tool_input, *, bypass_cache=False):
        captured.update({"tool_name": tool_name, "tool_input": tool_input, "bypass_cache": bypass_cache})
        return {"name": tool_name, "status": "ok", "data": {}}

    monkeypatch.setattr(server, "agent_tool_catalog", lambda: {})
    monkeypatch.setattr(
        server,
        "agent_tool_input_payload",
        lambda _name, _category, _payload: {"filter": {"region": "US"}},
    )
    monkeypatch.setattr(server, "execute_fastmoss_agent_tool", fake_execute)

    server.execute_agent_tool(
        "mcp__fastmoss__market_category_analysis",
        "minimizer bra",
        {"bypassCache": True},
    )

    assert captured == {
        "tool_name": "mcp__fastmoss__market_category_analysis",
        "tool_input": {"filter": {"region": "US"}},
        "bypass_cache": True,
    }

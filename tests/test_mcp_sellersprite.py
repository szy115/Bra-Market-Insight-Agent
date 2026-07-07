from insight_agent import mcp_sellersprite


SELLERSPRITE_SAMPLE_SCHEMA = [
    {
        "name": "market_research",
        "description": "SellerSprite market research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string"},
                "marketplace": {"type": "string"},
                "asin": {"type": "string"},
            },
            "required": ["keyword"],
            "additionalProperties": False,
        },
    },
    {
        "name": "keyword_history",
        "description": "SellerSprite keyword history",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}},
                "country": {"type": "string"},
            },
            "required": ["keywords"],
            "additionalProperties": False,
        },
    },
]


def test_build_sellersprite_tool_catalog_prefixes_tools(monkeypatch) -> None:
    monkeypatch.delenv("SELLERSPRITE_MCP_TOOLS", raising=False)

    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_SAMPLE_SCHEMA)

    assert "sellersprite_market_research" in catalog
    assert "sellersprite_keyword_history" in catalog
    assert catalog["sellersprite_market_research"]["mcp_tool"] == "market_research"
    assert catalog["sellersprite_market_research"]["source"] == "sellersprite_mcp"
    assert catalog["sellersprite_market_research"]["auth_env_names"] == [
        "SELLERSPRITE_MCP_SECRET_KEY",
        "SELLERSPRITE_SECRET_KEY",
        "SELLERSPRITE_API_KEY",
    ]


def test_build_sellersprite_tool_catalog_can_be_curated(monkeypatch) -> None:
    monkeypatch.setenv("SELLERSPRITE_MCP_TOOLS", "keyword_history")

    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_SAMPLE_SCHEMA)

    assert "sellersprite_keyword_history" in catalog
    assert "sellersprite_market_research" not in catalog


def test_build_sellersprite_input_payload_filters_to_schema(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_SAMPLE_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)

    payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_market_research",
        "minimizer bra",
        {
            "category": "minimizer bra",
            "marketplace": "Amazon US",
            "asin": "B012345678",
            "prompt": "should not be sent",
        },
    )

    assert payload == {
        "asin": "B012345678",
        "keyword": "minimizer bra",
        "marketplace": "Amazon US",
    }


def test_build_sellersprite_input_payload_adds_keyword_array_and_country(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_SAMPLE_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)

    payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_keyword_history",
        "minimizer bra",
        {"marketplace": "US"},
    )

    assert payload == {
        "country": "US",
        "keywords": ["minimizer bra"],
    }


def test_normalize_sellersprite_result_parses_text_content_json() -> None:
    status, data = mcp_sellersprite.normalize_sellersprite_result(
        {
            "content": [
                {
                    "type": "text",
                    "text": '{"items":[{"keyword":"minimizer bra","volume":123}],"summary":"ok"}',
                }
            ]
        }
    )

    assert status == "ok"
    assert data["items"][0]["keyword"] == "minimizer bra"
    assert data["summary"] == "ok"


def test_execute_sellersprite_agent_tool_returns_needs_user_action_without_secret(monkeypatch) -> None:
    monkeypatch.delenv("SELLERSPRITE_MCP_SECRET_KEY", raising=False)
    monkeypatch.delenv("SELLERSPRITE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SELLERSPRITE_API_KEY", raising=False)
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_SAMPLE_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)

    result = mcp_sellersprite.execute_sellersprite_agent_tool(
        "sellersprite_market_research",
        {"keyword": "minimizer bra", "marketplace": "US"},
    )

    assert result["status"] == "needs_user_action"
    assert "SellerSprite MCP requires authentication" in result["summary"]

from insight_agent import mcp_sif

SIF_SAMPLE_SCHEMA = [
    {
        "name": "market_get_keyword_demand",
        "description": "需求判断层",
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
    {
        "name": "market_get_keyword_history",
        "description": "ABA 历史数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}},
                "country": {"type": "string"},
                "granularity": {"type": "string"},
            },
            "required": ["keywords"],
            "additionalProperties": False,
        },
    },
    {"name": "ping", "description": "", "inputSchema": {"type": "object", "properties": {}}},
]


def test_build_sif_tool_catalog_prefixes_curated_tools(monkeypatch) -> None:
    monkeypatch.delenv("SIF_MCP_TOOLS", raising=False)

    catalog = mcp_sif.build_sif_tool_catalog(SIF_SAMPLE_SCHEMA)

    assert "sif_market_get_keyword_demand" in catalog
    assert "sif_market_get_keyword_history" in catalog
    assert "sif_ping" not in catalog
    assert catalog["sif_market_get_keyword_demand"]["mcp_tool"] == "market_get_keyword_demand"
    assert catalog["sif_market_get_keyword_demand"]["input_schema"]["required"] == ["keywords"]


def test_build_sif_input_payload_filters_to_schema_and_adds_defaults(monkeypatch) -> None:
    catalog = mcp_sif.build_sif_tool_catalog(SIF_SAMPLE_SCHEMA)
    monkeypatch.setattr(mcp_sif, "get_sif_tool_catalog", lambda: catalog)

    payload = mcp_sif.build_sif_input_payload(
        "sif_market_get_keyword_history",
        "minimizer bra",
        {
            "category": "minimizer bra",
            "marketplace": "Amazon US",
            "prompt": "should not be sent",
            "bypassCache": True,
        },
    )

    assert payload == {
        "country": "US",
        "granularity": "week",
        "keywords": ["minimizer bra"],
    }


def test_normalize_sif_result_parses_text_content_json() -> None:
    status, data = mcp_sif.normalize_sif_result(
        {
            "content": [
                {
                    "type": "text",
                    "text": '{"keywords":[{"keyword":"minimizer bra","latest":{"volume":123}}],"render_footer":"verify"}',
                }
            ]
        }
    )

    assert status == "ok"
    assert data["keywords"][0]["keyword"] == "minimizer bra"
    assert data["render_footer"] == "verify"


def test_execute_sif_agent_tool_returns_needs_user_action_without_token(monkeypatch) -> None:
    monkeypatch.delenv("SIF_MCP_TOKEN", raising=False)
    monkeypatch.delenv("SIF_API_KEY", raising=False)
    monkeypatch.delenv("SIF_TOKEN", raising=False)
    catalog = mcp_sif.build_sif_tool_catalog(SIF_SAMPLE_SCHEMA)
    monkeypatch.setattr(mcp_sif, "get_sif_tool_catalog", lambda: catalog)

    result = mcp_sif.execute_sif_agent_tool(
        "sif_market_get_keyword_demand",
        {"keywords": ["minimizer bra"], "country": "US"},
    )

    assert result["status"] == "needs_user_action"
    assert "Sif MCP requires authentication" in result["summary"]

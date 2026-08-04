import json

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
    {
        "name": "market_product_concentration",
        "description": "SellerSprite product concentration",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "object",
                    "properties": {
                        "marketplace": {"type": "string"},
                        "month": {"type": "string"},
                        "nodeIdPath": {"type": "string"},
                        "newProduct": {"type": "integer"},
                        "topN": {"type": "integer"},
                    },
                    "required": ["marketplace", "nodeIdPath"],
                }
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
]


SELLERSPRITE_MARKET_RESEARCH_REQUEST_SCHEMA = [
    {
        "name": "market_research",
        "description": "SellerSprite market research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "object",
                    "properties": {
                        "marketplace": {"type": "string"},
                        "departmentKeyword": {"type": "string"},
                        "month": {"type": "string"},
                        "size": {"type": "integer"},
                        "page": {"type": "integer"},
                        "newProduct": {"type": "integer"},
                        "topNum": {"type": "integer"},
                    },
                    "required": ["marketplace", "departmentKeyword", "month", "size", "page"],
                }
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
]


SELLERSPRITE_KEYWORD_RESEARCH_REQUEST_SCHEMA = [
    {
        "name": "keyword_research",
        "description": "SellerSprite keyword research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "object",
                    "properties": {
                        "departments": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "keywords": {"type": "string"},
                        "marketplace": {"type": "string"},
                        "month": {"type": "string"},
                        "page": {"type": "integer"},
                        "size": {"type": "integer"},
                    },
                    "required": ["marketplace"],
                }
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
]


SELLERSPRITE_ABA_WEEKLY_SCHEMA = [
    {
        "name": "aba_research_weekly",
        "description": "SellerSprite weekly ABA research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "object",
                    "properties": {
                        "marketplace": {"type": "string"},
                        "includeKeywords": {"type": "string"},
                        "departments": {"type": "array", "items": {"type": "string"}},
                        "searchModel": {"type": "integer"},
                        "date": {"type": "string"},
                        "page": {"type": "integer"},
                        "size": {"type": "integer"},
                    },
                    "required": ["marketplace", "date", "page", "size"],
                }
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    }
]


SELLERSPRITE_GOOGLE_TREND_SCHEMA = [
    {
        "name": "google_trend",
        "description": "SellerSprite Google Trends proxy",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "object",
                    "properties": {
                        "googleProp": {"type": "string"},
                        "keyword": {"type": "string"},
                        "marketplace": {"type": "string"},
                        "monthly": {"type": "boolean"},
                        "returnFields": {"type": "string"},
                    },
                    "required": ["keyword", "marketplace"],
                }
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    }
]


SELLERSPRITE_ASIN_DETAIL_SCHEMA = [
    {
        "name": "asin_detail",
        "description": "SellerSprite ASIN detail",
        "inputSchema": {
            "type": "object",
            "properties": {
                "marketplace": {"type": "string"},
                "asin": {"type": "string"},
            },
            "required": ["marketplace", "asin"],
            "additionalProperties": False,
        },
    }
]


SELLERSPRITE_REVIEW_SCHEMA = [
    {
        "name": "review",
        "description": "SellerSprite reviews",
        "inputSchema": {
            "type": "object",
            "properties": {
                "marketplace": {"type": "string"},
                "asin": {"type": "string"},
                "starList": {"type": "array", "items": {"type": "integer"}},
                "typeList": {"type": "array", "items": {"type": "integer"}},
                "page": {"type": "integer"},
                "size": {"type": "integer"},
                "startTimestamp": {"type": "integer"},
                "endTimestamp": {"type": "integer"},
            },
            "required": ["marketplace", "asin"],
            "additionalProperties": False,
        },
    }
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
        "marketplace": "US",
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


def test_request_month_uses_previous_complete_month() -> None:
    assert mcp_sellersprite._request_month(mcp_sellersprite.dt.date(2026, 7, 9)) == "202606"
    assert mcp_sellersprite._request_month(mcp_sellersprite.dt.date(2026, 1, 9)) == "202512"


def test_aba_weekly_request_forces_previous_complete_week_and_removes_department_text(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_ABA_WEEKLY_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)

    class FixedDate(mcp_sellersprite.dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 13)

    monkeypatch.setattr(mcp_sellersprite.dt, "date", FixedDate)

    payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_aba_research_weekly",
        "sports bra",
        {
            "marketplace": "Amazon US",
            "category": "sports bra",
            "request": {
                "marketplace": "US",
                "includeKeywords": "sports bra",
                "departments": ["sports bra"],
                "date": "20260711",
                "page": 1,
                "size": 20,
            },
        },
    )

    assert payload == {
        "request": {
            "marketplace": "US",
            "includeKeywords": "sports bra",
            "searchModel": 1,
            "date": "20260704",
            "page": 1,
            "size": 20,
        }
    }


def test_google_trend_request_defaults_to_monthly_web_and_preserves_explicit_scope(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_GOOGLE_TREND_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)

    default_payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_google_trend",
        "minimizer bra",
        {"marketplace": "Amazon US"},
    )
    explicit_payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_google_trend",
        "minimizer bra",
        {
            "marketplace": "US",
            "request": {
                "googleProp": "shoppingCart",
                "monthly": False,
                "returnFields": "timeline",
            },
        },
    )
    weekly_market_payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_google_trend",
        "minimizer bra",
        {
            "skillId": "weekly_market_insight",
            "marketplace": "US",
            "request": {"monthly": False},
        },
    )

    assert default_payload == {
        "request": {
            "googleProp": "web",
            "keyword": "minimizer bra",
            "marketplace": "US",
            "monthly": True,
        }
    }
    assert explicit_payload == {
        "request": {
            "googleProp": "shoppingCart",
            "keyword": "minimizer bra",
            "marketplace": "US",
            "monthly": False,
            "returnFields": "timeline",
        }
    }
    assert weekly_market_payload["request"]["monthly"] is True


def test_execute_aba_weekly_retries_one_earlier_week_on_date_error(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_ABA_WEEKLY_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")
    requests: list[dict] = []

    def fake_call(_tool_name, arguments):
        request = dict(arguments["request"])
        requests.append(request)
        if len(requests) == 1:
            payload = '{"code":"ERROR_PARAM","message":"日期参数错误，只能查询上一周的数据"}'
        else:
            payload = '{"data":{"total":1,"items":[{"keyword":"sports bra","searches":12000}]}}'
        return {"content": [{"type": "text", "text": payload}]}

    monkeypatch.setattr(mcp_sellersprite, "call_sellersprite_mcp_tool", fake_call)
    result = mcp_sellersprite.execute_sellersprite_agent_tool(
        "sellersprite_aba_research_weekly",
        {
            "request": {
                "marketplace": "US",
                "includeKeywords": "sports bra",
                "searchModel": 1,
                "date": "20260704",
                "page": 1,
                "size": 20,
            }
        },
    )

    assert [request["date"] for request in requests] == ["20260704", "20260627"]
    assert result["status"] == "ok"
    assert result["input"]["request"]["date"] == "20260627"
    assert result["data"]["query_resolution"]["selected_date"] == "20260627"
    assert "recovered" in result["summary"]


def test_build_sellersprite_input_payload_wraps_request_object(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_SAMPLE_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)
    monkeypatch.setattr(mcp_sellersprite.dt, "date", type("FixedDate", (mcp_sellersprite.dt.date,), {
        "today": classmethod(lambda cls: cls(2026, 7, 7)),
    }))

    payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_market_product_concentration",
        "minimizer bra",
        {
            "marketplace": "Amazon US",
            "category_node_id": "7141123011:7147440011:1040660:9522931011:14333511:1044960:1045002",
            "head_listing_count": 10,
            "new_product_window": "180d",
            "prompt": "should not be sent",
        },
    )

    assert payload == {
        "request": {
            "marketplace": "US",
            "month": "202606",
            "newProduct": 6,
            "nodeIdPath": "7141123011:7147440011:1040660:9522931011:14333511:1044960:1045002",
            "topN": 10,
        }
    }


def test_demand_trend_request_omits_month_for_rolling_series(monkeypatch) -> None:
    schema = [
        {
            "name": "market_product_demand_trend",
            "description": "SellerSprite rolling category demand trend",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {
                        "type": "object",
                        "properties": {
                            "marketplace": {"type": "string"},
                            "month": {"type": "string"},
                            "nodeIdPath": {"type": "string"},
                            "newProduct": {"type": "integer"},
                            "topN": {"type": "integer"},
                        },
                        "required": ["marketplace", "nodeIdPath"],
                    }
                },
                "required": ["request"],
            },
        }
    ]
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(schema)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)

    payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_market_product_demand_trend",
        "minimizer bra",
        {
            "marketplace": "US",
            "category_node_id": "7141123011:1045002",
            "request": {"month": "202606"},
        },
    )

    assert payload["request"]["nodeIdPath"] == "7141123011:1045002"
    assert "month" not in payload["request"]
    assert "newProduct" not in payload["request"]
    assert "topN" not in payload["request"]


def test_build_sellersprite_input_payload_overrides_model_invented_market_month(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_MARKET_RESEARCH_REQUEST_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)

    class FixedDate(mcp_sellersprite.dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 9)

    monkeypatch.setattr(mcp_sellersprite.dt, "date", FixedDate)

    payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_market_research",
        "back smoothing bra",
        {
            "prompt": (
                "使用 hot_product_pain_analysis Skill 做爆款痛点分析。"
                "参数：marketplace=Amazon US；category=back smoothing bra；head_listing_count=10。"
            ),
            "marketplace": "Amazon US",
            "category": "back smoothing bra",
            "head_listing_count": 10,
            "request": {
                "marketplace": "US",
                "departmentKeyword": "back smoothing bra",
                "month": "202503",
                "size": 10,
                "page": 1,
            },
        },
    )

    assert payload["request"]["month"] == "202606"


def test_build_sellersprite_input_payload_keeps_user_mentioned_market_month(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_MARKET_RESEARCH_REQUEST_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)

    class FixedDate(mcp_sellersprite.dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 9)

    monkeypatch.setattr(mcp_sellersprite.dt, "date", FixedDate)

    payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_market_research",
        "back smoothing bra",
        {
            "prompt": "分析 2025-03 的 back smoothing bra 市场。",
            "marketplace": "Amazon US",
            "category": "back smoothing bra",
            "request": {
                "marketplace": "US",
                "departmentKeyword": "back smoothing bra",
                "month": "202503",
                "size": 10,
                "page": 1,
            },
        },
    )

    assert payload["request"]["month"] == "202503"


def test_build_sellersprite_input_payload_does_not_infer_departments_from_category(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_KEYWORD_RESEARCH_REQUEST_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)

    class FixedDate(mcp_sellersprite.dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 9)

    monkeypatch.setattr(mcp_sellersprite.dt, "date", FixedDate)

    payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_keyword_research",
        "minimizer bra",
        {
            "prompt": "分析 minimizer bra。",
            "marketplace": "Amazon US",
            "category": "minimizer bra",
            "size": 10,
            "page": 1,
        },
    )

    assert payload == {
        "request": {
            "keywords": "minimizer bra",
            "marketplace": "US",
            "month": "202606",
            "page": 1,
            "size": 10,
        }
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
    assert "raw" not in data
    assert "text" not in data
    assert "parsed_content" not in data


def test_build_review_input_uses_skill_sample_size_and_recent_window(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_REVIEW_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)

    payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_review",
        "minimizer bra",
        {
            "skillId": "hot_product_pain_analysis",
            "marketplace": "Amazon US",
            "asin": "B08MVF8QDL",
            "size": 20,
            "starList": [1, 2, 3],
            "params": {"review_sample_size": 30, "time_range": "180d"},
        },
    )

    assert payload["marketplace"] == "US"
    assert payload["asin"] == "B08MVF8QDL"
    assert payload["size"] == 30
    assert payload["page"] == 1
    assert "starList" not in payload
    assert 179 * 24 * 60 * 60 * 1000 <= payload["endTimestamp"] - payload["startTimestamp"] <= 181 * 24 * 60 * 60 * 1000


def test_product_design_review_uses_balanced_sampling_defaults(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_REVIEW_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)

    payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_review",
        "strapless bra",
        {
            "skillId": "product_design_research",
            "marketplace": "Amazon US",
            "asin": "B08MVF8QDL",
            "starList": [5],
            "params": {"review_sample_size": 60, "time_range": "180d"},
        },
    )

    assert payload["size"] == 60
    assert "starList" not in payload
    assert payload[mcp_sellersprite.INSIGHT_CONTEXT_KEY] == {
        "balanced_review": True,
        "cache_time_range": "180d",
    }


def test_competitor_review_uses_full_history_and_exhaustive_pagination_context(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_REVIEW_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)

    payload = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_review",
        "post surgery bra",
        {
            "skillId": "competitor_product_deep_dive",
            "marketplace": "Amazon US",
            "asin": "B08MVF8QDL",
            "starList": [4, 5],
            "startTimestamp": 1_700_000_000_000,
            "endTimestamp": 1_800_000_000_000,
            "params": {"review_sample_size": 500, "time_range": "year"},
        },
    )

    assert payload["size"] == 100
    assert payload["page"] == 1
    assert "starList" not in payload
    assert "startTimestamp" not in payload
    assert "endTimestamp" not in payload
    assert payload[mcp_sellersprite.INSIGHT_CONTEXT_KEY] == {
        "exhaustive_review": True,
        "review_target": 500,
    }


def test_hot_product_concentration_buffers_candidates_and_excludes_mismatch(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_SAMPLE_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")
    calls = []

    def fake_call(_tool_name, arguments):
        calls.append(arguments)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "code": "OK",
                            "data": [
                                {"ranking": 1, "asin": "B000000001", "title": "Alpha Minimizer Bra", "imageUrl": "one.jpg"},
                                {"ranking": 2, "asin": "B000000002", "title": "HSIA Sports Bras for Women", "imageUrl": "two.jpg"},
                                {"ranking": 3, "asin": "B000000003", "title": "Beta Full Coverage Minimizer Bra", "imageUrl": "three.jpg"},
                            ],
                        }
                    ),
                }
            ]
        }

    monkeypatch.setattr(mcp_sellersprite, "call_sellersprite_mcp_tool", fake_call)
    tool_input = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_market_product_concentration",
        "minimizer bra",
        {
            "skillId": "hot_product_pain_analysis",
            "marketplace": "US",
            "category": "minimizer bra",
            "category_node_id": "7141123011:1045002",
            "head_listing_count": 2,
            "listing_sample_size": 20,
        },
    )
    result = mcp_sellersprite.execute_sellersprite_agent_tool(
        "sellersprite_market_product_concentration",
        tool_input,
    )

    assert tool_input["request"]["topN"] == 20
    assert mcp_sellersprite.INSIGHT_CONTEXT_KEY in tool_input
    assert mcp_sellersprite.INSIGHT_CONTEXT_KEY not in calls[0]
    assert result["status"] == "ok"
    assert result["data"]["resolved_params"]["selected_product_asins"] == ["B000000001", "B000000003"]
    assert result["data"]["product_selection"]["excluded"][0]["asin"] == "B000000002"


def test_product_design_concentration_uses_top_100_and_deduplicates_variation_families(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_SAMPLE_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)

    tool_input = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_market_product_concentration",
        "strapless bra",
        {
            "skillId": "product_design_research",
            "marketplace": "US",
            "category": "strapless bra",
            "category_node_id": "7141123011:1045002",
            "head_listing_count": 10,
            "listing_sample_size": 100,
        },
    )
    selection = mcp_sellersprite._hot_product_candidate_selection(
        {
            "data": [
                {
                    "ranking": 1,
                    "asin": "B000000001",
                    "parentAsin": "B000PARENT",
                    "title": "Alpha Strapless Bra",
                },
                {
                    "ranking": 2,
                    "asin": "B000000002",
                    "parentAsin": "B000PARENT",
                    "title": "Alpha Strapless Bra Black",
                },
                {
                    "ranking": 3,
                    "asin": "B000000003",
                    "title": "Beta Strapless Bra",
                },
            ]
        },
        {"category": "strapless bra", "head_listing_count": 10},
    )

    assert tool_input["request"]["topN"] == 100
    assert [item["asin"] for item in selection["eligible_candidates"]] == ["B000000001", "B000000003"]
    assert selection["excluded"][0]["exclusion_reason"] == "Duplicate parent/variation family: B000PARENT"


def test_execute_review_balances_stars_and_recovers_from_family_variant(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_REVIEW_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")
    calls = []

    def response(payload):
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    def fake_call(tool_name, arguments):
        calls.append((tool_name, dict(arguments)))
        asin = arguments.get("asin")
        if tool_name == "asin_detail":
            return response(
                {
                    "code": "OK",
                    "data": {
                        "parent": "B000PARENT",
                        "variationList": [{"asin": "B000FAMILY"}],
                    },
                }
            )
        if asin != "B000FAMILY":
            return response({"code": "OK", "data": {"page": 1, "total": 0, "items": []}})
        stars = arguments.get("starList")
        if stars == [1, 2, 3]:
            return response(
                {
                    "code": "OK",
                    "data": {
                        "page": 1,
                        "total": 2,
                        "items": [
                            {"author": "Low", "title": "Wire hurts", "content": "Digging", "date": 1500000000000, "star": 1},
                            {"author": "Old", "title": "Old batch", "content": "Historical", "date": 900000000000, "star": 2},
                        ],
                    },
                }
            )
        return response(
            {
                "code": "OK",
                "data": {
                    "page": 1,
                    "total": 3,
                    "items": [{"author": "High", "title": "Supportive", "content": "Fits well", "date": 1600000000000, "star": 5}],
                },
            }
        )

    monkeypatch.setattr(mcp_sellersprite, "call_sellersprite_mcp_tool", fake_call)
    result = mcp_sellersprite.execute_sellersprite_agent_tool(
        "sellersprite_review",
        {
            "marketplace": "US",
            "asin": "B08MVF8QDL",
            "size": 10,
            "page": 1,
            "startTimestamp": 1000000000000,
            "endTimestamp": 2000000000000,
            mcp_sellersprite.INSIGHT_CONTEXT_KEY: {"balanced_review": True},
        },
    )

    sampling = result["data"]["review_sampling"]
    items = result["data"]["data"]["items"]
    assert result["status"] == "ok"
    assert result["input"]["asin"] == "B08MVF8QDL"
    assert sampling["selected_review_asin"] == "B000FAMILY"
    assert sampling["scope"] == "variation_family"
    assert sampling["attempt_count"] == 3
    assert [item["star"] for item in items] == [1, 5]
    assert all(call[1].get("startTimestamp") == 1000000000000 for call in calls if call[0] == "review")
    assert "family variant" in result["summary"]


def test_execute_competitor_review_reads_every_available_page(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_REVIEW_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")
    calls: list[dict] = []

    def response(payload):
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    def fake_call(tool_name, arguments):
        assert tool_name == "review"
        calls.append(dict(arguments))
        page = arguments["page"]
        stars = arguments["starList"]
        total = 25 if stars == [1, 2, 3] else 13
        start = (page - 1) * 12
        stop = min(start + 12, total)
        return response(
            {
                "code": "OK",
                "data": {
                    "page": page,
                    "total": total,
                    "items": [
                        {
                            "id": f"R{stars[0]}-{index:03d}",
                            "author": f"Buyer {index}",
                            "title": f"Review {index}",
                            "content": f"Full review text {index}",
                            "star": stars[-1],
                        }
                        for index in range(start, stop)
                    ],
                },
            }
        )

    monkeypatch.setattr(mcp_sellersprite, "call_sellersprite_mcp_tool", fake_call)
    result = mcp_sellersprite.execute_sellersprite_agent_tool(
        "sellersprite_review",
        {
            "marketplace": "US",
            "asin": "B08MVF8QDL",
            "size": 100,
            "page": 1,
            mcp_sellersprite.INSIGHT_CONTEXT_KEY: {
                "exhaustive_review": True,
                "review_target": 500,
            },
        },
        bypass_cache=True,
    )

    sampling = result["data"]["review_sampling"]
    items = result["data"]["data"]["items"]
    assert result["status"] == "ok"
    assert [(call["starList"], call["page"]) for call in calls] == [
        ([1, 2, 3], 1),
        ([1, 2, 3], 2),
        ([1, 2, 3], 3),
        ([4, 5], 1),
        ([4, 5], 2),
    ]
    assert len(items) == 38
    assert sampling["mode"] == "exhaustive_balanced_pagination"
    assert sampling["source_total"] == 38
    assert sampling["collected_unique_count"] == 38
    assert sampling["coverage_rate"] == 1.0
    assert sampling["complete"] is True
    assert sampling["stop_reason"] == "complete"
    assert sampling["buckets"]["low_star"]["collected_unique_count"] == 25
    assert sampling["buckets"]["high_star"]["collected_unique_count"] == 13
    assert "read all 38" in result["summary"]


def test_resolve_sellersprite_product_node_rejects_wrong_leaf_category() -> None:
    resolution = mcp_sellersprite.resolve_sellersprite_product_node(
        {
            "data": [
                {
                    "nodeIdPath": "7141123011:7147440011:1040660:9522931011:14333511:2364767011:2364773011",
                    "nodeLabelPath": "Clothing, Shoes & Jewelry:Women:Clothing:Lingerie, Sleep & Lounge:Lingerie:Accessories:Bra Extenders",
                    "products": 266,
                }
            ]
        },
        "minimizer bra",
    )

    assert resolution["status"] == "no_match"
    assert resolution["selected"] is None
    assert resolution["candidates"][0]["match_score"] == 0.0


def test_resolve_sellersprite_product_node_accepts_unique_high_confidence_leaf() -> None:
    node_id_path = "7141123011:7147440011:1040660:9522931011:14333511:1044960:1045002"
    resolution = mcp_sellersprite.resolve_sellersprite_product_node(
        {
            "data": [
                {
                    "nodeIdPath": node_id_path,
                    "nodeLabelPath": "Clothing, Shoes & Jewelry:Women:Clothing:Lingerie, Sleep & Lounge:Lingerie:Bras:Minimizers",
                    "products": 328,
                },
                {
                    "nodeIdPath": node_id_path,
                    "nodeLabelPath": "Clothing, Shoes & Jewelry:Women:Clothing:Lingerie, Sleep & Lounge:Lingerie:Bras:Minimizers",
                    "products": 328,
                },
            ]
        },
        "minimizer bra",
    )

    assert resolution["status"] == "resolved"
    assert resolution["selected"]["nodeIdPath"] == node_id_path
    assert resolution["selected"]["match_score"] == 0.94
    assert len(resolution["candidates"]) == 1


def test_resolve_sellersprite_product_node_rejects_broad_parent_when_exact_leaf_exists() -> None:
    leaf_node = "7141123011:7147440011:1040660:9522931011:14333511:1044960:1044990"
    resolution = mcp_sellersprite.resolve_sellersprite_product_node(
        {
            "data": [
                {
                    "nodeIdPath": "3375251:10971181011",
                    "nodeLabelPath": "Sports & Outdoors:Sports",
                },
                {
                    "nodeIdPath": leaf_node,
                    "nodeLabelPath": "Clothing, Shoes & Jewelry:Women:Clothing:Lingerie:Bras:Sports Bras",
                },
            ]
        },
        "sports bra",
    )

    assert resolution["status"] == "resolved"
    assert resolution["selected"]["nodeIdPath"] == leaf_node
    broad_parent = next(item for item in resolution["candidates"] if item["nodeIdPath"] == "3375251:10971181011")
    assert broad_parent["match_score"] == 0.0


def test_product_node_query_candidates_do_not_broaden_sports_bra_to_sports() -> None:
    assert mcp_sellersprite._product_node_query_candidates("sports bra") == ["sports bra", "Sports Bras"]
    assert mcp_sellersprite._product_node_query_candidates("sports bras for women") == [
        "sports bras for women",
        "Sports Bras",
    ]
    assert mcp_sellersprite._product_node_query_candidates("minimizer bra") == ["minimizer bra", "Minimizers"]
    assert "Sports" not in mcp_sellersprite._product_node_query_candidates("sports bra")


def test_resolve_sellersprite_product_node_rejects_non_apparel_strapless_match() -> None:
    resolution = mcp_sellersprite.resolve_sellersprite_product_node(
        {
            "data": [
                {
                    "nodeIdPath": "3760901:3777371:3777781:3777811:676319011:17891907011",
                    "nodeLabelPath": "Health & Household:Sexual Wellness:Sex Toys:Dildos:Strapless Strap-On",
                    "products": 18,
                }
            ]
        },
        "strapless bra",
    )

    assert resolution["status"] == "no_match"
    assert resolution["selected"] is None
    assert resolution["candidates"][0]["context_eligible"] is False


def test_resolve_sellersprite_product_node_preserves_requested_audience_during_alias_lookup() -> None:
    girls_node = "7141123011:7147442011:1040664:3455761:2412720011:21490032011"
    resolution = mcp_sellersprite.resolve_sellersprite_product_node(
        {
            "data": [
                {
                    "nodeIdPath": girls_node,
                    "nodeLabelPath": "Clothing, Shoes & Jewelry:Girls:Clothing:Active:Underwear:Sports Bras",
                    "products": 198,
                },
                {
                    "nodeIdPath": "7141123011:7147440011:1040660:9522931011:14333511:1044960:1044990",
                    "nodeLabelPath": "Clothing, Shoes & Jewelry:Women:Clothing:Lingerie:Bras:Sports Bras",
                    "products": 2239,
                },
            ]
        },
        "Sports Bras",
        context_query="girls sports bra",
    )

    assert resolution["status"] == "resolved"
    assert resolution["selected"]["nodeIdPath"] == girls_node


def test_asin_detail_promotes_matching_weekly_market_category_node(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_ASIN_DETAIL_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")
    node_id_path = "7141123011:7147440011:1040660:9522931011:14333511:1044960:1044990"

    def fake_call(_tool_name, arguments):
        assert arguments == {"marketplace": "US", "asin": "B0DNPYC8CZ"}
        payload = json.dumps(
            {
                "data": {
                    "nodeIdPath": node_id_path,
                    "nodeLabelPath": "Clothing, Shoes & Jewelry:Women:Clothing:Lingerie:Bras:Sports Bras",
                }
            }
        )
        return {"content": [{"type": "text", "text": payload}]}

    monkeypatch.setattr(mcp_sellersprite, "call_sellersprite_mcp_tool", fake_call)
    tool_input = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_asin_detail",
        "sports bra",
        {
            "marketplace": "Amazon US",
            "category": "sports bra",
            "asin": "B0DNPYC8CZ",
            "skillId": "weekly_market_insight",
        },
    )
    result = mcp_sellersprite.execute_sellersprite_agent_tool("sellersprite_asin_detail", tool_input)

    assert result["status"] == "ok"
    assert result["data"]["resolved_params"]["category_node_id"] == node_id_path
    assert "resolved category node" in result["summary"]


def test_execute_product_node_exposes_resolved_skill_params(monkeypatch) -> None:
    schema = [
        {
            "name": "product_node",
            "description": "SellerSprite product node",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {
                        "type": "object",
                        "properties": {
                            "keyword": {"type": "string"},
                            "marketplace": {"type": "string"},
                            "month": {"type": "string"},
                        },
                        "required": ["marketplace"],
                    }
                },
                "required": ["request"],
            },
        }
    ]
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(schema)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")
    node_id_path = "7141123011:7147440011:1040660:9522931011:14333511:1044960:1045002"
    monkeypatch.setattr(
        mcp_sellersprite,
        "call_sellersprite_mcp_tool",
        lambda *_args, **_kwargs: {
            "content": [
                {
                    "type": "text",
                    "text": (
                        '{"data":[{"nodeIdPath":"'
                        + node_id_path
                        + '","nodeLabelPath":"Clothing, Shoes & Jewelry:Women:Clothing:Lingerie, Sleep & Lounge:Lingerie:Bras:Minimizers","products":328}]}'
                    ),
                }
            ]
        },
    )

    tool_input = mcp_sellersprite.build_sellersprite_input_payload(
        "sellersprite_product_node",
        "minimizer bra",
        {"marketplace": "Amazon US", "category": "minimizer bra"},
    )
    result = mcp_sellersprite.execute_sellersprite_agent_tool("sellersprite_product_node", tool_input)

    assert result["status"] == "ok"
    assert result["data"]["node_resolution"]["status"] == "resolved"
    assert result["data"]["resolved_params"]["category_node_id"] == node_id_path


def test_execute_product_node_recovers_with_official_plural_leaf(monkeypatch) -> None:
    schema = [
        {
            "name": "product_node",
            "description": "SellerSprite product node",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {
                        "type": "object",
                        "properties": {
                            "keyword": {"type": "string"},
                            "marketplace": {"type": "string"},
                            "month": {"type": "string"},
                        },
                        "required": ["marketplace"],
                    }
                },
                "required": ["request"],
            },
        }
    ]
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(schema)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")
    node_id_path = "7141123011:7147440011:1040660:9522931011:14333511:1044960:1045002"
    queries = []

    def fake_call(_tool_name, arguments):
        query = arguments["request"]["keyword"]
        queries.append(query)
        if query == "minimizer bra":
            rows = [
                {
                    "nodeIdPath": "7141123011:2364773011",
                    "nodeLabelPath": "Clothing, Shoes & Jewelry:Women:Bra Extenders",
                    "products": 266,
                }
            ]
        else:
            rows = [
                {
                    "nodeIdPath": node_id_path,
                    "nodeLabelPath": "Clothing, Shoes & Jewelry:Women:Lingerie:Bras:Minimizers",
                    "products": 328,
                }
            ]
        return {"content": [{"type": "text", "text": json.dumps({"code": "OK", "data": rows})}]}

    monkeypatch.setattr(mcp_sellersprite, "call_sellersprite_mcp_tool", fake_call)
    result = mcp_sellersprite.execute_sellersprite_agent_tool(
        "sellersprite_product_node",
        {"request": {"marketplace": "US", "keyword": "minimizer bra", "month": "202606"}},
    )

    assert queries == ["minimizer bra", "Minimizers"]
    assert result["status"] == "ok"
    assert result["input"]["request"]["keyword"] == "Minimizers"
    assert result["data"]["resolved_params"]["category_node_id"] == node_id_path
    assert result["data"]["node_query_resolution"]["attempt_count"] == 2


def test_execute_product_node_disambiguates_womens_sports_bras(monkeypatch) -> None:
    schema = [
        {
            "name": "product_node",
            "description": "SellerSprite product node",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {
                        "type": "object",
                        "properties": {
                            "keyword": {"type": "string"},
                            "marketplace": {"type": "string"},
                            "month": {"type": "string"},
                        },
                        "required": ["marketplace"],
                    }
                },
                "required": ["request"],
            },
        }
    ]
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(schema)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")
    women_node = "7141123011:7147440011:1040660:9522931011:14333511:1044960:1044990"
    queries: list[str] = []

    def fake_call(_tool_name, arguments):
        query = arguments["request"]["keyword"]
        queries.append(query)
        if query == "sports bra":
            rows = [
                {
                    "nodeIdPath": "3375251:10971181011",
                    "nodeLabelPath": "Sports & Outdoors:Sports",
                    "products": 314346,
                }
            ]
        else:
            rows = [
                {
                    "nodeIdPath": "7141123011:7147442011:1040664:3455761:2412720011:21490032011",
                    "nodeLabelPath": "Clothing, Shoes & Jewelry:Girls:Clothing:Active:Underwear:Sports Bras",
                    "products": 198,
                },
                {
                    "nodeIdPath": women_node,
                    "nodeLabelPath": "Clothing, Shoes & Jewelry:Women:Clothing:Lingerie:Bras:Sports Bras",
                    "products": 2239,
                },
            ]
        return {"content": [{"type": "text", "text": json.dumps({"code": "OK", "data": rows})}]}

    monkeypatch.setattr(mcp_sellersprite, "call_sellersprite_mcp_tool", fake_call)
    result = mcp_sellersprite.execute_sellersprite_agent_tool(
        "sellersprite_product_node",
        {"request": {"marketplace": "US", "keyword": "sports bra", "month": "202606"}},
    )

    assert queries == ["sports bra", "Sports Bras"]
    assert result["status"] == "ok"
    assert result["data"]["resolved_params"]["category_node_id"] == women_node
    assert result["data"]["node_resolution"]["disambiguation"]["method"] == "taxonomy_context"


def test_execute_product_node_uses_explicit_everyday_bra_proxy(monkeypatch) -> None:
    schema = [
        {
            "name": "product_node",
            "description": "SellerSprite product node",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {
                        "type": "object",
                        "properties": {
                            "keyword": {"type": "string"},
                            "marketplace": {"type": "string"},
                            "month": {"type": "string"},
                        },
                        "required": ["marketplace"],
                    }
                },
                "required": ["request"],
            },
        }
    ]
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(schema)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")
    proxy_node = "7141123011:7147440011:1040660:9522931011:14333511:1044960:2376204011"
    queries: list[str] = []

    def fake_call(_tool_name, arguments):
        query = arguments["request"]["keyword"]
        queries.append(query)
        if query == "Everyday Bras":
            rows = [
                {
                    "nodeIdPath": proxy_node,
                    "nodeLabelPath": "Clothing, Shoes & Jewelry:Women:Clothing:Lingerie:Bras:Everyday Bras",
                    "products": 7510,
                }
            ]
        else:
            rows = [
                {
                    "nodeIdPath": "3760901:3777371:3777781:3777811:676319011:17891907011",
                    "nodeLabelPath": "Health & Household:Sexual Wellness:Sex Toys:Dildos:Strapless Strap-On",
                    "products": 18,
                }
            ]
        return {"content": [{"type": "text", "text": json.dumps({"code": "OK", "data": rows})}]}

    monkeypatch.setattr(mcp_sellersprite, "call_sellersprite_mcp_tool", fake_call)
    result = mcp_sellersprite.execute_sellersprite_agent_tool(
        "sellersprite_product_node",
        {"request": {"marketplace": "US", "keyword": "strapless bra", "month": "202606"}},
    )

    assert queries == ["strapless bra", "strapless Bras", "Everyday Bras"]
    assert result["status"] == "ok"
    assert result["data"]["resolved_params"]["category_node_id"] == proxy_node
    assert result["data"]["resolved_params"]["category_node_is_proxy"] is True
    assert result["data"]["node_query_resolution"]["resolution_mode"] == "proxy"
    assert "broad proxy node" in result["summary"]


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


def test_execute_sellersprite_agent_tool_blocks_missing_required_request_param(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_SAMPLE_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")

    def fail_call(*args, **kwargs):
        raise AssertionError("SellerSprite MCP should not be called with missing required params")

    monkeypatch.setattr(mcp_sellersprite, "call_sellersprite_mcp_tool", fail_call)

    result = mcp_sellersprite.execute_sellersprite_agent_tool(
        "sellersprite_market_product_concentration",
        {"request": {"marketplace": "US", "month": "202606", "topN": 10}},
    )

    assert result["status"] == "needs_user_action"
    assert result["data"]["missing_required"] == ["request.nodeIdPath"]
    assert "request.nodeIdPath" in result["summary"]


def test_execute_market_research_recovers_with_discriminative_core_keyword(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_MARKET_RESEARCH_REQUEST_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")
    requests = []

    def fake_call(_tool_name, arguments):
        request = arguments["request"]
        requests.append(dict(request))
        if request["departmentKeyword"] == "minimizer":
            payload = '{"data":{"page":1,"size":10,"total":1,"items":[{"departmentName":"Minimizers"}]}}'
        else:
            payload = '{"data":{"page":1,"size":10,"total":0,"items":[]}}'
        return {"content": [{"type": "text", "text": payload}]}

    monkeypatch.setattr(mcp_sellersprite, "call_sellersprite_mcp_tool", fake_call)
    result = mcp_sellersprite.execute_sellersprite_agent_tool(
        "sellersprite_market_research",
        {
            "request": {
                "marketplace": "US",
                "departmentKeyword": "minimizer bra",
                "month": "202606",
                "page": 1,
                "size": 10,
            }
        },
    )

    assert [request["departmentKeyword"] for request in requests] == ["minimizer bra", "minimizer"]
    assert all(request["month"] == "202606" for request in requests)
    assert result["status"] == "ok"
    assert result["input"]["request"]["departmentKeyword"] == "minimizer"
    assert result["data"]["data"]["total"] == 1
    assert result["data"]["query_resolution"]["selected_keyword"] == "minimizer"
    assert result["data"]["query_resolution"]["attempt_count"] == 2
    assert "recovered" in result["summary"]


def test_execute_market_research_stays_empty_when_controlled_fallback_is_empty(monkeypatch) -> None:
    catalog = mcp_sellersprite.build_sellersprite_tool_catalog(SELLERSPRITE_MARKET_RESEARCH_REQUEST_SCHEMA)
    monkeypatch.setattr(mcp_sellersprite, "get_sellersprite_tool_catalog", lambda: catalog)
    monkeypatch.setenv("SELLERSPRITE_MCP_SECRET_KEY", "test-secret")
    requests = []

    def fake_call(_tool_name, arguments):
        requests.append(dict(arguments["request"]))
        return {
            "content": [
                {
                    "type": "text",
                    "text": '{"data":{"page":1,"size":10,"total":0,"items":[]}}',
                }
            ]
        }

    monkeypatch.setattr(mcp_sellersprite, "call_sellersprite_mcp_tool", fake_call)
    result = mcp_sellersprite.execute_sellersprite_agent_tool(
        "sellersprite_market_research",
        {
            "request": {
                "marketplace": "US",
                "departmentKeyword": "minimizer bra",
                "month": "202606",
                "page": 1,
                "size": 10,
            }
        },
    )

    assert [request["departmentKeyword"] for request in requests] == ["minimizer bra", "minimizer"]
    assert result["status"] == "ok"
    assert result["data"]["query_resolution"]["selected_keyword"] is None
    assert result["data"]["query_resolution"]["attempt_count"] == 2
    assert "returned 0 items" in result["summary"]

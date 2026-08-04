from insight_agent import server as server_module
from insight_agent.agent_tool_recovery import assess_agent_tool_result


def amazon_report(products: int = 1, reviews: int = 12) -> dict:
    return {
        "metrics": {
            "products": products,
            "total_review_count": reviews,
        },
        "price_bands": [],
        "brands": [],
        "queries": ["minimizer bra"],
        "products": [
            {
                "asin": "B000TEST",
                "title": "Test minimizer bra",
                "brand": "TestBrand",
                "product_url": "https://www.amazon.com/dp/B000TEST",
                "price_text": "$29.99",
                "rating_value": 4.3,
                "review_count": reviews,
                "review_samples": [],
                "badges": [],
            }
        ][:products],
    }


def test_agent_tool_retries_transient_error_and_returns_success(monkeypatch) -> None:
    calls = {"count": 0}

    def flaky_analyze_amazon(_payload):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary network reset")
        return amazon_report()

    monkeypatch.setattr(server_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server_module, "analyze_amazon_category", flaky_analyze_amazon)

    result = server_module.execute_agent_tool_with_timeout(
        "amazon_shelf",
        "minimizer bra",
        {"agentToolRetryAttempts": 2, "agentToolRetryDelayMs": 0},
    )

    assert result["status"] == "ok"
    assert result["outcome"] == "ok_with_data"
    assert result["recovery"]["attempt_count"] == 2
    assert result["recovery"]["retried"] is True
    assert result["recovery"]["attempts"][0]["status"] == "retryable_error"
    assert calls["count"] == 2


def test_agent_tool_empty_result_is_structured_without_blind_retry(monkeypatch) -> None:
    calls = {"count": 0}

    def empty_analyze_amazon(_payload):
        calls["count"] += 1
        return amazon_report(products=0, reviews=0)

    monkeypatch.setattr(server_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server_module, "analyze_amazon_category", empty_analyze_amazon)

    result = server_module.execute_agent_tool_with_timeout(
        "amazon_shelf",
        "minimizer bra",
        {"agentToolRetryAttempts": 2, "agentToolRetryDelayMs": 0},
    )

    assert result["status"] == "empty"
    assert result["outcome"] == "empty_result"
    assert result["data"]["products"] == []
    assert result["recovery"]["attempt_count"] == 1
    assert result["recovery"]["retryable"] is False
    assert result["recovery"]["suggested_next_actions"]
    assert calls["count"] == 1


def test_fastmoss_empty_status_is_not_promoted_to_success_or_blindly_retried() -> None:
    assessment = assess_agent_tool_result(
        "mcp__fastmoss__product_rank_new_listed",
        {
            "status": "empty",
            "summary": "FastMoss returned no usable market records.",
            "data": {"list": [], "total": 0},
        },
    )

    assert assessment.status == "empty"
    assert assessment.outcome == "empty_result"
    assert assessment.retryable is False
    assert "not proof of zero market activity" in assessment.suggested_next_actions[-1]


def test_agent_tool_login_failure_needs_user_action_without_retry(monkeypatch) -> None:
    calls = {"count": 0}

    def login_required(_payload):
        calls["count"] += 1
        raise RuntimeError("TikTok login required before reading detail pages")

    monkeypatch.setattr(server_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server_module, "analyze_tiktok_category", login_required)

    result = server_module.execute_agent_tool_with_timeout(
        "tiktok_social",
        "minimizer bra",
        {"agentToolRetryAttempts": 2, "agentToolRetryDelayMs": 0},
    )

    assert result["status"] == "needs_user_action"
    assert result["outcome"] == "needs_user_action"
    assert result["recovery"]["attempt_count"] == 1
    assert result["recovery"]["retryable"] is False
    assert calls["count"] == 1


def test_fastmoss_credit_balance_failure_needs_user_action_without_retry() -> None:
    assessment = assess_agent_tool_result(
        "mcp__fastmoss__shop_creator_analysis",
        {
            "status": "error",
            "summary": "FastMoss credits exhausted; credit balance is 0. Please recharge.",
            "data": {},
        },
    )

    assert assessment.status == "needs_user_action"
    assert assessment.outcome == "needs_user_action"
    assert assessment.retryable is False


def test_deterministic_builder_is_never_retried_with_unchanged_evidence(monkeypatch) -> None:
    calls = {"count": 0}

    def transient_builder_failure(tool_name, category, payload, timeout_seconds):  # noqa: ARG001
        calls["count"] += 1
        return {
            "name": tool_name,
            "status": "error",
            "summary": "temporary network unavailable",
            "input": {},
            "data": {},
        }

    monkeypatch.setattr(
        server_module, "execute_agent_tool_once_with_timeout", transient_builder_failure
    )
    result = server_module.execute_agent_tool_with_timeout(
        "build_tiktok_bra_competitor_shop_report_data",
        "女士文胸",
        {"agentToolRetryAttempts": 3, "agentToolRetryDelayMs": 0},
    )

    assert calls["count"] == 1
    assert result["recovery"]["attempt_count"] == 1
    assert result["recovery"]["retried"] is False


def test_agent_tool_retries_until_exhausted(monkeypatch) -> None:
    calls = {"count": 0}

    def always_flaky(_payload):
        calls["count"] += 1
        raise RuntimeError("temporary network reset")

    monkeypatch.setattr(server_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server_module, "analyze_amazon_category", always_flaky)

    result = server_module.execute_agent_tool_with_timeout(
        "amazon_shelf",
        "minimizer bra",
        {"agentToolRetryAttempts": 2, "agentToolRetryDelayMs": 0},
    )

    assert result["status"] == "retry_exhausted"
    assert result["outcome"] == "retryable_error"
    assert result["recovery"]["attempt_count"] == 3
    assert result["recovery"]["retried"] is True
    assert result["recovery"]["retryable"] is False
    assert calls["count"] == 3


def test_semantic_payload_error_is_detected_without_tool_specific_logic() -> None:
    assessment = assess_agent_tool_result(
        "any_mcp_tool",
        {
            "status": "ok",
            "summary": "MCP returned structured evidence.",
            "data": {
                "code": "ERROR_PARAM",
                "message": "参数错误",
                "data": "日期参数错误，只能查询上一周的数据",
            },
        },
    )

    assert assessment.status == "fatal_error"
    assert assessment.outcome == "semantic_error"
    assert assessment.retryable is False
    assert "ERROR_PARAM" in assessment.reason
    assert "日期参数错误" in assessment.reason


def test_semantic_payload_transient_error_is_retryable() -> None:
    assessment = assess_agent_tool_result(
        "any_mcp_tool",
        {
            "status": "ok",
            "summary": "MCP returned structured evidence.",
            "data": {
                "status": "failed",
                "message": "temporary service unavailable, please try again",
            },
        },
    )

    assert assessment.status == "retryable_error"
    assert assessment.outcome == "semantic_error"
    assert assessment.retryable is True


def test_completed_html_renderer_ignores_failed_attempt_history() -> None:
    assessment = assess_agent_tool_result(
        "render_html_report",
        {
            "status": "ok",
            "summary": "Rendered HTML report.",
            "data": {
                "html": "<!doctype html><html><head><style>body{color:#111}</style></head><body>ok</body></html>",
                "html_analysis": {
                    "status": "ok",
                    "attempts": [
                        {
                            "attempt": 1,
                            "status": "validation_failed",
                            "message": "LLM HTML must be a complete HTML document.",
                        },
                        {"attempt": 2, "status": "ok", "message": ""},
                    ],
                },
            },
        },
    )

    assert assessment.status == "ok"
    assert assessment.outcome == "ok_with_data"
    assert assessment.retryable is False


def test_sellersprite_ok_empty_items_is_empty_result() -> None:
    assessment = assess_agent_tool_result(
        "sellersprite_market_research",
        {
            "status": "ok",
            "summary": "SellerSprite returned structured evidence in `data`.",
            "data": {
                "code": "OK",
                "message": "成功",
                "data": {
                    "page": 1,
                    "size": 10,
                    "total": 0,
                    "items": [],
                },
            },
        },
    )

    assert assessment.status == "empty"
    assert assessment.outcome == "empty_result"
    assert assessment.retryable is False
    assert "0 items" in assessment.reason


def test_sif_empty_top_competitors_is_empty_result() -> None:
    assessment = assess_agent_tool_result(
        "sif_market_get_keyword_competition",
        {
            "status": "ok",
            "summary": "Sif completed.",
            "data": {
                "parsed_content": {
                    "keyword": "minimizer bra",
                    "total_competitors": 0,
                    "top_competitors": [],
                }
            },
        },
    )

    assert assessment.status == "empty"
    assert assessment.outcome == "empty_result"
    assert assessment.retryable is False


def test_sellersprite_product_node_requires_unique_resolution() -> None:
    unresolved = assess_agent_tool_result(
        "sellersprite_product_node",
        {
            "status": "ok",
            "summary": "Multiple nodes returned.",
            "data": {
                "node_resolution": {
                    "status": "ambiguous",
                    "selected": None,
                    "candidates": [{"nodeIdPath": "1:2"}, {"nodeIdPath": "1:3"}],
                }
            },
        },
    )

    assert unresolved.status == "empty"
    assert unresolved.outcome == "category_node_unresolved"
    assert unresolved.retryable is False


def test_partial_ok_tool_status_remains_successful() -> None:
    assessment = assess_agent_tool_result(
        "sellersprite_review",
        {
            "status": "partial_ok",
            "summary": "Only one star bucket had recent reviews.",
            "data": {"data": {"total": 1, "items": [{"star": 5}]}},
        },
    )

    assert assessment.status == "partial_ok"
    assert assessment.outcome == "partial_ok"


def test_agent_tool_retries_semantic_transient_error(monkeypatch) -> None:
    calls = {"count": 0}

    def semantic_flaky_tool(tool_name, category, payload, timeout_seconds):  # noqa: ARG001
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "name": tool_name,
                "label": "Generic MCP",
                "status": "ok",
                "summary": "MCP returned structured evidence.",
                "duration_ms": 1,
                "input": {},
                "data": {
                    "code": "TEMPORARY_UNAVAILABLE",
                    "message": "temporary network unavailable",
                },
            }
        return {
            "name": tool_name,
            "label": "Generic MCP",
            "status": "ok",
            "summary": "MCP returned usable evidence.",
            "duration_ms": 1,
            "input": {},
            "data": {"items": [{"value": 1}]},
        }

    monkeypatch.setattr(server_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server_module, "execute_agent_tool_once_with_timeout", semantic_flaky_tool)

    result = server_module.execute_agent_tool_with_timeout(
        "generic_mcp_tool",
        "minimizer bra",
        {"agentToolRetryAttempts": 2, "agentToolRetryDelayMs": 0},
    )

    assert result["status"] == "ok"
    assert result["outcome"] == "ok_with_data"
    assert result["recovery"]["attempt_count"] == 2
    assert result["recovery"]["retried"] is True
    assert result["recovery"]["attempts"][0]["outcome"] == "semantic_error"
    assert calls["count"] == 2

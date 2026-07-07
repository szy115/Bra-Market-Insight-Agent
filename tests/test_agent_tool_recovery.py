from insight_agent import server as server_module


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

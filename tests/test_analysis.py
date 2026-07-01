import os
from collections import Counter

from insight_agent import server as server_module
from insight_agent import settings as settings_module
from insight_agent.ingestion import agent_reach as agent_reach_module
from insight_agent.ingestion.agent_reach import normalize_opencli_read_items
from insight_agent.ingestion.amazon_opencli import AmazonResult, build_amazon_queries
from insight_agent.ingestion.schema import EvidenceItem, ProviderResult
from insight_agent.server import (
    amazon_review_url,
    analyze_amazon_category,
    analyze_category,
    analyze_combined_insight,
    build_reddit_query,
    build_trend_series,
    delete_research_history_item,
    list_research_history,
    save_research_history,
)
from insight_agent.settings import (
    build_llm_settings_response,
    build_reddit_settings_response,
    build_research_settings_response,
    load_llm_providers,
    update_reddit_settings,
    update_research_settings,
)


def test_query_expands_bra_subcategory() -> None:
    query = build_reddit_query("wireless bras for large bust")

    assert '"wireless bra"' in query
    assert '"large bust bra"' in query


def test_sample_analysis_returns_report_sections() -> None:
    result = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "sample",
            "limit": 8,
            "timeRange": "year",
            "useLlm": False,
        }
    )

    assert result["source_mode"] == "sample"
    assert result["coverage"]["posts"] == 8
    assert result["data_volume"]["requested_posts"] == 8
    assert result["data_volume"]["collected_posts"] == 8
    assert result["pain_points"]
    assert result["opportunities"]
    assert result["posts"]


def test_trend_series_fills_single_month_context() -> None:
    trend = build_trend_series(Counter({"2026-06": 5}))

    assert len(trend) == 6
    assert trend[-1] == {"month": "2026-06", "count": 5}
    assert trend[0]["count"] == 0


def test_agent_reach_analysis_uses_provider(monkeypatch) -> None:
    def fake_fetch(_query: str, _limit: int, _time_range: str) -> ProviderResult:
        return ProviderResult(
            [
                EvidenceItem(
                    source="reddit",
                    provider="agent_reach_opencli",
                    content_type="post",
                    title="Wireless bra support for large bust?",
                    text="Looking for lift, comfort, and no uniboob.",
                    url="https://www.reddit.com/r/ABraThatFits/comments/test/post/",
                    external_id="test",
                    community="ABraThatFits",
                    metrics={"score": 12, "comments": 3},
                    comments=[
                        {
                            "text": "Side support and fit are the biggest issue for me.",
                            "score": 5,
                        }
                    ],
                )
            ],
            [],
            "agent_reach",
        )

    monkeypatch.setattr("insight_agent.server.fetch_reddit_agent_reach", fake_fetch)

    result = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "agent_reach",
            "limit": 10,
            "timeRange": "year",
            "useLlm": False,
        }
    )

    assert result["source_mode"] == "agent_reach"
    assert result["coverage"]["posts"] == 1
    assert result["data_volume"]["collected_comments"] == 1
    assert result["data_volume"]["ai_comment_samples"] == 0
    assert result["posts"][0]["comment_items"]
    assert "Top comments" in result["posts"][0]["excerpt"]


def test_amazon_query_expansion_maps_large_bust_minimizer_terms() -> None:
    queries = build_amazon_queries("美国大胸显小内衣", 5)

    assert queries[0] == "美国大胸显小内衣"
    assert "minimizer bra" in queries
    assert "minimizer bras for large breasts" in queries


def test_amazon_analysis_uses_opencli_provider(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    def fake_fetch(
        _query: str,
        _limit: int,
        keyword_limit: int | None = None,
        bypass_cache: bool = False,
    ) -> AmazonResult:
        return AmazonResult(
            [
                {
                    "rank": 1,
                    "asin": "B0058LXNF0",
                    "title": "Vanity Fair Women's Beauty Back Smoothing Minimizer Bra",
                    "brand": "Vanity Fair",
                    "product_url": "https://www.amazon.com/dp/B0058LXNF0",
                    "price_text": "$29.99",
                    "price_value": 29.99,
                    "currency": "USD",
                    "rating_value": 4.3,
                    "review_count": 34856,
                    "badges": ["Overall Pick"],
                    "is_sponsored": False,
                    "bullet_points": ["Minimizes bust line up to 1.5 inches"],
                    "review_samples": [
                        {
                            "title": "Comfortable minimizer",
                            "body": "Smooths under shirts without uniboob.",
                            "rating_value": 5,
                            "verified_purchase": True,
                        }
                    ],
                }
            ],
            ["Bypassed local cache for Amazon collection."] if bypass_cache else [],
            queries=["minimizer bra", "full coverage minimizer bra"][: keyword_limit or 2],
            per_query_counts={"minimizer bra": 1, "full coverage minimizer bra": 1},
        )

    monkeypatch.setattr("insight_agent.server.fetch_amazon_opencli", fake_fetch)

    result = analyze_amazon_category(
        {
            "category": "minimizer bra",
            "limit": 10,
            "bypassCache": True,
            "useLlm": False,
        }
    )

    assert result["source_mode"] == "amazon_opencli"
    assert result["metrics"]["products"] == 1
    assert result["metrics"]["total_review_count"] == 34856
    assert result["data_volume"]["collected_review_samples"] == 1
    assert result["data_volume"]["query_count"] == 2
    assert result["data_volume"]["requested_products_per_query"] == 10
    assert result["products"][0]["asin"] == "B0058LXNF0"


def test_combined_insight_returns_fixed_cited_sections() -> None:
    reddit_report = {
        "category": "minimizer bra",
        "coverage": {"posts": 1},
        "data_volume": {"collected_comments": 1},
        "pain_points": [{"topic": "Fit and sizing"}],
        "posts": [
            {
                "title": "Looking for a minimizer bra that does not hurt",
                "url": "https://www.reddit.com/r/ABraThatFits/comments/test/minimizer/",
                "subreddit": "ABraThatFits",
                "excerpt": "Need smoothing under shirts without shoulder pain.",
                "comment_items": [{"text": "Side support and wire shape matter most."}],
            }
        ],
    }
    amazon_report = {
        "category": "minimizer bra",
        "metrics": {"products": 1, "review_samples": 1, "total_review_count": 1200, "price_avg": 29.99},
        "products": [
            {
                "title": "Smoothing Minimizer Bra",
                "brand": "Example",
                "product_url": "https://www.amazon.com/dp/B000000001",
                "price_text": "$29.99",
                "rating_value": 4.3,
                "review_count": 1200,
                "bullet_points": ["Minimizes bust line and smooths back."],
                "review_samples": [{"title": "Good shape", "body": "Fits well under button-down shirts.", "rating_value": 5}],
            }
        ],
    }

    result = analyze_combined_insight(
        {
            "category": "minimizer bra",
            "reddit_report": reddit_report,
            "amazon_report": amazon_report,
            "useLlm": False,
        }
    )

    assert result["verdict"]["citations"]
    assert len(result["opportunities"]) == 3
    assert len(result["risks"]) == 3
    assert len(result["data_gaps"]) == 3
    for section in (
        result["opportunities"],
        result["risks"],
        result["rd_recommendations"],
        result["brand_communication"],
        result["data_gaps"],
    ):
        assert all(item["citations"] for item in section)
    assert all(item["citations"] for item in result["evidence_chain"])


def test_amazon_review_url_prefers_review_id_and_falls_back_to_review_anchor() -> None:
    assert (
        amazon_review_url({"id": "R123ABC"}, "https://www.amazon.com/dp/B000000001")
        == "https://www.amazon.com/gp/customer-reviews/R123ABC"
    )
    assert (
        amazon_review_url({}, "https://www.amazon.com/dp/B000000001?th=1")
        == "https://www.amazon.com/dp/B000000001?th=1#customerReviews"
    )


def test_research_history_save_list_delete(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "HISTORY_PATH", tmp_path / "research-history.json")

    saved = save_research_history(
        {
            "category": "minimizer bra",
            "combined_report": {
                "category": "minimizer bra",
                "verdict": {"text": "Directional demand signal."},
                "data_summary": {"evidence_items": 3},
            },
        }
    )

    item_id = saved["item"]["id"]
    listed = list_research_history()
    assert listed["storage_path"].endswith("research-history.json")
    assert listed["items"][0]["id"] == item_id
    assert listed["items"][0]["has_combined"] is True

    deleted = delete_research_history_item(item_id)
    assert deleted["deleted_id"] == item_id
    assert deleted["items"] == []


def test_bypass_cache_forces_fresh_collection(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)
    query = build_reddit_query("wireless bras for large bust")
    cache_path = server_module.cache_key(
        [
            server_module.CACHE_VERSION,
            "analysis",
            query,
            "10",
            "year",
            "agent_reach",
            os.getenv("AGENT_REACH_DETAIL_LIMIT", ""),
            os.getenv("AGENT_REACH_COMMENTS_PER_POST", ""),
        ]
    )
    server_module.write_cache(
        cache_path,
        {
            "posts": [
                {
                    "id": "cached",
                    "title": "Cached post",
                    "excerpt": "cached text",
                    "subreddit": "ABraThatFits",
                    "url": "https://www.reddit.com/r/ABraThatFits/comments/cached/post/",
                    "created_utc": "",
                    "score": 1,
                    "comments": 1,
                    "comment_items": [{"text": "cached comment"}],
                    "source": "reddit_agent_reach_opencli",
                }
            ],
            "mode": "agent_reach",
        },
    )

    def fake_fetch(_query: str, _limit: int, _time_range: str) -> ProviderResult:
        return ProviderResult(
            [
                EvidenceItem(
                    source="reddit",
                    provider="agent_reach_opencli",
                    content_type="post",
                    title="Fresh post",
                    text="fresh text",
                    url="https://www.reddit.com/r/ABraThatFits/comments/fresh/post/",
                    external_id="fresh",
                    community="ABraThatFits",
                    metrics={"score": 2, "comments": 1},
                    comments=[{"text": "fresh comment"}],
                )
            ],
            [],
            "agent_reach",
        )

    monkeypatch.setattr("insight_agent.server.fetch_reddit_agent_reach", fake_fetch)

    cached = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "agent_reach",
            "limit": 10,
            "timeRange": "year",
            "useLlm": False,
        }
    )
    fresh = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "agent_reach",
            "limit": 10,
            "timeRange": "year",
            "bypassCache": True,
            "useLlm": False,
        }
    )

    assert cached["posts"][0]["title"] == "Cached post"
    assert fresh["posts"][0]["title"] == "Fresh post"
    assert "Bypassed local cache" in " ".join(fresh["warnings"])


def test_opencli_read_rows_are_normalized_as_comments() -> None:
    items = normalize_opencli_read_items(
        [
            {
                "type": "POST",
                "author": "op",
                "score": 9,
                "text": "Balconette bra fit check\n\nLooking for strap and cup feedback.",
            },
            {
                "type": "L0",
                "author": "helper",
                "score": 0,
                "text": "The wire looks too narrow in this size.",
            },
            {
                "type": "L1",
                "author": "reply",
                "score": 2,
                "text": "Try a wider cup or a different brand.",
            },
            {"type": "", "text": "[+3 more top-level comments]"},
        ],
        "https://www.reddit.com/r/ABraThatFits/comments/abc123/balconette_bra_fit_check/",
        "agent_reach_opencli",
    )

    assert len(items) == 1
    assert items[0].external_id == "abc123"
    assert items[0].title == "Balconette bra fit check"
    assert len(items[0].comments) == 2
    assert items[0].comments[0]["score"] == 0


def test_explicit_agent_reach_does_not_fallback_to_rss_or_sample(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    def fake_fetch(_query: str, _limit: int, _time_range: str) -> ProviderResult:
        return ProviderResult([], ["OpenCLI is installed, but the Chrome extension is not connected."], "agent_reach")

    def fail_rss(*_args, **_kwargs):
        raise AssertionError("RSS should not be called for explicit Agent Reach mode")

    monkeypatch.setattr("insight_agent.server.fetch_reddit_agent_reach", fake_fetch)
    monkeypatch.setattr("insight_agent.server.fetch_reddit_rss", fail_rss)

    result = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "agent_reach",
            "limit": 10,
            "timeRange": "year",
            "bypassCache": True,
            "useLlm": False,
        }
    )

    assert result["source_mode"] == "agent_reach"
    assert result["coverage"]["posts"] == 0
    assert result["data_volume"]["collected_posts"] == 0
    assert "OpenCLI is installed" in " ".join(result["warnings"])
    assert "Not falling back" in " ".join(result["warnings"])


def test_reconnect_opencli_restarts_daemon_and_refreshes_health(monkeypatch) -> None:
    commands: list[list[str]] = []
    health_calls = {"count": 0}

    def fake_health() -> dict[str, object]:
        health_calls["count"] += 1
        connected = health_calls["count"] >= 3
        return {
            "agent_reach_installed": True,
            "opencli_installed": True,
            "opencli_connected": connected,
            "rdt_installed": False,
            "agent_reach_path": "agent-reach",
            "opencli_path": "opencli",
            "rdt_path": "",
            "ready": connected,
            "recommended_backend": "opencli" if connected else "",
        }

    def fake_run_command(args: list[str], _timeout_seconds: int) -> tuple[int, str, str]:
        commands.append(args)
        if args == ["opencli", "daemon", "restart"]:
            return 0, "Daemon restarted", ""
        if args == ["opencli", "profile", "list"]:
            return 0, "Default profile", ""
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr(agent_reach_module, "agent_reach_health", fake_health)
    monkeypatch.setattr(agent_reach_module, "run_command", fake_run_command)
    monkeypatch.setattr(agent_reach_module.time, "sleep", lambda _seconds: None)

    result = agent_reach_module.reconnect_opencli_extension()

    assert result["ok"] is True
    assert result["health"]["opencli_connected"] is True
    assert ["opencli", "daemon", "restart"] in commands
    assert result["profiles"]["stdout"] == "Default profile"


def test_llm_provider_settings_are_data_driven() -> None:
    providers = load_llm_providers()
    names = {provider.name for provider in providers}
    settings = build_llm_settings_response()

    assert "openai" in names
    assert settings["providers"]
    assert "api_key_configured" in settings


def test_reddit_settings_redacts_secret() -> None:
    settings = build_reddit_settings_response(
        {
            "REDDIT_CLIENT_ID": "client-id",
            "REDDIT_CLIENT_SECRET": "client-secret",
            "REDDIT_USER_AGENT": "InsightAgentTest/0.1 by tester",
        }
    )

    assert settings["client_id"] == "client-id"
    assert settings["client_secret_configured"] is True
    assert "client-secret" not in settings.values()
    assert settings["oauth_ready"] is True


def test_update_reddit_settings_writes_env_and_syncs_process(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    env_path.write_text("", encoding="utf-8")
    example_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(settings_module, "ENV_PATH", env_path)
    monkeypatch.setattr(settings_module, "ENV_EXAMPLE_PATH", example_path)
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)

    result = update_reddit_settings(
        {
            "client_id": "abc123",
            "client_secret": "secret456",
            "user_agent": "InsightAgentTest/0.1 by tester",
        }
    )

    assert result["oauth_ready"] is True
    assert os.environ["REDDIT_CLIENT_ID"] == "abc123"
    assert os.environ["REDDIT_CLIENT_SECRET"] == "secret456"
    assert "REDDIT_CLIENT_SECRET=secret456" in env_path.read_text(encoding="utf-8")


def test_update_research_settings_writes_data_volume_defaults(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    env_path.write_text("", encoding="utf-8")
    example_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(settings_module, "ENV_PATH", env_path)
    monkeypatch.setattr(settings_module, "ENV_EXAMPLE_PATH", example_path)
    for key in (
        "INSIGHT_RESEARCH_MODE",
        "INSIGHT_RESEARCH_TIME_RANGE",
        "INSIGHT_RESEARCH_POST_LIMIT",
        "INSIGHT_LLM_EVIDENCE_POSTS",
        "INSIGHT_LLM_COMMENT_SAMPLES_PER_POST",
        "AMAZON_PRODUCT_LIMIT",
        "AMAZON_KEYWORD_LIMIT",
        "AMAZON_DETAIL_LIMIT",
        "AMAZON_DISCUSSION_LIMIT",
        "AMAZON_REVIEWS_PER_PRODUCT",
        "AMAZON_LLM_PRODUCT_LIMIT",
        "AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT",
    ):
        monkeypatch.delenv(key, raising=False)

    result = update_research_settings(
        {
            "mode": "agent_reach",
            "timeRange": "month",
            "limit": 120,
            "llmEvidencePosts": 30,
            "llmCommentSamplesPerPost": 10,
            "amazonProductLimit": 60,
            "amazonKeywordLimit": 9,
            "amazonDetailLimit": 12,
            "amazonDiscussionLimit": 8,
            "amazonReviewsPerProduct": 15,
            "amazonLlmProductLimit": 40,
            "amazonLlmReviewSamplesPerProduct": 6,
        }
    )

    assert result["limit"] == 120
    assert result["llmEvidencePosts"] == 30
    assert result["amazonProductLimit"] == 60
    assert result["amazonKeywordLimit"] == 9
    assert os.environ["INSIGHT_RESEARCH_POST_LIMIT"] == "120"
    assert os.environ["AMAZON_PRODUCT_LIMIT"] == "60"
    assert os.environ["AMAZON_KEYWORD_LIMIT"] == "9"
    assert "INSIGHT_LLM_COMMENT_SAMPLES_PER_POST=10" in env_path.read_text(encoding="utf-8")
    assert "AMAZON_DISCUSSION_LIMIT=8" in env_path.read_text(encoding="utf-8")


def test_research_settings_clamps_defaults() -> None:
    settings = build_research_settings_response(
        {
            "INSIGHT_RESEARCH_MODE": "auto",
            "INSIGHT_RESEARCH_TIME_RANGE": "year",
            "INSIGHT_RESEARCH_POST_LIMIT": "999",
            "INSIGHT_LLM_EVIDENCE_POSTS": "0",
            "INSIGHT_LLM_COMMENT_SAMPLES_PER_POST": "99",
            "AMAZON_PRODUCT_LIMIT": "999",
            "AMAZON_KEYWORD_LIMIT": "99",
            "AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT": "99",
        }
    )

    assert settings["limit"] == 500
    assert settings["llmEvidencePosts"] == 1
    assert settings["llmCommentSamplesPerPost"] == 50
    assert settings["amazonProductLimit"] == 100
    assert settings["amazonKeywordLimit"] == 20
    assert settings["amazonLlmReviewSamplesPerProduct"] == 50


def test_llm_analysis_is_requested_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server_module, "CACHE_DIR", tmp_path)

    def fake_enhance(_report: dict[str, object]) -> dict[str, object]:
        return {
            "provider": "test",
            "model": "test-model",
            "result": {"executive_summary": "Default AI synthesis ran."},
        }

    monkeypatch.setattr("insight_agent.server.enhance_report_with_llm", fake_enhance)

    result = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "sample",
            "limit": 6,
            "timeRange": "year",
        }
    )

    assert result["data_volume"]["llm_requested"] is True
    assert result["llm_analysis"]["enabled"] is True
    assert result["llm_analysis"]["status"] == "ok"
    assert result["llm_analysis"]["result"]["executive_summary"] == "Default AI synthesis ran."


def test_llm_analysis_fails_closed_without_key(monkeypatch) -> None:
    monkeypatch.setenv("INSIGHT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("INSIGHT_LLM_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    result = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "sample",
            "limit": 6,
            "timeRange": "year",
            "useLlm": True,
        }
    )

    assert result["llm_analysis"]["enabled"] is True
    assert result["llm_analysis"]["status"] == "unavailable"

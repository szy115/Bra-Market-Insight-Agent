import os

from insight_agent import server as server_module
from insight_agent import settings as settings_module
from insight_agent.ingestion import agent_reach as agent_reach_module
from insight_agent.ingestion.agent_reach import normalize_opencli_read_items
from insight_agent.ingestion.schema import EvidenceItem, ProviderResult
from insight_agent.server import analyze_category, build_reddit_query
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
        }
    )

    assert result["source_mode"] == "sample"
    assert result["coverage"]["posts"] == 8
    assert result["data_volume"]["requested_posts"] == 8
    assert result["data_volume"]["collected_posts"] == 8
    assert result["pain_points"]
    assert result["opportunities"]
    assert result["posts"]


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
        }
    )

    assert result["source_mode"] == "agent_reach"
    assert result["coverage"]["posts"] == 1
    assert result["data_volume"]["collected_comments"] == 1
    assert result["data_volume"]["ai_comment_samples"] == 0
    assert result["posts"][0]["comment_items"]
    assert "Top comments" in result["posts"][0]["excerpt"]


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
        }
    )
    fresh = analyze_category(
        {
            "category": "wireless bras for large bust",
            "mode": "agent_reach",
            "limit": 10,
            "timeRange": "year",
            "bypassCache": True,
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
    ):
        monkeypatch.delenv(key, raising=False)

    result = update_research_settings(
        {
            "mode": "agent_reach",
            "timeRange": "month",
            "limit": 120,
            "llmEvidencePosts": 30,
            "llmCommentSamplesPerPost": 10,
        }
    )

    assert result["limit"] == 120
    assert result["llmEvidencePosts"] == 30
    assert os.environ["INSIGHT_RESEARCH_POST_LIMIT"] == "120"
    assert "INSIGHT_LLM_COMMENT_SAMPLES_PER_POST=10" in env_path.read_text(encoding="utf-8")


def test_research_settings_clamps_defaults() -> None:
    settings = build_research_settings_response(
        {
            "INSIGHT_RESEARCH_MODE": "auto",
            "INSIGHT_RESEARCH_TIME_RANGE": "year",
            "INSIGHT_RESEARCH_POST_LIMIT": "999",
            "INSIGHT_LLM_EVIDENCE_POSTS": "0",
            "INSIGHT_LLM_COMMENT_SAMPLES_PER_POST": "99",
        }
    )

    assert settings["limit"] == 500
    assert settings["llmEvidencePosts"] == 1
    assert settings["llmCommentSamplesPerPost"] == 50


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

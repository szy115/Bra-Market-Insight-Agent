import json
from pathlib import Path

from insight_agent import server as server_module
from insight_agent.agent_params import agent_payload_from_params

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_fashion_trend_report_skill_follows_project_structure() -> None:
    skill = server_module.load_agent_skill_registry()["fashion_trend_report"]
    markdown = skill["markdown"]
    required_sections = (
        "## What It Does",
        "## When To Use",
        "## Required Inputs",
        "## Optional Defaults",
        "## Missing Params",
        "## Tool Policy",
        "## Recommended Tool Use",
        "## Evidence Contract",
        "## Output Rules",
    )

    positions = [markdown.index(section) for section in required_sections]
    assert positions == sorted(positions)
    assert skill["input_schema"]["required"] == ["category"]
    assert skill["input_schema"]["defaults"]["marketplace"] == "Global"
    assert skill["input_schema"]["defaults"]["time_range"] == "30d"
    assert skill["input_schema"]["defaults"]["article_results_per_query"] == 10
    assert skill["input_schema"]["defaults"]["article_candidate_limit"] == 30
    assert skill["input_schema"]["defaults"]["report_image_limit"] == 36


def test_fashion_trend_report_requires_target_platform_tool_and_html() -> None:
    skill = server_module.load_agent_skill_registry()["fashion_trend_report"]
    policy = {item["tool"]: item for item in skill["tool_policy"]}
    evidence = {item["evidence_id"]: item for item in skill["evidence_contract"]}

    assert policy["trend_platforms"]["policy"] == "required"
    assert policy["build_trend_report_data"]["policy"] == "required"
    assert policy["render_html_report"]["policy"] == "required"
    assert evidence["required_trend_platforms"]["severity"] == "block"
    assert evidence["required_trend_platforms"]["if_missing"] == "call_missing_tool"
    assert "WGSN、蝶讯、Pinterest" in evidence["required_trend_platforms"]["artifact_requirement"]
    assert evidence["structured_trend_report_data"]["tool"] == "build_trend_report_data"


def test_fashion_trend_report_is_exposed_in_frontend_skill_picker() -> None:
    app_source = (PROJECT_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    i18n_source = (PROJECT_ROOT / "frontend" / "src" / "lib" / "i18n.ts").read_text(encoding="utf-8")

    assert 'id: "fashion_trend_report"' in app_source
    assert 'skillId: "fashion_trend_report"' not in app_source
    assert 'value === "fashion_trend_report"' in app_source
    assert "使用 fashion_trend_report Skill" in i18n_source
    assert 'savedPrompt.includes("time_range=365d")' in app_source
    assert '"agent.template.fashionTrend.title": "流行趋势报告"' in i18n_source
    assert '"agent.template.fashionTrend.title": "Fashion Trend Report"' in i18n_source
    assert "category=women's intimates；marketplace=Global；time_range=30d" in i18n_source
    assert "category=women's intimates; marketplace=Global; time_range=30d" in i18n_source
    assert "article_candidate_limit=30；report_image_limit=36" in i18n_source
    assert "article_candidate_limit=30; report_image_limit=36" in i18n_source
    assert "4–6 个主题" in i18n_source
    assert "6–10 images per story" in i18n_source


def test_trend_platform_params_default_to_thirty_days() -> None:
    payload = agent_payload_from_params(
        {"prompt": "研究 women's intimates 趋势"},
        {"category": "women's intimates"},
    )

    tool_input = server_module.agent_tool_input_payload("trend_platforms", "fallback", payload)

    assert tool_input["category"] == "women's intimates"
    assert tool_input["marketplace"] == "Global"
    assert tool_input["timeRange"] == "30d"
    assert tool_input["resultsPerQuery"] == 10
    assert tool_input["pageReadLimit"] == 30
    assert tool_input["reportImageLimit"] == 36


def test_trend_platform_search_query_uses_requested_recency() -> None:
    payload = {
        "category": "women's intimates",
        "marketplace": "Global",
        "timeRange": "30d",
        "trendContext": "S/S 27",
    }

    queries = {
        target["platform_id"]: server_module.trend_platform_search_query(target, payload)
        for target in server_module.TREND_PLATFORM_TARGETS
    }

    assert "published last 30 days" not in " ".join(queries.values()).lower()
    assert "近30天" not in " ".join(queries.values())
    assert "S/S 27" in queries["wgsn"]
    assert "2027春夏" in queries["diexun"]
    assert "site:diction-style.com" in queries["diexun"]
    assert "site:pinterest.com" in queries["pinterest"]

    all_queries = server_module.trend_platform_search_queries(
        next(item for item in server_module.TREND_PLATFORM_TARGETS if item["platform_id"] == "wgsn"),
        payload,
    )
    assert {item["dimension"] for item in all_queries} >= {
        "overview",
        "colour",
        "materials",
        "silhouette",
        "details",
        "visual",
    }
    assert all("public WGSN" in item["agent_reach_query"] for item in all_queries)

    assert server_module.trend_relevance_status(
        "A fashion brand colour forecast",
        "women's intimates",
    )[0] == "adjacent"
    assert server_module.trend_page_is_generic_hub("https://www.wgsn.com/en/blog") is True
    assert server_module.trend_page_is_generic_hub("https://www.diexun.com/app/index.html") is True
    assert server_module.trend_page_is_generic_hub(
        "https://www.wgsn.com/en/blog/catwalk-trend-confirmations"
    ) is False
    assert server_module.trend_page_is_low_value("https://www.diction-style.com/about_us/")
    assert server_module.trend_page_is_low_value("https://www.pinterest.com/login/")
    assert (
        server_module.safe_trend_image_url(
            "https://www.wgsn.com/media/intro.mp4",
            "https://www.wgsn.com/en/blog/trend",
        )
        == ""
    )


def test_web_search_providers_receive_native_thirty_day_filters(monkeypatch) -> None:
    monkeypatch.setattr(server_module, "write_cache", lambda *_args, **_kwargs: None)

    brave_urls: list[str] = []
    monkeypatch.setattr(
        server_module,
        "search_provider_credentials",
        lambda: ("brave", {"api_key": "test"}),
    )

    def brave_get(url: str, **_kwargs):
        brave_urls.append(url)
        return b'{"web":{"results":[]}}'

    monkeypatch.setattr(server_module, "http_get", brave_get)
    server_module.web_search_query(
        "site:diction-style.com 女士内衣 色彩趋势",
        5,
        bypass_cache=True,
        time_range="30d",
        search_lang="zh-hans",
        country="cn",
    )
    brave_params = server_module.urllib.parse.parse_qs(
        server_module.urllib.parse.urlsplit(brave_urls[-1]).query
    )
    assert "to" in brave_params["freshness"][0]
    assert brave_params["search_lang"] == ["zh-hans"]
    assert brave_params["country"] == ["cn"]

    tavily_payloads: list[dict] = []
    monkeypatch.setattr(
        server_module,
        "search_provider_credentials",
        lambda: ("tavily", {"api_key": "test"}),
    )

    def tavily_post(_url: str, payload: dict, **_kwargs):
        tavily_payloads.append(payload)
        return b'{"results":[]}'

    monkeypatch.setattr(server_module, "http_post_json", tavily_post)
    server_module.web_search_query("WGSN lingerie colour", 5, True, time_range="30d")
    assert tavily_payloads[-1]["time_range"] == "month"
    assert tavily_payloads[-1]["start_date"]
    assert tavily_payloads[-1]["end_date"]

    google_urls: list[str] = []
    monkeypatch.setattr(
        server_module,
        "search_provider_credentials",
        lambda: ("google_cse", {"api_key": "test", "search_engine_id": "cx"}),
    )

    def google_get(url: str, **_kwargs):
        google_urls.append(url)
        return b'{"items":[]}'

    monkeypatch.setattr(server_module, "http_get", google_get)
    server_module.web_search_query("WGSN lingerie colour", 5, True, time_range="30d")
    google_params = server_module.urllib.parse.parse_qs(
        server_module.urllib.parse.urlsplit(google_urls[-1]).query
    )
    assert google_params["dateRestrict"] == ["d30"]


def test_agent_reach_query_describes_the_ideal_current_page(monkeypatch) -> None:
    observed_queries: list[str] = []
    monkeypatch.setattr(server_module, "write_cache", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        server_module,
        "search_provider_credentials",
        lambda: ("agent_reach", {}),
    )
    monkeypatch.setattr(
        server_module,
        "search_agent_reach_exa",
        lambda query, _count: observed_queries.append(query) or [],
    )

    server_module.web_search_query(
        "site:wgsn.com lingerie S/S 27",
        5,
        bypass_cache=True,
        time_range="30d",
        agent_reach_query="A public WGSN S/S 27 lingerie colour forecast",
    )

    assert "Prefer an editorial page published from" in observed_queries[-1]
    assert "current or upcoming fashion season" in observed_queries[-1]
    assert "published last 30 days latest" not in observed_queries[-1].lower()


def test_pinterest_ideas_page_date_is_not_treated_as_pin_recency() -> None:
    results = server_module.official_trend_search_results(
        [
            {
                "title": "Lingerie ideas",
                "url": "https://www.pinterest.com/ideas/lingerie/1234/",
                "snippet": "Lingerie colour and fabric inspiration",
                "published": "2026-07-10",
            }
        ],
        {"pinterest.com"},
        5,
        query_id="pinterest_colour",
        dimension="colour",
    )

    assert results[0]["published"] == ""
    merged = server_module.merge_trend_search_results(
        results,
        "women's intimates",
        "30d",
    )
    assert merged[0]["recency_status"] == "undated"


def test_editorial_headings_and_hashtags_become_pinterest_concepts() -> None:
    concepts = server_module.extract_trend_concepts(
        [
            {
                "search_results": [
                    {
                        "title": "Catwalk trend confirmations for women's A/W 26/27",
                        "snippet": (
                            "## Transformative Teal ## Cocoa Powder "
                            "Highlight print -- Polka Dots #WaistFocus #DopamineDressing"
                        ),
                    }
                ],
                "pages": [],
            }
        ],
        {"category": "women's intimates"},
        limit=10,
    )

    assert "Transformative Teal" in concepts
    assert "Cocoa Powder" in concepts
    assert "Polka Dots" in concepts
    assert "Waist Focus" in concepts
    assert "Dopamine Dressing" in concepts


def test_trend_platform_params_use_canonical_names() -> None:
    payload = agent_payload_from_params(
        {"prompt": "研究 2027 minimizer bra 趋势"},
        {
            "category": "minimizer bra",
            "marketplace": "US",
            "time_range": "365d",
            "design_goal": "规划下一季产品",
            "target_user": "full-bust users",
            "trend_context": "Spring/Summer",
            "article_results_per_query": 6,
            "article_candidate_limit": 1,
            "report_image_limit": 12,
        },
    )

    tool_input = server_module.agent_tool_input_payload("trend_platforms", "fallback", payload)

    assert tool_input["category"] == "minimizer bra"
    assert tool_input["marketplace"] == "US"
    assert tool_input["timeRange"] == "365d"
    assert tool_input["resultsPerPlatform"] == 6
    assert tool_input["pageReadLimit"] == 1
    assert tool_input["reportImageLimit"] == 12
    assert tool_input["designGoal"] == "规划下一季产品"
    assert tool_input["targetUser"] == "full-bust users"


def test_trend_platform_crawler_keeps_three_platforms_separate(monkeypatch) -> None:
    searched_queries: list[str] = []

    def fake_search(query: str, count: int, bypass_cache: bool = False):  # noqa: ARG001
        searched_queries.append(query)
        if "site:wgsn.com" in query:
            return (
                "agent_reach",
                [
                    {
                        "title": "Soft Romance colour forecast",
                        "url": "https://www.wgsn.com/en/blog/test-colours",
                        "snippet": "Soft Romance uses powder pink and sheer lace.",
                        "published": "2026-01-10",
                    }
                ],
                [],
            )
        if "site:diexun.com" in query:
            return (
                "agent_reach",
                [
                        {
                            "title": "蝶讯趋势",
                            "url": "https://www.diexun.com/fashion/trend-1.html",
                        "snippet": "色彩、面料、廓形与款式趋势。",
                        "published": "",
                    }
                ],
                [],
            )
        return (
            "agent_reach",
            [
                {
                    "title": "Pinterest fabric trend",
                    "url": "https://www.pinterest.com/pin/123456789/",
                    "snippet": "Fabric, silhouette and style inspiration.",
                    "published": "",
                }
            ],
            [],
        )

    def fake_fetch(url: str, category: str, *, bypass_cache: bool = False):  # noqa: ARG001
        if "pinterest.com" in url:
            raise ValueError("public page blocked")
        return {
            "title": url,
            "url": url,
            "final_url": url,
            "domain": server_module.article_domain(url),
            "access_mode": "direct_http",
            "readable_chars": 400,
            "evidence_snippets": [f"{category} colour and fabric direction"],
            "access_notes": [],
        }

    monkeypatch.setattr(server_module, "web_search_query", fake_search)
    monkeypatch.setattr(server_module, "fetch_public_trend_page_with_fallback", fake_fetch)

    result = server_module.crawl_trend_platforms(
        {
            "category": "minimizer bra",
            "marketplace": "US",
            "timeRange": "365d",
            "resultsPerPlatform": 5,
            "pageReadLimit": 1,
        }
    )

    assert [item["platform_id"] for item in result["platforms"]] == ["wgsn", "diexun", "pinterest"]
    assert result["coverage"]["required_platforms"] == 3
    assert result["coverage"]["accessed_platforms"] == 3
    assert result["coverage"]["readable_platforms"] == 2
    assert result["coverage"]["search_only_platforms"] == 1
    assert result["coverage"]["readable_pages"] == 2
    assert result["coverage"]["complete"] is True
    pinterest = next(item for item in result["platforms"] if item["platform_id"] == "pinterest")
    assert pinterest["access_status"] == "search_only"
    assert pinterest["search_results"][0]["evidence_level"] == "indexed_public_preview"
    assert "Soft Romance" in result["trend_concepts"]
    assert any(
        "site:pinterest.com" in query and "Soft Romance" in query
        for query in searched_queries
    )


def test_trend_visual_selection_is_global_quality_ranked_not_fixed_quota(monkeypatch) -> None:
    def fake_platform(target: dict, _payload: dict) -> dict:
        platform_id = target["platform_id"]
        visual_specs = {
            "wgsn": [(f"wgsn-{index}", 100 - index) for index in range(4)],
            "diexun": [("diexun-low", 19)],
            "pinterest": [("pinterest-one", 70)],
        }[platform_id]
        visuals = [
            {
                "image_url": (
                    f"https://i.pinimg.com/736x/a/b/{name}.jpg"
                    if platform_id == "pinterest"
                    else f"https://www.wgsn.com/media/{name}.jpg"
                ),
                "canonical_key": name,
                "platform_id": platform_id,
                "source_page_url": (
                    f"https://www.pinterest.com/pin/{1000 + index}/"
                    if platform_id == "pinterest"
                    else f"https://www.wgsn.com/en/blog/{name}"
                ),
                "quality_score": quality,
                "target_season_score": 1,
            }
            for index, (name, quality) in enumerate(visual_specs)
        ]
        return {
            "platform_id": platform_id,
            "name": target["name"],
            "accessed": True,
            "access_status": "readable",
            "page_read_count": 1,
            "qualified_page_count": 1,
            "recent_page_count": 1,
            "background_page_count": 0,
            "undated_page_count": 0,
            "search_results": [],
            "pages": [],
            "visual_evidence": visuals,
            "warnings": [],
        }

    monkeypatch.setattr(server_module, "crawl_one_trend_platform", fake_platform)
    result = server_module.crawl_trend_platforms(
        {"category": "women's intimates", "timeRange": "30d", "reportImageLimit": 5}
    )

    assert result["visual_coverage"]["by_platform"] == {
        "wgsn": 4,
        "diexun": 0,
        "pinterest": 1,
    }
    assert len(result["visual_evidence"]) == 5


def test_public_trend_html_parser_extracts_only_public_evidence(monkeypatch) -> None:
    html = b"""
    <html><head>
      <title>2027 Fabric Direction</title>
      <meta name="description" content="Colour, fabric and silhouette forecast.">
      <meta property="og:image" content="/trend.jpg">
      <meta property="article:published_time" content="2026-07-01T10:00:00Z">
      <script>secret gated payload</script>
      <script type="application/ld+json">{"image":"https://example.com/editorial.jpg"}</script>
    </head><body><h1>Soft structure</h1>
      <img data-src="/look-1.jpg" alt="Editorial look">
      <p>Textured fabric supports a fluid silhouette.</p></body></html>
    """

    class FakeHeaders:
        @staticmethod
        def get(name: str):
            return "text/html; charset=utf-8" if name == "Content-Type" else None

        @staticmethod
        def get_content_charset():
            return "utf-8"

    class FakeResponse:
        status = 200
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read(_limit: int):
            return html

        @staticmethod
        def geturl():
            return "https://example.com/trend"

    monkeypatch.setattr(server_module.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    page = server_module.fetch_public_trend_page(
        "https://example.com/trend",
        "minimizer bra",
        bypass_cache=True,
    )

    assert page["title"] == "2027 Fabric Direction"
    assert page["image_url"] == "https://example.com/trend.jpg"
    assert page["published"] == "2026-07-01T10:00:00+00:00"
    assert page["image_urls"] == [
        "https://example.com/trend.jpg",
        "https://example.com/look-1.jpg",
        "https://example.com/editorial.jpg",
    ]
    assert "secret gated payload" not in " ".join(page["evidence_snippets"])
    assert any("Textured fabric" in item for item in page["evidence_snippets"])


def test_build_trend_report_data_preserves_pages_dates_and_visuals() -> None:
    collection = {
        "category": "women's intimates",
        "marketplace": "Global",
        "time_range": "30d",
        "generated_at": "2026-07-14T00:00:00+00:00",
        "target_seasons": ["S/S 27"],
        "trend_concepts": ["Soft Romance", "Sheer Lace"],
        "coverage": {"required_platforms": 3, "accessed_platforms": 3, "readable_pages": 2},
        "platforms": [
            {
                "platform_id": "wgsn",
                "name": "WGSN",
                "access_status": "readable",
                "evidence_status": "qualified",
                "query_count": 6,
                "raw_result_count": 20,
                "unique_candidate_count": 8,
                "page_read_target": 30,
                "page_attempt_count": 3,
                "page_read_count": 1,
                "qualified_page_count": 1,
                "supporting_page_count": 0,
                "recent_page_count": 1,
                "background_page_count": 0,
                "undated_page_count": 0,
                "discarded_page_count": 2,
                "visual_count": 1,
                "pages": [
                    {
                        "title": "Public intimates colour direction",
                        "url": "https://www.wgsn.com/en/blog/intimates-colour",
                        "final_url": "https://www.wgsn.com/en/blog/intimates-colour",
                        "published": "2026-07-01T00:00:00+00:00",
                        "recency_status": "recent",
                        "relevance_status": "category_specific",
                        "evidence_status": "qualified",
                        "query_dimensions": ["colour"],
                        "evidence_snippets": ["Women's intimates colour direction with a public source."],
                        "images": [
                            {
                                "image_url": "https://www.wgsn.com/media/intimates-colour.jpg",
                            }
                        ],
                        "access_mode": "direct_http",
                    }
                ],
                "search_results": [],
                "warnings": [],
            },
            {
                "platform_id": "diexun",
                "name": "蝶讯 / DICTION",
                "access_status": "readable",
                "evidence_status": "supporting",
                "query_count": 6,
                "raw_result_count": 10,
                "unique_candidate_count": 4,
                "page_read_target": 30,
                "page_attempt_count": 1,
                "page_read_count": 1,
                "qualified_page_count": 0,
                "supporting_page_count": 1,
                "recent_page_count": 0,
                "background_page_count": 0,
                "undated_page_count": 1,
                "discarded_page_count": 0,
                "visual_count": 0,
                "pages": [
                    {
                        "title": "内衣面料趋势",
                        "url": "https://www.diexun.com/trend/1",
                        "published": "",
                        "recency_status": "undated",
                        "relevance_status": "category_specific",
                        "evidence_status": "qualified",
                        "query_dimensions": ["materials"],
                        "evidence_snippets": ["公开页面提及内衣面料方向。"],
                        "images": [],
                        "access_mode": "jina_reader",
                    }
                ],
                "search_results": [],
                "warnings": [],
            },
            {
                "platform_id": "pinterest",
                "name": "Pinterest",
                "access_status": "search_only",
                "evidence_status": "insufficient",
                "query_count": 6,
                "raw_result_count": 10,
                "unique_candidate_count": 1,
                "page_read_target": 30,
                "page_attempt_count": 1,
                "page_read_count": 0,
                "qualified_page_count": 0,
                "supporting_page_count": 0,
                "recent_page_count": 0,
                "background_page_count": 0,
                "undated_page_count": 0,
                "discarded_page_count": 0,
                "visual_count": 1,
                "pages": [],
                "search_results": [
                    {
                        "title": "Intimates moodboard",
                        "url": "https://www.pinterest.com/pin/123456789/",
                        "snippet": "Indexed visual inspiration preview.",
                        "published": "",
                        "recency_status": "undated",
                        "relevance_status": "category_specific",
                        "query_dimensions": ["visual"],
                        "images": [],
                    }
                ],
                "warnings": [],
            },
        ],
        "visual_evidence": [
            {
                "image_url": "https://www.wgsn.com/media/intimates-colour.jpg",
                "platform_id": "wgsn",
                "source_page_url": "https://www.wgsn.com/en/blog/intimates-colour",
                "source_page_title": "Public intimates colour direction",
                "published_at": "2026-07-01T00:00:00+00:00",
                "recency_status": "recent",
                "relevance_status": "category_specific",
                "query_dimensions": ["colour"],
            },
            {
                "image_url": "https://i.pinimg.com/736x/a1/b2/c3/sample.jpg",
                "platform_id": "pinterest",
                "source_page_url": "https://www.pinterest.com/pin/123456789/",
                "source_page_title": "Intimates moodboard",
                "published_at": "",
                "recency_status": "undated",
                "relevance_status": "category_specific",
                "query_dimensions": ["visual"],
            },
        ],
        "visual_coverage": {"available": 2, "selected_for_report": 2, "report_image_limit": 30},
        "method": {"notes": ["Public evidence only."]},
    }

    report_data = server_module.build_trend_report_data(
        {
            "category": "women's intimates",
            "timeRange": "30d",
            "reportImageLimit": 30,
            "toolResults": [{"name": "trend_platforms", "status": "ok", "data": collection}],
        }
    )

    assert report_data["schema_version"] == "trend_report_data.v1"
    assert report_data["query_summary"]["executed_queries"] == 18
    assert report_data["source_summary"]["readable_pages"] == 2
    assert report_data["source_summary"]["recent_pages"] == 1
    assert [item["evidence_id"] for item in report_data["evidence_map"]] == ["T001", "T002", "T003"]
    assert report_data["visual_coverage"]["selected_for_report"] == 2
    assert [item["visual_id"] for item in report_data["visual_evidence"]] == ["V001", "V002"]
    assert report_data["visual_evidence"][0]["source_evidence_id"] == "T001"
    assert report_data["data_gaps"] == []
    assert report_data["target_seasons"] == ["S/S 27"]
    assert report_data["trend_concepts"] == ["Soft Romance", "Sheer Lace"]
    assert report_data["editorial_brief"]["theme_count"] == {"minimum": 4, "maximum": 6}
    assert report_data["editorial_brief"]["visuals_per_theme"]["target_maximum"] == 10
    assert any("Pinterest" in item for item in report_data["source_notes"])
    assert report_data["artifact"]["risks"] == []


def test_trend_visual_atlas_uses_only_whitelisted_unique_images() -> None:
    visuals = [
        {
            "visual_id": "V001",
            "image_url": "https://www.wgsn.com/media/one.jpg",
            "platform_id": "wgsn",
            "source_page_url": "https://www.wgsn.com/en/blog/one",
            "source_page_title": "Source one",
            "source_evidence_id": "T001",
            "recency_status": "recent",
        },
        {
            "visual_id": "V002",
            "image_url": "https://i.pinimg.com/736x/a/b/c/two.jpg",
            "platform_id": "pinterest",
            "source_page_url": "https://www.pinterest.com/pin/2/",
            "source_page_title": "Source two",
            "source_evidence_id": "T002",
            "recency_status": "undated",
        },
    ]
    base_html = (
        "<!doctype html><html><head><style>body{font-family:sans-serif}</style></head><body>"
        "<main><h1>Trend report</h1><p>" + ("Evidence-based report content. " * 30) + "</p></main>"
        "</body></html>"
    )

    recovered, recovered_ids = server_module.ensure_trend_visual_atlas(base_html, visuals)

    assert recovered_ids == ["V001", "V002"]
    assert server_module.validate_llm_html_document(
        recovered,
        required_trend_visuals=visuals,
    ) == ""
    assert recovered.count("<img ") == 2
    assert "onerror=" not in recovered
    assert "更多灵感素材" in recovered
    assert "公开视觉证据图集" not in recovered
    assert "证据边界" not in recovered

    unsafe = recovered.replace(
        "</body>",
        '<img src="https://evil.example/image.jpg" onerror="alert(1)"></body>',
    )
    assert server_module.validate_llm_html_document(
        unsafe,
        required_trend_visuals=visuals,
    )


def test_trend_report_composer_passes_structured_evidence_and_recovers_visuals(monkeypatch) -> None:
    visuals = [
        {
            "visual_id": "V001",
            "image_url": "https://www.wgsn.com/media/one.jpg",
            "platform_id": "wgsn",
            "source_page_url": "https://www.wgsn.com/en/blog/one",
            "source_page_title": "Source one",
            "source_evidence_id": "T001",
            "recency_status": "recent",
        },
        {
            "visual_id": "V002",
            "image_url": "https://i.pinimg.com/736x/a/b/c/two.jpg",
            "platform_id": "pinterest",
            "source_page_url": "https://www.pinterest.com/pin/2/",
            "source_page_title": "Source two",
            "source_evidence_id": "T002",
            "recency_status": "undated",
        },
    ]
    report_data = {
        "schema_version": "trend_report_data.v1",
        "title": "Women's intimates 流行趋势报告",
        "category": "women's intimates",
        "marketplace": "Global",
        "time_range": "30d",
        "generated_at": "2026-07-14T00:00:00+00:00",
        "coverage": {"accessed_platforms": 3},
        "query_summary": {"executed_queries": 18},
        "source_summary": {"readable_pages": 12, "recent_pages": 4},
        "platforms": [],
        "target_seasons": ["S/S 27"],
        "trend_concepts": ["Soft Romance"],
        "editorial_brief": {
            "theme_count": {"minimum": 4, "maximum": 6},
            "forbidden_sections": ["验证矩阵"],
        },
        "source_notes": [],
        "evidence_map": [
            {
                "evidence_id": "T001",
                "platform_id": "wgsn",
                "source_type": "public_page",
                "title": "Source one",
                "url": "https://www.wgsn.com/en/blog/one",
                "recency_status": "recent",
                "relevance_status": "category_specific",
                "evidence_snippets": ["A public trend statement."],
            }
        ],
        "visual_evidence": visuals,
        "visual_coverage": {"selected_for_report": 2},
        "data_gaps": [],
        "artifact": {"title": "Women's intimates 流行趋势报告"},
    }
    base_html = (
        "<!doctype html><html><head><title>Trend report</title>"
        "<style>body{font-family:sans-serif}</style></head><body><main>"
        "<h1>Trend report</h1><p>" + ("Evidence-based trend report. " * 30) + "</p>"
        "</main></body></html>"
    )
    observed_payload: dict = {}
    observed_system: list[str] = []
    call_count = 0

    def fake_call(messages, **_kwargs):
        nonlocal call_count
        call_count += 1
        observed_system.append(messages[0]["content"])
        observed_payload.update(server_module.json.loads(messages[-1]["content"]))
        return {
            "provider": "test",
            "model": "html",
            "usage": {},
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": base_html},
        }

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_call)

    html_content, artifact, analysis = server_module.compose_html_report_with_llm(
        {
            "category": "women's intimates",
            "timeRange": "30d",
            "skillId": "fashion_trend_report",
            "trendReportData": report_data,
            "toolResults": [],
        }
    )

    assert observed_payload["report_data_schema"] == "trend_report_data.v1"
    trend_context = observed_payload["trend_report_data"]
    assert "query_summary" not in trend_context
    assert "platforms" not in trend_context
    assert "data_gaps" not in trend_context
    assert trend_context["trend_concepts"] == ["Soft Romance"]
    assert trend_context["editorial_brief"]["theme_count"]["maximum"] == 6
    assert trend_context["source_material"][0]["trend_signals"] == [
        "A public trend statement."
    ]
    assert "evidence_gaps" not in observed_payload
    assert "recency_status" not in observed_payload["required_trend_visuals"][0]
    assert "market_report_data" not in observed_payload
    assert "Create an editorial inspiration report" in observed_system[-1]
    assert "Forbidden sections include evidence boundaries" in observed_system[-1]
    assert html_content.count("<img ") == 2
    assert 'data-visual-id="V001"' in html_content
    assert "更多灵感素材" in html_content
    assert artifact["title"] == "Women's intimates 流行趋势报告"
    assert analysis["status"] == "ok"
    assert call_count == 2
    assert analysis["attempt_count"] == 2
    assert analysis["attempts"][0]["status"] == "validation_failed"
    assert analysis["recovered_visual_ids"] == ["V001", "V002"]


def test_fashion_trend_agent_routes_collection_through_builder_before_render(monkeypatch) -> None:
    def tool_call(call_id: str, name: str, arguments: dict) -> dict:
        return {
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }

    def chat_response(name: str, arguments: dict | None = None) -> dict:
        return {
            "provider": "test",
            "model": "native-tools",
            "usage": {},
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [tool_call(f"call-{name}", name, arguments or {})],
            },
        }

    responses = [
        chat_response(
            "load_skill",
            {
                "skill_id": "fashion_trend_report",
                "extracted_params": {
                    "category": "women's intimates",
                    "marketplace": "Global",
                    "time_range": "30d",
                },
            },
        ),
        chat_response("trend_platforms"),
        {
            "provider": "test",
            "model": "native-tools",
            "usage": {},
            "message": {"role": "assistant", "content": ""},
        },
    ]
    observed_payloads: dict[str, dict] = {}

    def fake_chat(_messages, tools=None, tool_choice=None):  # noqa: ARG001
        return responses.pop(0)

    def fake_execute(tool_name: str, category: str, payload: dict) -> dict:
        observed_payloads[tool_name] = payload
        if tool_name == "trend_platforms":
            data = {
                "category": category,
                "marketplace": "Global",
                "time_range": "30d",
                "platforms": [],
                "coverage": {"accessed_platforms": 3},
                "visual_evidence": [],
            }
        elif tool_name == "build_trend_report_data":
            assert any(item.get("name") == "trend_platforms" for item in payload["toolResults"])
            data = {
                "schema_version": "trend_report_data.v1",
                "title": "Women's intimates 流行趋势报告",
                "category": category,
                "visual_evidence": [],
                "artifact": {
                    "title": "Women's intimates 流行趋势报告",
                    "executive_summary": "Structured trend evidence.",
                },
            }
        elif tool_name == "render_html_report":
            assert payload["trendReportData"]["schema_version"] == "trend_report_data.v1"
            assert payload["marketReportData"] == {}
            data = {
                "format": "html",
                "title": "Women's intimates 流行趋势报告",
                "html": (
                    "<!doctype html><html><head><style>body{font-family:sans-serif}</style></head>"
                    "<body><main><h1>Women's intimates 流行趋势报告</h1></main></body></html>"
                ),
                "artifact": {
                    "title": "Women's intimates 流行趋势报告",
                    "executive_summary": "Structured trend evidence.",
                },
            }
        else:  # pragma: no cover - the runtime owns system tools.
            raise AssertionError(tool_name)
        return {
            "name": tool_name,
            "label": server_module.agent_tool_catalog()[tool_name]["label"],
            "status": "ok",
            "summary": f"{tool_name} completed",
            "duration_ms": 1,
            "input": payload,
            "data": data,
        }

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)
    monkeypatch.setattr(server_module, "execute_agent_tool_with_timeout", fake_execute)
    monkeypatch.setattr(
        server_module,
        "synthesize_report_insights_node",
        lambda payload: {
            "schema_version": "report_insight_narrative.v1",
            "status": "empty_supported_insights",
            "sections": [],
            "section_count": 0,
            "insight_count": 0,
        },
    )
    monkeypatch.setattr(
        server_module,
        "review_html_report_node",
        lambda payload: {
            "round": int(payload.get("reviewRound") or 1),
            "status": "ok",
            "decision": "approve",
            "approved": True,
            "summary": "通用报告审批通过。",
            "issues": [],
            "duration_ms": 1,
        },
    )
    monkeypatch.setattr(
        server_module,
        "red_team_html_report_node",
        lambda payload: {
            "schema_version": "report_red_team_review.v1",
            "round": int(payload.get("reviewRound") or 1),
            "status": "ok",
            "decision": "approve",
            "approved": True,
            "summary": "红队审查通过。",
            "findings": [],
            "issues": [],
            "duration_ms": 1,
        },
    )

    result = server_module.run_agent(
        {
            "prompt": "研究 women's intimates 最近 30 天流行趋势，必须访问 WGSN、蝶讯和 Pinterest。",
            "category": "women's intimates",
            "agentMode": "market",
            "useLlm": True,
        }
    )

    assert result["status"] == "ok"
    assert [item["name"] for item in result["tools"]] == [
        "trend_platforms",
        "build_trend_report_data",
        "analyze_market_report",
        "synthesize_report_insights",
        "render_report_charts",
        "render_html_report",
        "review_html_report",
        "red_team_html_report",
        "join_report_approval",
    ]
    assert observed_payloads["render_html_report"]["toolResults"] == []
    assert result["artifact"]["title"] == "Women's intimates 流行趋势报告"

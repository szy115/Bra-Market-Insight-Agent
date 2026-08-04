from insight_agent.agent_params import (
    adapt_agent_params_for_tool,
    agent_payload_from_params,
    category_supported_by_prompt,
    resolve_canonical_agent_params,
)


def test_resolve_canonical_agent_params_normalizes_skill_and_prompt_names() -> None:
    skill = {
        "input_schema": {
            "required": ["brand", "marketplace", "category", "time_range"],
            "defaults": {
                "reddit_limit": 22,
                "tiktok_limit": 5,
                "listing_sample_size": 44,
            },
        }
    }

    params, missing = resolve_canonical_agent_params(
        skill,
        {
            "prompt": "帮我分析美国 Amazon US 市场 minimizer bra 最近90天在变什么，品牌 Hsia。",
            "category": "minimizer bra",
        },
        {"market": "Amazon US"},
    )

    assert missing == []
    assert params["brand"] == "Hsia"
    assert params["marketplace"] == "Amazon US"
    assert params["category"] == "minimizer bra"
    assert params["time_range"] == "90d"
    assert params["reddit_post_limit"] == 22
    assert params["tiktok_video_limit"] == 5
    assert params["listing_sample_size"] == 44
    assert "reddit_limit" not in params
    assert "tiktok_limit" not in params


def test_agent_payload_from_params_bridges_canonical_to_existing_payload_keys() -> None:
    payload = {"prompt": "market task", "bypassCache": False}

    mapped = agent_payload_from_params(
        payload,
        {
            "brand": "Hsia",
            "marketplace": "Amazon US",
            "category": "minimizer bra",
            "asin": "B0CLPGQWNB",
            "time_range": "90d",
            "listing_sample_size": 35,
            "head_listing_count": 10,
            "review_sample_size": 30,
            "new_product_window": "180d",
            "category_node_id": "7141123011:7147440011:1045002",
            "reddit_post_limit": 40,
            "tiktok_video_limit": 7,
            "bypass_cache": True,
        },
    )

    assert mapped["params"]["time_range"] == "90d"
    assert mapped["marketplace"] == "Amazon US"
    assert mapped["asin"] == "B0CLPGQWNB"
    assert mapped["timeRange"] == "90d"
    assert mapped["amazonLimit"] == 35
    assert mapped["head_listing_count"] == 10
    assert mapped["review_sample_size"] == 30
    assert mapped["new_product_window"] == "180d"
    assert mapped["category_node_id"] == "7141123011:7147440011:1045002"
    assert mapped["redditLimit"] == 40
    assert mapped["tiktokLimit"] == 7
    assert mapped["bypassCache"] is True


def test_resolve_canonical_agent_params_extracts_asin_from_prompt() -> None:
    skill = {
        "input_schema": {
            "required": ["marketplace", "asin"],
            "defaults": {"brand": "Hsia"},
        }
    }

    params, missing = resolve_canonical_agent_params(
        skill,
        {
            "prompt": "深拆 Amazon US 商品 https://www.amazon.com/dp/B0CLPGQWNB，加入 Reddit VOC。",
        },
        {},
    )

    assert missing == []
    assert params["marketplace"] == "Amazon US"
    assert params["asin"] == "B0CLPGQWNB"
    assert params["brand"] == "Hsia"


def test_resolve_canonical_agent_params_accepts_llm_extracted_category() -> None:
    skill = {
        "input_schema": {
            "required": ["brand", "marketplace", "category"],
            "defaults": {"time_range": "90d"},
        }
    }

    params, missing = resolve_canonical_agent_params(
        skill,
        {"prompt": "帮我分析美国 Amazon US 市场 yoga pants 最近90天在变什么。"},
        {"brand": "Hsia", "market": "US", "category": "yoga pants"},
    )

    assert missing == []
    assert params["brand"] == "Hsia"
    assert params["marketplace"] == "US"
    assert params["category"] == "yoga pants"
    assert params["time_range"] == "90d"


def test_resolve_canonical_agent_params_rejects_model_example_category_not_in_prompt() -> None:
    skill = {
        "input_schema": {
            "required": ["brand", "marketplace", "category"],
            "defaults": {"time_range": "90d"},
        }
    }

    params, missing = resolve_canonical_agent_params(
        skill,
        {"prompt": "帮我生成 Hsia 美国市场 Sports Bras 本周洞察报告。"},
        {"market": "US", "category": "minimizer bra"},
    )

    assert "category" in missing
    assert params["brand"] == "Hsia"
    assert params["marketplace"] == "US"
    assert "category" not in params
    assert category_supported_by_prompt("sports bra", "Sports Bras 本周洞察报告")
    assert not category_supported_by_prompt("minimizer bra", "Sports Bras 本周洞察报告")


def test_adapt_agent_params_for_tool_uses_canonical_params() -> None:
    payload = {
        "params": {
            "category": "minimizer bra",
            "time_range": "90d",
            "listing_sample_size": 33,
            "reddit_post_limit": 45,
            "reddit_detail_limit": 8,
            "reddit_comments_per_post": 12,
            "tiktok_video_limit": 9,
            "tiktok_comments_per_video": 6,
        }
    }

    reddit_input = adapt_agent_params_for_tool("reddit_voc", "fallback", payload)
    amazon_input = adapt_agent_params_for_tool("amazon_shelf", "fallback", payload)
    tiktok_input = adapt_agent_params_for_tool("tiktok_social", "fallback", payload)

    assert reddit_input["category"] == "minimizer bra"
    assert reddit_input["timeRange"] == "90d"
    assert reddit_input["limit"] == 45
    assert reddit_input["redditDetailLimit"] == 8
    assert reddit_input["redditCommentsPerPost"] == 12
    assert amazon_input["limit"] == 33
    assert tiktok_input["limit"] == 9
    assert tiktok_input["tiktokCommentsPerVideo"] == 6


def test_market_report_builder_receives_canonical_category_node_id() -> None:
    builder_input = adapt_agent_params_for_tool(
        "build_market_report_data",
        "minimizer bra",
        {
            "params": {
                "category": "minimizer bra",
                "category_node_id": "3760901:1044960",
            },
            "toolResults": [],
        },
    )

    assert builder_input["categoryNodeId"] == "3760901:1044960"


def test_tiktok_new_product_builder_receives_canonical_skill_params() -> None:
    builder_input = adapt_agent_params_for_tool(
        "build_tiktok_new_product_report_data",
        "fallback",
        {
            "skillId": "tiktok_us_lingerie_new_product_insight",
            "params": {
                "brand": "Hsia",
                "marketplace": "US",
                "category": "女士文胸",
                "category_node_id": "601262",
                "time_range": "28d",
                "new_product_window": "30d",
                "listing_sample_size": 20,
                "head_listing_count": 5,
            },
            "toolResults": [{"name": "ranking"}],
        },
    )

    assert builder_input["skillId"] == "tiktok_us_lingerie_new_product_insight"
    assert builder_input["category"] == "女士文胸"
    assert builder_input["marketplace"] == "US"
    assert builder_input["categoryNodeId"] == "601262"
    assert builder_input["timeRange"] == "28d"
    assert builder_input["newProductWindow"] == "30d"
    assert builder_input["listingSampleSize"] == 20
    assert builder_input["headListingCount"] == 5
    assert builder_input["toolResults"] == [{"name": "ranking"}]


def test_tiktok_competitor_shop_builder_receives_canonical_skill_params() -> None:
    builder_input = adapt_agent_params_for_tool(
        "build_tiktok_bra_competitor_shop_report_data",
        "fallback",
        {
            "skillId": "tiktok_us_bra_competitor_shop_analysis",
            "params": {
                "brand": "Hsia",
                "marketplace": "US",
                "category": "女士文胸",
                "category_node_id": "601262",
                "time_range": "28d",
                "new_product_window": "30d",
                "shop_candidate_size": 50,
                "shop_analysis_count": 10,
            },
            "toolResults": [{"name": "ranking"}],
        },
    )

    assert builder_input["skillId"] == "tiktok_us_bra_competitor_shop_analysis"
    assert builder_input["categoryNodeId"] == "601262"
    assert builder_input["timeRange"] == "28d"
    assert builder_input["newProductWindow"] == "30d"
    assert builder_input["shopCandidateSize"] == 50
    assert builder_input["shopAnalysisCount"] == 10
    assert builder_input["toolResults"] == [{"name": "ranking"}]


def test_render_html_report_preserves_skill_html_template() -> None:
    template = '<section data-required-section="executive">{{EXECUTIVE}}</section>'

    rendered_input = adapt_agent_params_for_tool(
        "render_html_report",
        "minimizer bra",
        {
            "prompt": "从产品研发角度分析 minimizer bra。",
            "skillId": "competitor_product_deep_dive",
            "skillMarkdown": "### HTML Report Style Reference",
            "skillHtmlTemplate": template,
            "useLlm": True,
        },
    )

    assert rendered_input["skillHtmlTemplate"] == template
    assert rendered_input["skillId"] == "competitor_product_deep_dive"
    assert rendered_input["useLlm"] is True
    assert rendered_input["reportImageLimit"] == 60


def test_render_html_report_preserves_tiktok_new_product_report_data() -> None:
    report_data = {"schema_version": "tiktok_new_product_report_data.v1"}

    rendered_input = adapt_agent_params_for_tool(
        "render_html_report",
        "女士内衣",
        {
            "skillId": "tiktok_us_lingerie_new_product_insight",
            "tiktokNewProductReportData": report_data,
            "useLlm": True,
        },
    )

    assert rendered_input["tiktokNewProductReportData"] == report_data


def test_render_html_report_preserves_tiktok_competitor_shop_report_data() -> None:
    report_data = {"schema_version": "tiktok_bra_competitor_shop_report_data.v1"}

    rendered_input = adapt_agent_params_for_tool(
        "render_html_report",
        "女士文胸",
        {
            "skillId": "tiktok_us_bra_competitor_shop_analysis",
            "tiktokCompetitorShopReportData": report_data,
            "useLlm": True,
        },
    )

    assert rendered_input["tiktokCompetitorShopReportData"] == report_data


def test_html_builder_and_renderer_preserve_new_workflow_report_data() -> None:
    source_results = [{"name": "sellersprite_review", "status": "ok"}]
    builder_input = adapt_agent_params_for_tool(
        "build_competitor_product_report_data",
        "minimizer bra",
        {
            "skillId": "competitor_product_deep_dive",
            "params": {"asin": "B000TEST1", "marketplace": "Amazon US"},
            "toolResults": source_results,
        },
    )
    competitor_data = {"schema_version": "competitor_product_report_data.v1"}
    hot_product_data = {"schema_version": "hot_product_pain_report_data.v1"}
    rendered_input = adapt_agent_params_for_tool(
        "render_html_report",
        "minimizer bra",
        {
            "competitorProductReportData": competitor_data,
            "hotProductPainReportData": hot_product_data,
            "toolResults": [],
            "useLlm": True,
        },
    )

    assert builder_input["asin"] == "B000TEST1"
    assert builder_input["toolResults"] == source_results
    assert rendered_input["competitorProductReportData"] == competitor_data
    assert rendered_input["hotProductPainReportData"] == hot_product_data
    assert rendered_input["toolResults"] == []


def test_product_design_params_bridge_to_builder_markdown_and_public_urls() -> None:
    payload = agent_payload_from_params(
        {"prompt": "研究 strapless bra"},
        {
            "category": "strapless bra",
            "design_goal": "开发稳定不下滑的大胸抹胸文胸",
            "target_user": "US full-bust users",
            "brand_site_urls": ["https://wacoal-america.com/collections/best-sellers"],
            "trend_context": "Public color direction supplied by the designer.",
        },
    )

    assert payload["designGoal"] == "开发稳定不下滑的大胸抹胸文胸"
    assert payload["targetUser"] == "US full-bust users"
    assert payload["brandSiteUrls"] == ["https://wacoal-america.com/collections/best-sellers"]

    media_input = adapt_agent_params_for_tool("media_rankings", "strapless bra", payload)
    assert media_input["urls"] == ["https://wacoal-america.com/collections/best-sellers"]

    builder_input = adapt_agent_params_for_tool(
        "build_product_design_brief_data",
        "strapless bra",
        {**payload, "toolResults": [{"name": "example"}]},
    )
    assert builder_input["designGoal"] == "开发稳定不下滑的大胸抹胸文胸"
    assert builder_input["listingSampleSize"] == 100
    assert builder_input["reviewSampleSize"] == 60
    assert builder_input["toolResults"] == [{"name": "example"}]

    markdown_input = adapt_agent_params_for_tool(
        "render_markdown_report",
        "strapless bra",
        {
            **payload,
            "productDesignBriefData": {"schema_version": "product_design_brief_data.v1"},
            "useLlm": True,
        },
    )
    assert markdown_input["useLlm"] is True
    assert (
        markdown_input["productDesignBriefData"]["schema_version"] == "product_design_brief_data.v1"
    )

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

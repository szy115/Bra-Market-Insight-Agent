from pathlib import Path

from insight_agent.agent_skill_harness import allowed_data_tools_for_skill
from insight_agent.server import load_agent_skill_registry

SKILL_ID = "tiktok_us_bra_competitor_shop_analysis"


def test_competitor_shop_skill_defaults_and_task_mapping() -> None:
    skill = load_agent_skill_registry()[SKILL_ID]
    markdown = skill["markdown"]
    policy = {item["tool"]: item["policy"] for item in skill["tool_policy"]}

    assert skill["input_schema"]["required"] == []
    assert skill["input_schema"]["defaults"] == {
        "brand": "Hsia",
        "marketplace": "US",
        "category": "女士文胸",
        "category_node_id": "",
        "time_range": "28d",
        "shop_candidate_size": 50,
        "shop_analysis_count": 10,
        "new_product_window": "30d",
    }
    for tool in (
        "build_tiktok_bra_competitor_shop_report_data",
        "render_html_report",
        "mcp__fastmoss__search_category_by_words",
        "mcp__fastmoss__shop_rank_top_selling",
        "mcp__fastmoss__shop_base_info",
        "mcp__fastmoss__shop_product_analysis",
        "mcp__fastmoss__shop_sale_analysis",
        "mcp__fastmoss__shop_data_trends",
        "mcp__fastmoss__shop_creator_analysis",
        "mcp__fastmoss__fastmoss_detail_url_examples",
    ):
        assert policy[tool] == "required"
    assert policy["mcp__fastmoss__shop_video_analysis"] == "disallowed"
    assert policy["mcp__fastmoss__shop_live_analysis"] == "disallowed"
    assert policy["mcp__fastmoss__shop_investment_analysis"] == "disallowed"
    assert policy["mcp__fastmoss__shop_search"] == "disallowed"
    for task_id in range(1, 10):
        assert f"CS{task_id:02d}" in markdown
    assert "50 家外部竞品候选池" in markdown
    assert "同一组 seller_id" in markdown
    assert "不要调用 `build_market_report_data`" in markdown
    assert "category_id=842888" in markdown
    assert "禁止在该请求的 `filter` 中加入 `category_id`" in markdown
    assert "最多 3 页" in markdown
    assert "`category.l3.id`" in markdown
    assert "按 `product_id` 去重" in markdown
    assert "pending.resume_supported=true" in markdown


def test_competitor_shop_skill_exposes_only_declared_standard_workflow() -> None:
    skill = load_agent_skill_registry()[SKILL_ID]
    all_tools = [
        "build_market_report_data",
        "build_tiktok_bra_competitor_shop_report_data",
        "render_html_report",
        "mcp__fastmoss__shop_rank_top_selling",
        "mcp__fastmoss__shop_base_info",
        "mcp__fastmoss__shop_product_analysis",
        "mcp__fastmoss__shop_sale_analysis",
        "mcp__fastmoss__shop_data_trends",
        "mcp__fastmoss__shop_creator_analysis",
        "mcp__fastmoss__shop_video_analysis",
        "mcp__fastmoss__shop_live_analysis",
        "mcp__fastmoss__shop_investment_analysis",
    ]

    assert allowed_data_tools_for_skill(skill, all_tools) == [
        "build_tiktok_bra_competitor_shop_report_data",
        "render_html_report",
        "mcp__fastmoss__shop_rank_top_selling",
        "mcp__fastmoss__shop_base_info",
        "mcp__fastmoss__shop_product_analysis",
        "mcp__fastmoss__shop_sale_analysis",
        "mcp__fastmoss__shop_data_trends",
        "mcp__fastmoss__shop_creator_analysis",
    ]


def test_competitor_shop_skill_evidence_and_reader_first_contract() -> None:
    skill = load_agent_skill_registry()[SKILL_ID]
    markdown = skill["markdown"]
    evidence = {item["evidence_id"]: item for item in skill["evidence_contract"]}

    assert evidence["competitor_shop_ranking"]["min_success"] == 5
    for evidence_id in (
        "shop_base_snapshots",
        "bra_product_structures",
        "shop_trends",
        "shop_channels",
        "shop_creators",
    ):
        assert evidence[evidence_id]["min_success"] == "param:shop_analysis_count"
    assert evidence["compiled_competitor_shop_report"]["tool"] == (
        "build_tiktok_bra_competitor_shop_report_data"
    )
    assert "不要放任务覆盖率、P0缺失" in markdown
    assert "局部字段缺失时省略依赖该字段的比较或结论" in markdown
    assert "不生成数据缺口、不可判断清单" in markdown
    assert "观察样本集中度" in markdown
    assert "全店口径" in markdown


def test_competitor_shop_skill_is_exposed_in_frontend_picker() -> None:
    app_source = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    api_source = Path("frontend/src/lib/api.ts").read_text(encoding="utf-8")
    i18n_source = Path("frontend/src/lib/i18n.ts").read_text(encoding="utf-8")

    assert '| "tiktok_us_bra_competitor_shop_analysis"' in app_source
    assert 'id: "tiktok_us_bra_competitor_shop_analysis"' in app_source
    assert 'skillId: "tiktok_us_bra_competitor_shop_analysis"' not in app_source
    assert 'value === "tiktok_us_bra_competitor_shop_analysis"' in app_source
    assert "使用 tiktok_us_bra_competitor_shop_analysis Skill" in i18n_source
    assert 'mode: "competitor"' in app_source
    assert '"agent.template.tiktokUsBraCompetitors.title"' in i18n_source
    assert "50 家外部竞品候选" in i18n_source
    assert "前 10 个 seller_id" in i18n_source
    assert "本版不做 Top 3 视频、直播或广告深拆" in i18n_source
    assert 'data-testid="checkpoint-continuation"' in app_source
    assert "request.continueRunId" in app_source
    assert "request.contextRunId" in app_source
    assert "contextRunId?: string" in api_source
    assert "resume_supported?: boolean" in api_source

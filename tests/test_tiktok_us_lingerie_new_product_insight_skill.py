from pathlib import Path

from insight_agent.agent_skill_harness import allowed_data_tools_for_skill
from insight_agent.server import load_agent_skill_registry

SKILL_ID = "tiktok_us_lingerie_new_product_insight"


def test_new_product_skill_keeps_project_section_order_and_defaults() -> None:
    skill = load_agent_skill_registry()[SKILL_ID]
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
    assert skill["input_schema"]["required"] == []
    assert skill["input_schema"]["defaults"] == {
        "brand": "Hsia",
        "marketplace": "US",
        "category": "女士文胸",
        "time_range": "28d",
        "listing_sample_size": 20,
        "head_listing_count": 5,
        "new_product_window": "30d",
        "category_node_id": "",
    }


def test_new_product_skill_maps_small_task_set_to_fastmoss_tools() -> None:
    skill = load_agent_skill_registry()[SKILL_ID]
    markdown = skill["markdown"]
    policy = {item["tool"]: item["policy"] for item in skill["tool_policy"]}

    for tool in (
        "build_tiktok_new_product_report_data",
        "render_html_report",
        "mcp__fastmoss__search_category_by_words",
        "mcp__fastmoss__product_rank_new_listed",
        "mcp__fastmoss__product_detail_info",
        "mcp__fastmoss__product_sales_trend",
        "mcp__fastmoss__fastmoss_detail_url_examples",
    ):
        assert policy[tool] == "required"

    assert "build_market_report_data" not in policy
    assert "mcp__fastmoss__product_search" not in policy
    assert "mcp__fastmoss__shop_rank_top_selling" not in policy
    for task_id in range(1, 7):
        assert f"NP{task_id:02d}" in markdown
    assert "total_units_sold" in markdown
    assert "listing_end_date" in markdown
    assert "最近 1–3 天" in markdown
    assert "filter.category_l3_id" in markdown
    assert "类目与价格筛选都必须发生在去重、样本计数和销量排序之前" in markdown
    assert "不得只靠标题含 `bra` 判断" in markdown
    assert "非文胸或价格越界商品即使销量更高，也不得进入 Top" in markdown
    assert "20 <= current_price <= 100" in markdown
    assert "价格缺失、低于 20 USD 或高于 100 USD" in markdown
    assert "`shop_name`、`shop_id`" in markdown


def test_new_product_skill_only_exposes_declared_narrow_workflow() -> None:
    skill = load_agent_skill_registry()[SKILL_ID]
    all_tools = [
        "build_market_report_data",
        "build_tiktok_new_product_report_data",
        "render_html_report",
        "mcp__fastmoss__product_search",
        "mcp__fastmoss__product_rank_new_listed",
        "mcp__fastmoss__product_detail_info",
        "mcp__fastmoss__product_sales_trend",
        "mcp__fastmoss__shop_rank_top_selling",
    ]

    allowed = allowed_data_tools_for_skill(skill, all_tools)

    assert allowed == [
        "build_tiktok_new_product_report_data",
        "render_html_report",
        "mcp__fastmoss__product_rank_new_listed",
        "mcp__fastmoss__product_detail_info",
        "mcp__fastmoss__product_sales_trend",
    ]


def test_new_product_skill_has_per_product_evidence_gates() -> None:
    skill = load_agent_skill_registry()[SKILL_ID]
    evidence = {item["evidence_id"]: item for item in skill["evidence_contract"]}

    assert evidence["new_product_ranking"]["tool"] == "mcp__fastmoss__product_rank_new_listed"
    assert evidence["top_product_details"]["min_success"] == "param:head_listing_count"
    assert evidence["top_product_trends"]["min_success"] == "param:head_listing_count"
    assert evidence["compiled_new_product_report"]["tool"] == (
        "build_tiktok_new_product_report_data"
    )
    assert evidence["compiled_new_product_report"]["if_missing"] == "call_missing_tool"
    assert evidence["final_html_report"]["severity"] == "block"


def test_new_product_skill_report_contract_is_reader_first() -> None:
    markdown = load_agent_skill_registry()[SKILL_ID]["markdown"]

    assert "不要把数据完整性、P0 覆盖率或未完成任务放在顶部" in markdown
    assert "执行摘要 → 新品销量榜 → Top 新品逐品分析" in markdown
    assert "不生成数据缺口、执行审计" in markdown
    assert "不要调用 `build_market_report_data`" in markdown
    assert "renderer 只读取编译结果" in markdown
    assert "tiktok_new_product_report_data.v1" in markdown


def test_new_product_skill_is_exposed_in_frontend_picker() -> None:
    app_source = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    i18n_source = Path("frontend/src/lib/i18n.ts").read_text(encoding="utf-8")

    assert '| "tiktok_us_lingerie_new_product_insight"' in app_source
    assert 'id: "tiktok_us_lingerie_new_product_insight"' in app_source
    assert 'skillId: "tiktok_us_lingerie_new_product_insight"' not in app_source
    assert 'value === "tiktok_us_lingerie_new_product_insight"' in app_source
    assert "使用 tiktok_us_lingerie_new_product_insight Skill" in i18n_source
    assert '"agent.template.tiktokUsNewProducts.title"' in i18n_source
    assert "TK 美国女士文胸新品洞察" in i18n_source
    assert "category=女士文胸" in i18n_source
    assert "category_l3_id" in i18n_source
    assert "排除塑身衣等非文胸商品" in i18n_source
    assert "低于 20 USD 或高于 100 USD" in i18n_source
    assert "店铺名称和 shop_id" in i18n_source
    assert "不查询店铺榜" in i18n_source

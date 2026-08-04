from pathlib import Path

from insight_agent.server import load_agent_skill_registry

SKILL_ID = "tiktok_us_market_insight"


def test_tiktok_us_skill_keeps_project_section_order() -> None:
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
    assert skill["input_schema"]["required"] == ["brand", "category"]
    assert skill["input_schema"]["defaults"]["marketplace"] == "US"


def test_tiktok_us_skill_declares_fastmoss_core_tools() -> None:
    skill = load_agent_skill_registry()[SKILL_ID]
    policy = {item["tool"]: item for item in skill["tool_policy"]}

    required_tools = (
        "build_market_report_data",
        "render_html_report",
        "mcp__fastmoss__product_search",
        "mcp__fastmoss__search_category_by_words",
        "mcp__fastmoss__market_category_ranking",
        "mcp__fastmoss__market_category_analysis",
        "mcp__fastmoss__market_category_author_sales_matrix",
        "mcp__fastmoss__product_rank_top_selling",
        "mcp__fastmoss__product_overview",
        "mcp__fastmoss__product_sales_trend",
        "mcp__fastmoss__product_creator_analysis",
        "mcp__fastmoss__product_video_list",
        "mcp__fastmoss__shop_sale_analysis",
    )
    for tool in required_tools:
        assert policy[tool]["policy"] == "required"
    assert policy["mcp__fastmoss__product_rank_new_listed"]["policy"] == "allowed"

    evidence = {item["evidence_id"]: item for item in skill["evidence_contract"]}
    assert evidence["fastmoss_segment_search"]["tool"] == "mcp__fastmoss__product_search"
    assert evidence["fastmoss_segment_search"]["min_success"] == 3
    assert evidence["fastmoss_report_html"] == {
        "evidence_id": "fastmoss_report_html",
        "tool": "render_html_report",
        "required_when": "always",
        "min_success": 1,
        "severity": "block",
        "if_missing": "call_missing_tool",
        "artifact_requirement": (
            "最终 Artifact 必须发布 renderer 成功写出的 HTML 报告文件；"
            "不得跳过或使用固定模板 fallback"
        ),
    }


def test_tiktok_us_skill_uses_content_leading_indicators() -> None:
    skill = load_agent_skill_registry()[SKILL_ID]
    markdown = skill["markdown"]
    evidence = {item["evidence_id"]: item for item in skill["evidence_contract"]}

    assert "Market Outcome" in markdown
    assert "Content Momentum" in markdown
    assert "内容增量是领先信号，GMV 是滞后结果" in markdown
    assert "Market Outcome–Content Momentum 决策表" in markdown
    assert "| 上升 | 持平或下降 | `优先验证` |" in markdown
    assert "| 下降 | 下降 | `窗口关闭` |" in markdown
    assert evidence["fastmoss_product_videos"]["severity"] == "block"
    assert evidence["fastmoss_product_videos"]["min_success"] == "param:head_listing_count"
    assert evidence["fastmoss_market_report_data"]["tool"] == "build_market_report_data"
    assert evidence["fastmoss_market_report_data"]["if_missing"] == "call_missing_tool"


def test_tiktok_us_skill_defines_tasks_before_tool_mapping() -> None:
    markdown = load_agent_skill_registry()[SKILL_ID]["markdown"]

    assert "### 0. 先定义任务，再选择工具" in markdown
    assert "## Analysis Dimension Coverage" in markdown
    for index in range(1, 13):
        assert f"FM{index:02d} / P0" in markdown
    assert "任务到工具映射" in markdown
    assert "FM01 / P0 | 美国功能细分与查询边界" in markdown
    assert "FM02 / P0 | 细分商品样本覆盖与质量" in markdown
    assert "FM03 / P0 | 代理父类目解析与披露" in markdown
    assert "product_search" in markdown
    assert "关键词商品召回不是搜索量" in markdown
    assert "`html_render` 只读取编译数据、`insight_narrative`" in markdown
    assert "不直接读取原始 FastMoss tool results" in markdown


def test_tiktok_us_skill_separates_market_product_and_hsia_fit() -> None:
    markdown = load_agent_skill_registry()[SKILL_ID]["markdown"]

    assert "Entry Timing 只回答“市场窗口如何”，不回答“具体产品是否值得做”" in markdown
    assert "不得从类目增长或单品爆发推导 Hsia 适配度" in markdown
    assert "`brand=Hsia` 只是研究对象标签，不是适配证据" in markdown
    assert "只有存在 Hsia 内部事实或用户明确品牌证据时才展示 `Hsia Fit 门禁表`" in markdown


def test_tiktok_us_skill_fixes_market_scope_and_guards_search_claims() -> None:
    markdown = load_agent_skill_registry()[SKILL_ID]["markdown"]

    assert "所有市场级 FastMoss 调用必须显式使用 `region=US`" in markdown
    assert "任何 MX 或其他市场记录不得进入比较、汇总或结论" in markdown
    assert "北美" not in markdown
    assert "North America" not in markdown
    assert "FastMoss 不提供 Amazon 式 VoS 搜索量证据" in markdown
    assert "不得声称是唯一商品家族" in markdown
    assert "不得把视频播放量称为搜索需求" in markdown
    assert "最终正文不生成“数据完整性与未完成任务”" in markdown
    assert "最终 HTML 直接省略该结论和空模块" in markdown
    assert "`html_render` 成功后同时进入事实 `report_review` 与独立 `report_red_team`" in markdown
    assert "由 `approval_join` 等待并汇合" in markdown
    assert "第二轮仍未通过时再返工一次并直接进入 `synthesize_artifact`" in markdown
    assert (
        "Planner 不调用 builder、data_analysis、insight_synthesis、chart_render、renderer、"
        "review、red-team、approval_join、revision 或 "
        "`synthesize_artifact`"
    ) in markdown


def test_tiktok_us_skill_is_exposed_in_frontend_skill_picker() -> None:
    app_source = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    i18n_source = Path("frontend/src/lib/i18n.ts").read_text(encoding="utf-8")

    assert '| "tiktok_us_market_insight"' in app_source
    assert 'id: "tiktok_us_market_insight"' in app_source
    assert 'skillId: "tiktok_us_market_insight"' not in app_source
    assert 'value === "tiktok_us_market_insight"' in app_source
    assert "使用 tiktok_us_market_insight Skill" in i18n_source
    assert 'sources: ["FastMoss"]' in app_source
    assert '"agent.template.tiktokUs.title"' in i18n_source
    assert "TK 美国市场洞察" in i18n_source
    assert "marketplace=US" in i18n_source
    assert "tiktok_north_america_market_insight" not in app_source
    assert "tiktok_north_america_market_insight" not in i18n_source

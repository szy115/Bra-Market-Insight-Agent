from insight_agent.server import load_agent_skill_registry


def test_weekly_market_insight_skill_keeps_project_section_order() -> None:
    markdown = load_agent_skill_registry()["weekly_market_insight"]["markdown"]
    required_sections = (
        "## What It Does",
        "## When To Use",
        "## Required Inputs",
        "## Optional Defaults",
        "## Missing Params",
        "## Tool Policy",
        "## Recommended Tool Use",
        "## Analysis Dimension Coverage",
        "## Evidence Contract",
        "## Output Rules",
    )

    positions = [markdown.index(section) for section in required_sections]
    assert positions == sorted(positions)


def test_weekly_market_insight_skill_declares_vom_vos_decision_contract() -> None:
    skill = load_agent_skill_registry()["weekly_market_insight"]
    markdown = skill["markdown"]

    required_contract_text = (
        "VoM (Volume of Market)",
        "VoS (Volume of Search)",
        "## VoM–VoS Decision Logic",
        "同一 `marketplace`、同一目标用户任务和同一市场边界",
        "| 上升 | 持平或下降 | `优先验证` |",
        "| 下降 | 下降 | `暂缓进入` |",
        "证据 → 解释 → 替代解释 → 决策影响 → 验证动作",
    )
    for expected in required_contract_text:
        assert expected in markdown


def test_weekly_market_insight_skill_separates_market_timing_product_and_hsia_fit() -> None:
    skill = load_agent_skill_registry()["weekly_market_insight"]
    markdown = skill["markdown"]

    assert "Entry Timing 只回答“现在有没有窗口”，不回答“这个具体产品值得做”" in markdown
    assert "不得从市场吸引力推导 Hsia 适配度" in markdown
    assert "`brand=Hsia` 只是研究对象标签，不是适配证据" in markdown
    assert "报告必须固定包含一张 `VoM–VoS 决策表`" in markdown
    assert "只有存在 Hsia 内部事实或用户明确品牌证据时才展示 `Hsia Fit 门禁表`" in markdown


def test_weekly_market_insight_skill_requires_bra_attribute_share_chart() -> None:
    skill = load_agent_skill_registry()["weekly_market_insight"]
    markdown = skill["markdown"]
    evidence = {item["evidence_id"]: item for item in skill["evidence_contract"]}

    for attribute_axis in (
        "钢圈结构",
        "肩带形态",
        "穿脱/扣合方式",
        "罩杯衬垫结构",
        "罩杯覆盖度",
        "背部结构",
        "下围长度",
        "包装数量",
    ):
        assert attribute_axis in markdown
    assert 'data-chart-id="bra_attribute_distribution"' in markdown
    assert (
        "`bra_attribute_distribution` 不得进入 `summary_chart_ids` 或“市场任务图谱”"
        in markdown
    )
    assert "必须且只能在“文胸属性结构”章节出现一次" in markdown
    assert "不得用“标题没有写 strapless”推断“有肩带”" in markdown
    assert evidence["sellersprite_product_concentration"]["required_when"] == "param_present:category_node_id"
    assert evidence["sellersprite_product_concentration"]["severity"] == "block"


def test_weekly_market_insight_skill_keeps_vom_and_vos_evidence_blocking() -> None:
    skill = load_agent_skill_registry()["weekly_market_insight"]
    evidence = {item["evidence_id"]: item for item in skill["evidence_contract"]}

    assert evidence["sif_keyword_demand"]["severity"] == "block"
    assert evidence["sellersprite_market_base"]["severity"] == "block"
    assert evidence["sif_keyword_demand"]["if_missing"] == "continue_with_gap"
    assert evidence["sellersprite_market_base"]["if_missing"] == "continue_with_gap"
    assert "VoS" in evidence["sif_keyword_demand"]["artifact_requirement"]
    assert "VoM" in evidence["sellersprite_market_base"]["artifact_requirement"]
    assert "阻止依赖该证据的具体结论，而不是阻止整份报告" in skill["markdown"]
    assert "缺口只保留在 ReportData、工具 JSON 和审批输入中" in skill["markdown"]
    assert "最终 HTML 不生成“数据完整性与未完成任务”“数据缺口”" in skill["markdown"]
    assert "对应结论直接从可见正文省略" in skill["markdown"]


def test_weekly_market_insight_skill_maps_market_questions_and_scopes_product_identity() -> None:
    skill = load_agent_skill_registry()["weekly_market_insight"]
    markdown = skill["markdown"]
    policy = {item["tool"]: item for item in skill["tool_policy"]}
    evidence = {item["evidence_id"]: item for item in skill["evidence_contract"]}

    for dimension_id in ("M01", "M02", "M04", "M09", "M11", "M13", "M16", "M17", "M18", "M19"):
        assert f"| {dimension_id} /" in markdown
    assert policy["sellersprite_keyword_research"]["policy"] == "required"
    assert policy["sellersprite_keyword_research_trends"]["policy"] == "required"
    assert policy["sellersprite_google_trend"]["policy"] == "required"
    assert evidence["sellersprite_google_trend"]["required_when"] == "always"
    assert evidence["sellersprite_google_trend"]["severity"] == "block"
    assert evidence["sellersprite_google_trend"]["if_missing"] == "continue_with_gap"
    assert evidence["sellersprite_market_statistics"]["severity"] == "block"
    assert evidence["sellersprite_seller_concentration"]["severity"] == "block"
    assert evidence["sellersprite_rating_distribution"]["severity"] == "block"
    assert evidence["sellersprite_listing_trend_distribution"]["severity"] == "block"
    assert policy["sellersprite_market_product_concentration"]["policy"] == "conditional"
    assert "passthrough_v0" in markdown
    assert "market_product_identity.v1" in markdown
    assert "deduplication.applied=true" in markdown
    assert "scope=product_identity_only" in markdown
    assert "每份周报最多10个" in markdown
    assert "最多下载20张" in markdown
    assert "MCP tool description 不得作为证据引用" in markdown


def test_weekly_market_insight_skill_declares_two_round_approval_then_publish() -> None:
    skill = load_agent_skill_registry()["weekly_market_insight"]
    markdown = skill["markdown"]
    policy = {item["tool"]: item for item in skill["tool_policy"]}

    assert policy["render_html_report"]["policy"] == "required"
    assert (
        "html_render →（report_review 与 report_red_team 并行）→ approval_join → "
        "首轮任一分支未通过则 html_revision → 两分支再次并行 → approval_join → "
        "第二轮仍未通过则 html_revision 并直接发布"
    ) in markdown
    assert "所有 HTML Skill 共享通用链路" in markdown
    assert "data_analysis → insight_synthesis → chart_render → html_render" in markdown
    assert "不得继续发起第三轮审批" in markdown
    assert "不得因审批未通过而阻断发布" in markdown
    assert "审批记录保留在运行元数据中" in markdown

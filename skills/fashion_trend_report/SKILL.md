---
name: fashion_trend_report
description: Use when a design team needs a current fashion-trend inspiration report built from WGSN, 蝶讯, and Pinterest for a broad apparel category or product family.
version: 0.1
owner: Hsia R&D Insight Agent
---

# 流行趋势灵感报告

## What It Does

为服装与产品设计人员生成视觉优先的趋势灵感板。用 WGSN、蝶讯判断色彩、面料、廓形、细节和风格的宏观方向，再用 Pinterest 延展为可浏览、可讨论、可转译的视觉主题；报告不是市场审计或数据验证报告。

## When To Use

- 用户希望获得某个服装大类、产品家族或设计方向的近期流行趋势。
- 用户提到 WGSN、蝶讯、Pinterest、趋势预测、流行色、面料趋势、款式灵感或 moodboard。
- 设计团队需要为下一季企划、系列概念或款式开发寻找灵感。

## Required Inputs

| 字段 | 说明 |
| --- | --- |
| category | 研究的服装大类或产品家族，例如 women's intimates、女装、运动服；不要自动缩窄到 minimizer bra 等单一功能款 |

## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| marketplace | Global | 趋势观察市场；用户指定地区时以用户输入为准 |
| time_range | 30d | 新发布内容的优先检索窗口 |
| article_results_per_query | 10 | 每组短查询优先保留的候选结果数 |
| article_candidate_limit | 30 | 每个平台最多尝试读取的有效候选页面数 |
| report_image_limit | 36 | 报告最多展示的去重灵感图片数 |
| design_goal | 为设计团队提供下一季灵感与可转译方向 | 报告的设计用途 |

## Missing Params

如果无法从用户请求推断 `category`，先调用 `ask_user` 询问服装大类或产品家族，再执行数据工具。不要把品牌、细分功能款或目标用户设为默认必填项，也不要覆盖用户明确给出的时间范围和设计目标。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill 与参数合同 |
| ask_user | system | 仅在无法推断必填品类时询问用户 |
| respond_to_user | system | 回答解释、状态或非报告型问题 |
| trend_platforms | required | 实际访问 WGSN、蝶讯和 Pinterest，并收集页面、趋势线索与公开图片 |
| build_trend_report_data | required | 将检索结果整理为趋势主题、来源和视觉素材 |
| render_html_report | required | 生成面向设计师的自包含 HTML 灵感报告 |
| synthesize_artifact | system | LangGraph 最终节点；发布已渲染的最终报告，不由 Planner 调用 |

## Recommended Tool Use

1. 先确认 `category`，保持在服装大类或产品家族层级。除非用户明确指定，不要把研究自动缩窄到 minimizer bra 等单一功能款。
2. 调用 `trend_platforms`，分别访问三个目标平台，不要用一个平台的结果替代另一个平台：
   - WGSN：寻找当前及未来季节的 Big Ideas、Key Colours、Catwalk、材料、印花和轮廓方向。
   - 蝶讯：使用中文站内语汇寻找主题企划、色彩趋势、面料趋势、单品趋势和工艺细节。
   - Pinterest：先从 WGSN、蝶讯提取明确的趋势词，再组合品类、色彩、材质、廓形、细节和美学词做视觉延展；Pinterest 不承担宏观趋势判断。
3. 每个平台使用多组简短、站点原生的查询，不要把品类同义词、年份和所有维度塞进一条长查询。优先使用当前月份、年份和当前/未来季节表达，并去重重复 URL、转载页和相同图片。
4. `time_range=30d` 表示新发布内容优先窗口。先增加短查询组合以尽量多读窗口内有效页面；若某平台近期公开内容不足，可回退到与当前或未来适用季节直接相关的页面，并把它作为“季节灵感”而非“近 30 天新发布”使用。
5. 丢弃企业介绍、课程招生、工具功能、登录页、帮助页、空白聚合页和纯商品销售页。不要为了满足页面数或图片数用无关内容凑数。
6. 以趋势含义和视觉新鲜度排序候选。近期高相关页面优先，其次是当前/未来季节的高相关页面；旧但经典的参考只能少量作为背景，不能主导报告。
7. `trend_platforms` 完成或耗尽恢复策略后，Planner 停止发出工具调用。LangGraph 的 `report_data_builder` 节点调用 `build_trend_report_data`，把跨平台信号聚合成 4–6 个清晰趋势主题，并只为有明确数值语义的数据输出有界 `metric_facts`。每个主题应有概念名称、核心情绪、色彩、面料/肌理、廓形/细节、视觉参考和可执行设计提示。
8. LangGraph 随后进入 `data_analysis`；LLM 只能从本 Skill 的少量固定趋势指标中选择并绑定 `fact_id`，脚本校验后计算。没有可算的结构化指标是正常结果，不得把文本热度编造成增长率。
9. `insight_synthesis` 把有证据支持的平台信号和 `status=calculated` 的指标组织为“趋势观察 → 设计解释 → 产品影响 → 转译动作”，每条结论绑定真实 `evidence_ids`；不支持的趋势维度直接省略。
10. LangGraph 随后进入通用 `chart_render`；它只处理 builder 有明确数值语义的有界 `chart_specs`，固定调用本机 Flint MCP，单图失败时确定性降级，没有可画图表也是正常结果。随后 `html_render` 以 `insight_narrative` 为文字主轴生成视觉优先的设计灵感板，再同时进入事实 `report_review` 与独立 `report_red_team`，由 `approval_join` 汇合。任一分支首轮未通过时由 `html_revision` 返工并同时开始第二轮，第二轮仍未通过时再返工一次并直接进入 `synthesize_artifact`，不发起第三轮审批或红队。Planner 不调用 builder、data_analysis、insight_synthesis、chart_render、renderer、review、red-team、approval_join、revision 或 `synthesize_artifact`。图片按趋势主题编排，不设平台固定配额；在相关且不重复的前提下尽量使用 `report_image_limit`，不要用低价值图片填满额度。
11. `report_red_team` 不获得源数据工具，只依据当前 HTML、完整裁剪后的 ReviewReportData 与本 Skill 合同在当轮给出 approve/revise；证据不足时收窄、改写或移除当前结论，补数建议仅留给下一次任务，不触发本轮 Builder 或报告链重跑。

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| required_trend_platforms | trend_platforms | always | 1 | block | call_missing_tool | 必须实际访问 WGSN、蝶讯、Pinterest；某平台近期无公开内容时可使用相关的当前/未来季节页面，但不得用企业、课程、工具或登录页凑数 |
| structured_trend_report_data | build_trend_report_data | always | 1 | block | call_missing_tool | 最终报告必须先将页面与图片组织为设计趋势主题，不得直接堆叠搜索结果 |
| final_html_report | render_html_report | always | 1 | block | call_missing_tool | 最终产物必须是已成功渲染、可供设计团队浏览的 HTML 灵感报告 |

## Output Rules

- 把报告写成设计师灵感板，而不是审计报告。正文不得设置“证据边界”“验证矩阵”“覆盖率审计”或长篇方法论章节。
- 报告开头给出一页视觉总览，正文组织 4–6 个趋势故事；每个故事至少包含概念名、方向短句、色彩、面料/肌理、廓形或细节、2–4 条设计转译提示，并优先配置 6–10 张去重图片。高质量图片不足时少用，不以无关图片补足数量。
- 清楚区分“平台呈现的趋势方向”和“面向该品类的设计转译”。Pinterest 只作为视觉延展，不把单张 Pin 描述成宏观趋势证据。
- 来源信息保持轻量：在图片卡片或主题页脚标注平台、页面标题、链接以及可获得的发布日期或目标季节；不要让来源说明压过视觉内容。
- 优先使用最近 30 天的有效内容；使用季节回退时，用简短标签注明“当前/未来季节参考”，不要反复强调数据缺口。
- 只基于工具访问到的页面描述趋势，不得编造发布日期、平台观点、销量、搜索量、市场规模或人口画像。
- 色板、材质组合或款式建议可以作为设计转译提出，但必须使用“灵感色板”“建议尝试”等表达，不能伪装成平台原文结论。
- 公开数据仅作为方向性灵感。目标平台不可访问时省略依赖该平台的趋势结论，不生成缺口、覆盖率或验证说明，也不使用无关页面替代。

---
name: template_skill_id
description: One sentence explaining when the agent should use this Skill.
version: 0.1
owner: Hsia R&D Insight Agent
---

# Template Skill

## What It Does

Describe the business task this Skill completes and who uses the output.

## When To Use

- User intent example 1
- User intent example 2
- User wording example

## Required Inputs

| 字段 | 说明 |
| --- | --- |
| brand | 研究对象品牌 |
| marketplace | 电商市场 |
| category | 研究品类 |

## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| listing_sample_size | 30 | 商品样本数 |

## Missing Params

如果缺少必填参数，先向用户反问，不要直接执行后续工具步骤。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill |
| ask_user | system | 缺参时询问用户 |
| respond_to_user | system | 回答非任务型问题或解释当前状态 |
| synthesize_artifact | system | LangGraph 最终节点；生成并发布最终产物，不由 Planner 调用 |
| reddit_voc | allowed | 获取用户声音和场景语言 |
| amazon_shelf | allowed | 获取商品货架、价格、评分、评论量和品牌信号 |
| sif_market_get_keyword_demand | conditional | 用户要求搜索量、ABA 或关键词需求量化时补充 Sif MCP 证据 |

<!--
如果本 Skill 需要 HTML 报告，必须在上表增加并设为 required：
1. 与工作流匹配且已在运行时注册的 build_<workflow>_report_data
2. render_html_report
不得只声明 renderer，也不得为了过检查而复用业务/schema 不匹配的整理器。
-->

## Recommended Tool Use

- 先检查 Required Inputs 是否完整；如果缺少必填参数，调用 `ask_user` 反问，不要执行数据工具。
- 按任务需要调用数据工具，记录每个工具结果。
- 证据足够后停止发出工具调用，由 LangGraph 进入最终产物节点。

<!--
HTML 报告型 Skill 把最后一步改为：
Planner: data tools -> 停止发出工具调用；
LangGraph: build_<workflow>_report_data -> data_analysis -> insight_synthesis -> chart_render -> html_render ->（report_review 与 report_red_team 并行）-> approval_join -> 必要时 html_revision -> synthesize_artifact。
每份 HTML 最多并行审批两轮：每轮事实审批与红队同时执行并由 approval_join 汇合；任一分支首轮不通过时返工并并行复审，第二轮仍不通过时再返工一次并直接发布，不发起第三轮审批。
红队不获得源数据工具，只依据当前 HTML、完整裁剪后的 ReviewReportData 与 Skill 合同在当轮给出 approve/revise；证据不足时收窄、改写或移除当前结论，补数建议仅留给下一次任务，不触发本轮 Builder 或报告链重跑。
builder 必须输出有界的 metric_facts；data_analysis 中 LLM 只选择固定指标并绑定 fact_id，脚本负责校验分母、周期、样本完整性并计算。
insight_synthesis 只把有证据支持的一级/二级指标转成结构化文字结论，不限制章节数、洞察数或每章图表数；每张 ready 图表都生成且只生成一条统一的 chart_insight，必须说明具体观察和有限解释，只有确实影响业务决策时才补充业务影响与动作。
chart_render 只消费 builder 的有界 chart_specs，并固定调用本机 Flint MCP 生成经过校验的静态 SVG；单图失败时使用确定性服务端图表降级，不阻断整份报告。
renderer 只消费版本化、有限大小的整理结果、脚本计算的二级指标、已编译图表和展示指令，不直接读取原始 MCP/tool results；结论和观察在前，全宽图表居中，解释、业务影响和动作紧接在图表下方，禁止左右并排、先堆文字再堆图表或建立独立图表集。
Planner 不调用 builder、data_analysis、insight_synthesis、chart_render、renderer、review、red-team、revision 或 synthesize_artifact。整理器缺证据时只补缺失源数据工具并再次停止工具调用；renderer 失败时不得绕过整理器。
-->

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| primary_evidence | amazon_shelf | always | 1 | block | call_missing_tool | 缺少核心证据时不得生成最终结论 |
| user_voc | reddit_voc | prompt_mentions:用户,痛点,VOC,评论,Reddit | 1 | warn | continue_with_gap | 冻结依赖用户声音的结论，缺口仅保留在内部元数据 |
| sif_keyword_demand | sif_market_get_keyword_demand | prompt_mentions:Sif,ABA,搜索量,关键词需求 | 1 | warn | continue_with_gap | 冻结依赖关键词需求的结论，缺口仅保留在内部元数据 |

<!--
HTML 报告型 Skill 必须再加入两条 block + call_missing_tool 证据：
- compiled_report_data -> build_<workflow>_report_data
- final_html_report -> render_html_report
-->

## Output Rules

- 只基于工具证据输出结论。
- 不得编造销量、搜索量、人口画像或平台级市场规模。
- 公开数据只能作为方向性证据。
- 如果证据缺失或样本不足，必须在最终产物中明确标注。

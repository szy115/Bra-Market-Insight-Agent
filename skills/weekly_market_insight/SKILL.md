---
name: weekly_market_insight
description: Generate a weekly Hsia R&D market insight report for the requested US ecommerce category; use when the user asks what the market is doing, whether a category is worth entering, what changed recently, or what Hsia should research next.
version: 0.7
owner: Hsia R&D Insight Agent
---

# 市场洞察 Skill

## What It Does

生成面向 Hsia 商品企划、设计团队和研发负责人的每周市场洞察报告。

这个 Skill 只使用 Sif MCP 和 SellerSprite MCP 建立市场级、关键词级、类目级结构化底盘。第一版周报不再调用 Reddit、TikTok、Amazon shelf 或媒体文章工具，避免把样本型抓取结果和市场级数据混在一起。

最终报告不能直接从原始 tool results 生成。必须先调用 `build_market_report_data` 把本轮工具结果编译成稳定的 MarketReportData JSON；该步骤同时生成业务 `chart_specs`。随后调用 `render_html_report`，只把 MarketReportData 和本 Skill 的样式要求交给 LLM，最后调用 `synthesize_artifact` 发布产物。不得把原始工具结果与 MarketReportData 重复传入 renderer。

## When To Use

- 用户想知道美国某个电商品类或关键词市场最近在变什么，例如 sports bra、full coverage bra 或 large bust bra。
- 用户要求市场洞察快报、品类分析、趋势机会、研发机会、是否值得进入。
- 用户要求输出复杂 HTML 市场洞察报告、周报、经营分析或企划会材料。
- 用户问 Hsia 下一步应该研究什么、做什么价格带、关注哪些卖点和结构。

## Required Inputs

| 字段 | 说明 |
| --- | --- |
| brand | 研究对象品牌，默认应围绕 Hsia / 遐 |
| marketplace | 电商市场，通常是 Amazon US / 美国站 |
| category | 研究品类或关键词，例如 sports bra |

## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| time_range | 90d | 最近市场变化观察窗口 |
| listing_sample_size | 100 | SellerSprite 样本数量目标 |
| head_listing_count | 10 | 头部商品数量 |
| new_product_window | 180d | 新品定义 |
| category_node_id |  | SellerSprite 节点级工具需要的 nodeIdPath；缺省时先自动解析，不要求用户手动提供 |

## Missing Params

如果缺少 `brand`、`marketplace` 或 `category`，先调用 `ask_user` 反问，不要执行数据工具。

不要因为缺少 `category_node_id` 直接询问用户。先调用 `sellersprite_product_node` 自动查找并校验 `nodeIdPath`；只有连续两次使用更精确的类目名称仍无法得到唯一高置信节点，并且 ASIN 类目也无法交叉验证时，才调用 `ask_user` 让用户从候选类目路径中选择。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill |
| ask_user | system | 缺参时询问用户 |
| respond_to_user | system | 回答非任务型问题或解释当前状态 |
| build_market_report_data | required | 将本轮工具结果编译为稳定 MarketReportData JSON，作为最终报告唯一结构化输入 |
| render_html_report | required | 用 LLM 将 MarketReportData 内的 chart_specs 和当前 Skill 要求写成最终 HTML 报告 |
| synthesize_artifact | system | 发布已渲染的最终市场洞察产物 |
| sif_market_get_keyword_demand | required | 建立关键词需求生命周期、搜索量趋势和行动时机判断 |
| sif_market_get_keyword_history | required | 获取 ABA 搜索量、排名和 Top3 集中度历史数字 |
| sif_market_get_keyword_root_trend | required | 判断精确词与长尾词根需求边界 |
| sif_market_get_keyword_competition | required | 获取关键词竞争格局、Top ASIN 和流量份额 |
| sellersprite_market_research | required | 用 SellerSprite 类目/关键词市场数据验证市场规模、竞争强度、利润空间和新品机会 |
| sellersprite_aba_research_weekly | required | 获取 Amazon 站内热门/增长/潜力关键词机会 |
| sellersprite_product_node | conditional | 缺少 category_node_id 时按类目名称自动查找并校验 SellerSprite nodeIdPath |
| sellersprite_asin_detail | conditional | product_node 候选不唯一或名称不匹配时，用已知 Top ASIN 的 nodeIdPath 交叉验证类目 |
| sellersprite_market_product_demand_trend | conditional | 有 category_node_id 时获取节点级需求趋势、退货率、搜索购买比和商品总数 |
| sellersprite_market_product_concentration | conditional | 有 category_node_id 时获取头部 Listing 集中度与 Top 商品 |
| sellersprite_market_brand_concentration | conditional | 有 category_node_id 时获取品牌集中度 |
| sellersprite_market_price_distribution | conditional | 有 category_node_id 时获取价格区间分布与销量占比 |
| sellersprite_market_ratings_count_distribution | conditional | 有 category_node_id 时获取评分数门槛与新品进入难度 |
| sellersprite_market_listing_date_distribution | conditional | 有 category_node_id 时获取新品/老品上架时间结构 |

## Recommended Tool Use

1. 先检查 Required Inputs。缺少 `brand`、`marketplace` 或 `category` 时，调用 `ask_user`。
2. 必须调用 Sif 和 SellerSprite MCP 工具，不要调用 Reddit、TikTok、Amazon shelf 或 Media 工具。
3. Sif 第一组工具用于回答：需求是否增长、搜索量/ABA 是否健康、长尾市场边界、关键词竞争格局、Top ASIN 流量份额。
4. 如果没有 `category_node_id`，必须先调用 `sellersprite_product_node` 自动解析，再调用 `sellersprite_market_research`。先用用户原始 `category`，校验候选 `nodeLabelPath` 的末级名称是否与目标品类一致；不得直接采用第一个结果。名称不匹配时，用更短的 Amazon 正式末级类目名称重试，例如把 `minimizer bra` 改为 `Minimizers`。连续两次仍有歧义时，使用 Sif 返回的 Top ASIN 调用 `sellersprite_asin_detail`，用 ASIN 的 `nodeIdPath` 与候选路径交叉验证。只有仍无法唯一确定时才调用 `ask_user`，并展示候选完整路径。
5. SellerSprite 第一组工具用于回答：市场规模、竞争强度、利润/价格空间、新品机会、ABA 热门/增长/潜力关键词。`sellersprite_market_research` 如果对用户原始短语返回 `total=0/items=[]`，适配器会保留站点、月份、已解析节点和分页参数，只去掉 `bra/bras`、性别词、介词等通用修饰词，用剩余的辨识性核心词自动回退一次，例如 `minimizer bra -> minimizer`。不得继续扩大成 `bra` 等通用大类；回退过程必须记录在 `data.query_resolution`。
6. 一旦 `sellersprite_product_node` 返回唯一高置信节点，运行时会自动把 `nodeIdPath` 写入 `category_node_id`。随后必须调用并成功取得 SellerSprite 六个节点级结果：需求趋势、商品集中度、品牌集中度、价格分布、评分数分布、上架时间分布。`sellersprite_market_research` 原词和受控回退词均为空，或任一节点级工具返回 `empty`、`error`、`timeout`、需要用户处理时，先修正参数或重试，不要进入 HTML renderer。
7. 所有 block 级证据成功后才能调用 `build_market_report_data`。这个工具会按具体来源工具编译统一结构：market_kpis、keyword_trends、demand_trend、category_benchmark、top_products、brand_competition、price_distribution、ratings_count_distribution、listing_date_distribution、analysis_sections、opportunity_pool、evidence_map、data_gaps 和 chart_specs。不得把 ASIN 价格冒充价格带、把份额数值冒充品牌名或把不同关键词排名画成时间折线。
8. MarketReportData 成功后直接调用 `render_html_report`。renderer 只能接收 MarketReportData、证据缺口和本 Skill 的 `HTML Report Style Reference`，不得再次传入原始 Sif/SellerSprite tool results。图表只能表达市场、关键词、价格、品牌、商品和机会判断，不展示工具链执行过程。
9. HTML 报告成功后调用 `synthesize_artifact` 发布最终产物。最终报告必须区分“可量化市场信号”“分析判断”“需要补数的缺口”。

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| sif_keyword_demand | sif_market_get_keyword_demand | always | 1 | block | call_missing_tool | 缺少 Sif 需求生命周期证据时，不得判断市场需求增长、下滑或行动时机 |
| sif_keyword_history | sif_market_get_keyword_history | always | 1 | block | call_missing_tool | 缺少 Sif 历史搜索/ABA 数据时，不得判断近期关键词趋势 |
| sif_root_trend | sif_market_get_keyword_root_trend | always | 1 | block | call_missing_tool | 缺少 Sif 词根趋势时，不得判断长尾市场边界或需求集中度 |
| sif_keyword_competition | sif_market_get_keyword_competition | always | 1 | block | call_missing_tool | 缺少 Sif 关键词竞争证据时，不得判断 Top ASIN 流量份额或进入难度 |
| sellersprite_market_base | sellersprite_market_research | always | 1 | block | call_missing_tool | 缺少 SellerSprite 市场研究证据时，不得声称完成类目市场规模、竞争强度或新品机会验证 |
| sellersprite_aba_weekly | sellersprite_aba_research_weekly | always | 1 | block | call_missing_tool | 缺少 SellerSprite ABA 周度关键词证据时不得生成市场洞察报告 |
| sellersprite_node_demand | sellersprite_market_product_demand_trend | param_present:category_node_id | 1 | block | call_missing_tool | 节点级需求趋势、退货率或搜索购买比缺失时不得生成报告 |
| sellersprite_product_concentration | sellersprite_market_product_concentration | param_present:category_node_id | 1 | block | call_missing_tool | 商品集中度缺失时不得生成报告 |
| sellersprite_brand_concentration | sellersprite_market_brand_concentration | param_present:category_node_id | 1 | block | call_missing_tool | 品牌集中度缺失时不得生成报告 |
| sellersprite_price_distribution | sellersprite_market_price_distribution | param_present:category_node_id | 1 | block | call_missing_tool | 价格区间及销量占比缺失时不得生成报告 |
| sellersprite_ratings_distribution | sellersprite_market_ratings_count_distribution | param_present:category_node_id | 1 | block | call_missing_tool | 评分数门槛分布缺失时不得生成报告 |
| sellersprite_listing_date_distribution | sellersprite_market_listing_date_distribution | param_present:category_node_id | 1 | block | call_missing_tool | 上架时间与新品接受度分布缺失时不得生成报告 |
| market_report_data | build_market_report_data | always | 1 | block | call_missing_tool | 最终报告前必须先生成 MarketReportData，不能直接从原始工具结果生成 HTML |
| market_report_html | render_html_report | always | 1 | block | call_missing_tool | 最终产物必须来自 LLM 基于 MarketReportData 和 chart_specs 写出的 HTML 报告 |

## Output Rules

- 最终产物必须是市场洞察快报，不是原始数据罗列。
- 报告首屏必须回答：当前是否值得进入企划验证、核心需求入口是什么、竞争锚点是谁、价格锚点是什么、下一步优先推进什么。
- 报告结构优先采用：答案先行、关键市场信号、执行摘要、核心 KPI、市场容量与基本盘、关键词趋势、价格带与利润结构、竞争结构、Top ASIN/品牌、关键发现与 So What、Hsia 研发机会、风险和下一步验证动作。
- HTML 版式要服务阅读：首屏只放 verdict、4 个关键信号和一个优先行动；长表格和原始结构化证据放到后半段。
- 最终 HTML 必须由 LLM 直接组织文案、结构和样式，不要再通过中间 blueprint 或固定章节模板二次渲染；LLM 失败时不要产出 HTML 报告。
- 任一 Evidence Contract `block` 级工具没有成功数据时，停止在 HTML renderer 之前，不生成或发布报告。
- 最终报告不得展示工具调用成功率、调用了几个工具、原始 JSON、evidence_map 表格或 source_summary 调试信息；这些只属于左侧执行时间线。
- 每个重要结论必须能追溯到 Sif 或 SellerSprite 的工具证据。
- Sif 和 SellerSprite 支撑市场级/关键词级/类目级判断。
- 不得编造销量、搜索量、市场规模、人口画像或平台级数据。可以引用 Sif/SellerSprite 返回的量化字段，但必须保留来源。
- 如果 Evidence Contract 有 warn 级缺口，最终报告必须在“数据缺口/风险”中标注。
- 如果自动节点解析失败，报告必须写明尝试过的查询词和候选路径；不得笼统要求用户自行补充 `category_node_id`。
- 输出 Hsia 机会时必须包含：机会名称、证据、建议价格带/尺码/颜色或结构方向、风险、下一步验证动作。

### HTML Report Style Reference

参考 LinkFox 市场报告风格，但只复用版式和写法，不复用示例中的真实数值、类目排名、ASIN、品牌判断或图表数据。

视觉与结构要求：

- 使用白底、轻边框、紫蓝主色、青/绿/橙/红作为图表或风险语义色；不要把所有内容做成厚重卡片。
- 不生成右侧目录、侧边栏、TOC 或锚点导航；页面采用单栏主内容布局，桌面端和移动端都以正文阅读为主。
- 顶部使用渐变报告头：报告标题、报告副标题、生成周期/数据源说明。
- KPI 采用横向轻量指标条，不使用大面积 KPI 卡片。每个 KPI 显示：指标名、数值、变化或来源。
- 正文用 `.content-section` 式分段，每段必须有一个明确问题：执行摘要、核心指标全景、子类目/关键词对标、关键发现与 So What、行动建议。
- 每个重要段落末尾显示数据源脚注：工具名、时间窗口、口径限制。
- 图表必须使用静态内联 SVG 实现，不依赖外部 CDN；不得使用 JavaScript、Canvas、ECharts、Chart.js 或其他运行时绘图库。前端报告预览会禁用脚本，因此所有柱、线、点、扇区、坐标轴和标签节点必须直接存在于最终 HTML 中，禁止输出空 `<svg>` 再用脚本填充。

图表渲染要求：

- 只渲染 `market_report_data.chart_specs` 中 `quality_status=ready` 的图表，完整报告选择 3-5 张最有决策价值的图；不得从其他表格自行拼出新图。每张图必须用 `<figure class="chart-card" data-chart-id="{chart_id}">` 包裹，`data-chart-id` 必须与规格完全一致。
- `line` 只允许真实日期/月度序列且至少 4 个连续点；不同关键词或不同品牌的排名不得画折线。`donut` 只允许 3-7 个互斥份额项且总和约等于 100%；不满足时改用横向柱状图。长标签、Top 商品和关键词一律优先横向柱状图。
- 所有图使用统一组件：白底、1px `#E5E7EB` 边框、6px 圆角、无阴影、无 3D、无渐变填充、无动画。主色按 `#4F46E5`、`#0891B2`、`#16A34A`、`#D97706`、`#DC2626` 循环，不使用随机色。
- 图表宽度为容器 100%；桌面端绘图区高 300-360px，横向条形图按每行 34-40px 自适应但最高 380px；移动端高 260-320px。使用 SVG 时必须设置响应式 `viewBox` 和 `preserveAspectRatio`，文字不得超出绘图区。
- 每张图固定包含：标题、最多一行副标题、单位、清晰轴/基线、必要的数据标签、1-2 句商业判断、`source` 数据源脚注。每个必需图表的 `<figure>` 内必须包含已填充的 `<svg>` 和至少一个可见的 `path`、`rect`、`circle`、`line`、`polyline` 或 `polygon` 图形节点。数字统一格式化：千/百万缩写、百分比 1 位小数、货币带 `$`；同一张图禁止混用销量、销售额、评论数和份额。
- 横向柱状图最多 8 项并按数值排序，标签列宽稳定；折线图只标首点、末点、最高点和最低点；环形图标签放右侧图例，不把文字塞进扇区。重复标签、空标签、单点、全零或单位不明的规格不渲染。
- 输出前做图表 QA：确认无标签重叠、无截断数值、无重复图例、无错误单位、无空白画布，并确认每张图能直接回答一个业务问题。数据不足时用简短缺口提示替代图表，不编造数据凑数量。

表格渲染要求：

- 数据足够时至少生成“核心指标对标表”和“Top ASIN/品牌/关键词明细表”，不得只输出 KPI 卡片和文字摘要。
- 核心指标表至少包含：指标、当前值、对标值、差异、商业解释、证据来源。Top 明细表只选择证据中实际存在的名称、ASIN/关键词、指标值、排名或份额、来源字段。
- 使用完整的 `<table>`、`<thead>`、`<tbody>` 和真实数据行，不用省略号代替内容；表头清晰，数值右对齐，移动端用横向滚动容器。
- 表格和图表只能使用 MarketReportData、chart_specs 和工具证据；字段缺失时显示 `—` 或数据缺口，不推算未提供的指标。

内容骨架必须接近：

```html
<header class="report-header">
  <h1>{marketplace} {category} 市场洞察报告</h1>
  <p class="report-subtitle">{one_sentence_verdict}</p>
  <p class="report-meta">数据周期：{time_range} · 数据来源：Sif / SellerSprite</p>
</header>

<section class="kpi-grid">
  <article class="kpi-card"><span>{kpi_label}</span><strong>{metric}</strong><em>{source_or_change}</em></article>
</section>

<section class="content-section">
  <h2>执行摘要</h2>
  <div class="summary-box">
    <p>{answer_first_verdict}</p>
  </div>
  <ul class="insight-list">
    <li class="priority-high"><strong>So What：</strong>{business_implication}</li>
  </ul>
  <div class="data-source">数据源：{tool_name} · {time_range} · {limitation}</div>
</section>

<section class="content-section">
  <h2>关键发现与 So What 商业建议</h2>
  <div class="swot-grid">
    <article class="swot-card strengths">...</article>
    <article class="swot-card weaknesses">...</article>
    <article class="swot-card opportunities">...</article>
    <article class="swot-card threats">...</article>
  </div>
  <ul class="insight-list">
    <li class="priority-high"><strong>紧急行动：</strong>{next_action}</li>
    <li class="priority-medium"><strong>差异化定位：</strong>{positioning}</li>
  </ul>
</section>
```

分析写法要求：

- 每个 `h3` 小节先给判断，再给证据，最后给 `So What`；不要先堆表格。
- 对标分析必须说明“为什么这个对标对象重要”，例如体量、价格、利润、退货率、品牌数、评论门槛或流量份额中的一个或多个。
- 行动建议必须分优先级：`priority-high`、`priority-medium`、`priority-low`。
- 可以出现 SWOT，但 SWOT 中每条都必须来自工具证据或明确标注为待验证假设。

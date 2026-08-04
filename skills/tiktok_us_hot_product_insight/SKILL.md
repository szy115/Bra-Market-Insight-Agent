---
name: tiktok_us_hot_product_insight
description: Identify and diagnose TikTok Shop US category hot products with FastMoss, using creator/video momentum as the leading signal, GMV and units as outcomes, channel attribution as the breakout mechanism, and product reviews as required evidence for user likes, complaints, use cases, and product opportunities.
version: 0.1
owner: Hsia R&D Insight Agent
---

# TikTok Shop 美国爆款洞察 Skill

## What It Does

面向商品企划、研发和 TikTok Shop 运营团队，筛选指定类目的头部热销商品，并判断它们处于增长期、爆发期还是稳定期。分析必须把内容动量放在成交结果之前：达人和视频增量是领先信号，GMV 与销量是滞后结果；再用广告/自然、达人/店铺自营、短视频/直播/商品卡结构解释爆发机制。

评论分析是主链路，不是可选附录。对每个深挖商品提取正向喜欢点、负向痛点、使用场景、预期落差和研发机会，并把评论证据与商品表现、内容动量和渠道结构关联起来。最终产物回答：谁是真正仍在增长的爆款、为什么爆、用户为什么买、买后哪里不满、哪些机会值得验证。

## When To Use

- 用户要找 TikTok Shop 美国某类目的爆款、潜力款或值得跟进的商品。
- 用户要求分析爆款生命周期、起量机制、达人/视频动量或广告与自然流量结构。
- 用户要求对 TikTok 商品做评论分析、好差评归因、VOC、痛点或研发机会分析。
- 用户输入类似“分析美国站运动文胸 Top 5 爆款，包含评论痛点和跟进建议”。
- 用户输入类似“这个类目哪些商品还在涨，怎么爆的，用户买后吐槽什么”。

## Required Inputs

| 字段 | 说明 |
| --- | --- |
| category | TikTok Shop 商品类目或明确细分关键词 |

## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| brand | Hsia | 报告使用方；不自动构成品牌适配证据 |
| marketplace | US | 固定为 TikTok Shop 美国市场 |
| time_range | 28d | 当前表现与内容动量观察窗口 |
| listing_sample_size | 20 | 类目爆款候选池大小 |
| head_listing_count | 5 | 深挖并完成评论分析的商品数 |
| review_sample_size | 30 | 每个商品的评论目标样本数；由 FastMoss 可得评论量约束 |
| category_node_id |  | FastMoss 标准类目 ID；缺省时自动解析 |

## Missing Params

缺少 `category` 时，先调用 `ask_user` 询问具体类目或细分关键词，不要执行数据工具。所有 FastMoss 调用必须使用 `region=US`；用户要求其他市场时，先询问是否切换到相应市场工作流。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill |
| ask_user | system | 缺参或市场冲突时询问用户 |
| respond_to_user | system | 回答非任务型问题或解释当前状态 |
| build_market_report_data | required | 将 FastMoss 商品、内容、渠道和评论证据编译为版本化、有界的 FastMossMarketReportData |
| render_html_report | required | 只使用编译数据、确定性分析、洞察结果和图表生成最终 HTML |
| synthesize_artifact | system | LangGraph 终端节点；发布最终产物，不由 Planner 调用 |
| mcp__fastmoss__search_category_by_words | required | 把用户类目解析为标准 category_id 与类目路径 |
| mcp__fastmoss__product_rank_top_selling | required | 获取同一完整周期、同一标准类目的爆款候选池 |
| mcp__fastmoss__product_overview | required | 获取单品成交、广告/自然、渠道和内容结构 |
| mcp__fastmoss__product_sales_trend | required | 判断当前成交结果及周期变化 |
| mcp__fastmoss__product_creator_analysis | required | 获取达人参与和增量信号 |
| mcp__fastmoss__product_video_list | required | 获取视频供给、发布时间、广告标记和内容表现 |
| mcp__fastmoss__product_review_list | required | 获取每个深挖商品的评论样本，支持喜欢点、痛点和场景分析 |
| mcp__fastmoss__fastmoss_detail_url_examples | required | 生成可追溯的 FastMoss 商品详情链接 |
| mcp__fastmoss__product_investment | conditional | 用户要求广告花费、投流或 ROAS 时补充；无花费时不得计算 ROAS |
| mcp__fastmoss__shop_sale_analysis | conditional | 需要解释代表店铺的联盟、自营、直播、短视频或商品卡结构时使用 |
| mcp__fastmoss__product_detail_info | conditional | 排名行缺少标题、图片、店铺、评分或评论量时补充 |
| mcp__fastmoss__product_search | conditional | 标准类目过宽、用户给出功能词或需要补充同义词商品池时使用 |

## Recommended Tool Use

1. 检查 `category`。缺失时调用 `ask_user`；参数完整后固定 `region=US`，默认使用最近 28 天。
2. 调用 `mcp__fastmoss__search_category_by_words`。优先选择叶子名称与用户目标一致的最深标准类目；多个候选都合理时，用用户原词和商品化同义词重试，不直接采用第一条。
3. 使用已解析的同一 `category_id` 调用 `mcp__fastmoss__product_rank_top_selling`，只使用已完成周期。按 `product_id` 去重，保留至少 `listing_sample_size` 个候选，并记录排序字段、周期、页码和类目路径。若用户输入的是功能细分词，可用 `product_search` 补充召回，但不得把关键词召回写成搜索量或完整市场规模。
4. 从候选池选择前 `head_listing_count` 个不同商品，逐个调用 `product_overview`、`product_sales_trend`、`product_creator_analysis`、`product_video_list` 和 `product_review_list`。所有单品工具必须对齐同一市场、同一 product_id 和可比较周期；不得用类目累计值替代单品当前表现。
5. 评论调用以 `review_sample_size` 为目标上限。保留返回的评论 ID、评分、日期、文本、SKU/变体和媒体字段；按评论 ID 或规范化文本去重。某商品评论为空时只表示评论数据未取回，继续执行其他商品，但冻结该商品及跨商品的 VOC 结论。
6. 对每个商品分别整理评论：
   - 正向喜欢点：被明确称赞的功能、版型、材质、舒适、外观、价格或场景。
   - 负向痛点：尺码/版型、支撑、舒适、材质/做工、耐穿/清洗、外观、包装/履约、价格感知和预期落差。
   - 场景与人群语言：只复述评论中明确出现的使用场景，不推断人口画像。
   - 证据强度：按“提及该主题的不同评论数 / 有效评论样本数”计算样本内提及率；不得把词频、点赞量或总评论量当作主题人数。
   - 证据锚点：每个主题保留 product_id、review_id、评分、日期和短摘录。只有一条评论支持时标为单点信号，不泛化为共性问题。
7. 先判断 Content Momentum，再判断 Market Outcome：
   - 达人/视频增量连续上升且销售趋势同步上升，支持增长期或仍热的爆发期。
   - GMV 很高但达人/视频增量停滞或下降，优先判断窗口后段或稳定期。
   - 内容上升而销售持平/下降，只能判为优先验证；替代解释包括转化弱、内容同质化或统计滞后。
   - 没有当前与前一等长窗口时，不输出确定生命周期。
8. 用 `product_overview` 的广告分布、渠道分布和内容分布解释“怎么爆”：区分广告与自然、达人与店铺自营、短视频与直播与商品卡。视频列表中的少量广告标记不能替代完整渠道归因。
9. 把评论主题与商业表现交叉：高频喜欢点只能说明当前样本中被验证的购买后价值；高频痛点要结合商品规模、内容动量和竞品重复性判断机会。研发建议必须给出评论证据、受影响商品、具体动作和验证实验，不能从高 GMV 直接推导产品机会。
10. 完成、失败或耗尽所有源数据恢复策略后，Planner 停止发出工具调用。LangGraph 自动执行 `build_market_report_data -> data_analysis -> insight_synthesis -> chart_render -> html_render ->（report_review 与 report_red_team 并行）-> approval_join -> 必要时 html_revision -> synthesize_artifact`。Builder 输出有界 `metric_facts` 与 `chart_specs`；`data_analysis` 只选择已注册指标并绑定事实，由确定性代码校验和计算；`insight_synthesis` 只输出证据支持的观察与有限解释，每张 ready 图表恰好一条 `chart_insight`；`chart_render` 固定调用本机 Flint MCP，单图失败时确定性降级。
11. Planner 不调用 builder、`data_analysis`、`insight_synthesis`、`chart_render`、renderer、`report_review`、`report_red_team`、`approval_join`、`html_revision` 或 `synthesize_artifact`，也不把原始 FastMoss 结果直接交给 renderer。
12. 每份 HTML 最多两轮并行审批。每轮同时运行事实 `report_review` 与独立、无源数据工具的 `report_red_team`，由 `approval_join` 汇合；任一分支首轮拒绝时执行 `html_revision` 并重跑两分支，第二轮仍拒绝时再执行一次最终 `html_revision` 后直接发布，不启动第三轮。
13. `report_red_team` 只依据当前 HTML、完整裁剪后的 ReviewReportData 和本 Skill 合同挑战生命周期、爆发机制、评论共性和研发机会。缺少比较时收窄、改写或删除当前主张；未来补数动作只进入内部元数据，不触发本轮源数据、Builder 或报告链重跑。

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| fastmoss_category_resolution | mcp__fastmoss__search_category_by_words | always | 1 | block | continue_with_gap | 未解析标准类目时冻结类目爆款排名，仅保留已有单品证据 |
| fastmoss_hot_product_pool | mcp__fastmoss__product_rank_top_selling | always | 1 | block | continue_with_gap | 缺少同类目同周期候选池时不得声称已识别类目爆款 |
| fastmoss_product_overview | mcp__fastmoss__product_overview | always | param:head_listing_count | block | continue_with_gap | 未完成商品不得输出爆发渠道、广告/自然结构或完整机会 |
| fastmoss_product_trend | mcp__fastmoss__product_sales_trend | always | param:head_listing_count | block | continue_with_gap | 未完成商品不得输出当前销售方向或生命周期 |
| fastmoss_creator_momentum | mcp__fastmoss__product_creator_analysis | always | param:head_listing_count | block | continue_with_gap | 未完成商品不得判断达人增量或内容领先信号 |
| fastmoss_video_momentum | mcp__fastmoss__product_video_list | always | param:head_listing_count | block | continue_with_gap | 缺少可比视频窗口时不得输出确定生命周期 |
| fastmoss_product_reviews | mcp__fastmoss__product_review_list | always | param:head_listing_count | block | continue_with_gap | 未完成商品不得输出已验证喜欢点、痛点、场景或评论驱动机会；跨商品共性只基于评论成功商品 |
| fastmoss_detail_links | mcp__fastmoss__fastmoss_detail_url_examples | always | 1 | warn | continue_with_gap | 缺少模板时省略不可验证的详情链接，不伪造 URL |
| fastmoss_ads | mcp__fastmoss__product_investment | prompt_mentions:广告,投流,花费,ROAS,VSA,LSA,PSA | 1 | warn | continue_with_gap | 缺少花费与归因时不得计算 ROAS 或输出确定投放建议 |
| hot_product_report_data | build_market_report_data | always | 1 | block | call_missing_tool | 最终 HTML 前必须把 FastMoss 源证据编译为 FastMossMarketReportData，禁止原始结果直送 renderer |
| final_html_report | render_html_report | always | 1 | block | call_missing_tool | 最终 Artifact 必须发布 renderer 成功写出的 HTML 文件 |

## Output Rules

- 最终产物必须是爆款洞察报告，不是排行榜或评论摘抄堆砌。
- 首屏必须回答：仍在增长的爆款、窗口后段的爆款、主要爆发机制、用户最强喜欢点、最大痛点和首要验证动作。
- 主表至少包含：商品与 FastMoss 链接、价格、周期 GMV/销量、销售变化、达人/视频动量、广告/自然结构、主要渠道、生命周期、评论样本数、首要喜欢点、首要痛点和置信度。
- 每个深挖商品必须有独立评论卡，展示有效样本数、评分/日期范围、正向主题、负向主题、场景、单点信号和证据摘录。摘录保持短句，不编造原话。
- 跨商品 VOC 只统计不同评论数和评论成功商品数；同一评论重复出现、同一文本变体或词频不得重复计数。
- 生命周期必须优先使用达人和视频增量；最高累计 GMV 不自动等于仍值得跟进。
- 评论样本是方向性证据，不代表全部买家。总评论量、点赞量和样本内提及率保持不同口径。
- 商品、店铺、视频和达人链接优先使用返回的 `fastmoss_url`，缺失时使用 FastMoss URL 模板；不生成 TikTok 假链接。
- 只有渠道分布证据支持时才判断广告、自营、联盟、短视频、直播或商品卡驱动；没有广告花费时不计算 ROAS。
- 每个研发机会必须包含：机会名称、评论痛点/喜欢点、涉及商品与评论证据、商业表现关联、具体研发或内容动作、验证实验和否决条件。
- `block + continue_with_gap` 只冻结依赖结论。缺口保留在内部元数据；最终 HTML 省略无证据结论和空模块，不生成数据完整性或未完成任务章节。
- 最终 HTML 只消费版本化、有界的 Builder 数据、确定性二级指标、已验证洞察和图表，不接收原始 FastMoss tool results。
- 只基于工具证据与用户明确提供的品牌事实输出结论；不编造 GMV、销量、搜索量、市场规模、人口画像、评论、成本、利润、退货率或合作成本。

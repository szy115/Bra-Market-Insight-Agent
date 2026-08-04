---
name: tiktok_us_market_insight
description: Analyze TikTok Shop US categories with FastMoss MCP evidence to judge market structure, content momentum, entry timing, product feasibility, and Hsia fit; use for US TK market insight, category entry, product scouting, and weekly opportunity reports.
version: 0.5
owner: Hsia R&D Insight Agent
---

# TikTok Shop 美国市场洞察 Skill

## What It Does

生成面向 Hsia 商品企划、设计、研发和 TikTok Shop 运营团队的美国市场洞察报告。报告以 FastMoss MCP 为唯一 TikTok Shop 市场数据源，先用 `product_search` 把 minimizer bra 等功能词构造成关键词商品样本，再用标准父类目提供背景，最后基于同一批细分商品判断 Market Outcome、Content Momentum、Entry Timing、产品可进入性和 Hsia Fit。

本 Skill 固定使用“双边界”：

- `功能细分边界`：由多个 `product_search(keywords=...)` 结果合并而成，代表 FastMoss 关键词可识别商品样本。
- `代理父类目边界`：由 `search_category_by_words` 解析的标准类目，只提供规模、趋势、价格和生态背景。

代理父类目的 GMV、销量、价格或集中度不得改写成功能细分的市场规模。关键词商品召回不是搜索量、关键词需求或完整市场普查。

本 Skill 固定区分四个结论层，禁止从单一爆款、单一高 GMV 或单一达人直接跳到“值得做”或“Hsia 应入场”：

- `Market Outcome`：市场已兑现结果，使用 FastMoss 返回的 GMV、销量、增长趋势、价格带和集中度衡量。
- `Content Momentum`：内容供给动量，优先使用同口径周期内新增带货视频、达人参与变化及其成交贡献衡量。TikTok Shop 是内容驱动市场，内容增量是领先信号，GMV 是滞后结果。
- `Entry Timing`：在同一市场、类目和可比周期内联合判断 Market Outcome 与 Content Momentum，输出窗口打开、优先验证、窗口收窄、窗口关闭或不可判断。
- `Hsia Fit`：Hsia 对机会的用户、产品能力、价格经济性、供应链和 TikTok 渠道能力适配度。`brand=Hsia` 只是研究对象标签，不是适配证据。

本 Skill 只分析 TikTok Shop US。所有市场级 FastMoss 调用必须显式使用 `region=US`，所有金额使用 FastMoss 返回的 USD 口径；不得混入 MX 或其他市场的数据。

## When To Use

- 用户要求 TikTok Shop、TK 或 TikTok 电商的美国市场洞察、周报或品类分析。
- 用户想了解某个 TikTok Shop 类目的规模、增长、价格带、商品/店铺集中度或达人结构。
- 用户想寻找新品、增长品、爆发品、蓝海类目，或判断跟卖和入场窗口。
- 用户要求解释一个类目或商品为何增长，区分广告、自然短视频、直播、商品卡、达人联盟或店铺自营驱动。
- 用户需要把 FastMoss 数据转成 Hsia 商品企划、产品验证、内容策略或达人策略建议。

## Required Inputs

| 字段 | 说明 |
| --- | --- |
| brand | 研究对象品牌，通常为 Hsia / 遐 |
| category | 研究品类或消费者任务，例如 minimizer bra、sports bra |

## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| marketplace | US | 固定分析 TikTok Shop 美国市场，FastMoss region 使用 US |
| time_range | 28d | 商品详情、趋势和内容动量的默认观察窗口 |
| listing_sample_size | 20 | 合并热销榜、增长榜和新品榜后的商品候选池目标数 |
| head_listing_count | 5 | 进入商品详情、趋势、达人和视频深挖的去重商品数 |
| new_product_window | 30d | FastMoss 新品定义；不得改写为 Amazon 常见的 90/180 天 |
| review_sample_size | 50 | 用户明确要求 VOC、评论或研发痛点时的每商品评论目标数 |
| category_node_id |  | FastMoss TikTok 商品 category_id；缺省时自动解析 |

## Missing Params

如果缺少 `brand` 或 `category`，先调用 `ask_user` 反问，不要执行数据工具。`marketplace` 缺省时直接使用 `US`，不要追问。用户明确指定非美国市场时，说明本 Skill 仅支持 TikTok Shop US，并请用户切换到相应市场工作流；不得继续执行本 Skill 的数据工具。

不要因为缺少 `category_node_id` 直接询问用户。先为原始 `category` 生成至少一个同义词和一个商品化表达，并用 `mcp__fastmoss__product_search` 在 `region=US` 下召回商品；同时调用 `mcp__fastmoss__search_category_by_words` 解析最接近的标准父类目。只有父类目存在多个同等可信候选且会实质改变背景分析时，才调用 `ask_user`。

缺少 Hsia 内部成本、目标售价、供应链、尺码能力、达人资源或内容产能时，不阻断市场分析，但必须把对应 Hsia Fit 项标为 `证据不足`。如果用户要求二元的 Hsia 入场结论，再询问缺少的品牌事实；不得以常识替代。

如果 FastMoss MCP 缺失、未认证或不可达，停止实时分析并说明需要安装或重新连接 FastMoss MCP。`product_search` 空结果表示“关键词数据未取回”，不是“市场没有商品或销量为零”；依次扩展同义词、移除 category_path 过滤、调整排序并翻页重试。仍为空时只生成代理父类目背景报告，冻结细分市场规模、Entry Timing 和产品机会结论。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill |
| ask_user | system | 缺少必填参数或类目路径歧义时询问用户 |
| respond_to_user | system | 回答非任务型问题或解释当前状态 |
| build_market_report_data | required | 按 FM01–FM12 编译任务覆盖、任务证据、图表规格和数据缺口；renderer 不直接读取原始 FastMoss tool results |
| render_html_report | required | 将 FastMoss 的有证据市场结论和洞察文字组织为最终 HTML 报告文件 |
| synthesize_artifact | system | LangGraph 最终节点；发布市场洞察产物，不由 Planner 调用 |
| mcp__fastmoss__product_search | required | 用多个关键词在美国市场召回功能细分商品，建立规模、销量和新品样本池 |
| mcp__fastmoss__search_category_by_words | required | 将自然语言品类解析为代理父类目；父类目只提供背景 |
| mcp__fastmoss__market_category_ranking | required | 获取类目规模、增长和商品/店铺集中度的横向排名 |
| mcp__fastmoss__market_category_analysis | required | 获取类目基础指标、连续销售趋势和价格带结构 |
| mcp__fastmoss__market_category_author_sales_matrix | required | 获取不同粉丝层级达人的数量、GMV 和销售贡献结构 |
| mcp__fastmoss__product_rank_top_selling | required | 获取代理父类目的头部商品背景；不得混入功能细分商品池 |
| mcp__fastmoss__product_rank_new_listed | allowed | 需要补充代理父类目的新品背景时调用；细分新品池优先使用 product_search |
| mcp__fastmoss__product_overview | required | 获取头部商品的 GMV、渠道、广告/自然和内容结构 |
| mcp__fastmoss__product_sales_trend | required | 获取头部商品的 GMV 与销量趋势，验证内容信号是否兑现 |
| mcp__fastmoss__product_creator_analysis | required | 获取头部商品的带货达人结构、集中度和贡献 |
| mcp__fastmoss__product_video_list | required | 获取头部商品近期带货视频、播放、成交及广告标记 |
| mcp__fastmoss__shop_rank_top_selling | required | 获取类目头部店铺及销售结构，判断店铺集中风险 |
| mcp__fastmoss__creator_rank_top_ecommerce | required | 获取类目头部带货达人，补充内容生态和达人依赖判断 |
| mcp__fastmoss__fastmoss_detail_url_examples | required | 生成商品、达人、店铺和视频的 FastMoss 站内详情链接 |
| mcp__fastmoss__product_detail_info | allowed | 榜单字段不足时补充价格、店铺、评分、物流和广告状态 |
| mcp__fastmoss__product_sku | conditional | 用户要求 SKU、颜色、尺码、库存或变体结构时调用 |
| mcp__fastmoss__product_investment | conditional | 用户要求广告、投流、花费或 ROAS，或商品明显广告驱动时调用 |
| mcp__fastmoss__product_review_list | conditional | 用户要求评论、VOC、痛点或研发机会时调用 |
| mcp__fastmoss__shop_sale_analysis | required | 获取代表店铺的短视频、直播、商品卡、联盟或自营渠道结构 |
| mcp__fastmoss__creator_profile_overview | conditional | 需要评估代表达人合作价值时调用 |
| mcp__fastmoss__creator_fans_distribution | conditional | 用户要求达人受众与目标用户匹配度时调用 |
| mcp__fastmoss__video_script_info | conditional | 用户要求爆款脚本、钩子或拍摄 brief 时调用 |
| mcp__fastmoss__search_fastmoss_documents | allowed | 查询 FastMoss 指标、规则和功能说明；文档说明不得替代市场数据证据 |

## Recommended Tool Use

### 0. 先定义任务，再选择工具

本 Skill 以 `FM01–FM12` 市场任务为主线，不以工具数量为主线。开始调用 FastMoss 前先确定本轮必须完成的任务；每次工具调用必须服务于一个任务及其完成条件。工具返回成功不等于任务完成：关键词查询数、去重商品数、region、代理 category_id、完整周期、深挖商品对齐或可比窗口不符合要求时，该任务仍为 `missing_data`。

执行顺序固定为：

1. 执行 `FM01–FM02`：先用多个 `product_search` 查询建立美国功能细分样本，不依赖独立 category_id。
2. 执行 `FM03–FM06`：解析代理父类目，并把规模、趋势、价格、竞争和达人生态明确标为背景。
3. 执行 `FM07`：在相同关键词边界内建立 GMV、销量和新品三个细分商品池。
4. 从 FM07 的去重 product_id 中选出相同的 `head_listing_count` 个对象，执行 `FM08–FM10`；不同工具不得更换样本。
5. 只有 FM01、FM02、FM08、FM09 完成时才派生 `FM11 Entry Timing`；FM12 还需要 FM07–FM10 和 Hsia 内部事实。
6. 源数据工具完成后，Planner 停止发出工具调用。LangGraph 调用 `build_market_report_data` 编译任务覆盖；renderer 只读取编译后的 FastMossMarketReportData，不直接读取原始 MCP 结果。

### 1. 建立功能细分边界

1. 检查 Required Inputs 和 FastMoss MCP 可用性，将 `marketplace` 固定映射为 `region=US`。
2. 从用户原始 `category` 生成查询组：原词、至少一个同义词、至少一个商品化表达。例如 minimizer bra 可扩展为 minimizing bra、full coverage minimizer bra；不得把普通 full coverage bra 自动视为 minimizer。
3. 对至少两个不同 `keywords` 调用 `mcp__fastmoss__product_search`。第一轮不得附加 category_path，以免错误父类目过滤导致假空；分别保留 query、region、orderby、page 和 pagesize。
4. 若结果为空，先换同义词，再移除类目过滤、改用 `day28_gmv`/`day28_units_sold` 排序并翻页。仍为空时记录“数据未取回”，不得推导市场为零。
5. 合并所有结果并按 `product_id` 去重，保留每个商品命中的查询词和证据来源。该集合称为“FastMoss 关键词可识别细分样本”，不称完整市场。

### 2. 建立代理父类目背景

仅对 TikTok Shop US 执行，并始终标记为代理父类目背景：

1. 调用 `mcp__fastmoss__search_category_by_words` 解析最接近的标准类目路径和 category_id。功能词不存在独立类目时，明确写“代理父类目”，不反复用功能词请求不存在的 category_id。
2. 调用 `mcp__fastmoss__market_category_ranking`，取得代理父类目的相对位置。
3. 调用 `mcp__fastmoss__market_category_analysis` 三次，分别使用 `basic_metrics`、`sales_trends` 和 `price_distribution`。
4. 调用 `mcp__fastmoss__market_category_author_sales_matrix`、`shop_rank_top_selling`、`product_rank_top_selling` 和 `creator_rank_top_ecommerce`，建立代理父类目竞争与内容生态背景。
5. 榜单只使用完整周期：日榜为美国目标时区昨天，周榜为上一完整自然周，月榜为上一完整自然月。任何父类目指标不得改写成关键词细分规模。

### 3. 建立细分商品候选池

1. 对功能细分查询组调用 `mcp__fastmoss__product_search`，分别按 `day28_gmv` 和 `day28_units_sold` 降序建立“规模池”和“销量池”。
2. 在相同关键词与 `region=US` 下设置 `filter.is_new_listed=true` 建立“新品池”。新品使用 FastMoss 定义，不用代理父类目的全类目新品榜替代。
3. 合并三个池并按 `product_id` 去重，目标为 `listing_sample_size`；保留 matched_queries、排序入口和新品入口。没有 parent/variation 证据时，只能称“去重商品记录”。
4. 从三个池保留代表商品，并按相关性与证据完整度选出 `head_listing_count` 个深挖对象。代理父类目榜单商品不得自动进入细分深挖池。

### 4. 深挖头部商品和内容动量

只对 FM07 细分商品池选出的同一组 product_id 调用：

1. `mcp__fastmoss__product_overview`：读取 `period_summary`、`ads_distribution`、`channel_distribution` 和 `content_distribution`。
2. `mcp__fastmoss__product_sales_trend`：读取同口径 GMV、销量和日趋势，验证内容动量是否已转化为销售结果。
3. `mcp__fastmoss__product_creator_analysis`：读取达人层级、达人类目和头部贡献。若结果只有累计快照，不得声称达人数量正在增长。
4. `mcp__fastmoss__product_video_list`：分别统计当前与前一可比窗口的新发布带货视频；区分广告视频和自然视频。若无法取得前一窗口，Content Momentum 标为 `不可判断`，不得用当前视频总数代替增量。
5. 只有用户询问广告，或 `ads_distribution` 显示商品明显依赖广告时，调用 `mcp__fastmoss__product_investment` 校验广告 GMV、花费和 ROAS。缺少 spend 时不得自行计算 ROAS。

### 5. 执行可比性门禁

只有同时满足以下条件，才允许比较 Market Outcome 与 Content Momentum：

- 同一 `marketplace=US`、同一关键词细分边界和同一组 product_id；代理父类目数据只作为单独背景；
- 使用相同或明确对齐的完整周期，并标注采集日期和目标市场时区；
- GMV、销量、视频数、达人数和份额保留各自定义，不直接相加或制造综合指数；
- 内容增量来自当前与前一等长窗口，不用累计视频数或累计达人数伪装增长；
- 广告、自然、联盟、自营、短视频、直播和商品卡是不同口径，不互相替代；
- 所有输入和返回 region 均为 US；任何 MX 或其他市场记录不得进入比较、汇总或结论。

任一条件不满足时，不输出 Entry Timing 结论，也不渲染缺失证据或补数动作；相关状态只保留在内部任务结果。

### 6. 判断类目状态与入场时机

先分别判断 Market Outcome 与 Content Momentum 的当前水平和变化方向，再使用下表：

| Content Momentum | Market Outcome | Entry Timing | 默认解释与限制 |
| --- | --- | --- | --- |
| 上升 | 上升 | `窗口打开` | 内容供给和成交同步扩张；仍需检查集中度、广告依赖、利润和 Hsia Fit |
| 上升 | 持平或下降 | `优先验证` | 内容可能领先 GMV，也可能是低转化、无效铺量或统计滞后；先验证转化与渠道质量 |
| 持平或下降 | 上升 | `窗口收窄` | 可能由广告、直播大场、商品卡或历史内容继续兑现；不得把高 GMV 当作持续增长 |
| 下降 | 下降 | `窗口关闭` | 内容和成交共同转弱；除非存在明确反周期策略，否则暂缓进入 |
| 不可比或冲突 | 任意 | `不可判断` | 补齐同市场、同类目和等长周期数据后再判断 |

绝对规模不能被方向矩阵覆盖。低基数的同步增长最多支持“小规模增长/继续验证”；高位同步回落应判断为“窗口后段”，不能因为绝对 GMV 大就判定值得跟进。

### 7. 判断单品生命周期和产品可进入性

单品生命周期使用互斥的四阶段，并优先采用内容领先指标：

| 阶段 | FastMoss 证据要求 | 产品判断 |
| --- | --- | --- |
| 新品期 | 上架不超过 30 天、累计 GMV 较小、达人和视频刚开始出现 | 尚未验证；只能进入小规模测试 |
| 增长期 | 新增视频/达人参与明显上升、连续周期销售增长、排名上升 | 窗口较好；继续检查竞争和渠道质量 |
| 爆发期 | 类目头部 GMV、排名稳定、内容仍增加但增速开始放缓 | 窗口收窄；必须做价格、产品或内容差异化 |
| 稳定期 | 累计 GMV 很大，但内容增量停滞/下降、增长降至低位、排名难提升 | 跟卖窗口基本关闭；不要因历史 GMV 大而追高 |

没有当前/前一周期内容证据时，不得输出确定生命周期。Entry Timing 只回答“市场窗口如何”，不回答“具体产品是否值得做”。产品还必须通过：市场边界、竞争集中度、价格经济性、内容可复制性、履约/退货风险和可验证差异六项门禁。

产品结论只使用：`不建议做`、`观察`、`进入验证`、`有条件可做`。缺少成本、利润、履约或退货证据时，不使用无条件的“值得做”。

### 8. 单独判断 Hsia Fit

不得从类目增长或单品爆发推导 Hsia 适配度。逐项检查：

| Hsia Fit 维度 | 所需证据 |
| --- | --- |
| 用户与品牌相邻性 | Hsia 目标用户和场景是否与目标类目、达人受众及内容表达重合 |
| 产品能力相邻性 | Hsia 已有版型、支撑结构、材料和研发能力是否可迁移 |
| 价格与经济性 | 市场价格、佣金、广告、物流、退货和目标毛利是否可同时成立 |
| 尺码与供应链 | 尺码深度、SKU 数、MOQ、备货、交期和质量控制是否可承受 |
| TikTok 渠道 right-to-win | 是否具备达人获取、样品履约、持续内容产能、广告测试和本地履约能力 |

Hsia 事实只能来自用户明确提供的品牌 brief、可追溯自有数据或已注册工具。仅有 FastMoss 市场与竞品数据时，省略 Hsia Fit 结论，不列出待确认事实。

### 9. 强制结论链

每个重要判断按以下顺序写：

1. `证据`：指标、数值、周期、过滤条件和 FastMoss 工具来源；
2. `解释`：该证据在当前市场和类目边界内意味着什么；
3. `替代解释`：至少一个可能造成相同表现的其他原因；
4. `决策影响`：该证据最多支持到哪一级结论；
5. `验证动作`：需要补充的数据、实验或否决阈值。

示例：`新增自然带货视频上升，但 GMV 持平`只能解释为“内容可能领先成交”，替代解释包括视频转化低或内容同质化，只能输出“优先验证”，下一步检查视频成交效率、广告占比和随后一周 GMV，不得直接声称存在蓝海。

### 10. 渲染并发布报告

1. 所有源数据工具完成、失败或耗尽恢复策略后，Planner 停止发出工具调用。LangGraph 的 `report_data_builder` 节点调用 `build_market_report_data`；它必须生成 `fastmoss_task_results`、`analysis_coverage`、`dimension_results`、`chart_manifest`、`chart_specs`、`report_quality`、`period_contract`、有界 `metric_facts` 和数据缺口。
2. `FM01–FM02` 发现关键词查询不足、非 US 或细分商品为空时，编译器必须冻结细分结论；FM03–FM06 的代理父类目背景仍可降级发布，但不得冒充细分市场。
3. 编译成功后先进入 `data_analysis`：LLM 只能从固定二级指标目录中选择 `metric_id` 并绑定 `fact_id`，脚本校验分母、范围、周期和样本完整性后计算。
4. `insight_synthesis` 随后把有界一级指标和 `status=calculated` 二级指标转成结构化“观察 → 解释 → 业务影响 → 动作”文字结论；每条结论必须绑定真实 `evidence_ids`。不支持的维度和 `metric_gaps` 仅保留在内部元数据，不能出现在报告正文。
5. `chart_render` 只读取 FastMossMarketReportData 的有界 `chart_specs`，固定调用本机 Flint MCP并缓存静态 SVG；单图失败时确定性降级。`html_render` 只读取编译数据、`insight_narrative`、已校验二级指标与已编译图表，不直接读取原始 FastMoss tool results，并必须把每条重要结论展开为数据观察、解释和业务含义。
6. `block + continue_with_gap` 仅冻结依赖该证据的结论；最终 HTML 直接省略该结论和空模块，不披露逐项缺口。
7. `html_render` 成功后同时进入事实 `report_review` 与独立 `report_red_team`，由 `approval_join` 等待并汇合。任一分支首轮未通过时由 `html_revision` 返工并同时开始第二轮；第二轮仍未通过时再返工一次并直接进入 `synthesize_artifact`。Planner 不调用 builder、data_analysis、insight_synthesis、chart_render、renderer、review、red-team、approval_join、revision 或 `synthesize_artifact`。
8. `report_red_team` 不获得源数据工具，只依据当前 HTML、完整裁剪后的 ReviewReportData 与本 Skill 合同在当轮给出 approve/revise；证据不足时收窄、改写或移除当前结论，补数建议仅留给下一次任务，不触发本轮 Builder 或报告链重跑。

## Analysis Dimension Coverage

完整报告按任务而不是工具数量判断完成度。每个任务都必须保留：市场问题、工具映射、完成条件、允许结论和限制。P0 未全部完成时报告状态为 `degraded`，仅冻结依赖缺失任务的结论。

| ID | 市场任务 | 任务到工具映射 | 完成条件 | 允许结论与限制 |
| --- | --- | --- | --- | --- |
| FM01 / P0 | 美国功能细分与查询边界 | `product_search` 使用原词、同义词和商品化表达 | 至少两个不同 keywords 成功执行；全部证据为 US 或无 region 的静态说明 | 只定义 FastMoss 关键词可识别细分，不把关键词商品搜索写成需求量 |
| FM02 / P0 | 细分商品样本覆盖与质量 | 多次 `product_search` 结果合并 | 去重 product_id 至少达到 `listing_sample_size`；记录 query、排序、页码、原始数和去重数 | 样本不足时降级；空结果是未取回数据，不是市场为零 |
| FM03 / P0 | 代理父类目解析与披露 | `search_category_by_words` | 标准类目路径和 category_id 已解析，并显式标为 proxy/background | 父类目不得代表功能细分市场规模、份额或竞争结构 |
| FM04 / P0 | 代理父类目规模与趋势 | `market_category_ranking` + `market_category_analysis(basic_metrics,sales_trends)` | 同代理 category_id、同完整周期成功；趋势至少两个可比点 | 只描述父类目背景，不把方向归因到功能细分 |
| FM05 / P0 | 代理父类目价格与竞争背景 | `market_category_analysis(price_distribution)` + `shop_rank_top_selling` + `product_rank_top_selling` | 价格带、头部店铺和头部商品均成功 | 与细分商品样本分栏展示；不得互相替代 |
| FM06 / P0 | 代理父类目达人生态 | `market_category_author_sales_matrix` + `creator_rank_top_ecommerce` | 达人层级矩阵和具体达人榜均成功 | 只作为父类目内容生态背景；粉丝量不代表带货能力 |
| FM07 / P0 | 细分规模、销量与新品商品池 | `product_search` 按 day28_gmv、day28_units_sold 排序，并使用 is_new_listed | 三种入口均成功；按 product_id 合并；至少达到深挖目标 | 不提供关键词增长率或需求量；无 parent/variation 不称唯一商品家族 |
| FM08 / P0 | 细分商品 Market Outcome | FM07 商品逐个调用 `product_sales_trend` | 同一组 `head_listing_count` product_id 全部完成 | 逐商品判断成交结果；不得从父类目趋势替代 |
| FM09 / P0 | 细分商品 Content Momentum | 同一商品调用 `product_creator_analysis` + `product_video_list` | 与 FM08 对齐的 product_id 全部完成；视频保留广告标记和发布时间 | 无前一等长窗口不得声称内容增长或确定生命周期 |
| FM10 / P0 | 细分渠道与广告归因 | 同一商品调用 `product_overview`；代表店铺调用 `shop_sale_analysis` | FM08–FM10 对齐同一组商品，且至少一个店铺渠道分析成功 | 只按 distribution 字段判断渠道；视频 is_ad 样本不能替代完整归因 |
| FM11 / P0 | Entry Timing | 派生自 FM01、FM02、FM08、FM09 | 功能边界、样本、Market Outcome 和 Content Momentum 全部可比 | 输出窗口打开/优先验证/收窄/关闭；否则不可判断 |
| FM12 / P0 | 产品可进入性与 Hsia Fit | 派生自 FM07–FM10 + 用户/内部 Hsia 事实 | 四个细分商品任务完成；成本、退货、供应链、尺码和内容产能有可追溯事实 | 产品结论与 Hsia Fit 分开；内部事实缺失时 Hsia Fit 为证据不足 |

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| fastmoss_segment_search | mcp__fastmoss__product_search | always | 3 | block | continue_with_gap | 缺少关键词 GMV、销量或新品入口时，冻结功能细分商品池、Entry Timing 和产品机会；空结果不得写成市场为零 |
| fastmoss_category_resolution | mcp__fastmoss__search_category_by_words | always | 1 | block | continue_with_gap | 类目未解析时冻结代理父类目背景，但已取得的关键词细分商品证据仍可降级展示 |
| fastmoss_category_ranking | mcp__fastmoss__market_category_ranking | always | 1 | block | continue_with_gap | 缺少同周期排名时，不得判断代理父类目相对位置；报告标为 degraded |
| fastmoss_category_analysis | mcp__fastmoss__market_category_analysis | always | 3 | block | continue_with_gap | 缺少基础指标、趋势或价格带任一结果时，冻结对应类目结论，缺失信息只保留在内部元数据 |
| fastmoss_creator_matrix | mcp__fastmoss__market_category_author_sales_matrix | always | 1 | block | continue_with_gap | 缺少达人层级销售结构时，不得判断类目的达人生态或达人依赖 |
| fastmoss_top_products | mcp__fastmoss__product_rank_top_selling | always | 1 | block | continue_with_gap | 缺少代理父类目头部商品时，冻结父类目竞争背景；不得用它替代关键词细分商品池 |
| fastmoss_product_overview | mcp__fastmoss__product_overview | always | param:head_listing_count | block | continue_with_gap | 未完成的商品不得判断渠道归因、广告/自然结构或完整产品机会 |
| fastmoss_product_trend | mcp__fastmoss__product_sales_trend | always | param:head_listing_count | block | continue_with_gap | 未完成的商品不得判断销售趋势、生命周期或内容信号是否兑现 |
| fastmoss_product_creators | mcp__fastmoss__product_creator_analysis | always | param:head_listing_count | block | continue_with_gap | 未完成的商品不得判断达人结构、达人集中度或合作依赖 |
| fastmoss_product_videos | mcp__fastmoss__product_video_list | always | param:head_listing_count | block | continue_with_gap | 缺少可比视频窗口时 Content Momentum 与生命周期必须标为不可判断 |
| fastmoss_shop_channels | mcp__fastmoss__shop_sale_analysis | always | 1 | block | continue_with_gap | 缺少代表店铺渠道结构时，不得判断联盟、自营、短视频、直播或商品卡归因 |
| fastmoss_top_shops | mcp__fastmoss__shop_rank_top_selling | always | 1 | warn | continue_with_gap | 缺少店铺证据时冻结店铺竞争与集中度结论，不得用商品集中度替代 |
| fastmoss_top_creators | mcp__fastmoss__creator_rank_top_ecommerce | always | 1 | warn | continue_with_gap | 缺少头部达人样本时冻结具体达人结论，不得用粉丝层级矩阵替代 |
| fastmoss_detail_links | mcp__fastmoss__fastmoss_detail_url_examples | always | 1 | warn | continue_with_gap | 无 URL 模板时仍可输出降级报告，但必须标注无法生成 FastMoss 详情链接 |
| fastmoss_product_ads | mcp__fastmoss__product_investment | prompt_mentions:广告,投流,ROAS,花费,VSA,LSA,PSA | 1 | warn | continue_with_gap | 缺少广告花费或归因数据时不得计算 ROAS 或给出确定投放结论 |
| fastmoss_product_voc | mcp__fastmoss__product_review_list | prompt_mentions:评论,好评,差评,痛点,VOC,研发 | param:head_listing_count | warn | continue_with_gap | 缺少评论证据时只能输出结构假设，不得声称已验证用户痛点或产品解法 |
| fastmoss_market_report_data | build_market_report_data | always | 1 | block | call_missing_tool | 最终报告前必须按 FM01–FM12 编译 FastMossMarketReportData；不得从原始 tool results 直接生成 HTML |
| fastmoss_report_html | render_html_report | always | 1 | block | call_missing_tool | 最终 Artifact 必须发布 renderer 成功写出的 HTML 报告文件；不得跳过或使用固定模板 fallback |

## Output Rules

- 最终产物必须是市场洞察报告，不是 FastMoss 原始字段或排行榜堆砌。
- 最终报告只能以 `build_market_report_data` 输出的 FastMossMarketReportData 为结构化输入；不得把原始 FastMoss tool results 直接塞给 renderer。
- FM01–FM12 任务覆盖率只保留在运行元数据和审批输入中。最终 HTML 仅披露实际使用数据的市场、类目/代理边界、周期、过滤条件与样本范围，不显示 `missing_data` 任务表。
- 报告首屏必须分开显示：`类目状态`、`Entry Timing`、`产品适合度`、`Hsia Fit`、`最终 verdict`。每项显示置信度、首要证据和首要阻断项。
- 最终 verdict 只使用：`适合入场`、`有条件入场`、`进入验证`、`观察`、`暂缓/不进入`。禁止用加权总分掩盖关键失败。
- 报告结构优先采用：功能细分查询边界、关键词样本覆盖、代理父类目背景、细分商品池、Market Outcome、Content Momentum、渠道归因、Entry Timing、单品生命周期、产品门禁、Hsia Fit、风险与下一步验证。
- 每次展示榜单或数据都标注：`数据源：FastMoss`、市场、category_id/类目路径、过滤条件、排序字段、完整周期和采集日期。
- 只展示 TikTok Shop US 数据。不得混入、求和或引用 MX 及其他市场数据，也不得把跨市场数据写成美国市场规模。
- FastMoss 不提供 Amazon 式 VoS 搜索量证据；不得编造搜索量、搜索趋势、人口画像或平台级 TAM，也不得把视频播放量称为搜索需求。
- `product_search` 是商品关键词召回，不是关键词搜索量工具。报告必须分别披露关键词细分样本和代理父类目背景；不得把父类目 GMV、销量、价格带或集中度标成 minimizer bra 等功能细分指标。
- GMV、销量、广告归因、播放和达人贡献均按 FastMoss 返回口径引用，并标注为第三方估算/方向性证据，不写成平台财务真值。
- 每个产品、达人、店铺和视频必须链接到 FastMoss 详情页。优先使用返回的 `fastmoss_url`；缺失时使用 `mcp__fastmoss__fastmoss_detail_url_examples` 的模板。不要链接到 TikTok 详情页。
- 商品主表至少包含：商品、FastMoss 链接、价格、周期 GMV/销量、销售变化、当前/前期视频增量、广告/自然占比、主要渠道、达人集中度、生命周期、置信度和限制。字段缺失显示 `—`，不得推算。
- 固定包含一张 `Market Outcome–Content Momentum 决策表`，列为：市场/商品、Market Outcome、Content Momentum、渠道归因、主解释、替代解释、Entry Timing、置信度、证据来源。
- 只有存在 Hsia 内部事实或用户明确品牌证据时才展示 `Hsia Fit 门禁表`；没有证据的维度省略，不得显示缺口或自动判为通过。
- 规模商品、销量商品和新品必须按 `product_id` 去重。没有 parent/variation 证据时只能声称“去重商品记录数”，不得声称是唯一商品家族。
- 最高累计 GMV 不等于最佳机会；当前视频/达人增量停滞时，应优先解释为窗口后段或稳定期风险。
- 达人粉丝数不等于带货能力。评价达人或达人层级时优先使用近期 GMV、视频成交、平均每条视频 GMV和履约相关证据；字段缺失时明确限制。
- 广告驱动爆发不等于自然内容验证。只有 `ads_distribution`、`product_investment` 或视频广告标记支持时，才可判断广告依赖。
- 每个机会建议必须包含：市场证据、内容证据、渠道结构、主解释、替代解释、产品门禁、Hsia Fit、风险、否决条件和下一步实验。
- Evidence Contract 中 `block + continue_with_gap` 只冻结依赖该证据的结论，不阻止整份报告。ReportData 和运行元数据保留缺口供审批与调试，最终正文不生成“数据完整性与未完成任务”、数据缺口或不可判断清单。
- `product_search` 先用同义词扩展、无 category_path、替代排序和翻页恢复。重试仍为空时只表示关键词商品数据未取回；报告可保留代理父类目背景，但不得推导“没有商品、销量、达人、视频或市场活动”。
- FastMoss 返回余额不足或 402 时，说明 FastMoss credits 不足并提供返回的充值链接；充值前停止依赖该工具的实时结论。
- 只基于工具证据和用户明确提供的品牌事实输出结论。不得编造销量、GMV、搜索量、市场规模、人口画像、成本、利润、退货率或达人合作成本。
- 使用简洁表格和业务语言，不使用 emoji。每个重要结论按“证据 → 解释 → 替代解释 → 决策影响 → 验证动作”组织。

---
name: weekly_market_insight
description: Analyze a US ecommerce category with an explicit VoM-versus-VoS decision chain, mandatory bra-attribute share analysis, product feasibility gates, and separate Hsia right-to-win evidence; use for weekly market insight, category entry, product feasibility, assortment structure, and Hsia R&D opportunity decisions.
version: 1.5
owner: Hsia R&D Insight Agent
---

# 市场洞察 Skill

## What It Does

生成面向 Hsia 商品企划、设计团队和研发负责人的每周市场洞察报告。报告先比较市场容量与用户搜索需求，判断当前入场时机，再单独判断产品机会和 Hsia 适配度，不允许从单个高相关指标直接跳到“值得做”或“Hsia 应入场”。当 `category` 属于文胸、bra、brassiere、bralette 或 minimizer 领域时，额外强制执行文胸属性占比合同；非文胸品类不生成该图。

本 Skill 固定使用以下定义，禁止改写含义：

- `VoM (Volume of Market)`：市场已兑现容量，使用销量、销售额、销售趋势、新品销量承载等市场结果指标衡量。
- `VoS (Volume of Search)`：用户搜索需求，使用搜索量、流量、点击率、点击份额、ABA 趋势和搜索购买比等需求指标衡量；不同指标必须保留原始定义，不得把点击份额写成点击率。
- `Entry Timing`：在同一市场边界、站点和可比时间窗口内比较 VoM 与 VoS 的水平和变化，判断需求与销量是否同步、需求是否领先销量或需求是否转弱。
- `Hsia Fit`：Hsia 对该机会的用户、价格、产品能力、尺码/供应链和渠道经济性适配度。`brand=Hsia` 只是研究对象标签，不是适配证据。

这个 Skill 只使用 Sif MCP 和 SellerSprite MCP 建立市场级、关键词级、类目级结构化底盘。最终报告必须先由 `build_market_report_data` 生成 `dimension_results`、`chart_manifest` 和 `chart_specs`，再由通用 `HTML 渲染 Agent` 组织结论与 HTML；不得直接从原始 tool results 生成报告。与所有 HTML 报告型 Skill 一样，首稿由通用 `报告审批 Agent` 审批：首轮未通过时返工并复审，第二轮仍未通过时再返工一次并直接发布，不进行第三轮审批。

## When To Use

- 用户想知道美国某个电商品类或关键词市场最近在变什么，例如 sports bra、full coverage bra 或 large bust bra。
- 用户要求市场洞察快报、品类分析、趋势机会、研发机会、是否值得进入。
- 用户要求比较销量/销售额与搜索量/流量/点击信号，判断现在是不是入场窗口。
- 用户要求输出复杂 HTML 市场洞察报告、周报、经营分析或企划会材料。
- 用户问产品适不适合做、Hsia 适不适合入场、下一步应该验证什么。

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
| listing_sample_size | 100 | 文胸属性模块的统一商品家族样本目标；低于30不得生成文胸属性图 |
| head_listing_count | 10 | 头部商品数量 |
| new_product_window | 180d | 新品定义 |
| category_node_id |  | SellerSprite 节点级工具需要的 nodeIdPath；缺省时先自动解析，不要求用户手动提供 |

## Missing Params

如果缺少 `brand`、`marketplace` 或 `category`，先调用 `ask_user` 反问，不要执行数据工具。

不要因为缺少 `category_node_id` 直接询问用户。先调用 `sellersprite_product_node` 自动查找并校验 `nodeIdPath`；只有连续两次使用更精确的类目名称仍无法得到唯一高置信节点，并且 ASIN 类目也无法交叉验证时，才调用 `ask_user` 让用户从候选类目路径中选择。

缺少 Hsia 品牌能力、目标成本或供应链事实时，不阻断 VoM/VoS 市场分析，但必须把 `Hsia Fit` 标为 `证据不足`。若用户明确要求二元的 Hsia 入场结论，再调用 `ask_user` 补充相关品牌事实；不得把 `brand=Hsia` 当作这些事实的默认值。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill |
| ask_user | system | 缺参时询问用户 |
| respond_to_user | system | 回答非任务型问题或解释当前状态 |
| build_market_report_data | required | 将本轮工具结果编译为稳定 MarketReportData JSON，作为最终报告唯一结构化输入 |
| render_html_report | required | 用通用 HTML 渲染 Agent 将 MarketReportData 写成 HTML，并进入所有 HTML Skill 共享的审批与返工链路 |
| synthesize_artifact | system | LangGraph 最终节点；发布已渲染的市场洞察产物，不由 Planner 调用 |
| sif_market_get_keyword_demand | required | 提供 VoS 的搜索需求、生命周期和行动时机信号 |
| sif_market_get_keyword_history | required | 提供 VoS 的 ABA 搜索、排名、点击和集中度历史信号 |
| sif_market_get_keyword_root_trend | required | 校验 VoS 是否只由单一大词驱动，并界定长尾需求边界 |
| sif_market_get_keyword_competition | required | 提供 VoS 的流量分配、Top ASIN 和点击竞争信号 |
| sellersprite_market_research | required | 提供 VoM 的销量、销售额、市场容量及基础竞争信号 |
| sellersprite_aba_research_weekly | required | 补充 VoS 的 Amazon 热门、增长和潜力关键词信号 |
| sellersprite_keyword_research | required | 提供搜索量、购买量、购买率、供需比、均价与 PPC 等关键词市场结构 |
| sellersprite_keyword_research_trends | required | 提供核心关键词搜索量、购买量、购买率及同比/环比/近三月趋势 |
| sellersprite_product_node | conditional | 缺少 category_node_id 时按类目名称自动查找并校验 SellerSprite nodeIdPath |
| sellersprite_asin_detail | conditional | product_node 候选不唯一时校验类目；三池存在高优先级疑似同款且缺少 parent/variation 时补查商品关系，每份周报最多10个去重 ASIN |
| sellersprite_market_research_statistics | conditional | 有 category_node_id 时验证市场成熟度、头部强度、新品承载与利润代理 |
| sellersprite_market_product_demand_trend | conditional | 有 category_node_id 时获取 VoM/VoS 同表信号，包括销量趋势、搜索购买比、退货率和商品总数 |
| sellersprite_market_product_concentration | conditional | 有 category_node_id 时获取商品集中度；文胸品类同时为属性家族分析提供候选池 |
| sellersprite_market_brand_concentration | conditional | 有 category_node_id 时获取品牌集中度 |
| sellersprite_market_seller_concentration | conditional | 有 category_node_id 时区分卖家集中度与品牌集中度 |
| sellersprite_market_price_distribution | conditional | 有 category_node_id 时获取价格区间分布与销量占比 |
| sellersprite_market_rating_distribution | conditional | 有 category_node_id 时获取评分值结构与质量成熟度 |
| sellersprite_market_ratings_count_distribution | conditional | 有 category_node_id 时获取评分数门槛与新品进入难度 |
| sellersprite_market_listing_date_distribution | conditional | 有 category_node_id 时获取新品/老品上架时间结构 |
| sellersprite_market_listing_trend_distribution | conditional | 有 category_node_id 时获取绝对上架年份、销售效率与生命周期结构 |
| sellersprite_keyword_miner | conditional | 市场边界或长尾词簇不足时扩展消费者真实搜索词，不替代核心词证据 |
| sellersprite_product_research | conditional | 功能型/伪分类市场需要建立跨关键词商品候选池时使用 |
| sellersprite_competitor_lookup | conditional | 已有代表 ASIN，需要补相似商品并复核市场边界时使用 |
| sellersprite_review | conditional | 用户明确要求 VOC、好差评、失败机制或研发机会时使用 |
| sellersprite_google_trend | required | 提供 Google 站外相对热度，独立校验 Amazon 站内需求方向、季节性和背离；不得与站内搜索量相加 |
| sellersprite_market_seller_type_concentration | conditional | 需要解释 FBA/FBM/Amazon 自营结构时使用 |
| sellersprite_market_seller_country_distribution | conditional | 需要解释卖家地域结构与潜在竞争风险时使用 |
| sellersprite_market_ebc_distribution | conditional | 需要判断 A+/视频等内容门槛时使用 |

## Recommended Tool Use

1. 先检查 Required Inputs。缺少 `brand`、`marketplace` 或 `category` 时，调用 `ask_user`。
2. 必须调用 Sif 和 SellerSprite MCP 工具，不要调用 Reddit、TikTok、Amazon shelf 或 Media 工具。
3. 先建立 M01 市场边界：用户任务、关键词簇、Amazon 节点、纳入项和排除项。没有 `category_node_id` 时先调用 `sellersprite_product_node`；校验末级类目名称和完整路径，宽泛父节点不得代表目标市场。候选仍有歧义时才用 Top ASIN 调用 `sellersprite_asin_detail` 交叉验证，最后才询问用户。
4. 调用 Sif 四个关键词工具、SellerSprite ABA、`keyword_research`、`keyword_research_trends` 和 `google_trend`，覆盖 M03–M07 与 M19。`google_trend` 固定使用目标市场的核心非品牌词、目标 `marketplace`、`monthly=true`，默认 `googleProp=web`；相对指数只做站外方向和季节性校验。周度 ABA 使用适配器提供的上一完整周日期和 `includeKeywords`，不要自行写 `departments`；原词无结果时只允许适配器执行受控词根回退，不得扩大成 `bra` 等大类词。
5. 节点确定后调用十个节点工具，覆盖 M02、M08–M16：市场统计、需求质量、商品/品牌/卖家集中度、价格、评分值、评论数、上架时长和生命周期。任一结果为空或失败时先按工具恢复策略修复；恢复仍失败时记录对应维度缺口，继续生成降级报告。
6. 功能型/伪分类市场需要商品范围复核时调用 `product_research`，`competitor_lookup` 只补充相似商品；用户明确要求评论、痛点或研发机会时调用 `review`。完成商品工具后，把 `market_product_concentration`、`product_research`、`competitor_lookup` 送入统一商品身份层；对缺少 parent/variation 的高优先级疑似 ASIN，运行时在编译前自动调用 `asin_detail`，同一 ASIN 不重复调用且每份周报最多10个。它们分别对应 M17 和 M18。
7. 所有计划源数据工具完成、失败或耗尽恢复策略后，Planner 停止发出工具调用。LangGraph 的 `report_data_builder` 节点随后调用 `build_market_report_data`，生成 M01–M19 的 `dimension_results`、`chart_manifest`、全部适合可视化的 `chart_specs`、不适合画图的 `non_chart_presentations`、最多5张 `summary_chart_ids`、`report_quality`、`market_product_identity.v1`、`deduplication` 审计和有界 `metric_facts`。身份解析最多下载20张未缓存 Amazon 主图；超出补查或图片预算的疑似项进入 `unresolved`，不得强行归并。数据证据缺失时冻结对应结论；只有 builder 或最终 renderer 本身无法生成可用 HTML 时才不能发布报告。报告审批结论本身不阻断最终发布。MCP description 只指导分析，不是证据。
8. `data_analysis` 节点根据当前任务从周度市场固定指标目录中选择指标并绑定 `fact_id`；LLM 不得自定义公式或计算，脚本负责校验分母、实体范围、周期和样本完整性后输出 `derived_metrics` 与内部 `metric_gaps`。没有可算指标时继续流程，但不得把缺口改写成正文。
9. `insight_synthesis` 只使用 Builder 的有界一级指标、`status=calculated` 的二级指标和 Skill 合同，生成结构化“观察 → 解释 → 业务影响 → 动作”文字结论。每条结论必须绑定真实 `evidence_ids`；没有证据支持的维度直接省略，缺失原因只保留在运行元数据。
10. `chart_render` 节点只读取 builder 的有界 `chart_specs`，固定调用本机 Flint MCP `render_chart` 生成经校验的静态 SVG；不支持或失败的单图交给确定性服务端图表降级，不阻断报告。随后 `html_render` 以 `insight_narrative` 为分析主轴，把结论放到相关图表和表格附近，不得把报告压缩成 KPI 卡片与图注。所有 HTML Skill 共享通用链路：`data_analysis → insight_synthesis → chart_render → html_render →（report_review 与 report_red_team 并行）→ approval_join → 首轮任一分支未通过则 html_revision → 两分支再次并行 → approval_join → 第二轮仍未通过则 html_revision 并直接发布`。`report_review` 只做数字、证据、周期、范围和图文一致性审批；`report_red_team` 同时独立挑战关键业务结论，`approval_join` 等待并合并两者结果。最后由 LangGraph 进入 `synthesize_artifact` 终态节点。Planner 不调用 builder、data_analysis、insight_synthesis、chart_render、renderer、事实审批、红队、汇合、返工或 `synthesize_artifact`。
11. `report_red_team` 不获得源数据工具，只依据当前 HTML、完整裁剪后的 ReviewReportData 与本 Skill 合同在当轮给出 approve/revise；证据不足时收窄、改写或移除当前结论，补数建议仅留给下一次任务，不触发本轮 Builder 或报告链重跑。

## Analysis Dimension Coverage

本 Skill 按市场问题而不是工具数量判断覆盖度。完整报告要求 P0 全部 `covered`；P0 有缺口时报告状态必须是 `degraded`，P1 仅在触发后要求覆盖。只有具备趋势、比较、分布或关系强度的数据才生成稳定 `chart_id`；范围定义、口径审计或单一来源计数使用 `text_only` 的结构化文字/表格，数据不足时记录缺口而不是伪造图表。

| ID | 任务 | 核心证据 | 固定图表 |
| --- | --- | --- | --- |
| M01 / P0 | 市场边界 | `product_node`/`asin_detail` + `keyword_root_trend` | 文字范围卡：研究入口、Amazon 末级节点、消费者词与纳入边界；禁止画关系图 |
| M02 / P0 | VoM 容量与成熟度 | `market_research` + `market_research_statistics` | 容量分面指标图 |
| M03 / P0 | 核心词与长尾边界 | `keyword_root_trend` | 关键词需求分布图 |
| M04 / P0 | VoS 与购买效率 | `keyword_history` + `keyword_research` | 搜索量×购买率气泡图 |
| M05 / P0 | 需求趋势与生命周期 | `keyword_demand` + `keyword_research_trends` | 连续周期趋势图 |
| M06 / P0 | 周度关键词变化 | `aba_research_weekly` | 增减幅排序图 |
| M07 / P0 | 关键词竞争 | `keyword_competition` | Top ASIN 流量份额图 |
| M08 / P0 | 节点需求质量 | `market_product_demand_trend` | 节点质量分面指标图 |
| M09 / P0 | 商品集中度 | `market_product_concentration` | Top 商品销量/份额图 |
| M10 / P0 | 品牌集中度 | `market_brand_concentration` | 品牌份额图 |
| M11 / P0 | 卖家集中度 | `market_seller_concentration` | 卖家份额图 |
| M12 / P0 | 价格带结构 | `market_price_distribution` | 价格带销量占比图 |
| M13 / P0 | 评分值成熟度 | `market_rating_distribution` | 评分值销量分布图 |
| M14 / P0 | 评论壁垒 | `market_ratings_count_distribution` | 评论数门槛图 |
| M15 / P0 | 新品接受度 | `market_listing_date_distribution` | 上架时长销量图 |
| M16 / P0 | 生命周期结构 | `market_listing_trend_distribution` | 上架年份销量结构图 |
| M17 / P1 | 商品候选池范围 | `market_product_concentration` + `product_research`；`competitor_lookup` 仅补充 | 样本范围与去重口径表；只有两个以上来源时才列跨来源重叠，禁止用来源数量声称样本代表性 |
| M18 / P1 | 评论与研发机会 | `review` | 评论星级层级图 |
| M19 / P0 | Google 站外搜索趋势校验 | `google_trend` | Google 相对热度连续趋势图 |

`MarketReportData.dimension_results` 保存结论边界和限制，`chart_manifest` 保存每个任务的 `ready / text_only / blocked_by_evidence / missing_data / not_triggered` 状态。M01 与 M17 固定采用 `text_only`，由 `non_chart_presentations` 提供范围卡或样本审计表；HTML Render 不得自行把它们转换成图。卖家类型/地域、A+/视频、Coupon 和 ASIN 级趋势属于按需验证工具，不为追求工具覆盖率机械调用。Google 趋势是独立 P0 校验，不再属于按需工具。

M19 只比较同一核心非品牌词、同一目标地区和同一时间窗口内的 Google 相对热度，并与 Amazon 站内趋势判断方向一致、背离或证据不足。它不能替代 VoS、不能与 Amazon 搜索量相加，也不能从相对指数换算搜索量、销量或市场规模；站内外方向不一致时必须披露背离并保留替代解释。

商品数据使用 `market_product_identity.v1` 统一归并三个商品池；关键词、评论、品牌和其他市场数据仍使用 `passthrough_v0`。身份解析成功时 `deduplication.applied=true`、`status=partial`、`scope=product_identity_only`，只能声称统一池内的唯一商品家族数，不能声称关键词或整个市场已完成通用去重。M09、M17 和文胸属性模块必须共享相同 `family_id`。

统一身份按置信度从高到低自动归并：相同 parent 或 `variationList` 明确关联（1.00）；品牌、非空型号和显式包装数量一致（0.95）；品牌、主图和核心标题相似度至少0.90（0.92）；品牌和核心标题相似度至少0.90，且同站点、同月份、同销量口径的售价与销量完全一致（0.75）。启发式规则遇到型号、包装或核心结构冲突时必须阻断，明确 parent/variation 关系仍归并并把冲突写入审计。家族内销量、销售额、价格和份额不得求和，展示代表行并在 `observations` 保留全部来源和月份指标。

## VoM–VoS Decision Logic

### 1. 先做可比性门禁

只有同时满足以下条件，才允许比较 VoM 与 VoS 并判断时机：

- 同一 `marketplace`、同一目标用户任务和同一市场边界；
- 时间窗口可比，明确最新完整周期、同比/环比基准和采集日期；
- VoM 保留销量/销售额定义，VoS 保留搜索/流量/点击定义，不直接相加；
- 单关键词搜索量不得代表整个市场，Amazon 节点也不得代表完整用户需求；
- 仅当工具直接提供可比的搜索购买比或转换指标时才能引用该比值；不得自行用不同口径的搜索量除以销量制造精确比率。

任一条件不满足时，Entry Timing 必须输出 `不可判断` 或 `低置信待验证`，不能继续给肯定入场结论。

### 2. 分别判断 VoM 与 VoS

VoM 和 VoS 都必须同时判断“当前水平”和“变化方向”，不得只挑最大值：

| 层 | 必答问题 | 允许状态 |
| --- | --- | --- |
| VoM 市场容量 | 销量/销售额有多大；环比/同比如何；新品是否获得销量；销量是否被少数老品、套装或低价商品扭曲 | 强 / 中 / 弱 / 不可判断 |
| VoS 用户需求 | 搜索/流量/点击有多大；近期增长还是下降；需求是否由单一大词或品牌词驱动；点击是否过度集中 | 强 / 中 / 弱 / 不可判断 |

季节性判断至少需要两个可比较的季节周期，或由工具返回明确季节性证据。只有一个年度峰值时，只能写“季节性假设”，不得写“稳定旺季”或计算虚假的距峰值周数。最新点若低于前一点，不得描述为“正在爬坡”。

### 3. 用方向矩阵判断 Entry Timing

先比较趋势方向，再结合绝对水平、季节性和置信度解释：

| VoS 用户需求 | VoM 市场容量 | Entry Timing | 默认解释与限制 |
| --- | --- | --- | --- |
| 上升 | 上升 | `窗口成立` | 需求正在被销量兑现；仍需检查竞争门槛、利润和 Hsia Fit，不能直接判定应做 |
| 上升 | 持平或下降 | `优先验证` | 可能存在需求领先供给、转化断点或产品缺口；也可能是低转化、流量质量差或统计滞后，必须列出替代解释 |
| 持平或下降 | 上升 | `谨慎/观察` | 可能是促销、铺货、低价或季节滞后推动销量，不能用销量增长推导需求健康 |
| 下降 | 下降 | `暂缓进入` | 当前需求和容量共同转弱；除非存在明确反周期策略，不进入产品立项 |
| 不可比或冲突 | 任意 | `不可判断` | 先补齐同周期、同边界数据，不得强行选择象限 |

方向矩阵不能覆盖绝对水平：VoM 与 VoS 都处于低位时，即使短期同时上升，也最多判断为“弱复苏/继续观察”；两者仍处高位但同步下降时，应判断为“窗口后段/谨慎”，不能只看市场仍大。周度 VoS 与月度 VoM 必须先对齐完整周期或明确统计滞后，不能直接比较涨跌幅。

高 VoS/低 VoM 不是自动机会；它也可能意味着低转化、错误流量或供给不匹配。高 VoM/低 VoS 不是自动成熟市场；它也可能由促销、头部垄断或历史存量贡献。报告必须同时写出主解释和至少一个可信替代解释。

### 4. Entry Timing 之后再判断产品是否适合做

Entry Timing 只回答“现在有没有窗口”，不回答“这个具体产品值得做”。产品机会至少还要通过：

1. 市场边界：目标产品解决的用户任务与本轮 VoS 需求一致；
2. 供给兑现：VoM 不是由不相关子类、父子变体重复、3 Pack 与单件混算造成；
3. 可进入性：品牌/商品集中度、评分数门槛和新品销量承载没有形成无法解释的进入壁垒；
4. 价格与经济性：主力价格带只用于定位测试；没有单件归一化价格、费用、退货率或利润证据时，不得声称该价格带适合 Hsia；
5. 可验证差异：产品方向必须能映射到明确需求证据。没有评论/VOC/结构证据时，只能输出“结构假设”，不得输出确定设计结论。

产品结论使用：`不建议做`、`观察`、`进入验证`、`有条件可做`。在缺少成本、利润或产品验证证据的周度市场报告中，不使用无条件的“值得做”。

### 5. 单独判断 Hsia Fit

不得从市场吸引力推导 Hsia 适配度。必须逐项检查：

| Hsia Fit 维度 | 所需证据 |
| --- | --- |
| 用户与品牌相邻性 | Hsia 当前目标用户/使用场景与本轮需求是否重合 |
| 产品能力相邻性 | Hsia 已有版型、支撑结构、材料或研发能力是否可以迁移 |
| 价格与成本适配 | 单件归一化市场价格是否覆盖 Hsia 目标售价、成本、平台费用、广告和退货风险 |
| 尺码与供应链适配 | 目标尺码深度、颜色/SKU复杂度、MOQ和质量控制是否可承受 |
| 渠道 right-to-win | Hsia 是否有可迁移的评价基础、关键词资产、受众或差异化表达 |

Hsia 事实只能来自用户明确提供的品牌 brief、可追溯的 Hsia 自有商品证据或已注册的数据工具。若只有市场和竞品数据，Hsia Fit 必须写 `证据不足`，并输出待确认事实；不得把对 Hsia 的常识性印象写成证据。

### 6. 最终 verdict 规则

- `适合入场`：Entry Timing=`窗口成立`，产品=`有条件可做`，Hsia Fit 五项均有证据且无关键失败，并有可用经济性证据。
- `有条件入场`：时机和产品方向成立，但 Hsia Fit 或经济性仍有明确、可关闭的条件；必须列出条件与否决阈值。
- `进入验证`：VoM–VoS 显示潜在窗口，但产品或 Hsia Fit 证据不足；这是默认的正向结论。
- `观察`：信号不同步、需求不强或竞争解释不清，先补数据或等待下一周期。
- `暂缓/不进入`：VoM 与 VoS 同时转弱，或产品/Hsia 存在无法通过的关键门槛。

禁止用加权总分掩盖关键失败。一个高搜索量、一个大销量或一个主力价格带都不能抵消节点错误、需求下降、利润不可行或 Hsia Fit 缺失。

### 7. 强制结论链

每个重要判断都按以下格式写，缺一项就降级为待验证：

1. `证据`：原始指标、周期、口径和来源；
2. `解释`：该指标在本市场边界内意味着什么；
3. `替代解释`：至少一个可能导致相同数据表现的其他原因；
4. `决策影响`：只写该证据允许支持到哪一级结论；
5. `验证动作`：需要补什么数据、实验或阈值才能升级 verdict。

示例：`VoS 同比上升而 VoM 持平` → 解释为“需求可能领先销量” → 替代解释为“低转化或流量不精准” → 只能输出“优先验证”，不能输出“存在市场空白” → 下一步校验搜索购买比、Top ASIN 转化代理、新品销量承载和退货率。

## Bra Attribute Distribution Contract

当 `category` 属于文胸、bra、brassiere、bralette 或 minimizer 领域时，市场报告必须把“品类名”进一步拆成跨文胸品类通用结构属性。每个属性轴内部互斥，每个去重商品家族在每个轴上只能落入一个值；无法判断时进入 `未知`，证据冲突时进入 `冲突`。非文胸品类跳过本节全部要求。

### 必须统计的核心属性轴

| 属性轴 | 互斥取值 | 为什么影响市场判断 |
| --- | --- | --- |
| 钢圈结构 | 有钢圈 / 无钢圈 / 未知 / 冲突 | 影响支撑方式、舒适感、目标用户和 Hsia 技术路径 |
| 肩带形态 | 有肩带 / 无肩带 / 可拆或多穿 / 未知 / 冲突 | 影响稳定性、场景和版型难度 |
| 穿脱/扣合方式 | 前扣 / 后扣 / 侧扣 / 套头或无扣 / 未知 / 冲突 | “无前扣”不能作为单一类别，它包含后扣、侧扣和套头 |
| 罩杯衬垫结构 | 固定衬垫或模杯 / 可拆杯垫 / 无衬或薄杯 / 未知 / 冲突 | 影响轮廓、体积感、透气性和包装成本 |
| 罩杯覆盖度 | 全罩杯 / 半罩或阳台杯 / 低胸或深V / 未知 / 冲突 | 影响目标胸型、包容性和穿衣场景 |
| 背部结构 | 工字背 / 交叉背 / U背或背心背 / 露背 / 未知 / 冲突 | 影响肩带稳定、受力分配和外穿效果 |
| 下围长度 | 长下围 / 常规下围 / 未知 / 冲突 | 影响支撑面积、卷边风险和造型 |
| 包装数量 | 单件 / 多件装 / 未知 / 冲突 | 影响表面价格、单件价格和销量解释，必须避免把3 Pack与单件直接比较 |

按品类增加条件属性轴：Sports Bra 增加低/中/高支撑与运动场景；Nursing Bra 增加哺乳开合；Strapless Bra 增加防滑和侧翼结构；Minimizer Bra 增加显小结构、全罩覆盖和大杯尺码覆盖。面料、蕾丝/光面、无缝/有缝、领口和颜色属于条件轴；只有取值互斥且分类覆盖足够时才进入比例图。

### 分类与分母规则

1. 只使用 SellerSprite 返回的结构化商品属性、feature/bullet 或标题中的明确文字；证据优先级为结构化字段 > feature/bullet > title。
2. 不得用“标题没有写 strapless”推断“有肩带”，不得用“没有写 front closure”推断“后扣”。缺少明确证据统一进入 `未知`。
3. 同一属性轴命中两个互斥值时进入 `冲突`，不得由 LLM 自行选择更像的一个。
4. 直接使用 `market_product_identity.v1` 的统一商品家族，每个 `family_id` 只进入一次；不得再建立独立的局部 parent 去重口径。默认目标为100个商品家族；少于30个时不生成文胸属性比例图，并把该维度标为证据不足，但其他已完成维度仍进入降级报告。
5. 固定计算两套比例：`product_family_share`（商品家族数量占比）和 `estimated_sales_share`（第三方估算销量加权占比）。每个轴的分母都包含未知和冲突项，合计必须约等于100%。
6. 报告必须展示：原始商品数、去重家族数、具有销量字段的家族数、每个轴的已分类覆盖率、未知率和冲突率。
7. 某轴已分类覆盖率低于70%时仍展示完整比例和未知份额，但只能写“方向性样本”，不得用该轴判断主流结构或 Hsia 机会。

### 强制比例图

- 样本达到30个去重商品家族时，`MarketReportData` 必须包含 `bra_attribute_distribution`，并生成 `data-chart-id="bra_attribute_distribution"` 的 `quality_status=ready` 图表规格；条件不满足时直接省略该图和依赖它的结构结论，不生成缺口占位。
- 图表使用100%横向堆叠条形图，每个核心属性轴一行、每个互斥取值一个色块；不要为每个轴生成独立饼图或环形图。
- 销量字段覆盖率达到70%时，主图使用 `estimated_sales_share`；否则使用 `product_family_share`，并在副标题写明权重口径。表格必须同时保留两套比例。
- `未知`使用灰色，`冲突`使用红色斜纹或红色；不得隐藏未知项来制造更漂亮的比例。
- 图下注释必须回答：哪些结构是货架主流、哪些结构的销量效率高于商品供给占比、哪些结论因未知率过高仍不能使用，以及这些结构如何改变 VoM/VoS 和 Hsia Fit 判断。

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| sif_keyword_demand | sif_market_get_keyword_demand | always | 1 | block | continue_with_gap | 缺少 VoS 需求生命周期证据时，不得判断搜索需求方向或 Entry Timing；报告标为降级 |
| sif_keyword_history | sif_market_get_keyword_history | always | 1 | block | continue_with_gap | 缺少 VoS 历史搜索/ABA 数据时，不得判断近期需求趋势或与 VoM 比较；报告标为降级 |
| sif_root_trend | sif_market_get_keyword_root_trend | always | 1 | block | continue_with_gap | 缺少 Sif 词根趋势时，不得判断长尾市场边界或需求集中度；报告标为降级 |
| sif_keyword_competition | sif_market_get_keyword_competition | always | 1 | block | continue_with_gap | 缺少 Sif 关键词竞争证据时，不得判断 Top ASIN 流量份额或进入难度；报告标为降级 |
| sellersprite_market_base | sellersprite_market_research | always | 1 | block | continue_with_gap | 缺少 VoM 销量/销售额容量证据时，不得判断 Entry Timing、产品适合度或市场规模；报告标为降级 |
| sellersprite_aba_weekly | sellersprite_aba_research_weekly | always | 1 | block | continue_with_gap | 缺少 VoS 周度关键词证据时，不得生成 Entry Timing 结论；报告仍按降级模式生成 |
| sellersprite_keyword_market | sellersprite_keyword_research | always | 1 | block | continue_with_gap | 缺少关键词搜索量、购买量、购买率或供需结构时，不得完整判断 VoS 水平和关键词机会；报告标为降级 |
| sellersprite_keyword_trends | sellersprite_keyword_research_trends | always | 1 | block | continue_with_gap | 缺少核心词趋势数据时，不得判断需求增长、衰退或生命周期；报告标为降级 |
| sellersprite_google_trend | sellersprite_google_trend | always | 1 | block | continue_with_gap | 缺少 Google 站外相对热度趋势时，M19 标为缺失，报告降级；不得声称已完成跨渠道需求方向或季节性校验 |
| sellersprite_market_statistics | sellersprite_market_research_statistics | param_present:category_node_id | 1 | block | continue_with_gap | 缺少节点级成熟度、头部对比和新品承载统计时，不得完成 VoM 与新品可进入性判断；报告标为降级 |
| sellersprite_node_demand | sellersprite_market_product_demand_trend | param_present:category_node_id | 1 | block | continue_with_gap | 节点级 VoM/VoS 趋势、退货率或搜索购买比缺失时不得判断当前入场窗口；报告标为降级 |
| sellersprite_product_concentration | sellersprite_market_product_concentration | param_present:category_node_id | 1 | block | continue_with_gap | 商品集中度缺失时不得判断爆款主导程度；M09 只使用该来源观测所在的统一家族，文胸样本少于30个家族时对应属性结论降级 |
| sellersprite_brand_concentration | sellersprite_market_brand_concentration | param_present:category_node_id | 1 | block | continue_with_gap | 品牌集中度缺失时不得判断品牌竞争结构；报告标为降级 |
| sellersprite_seller_concentration | sellersprite_market_seller_concentration | param_present:category_node_id | 1 | block | continue_with_gap | 卖家集中度缺失时不得把品牌集中度当作完整竞争结构；报告标为降级 |
| sellersprite_price_distribution | sellersprite_market_price_distribution | param_present:category_node_id | 1 | block | continue_with_gap | 价格区间及销量占比缺失时不得判断主力价格带或定价机会；报告标为降级 |
| sellersprite_rating_distribution | sellersprite_market_rating_distribution | param_present:category_node_id | 1 | block | continue_with_gap | 评分值结构缺失时不得判断市场质量成熟度或产品改善空间；报告标为降级 |
| sellersprite_ratings_distribution | sellersprite_market_ratings_count_distribution | param_present:category_node_id | 1 | block | continue_with_gap | 评分数门槛分布缺失时不得判断评价门槛；报告标为降级 |
| sellersprite_listing_date_distribution | sellersprite_market_listing_date_distribution | param_present:category_node_id | 1 | block | continue_with_gap | 上架时间与新品接受度分布缺失时不得判断新品接受度；报告标为降级 |
| sellersprite_listing_trend_distribution | sellersprite_market_listing_trend_distribution | param_present:category_node_id | 1 | block | continue_with_gap | 绝对上架年份与销售效率缺失时不得判断生命周期结构；报告标为降级 |
| sellersprite_product_universe | sellersprite_product_research | prompt_mentions:功能型,伪分类,用户任务,完整市场,跨关键词 | 1 | warn | continue_with_gap | 未建立跨关键词商品候选池时，只能披露关键词和节点市场，不得声称已覆盖全部功能型商品 |
| sellersprite_review_voc | sellersprite_review | prompt_mentions:评论,好评,差评,痛点,VOC,研发 | 1 | warn | continue_with_gap | 缺少分层评论时只能输出市场机会和结构假设，不得输出确定的用户痛点或产品解法 |
| market_report_data | build_market_report_data | always | 1 | block | call_missing_tool | 最终报告前必须先生成 MarketReportData，不能直接从原始工具结果生成 HTML |
| market_report_html | render_html_report | always | 1 | block | call_missing_tool | 最终产物必须来自 MarketReportData 和 chart_specs，并经过通用报告审批与必要的 HTML 返工链路 |

## Output Rules

- 最终产物必须是市场洞察快报，不是原始数据罗列。
- 报告首屏必须分开显示：`Entry Timing`、`产品适合度`、`Hsia Fit`、`最终 verdict`。每项同时显示置信度、首要支持证据和首要阻断项，不能只给一句综合结论。
- 报告结构优先采用：答案先行、VoM–VoS 对比、Entry Timing 象限、强制结论链、产品可进入性、Hsia Fit、核心 KPI、市场容量与需求趋势、价格/竞争/新品门槛、风险、否决条件和下一步验证动作。
- HTML 版式要服务阅读：首屏只放四项 verdict、四个关键信号和一个优先行动；长表格和原始结构化证据放到后半段。
- 最终 HTML 必须由 LLM 直接组织文案、结构和样式，不要再通过中间 blueprint 或固定章节模板二次渲染；LLM 失败时不要产出 HTML 报告。
- 本 Skill 与其他 HTML 报告型 Skill 共用通用 `报告审批 Agent` 和 `HTML 渲染 Agent`。审批 Agent 只给结构化意见，不直接修改 HTML；渲染 Agent 按意见返工。最多执行两轮审批：第一轮未通过后生成第二稿并复审，第二轮仍未通过后生成第三稿并直接发布，不得继续发起第三轮审批，也不得因审批未通过而阻断发布。审批记录保留在运行元数据中，不作为报告正文内容。
- Evidence Contract 的 `block + continue_with_gap` 表示阻止依赖该证据的具体结论，而不是阻止整份报告。工具最终仍未成功时继续进入 HTML renderer；对应结论直接从可见正文省略，缺口只保留在 ReportData、工具 JSON 和审批输入中。某工具先失败后恢复成功时，以最终成功证据为准，已恢复的失败尝试只保留在执行时间线。
- 最终 HTML 不生成“数据完整性与未完成任务”“数据缺口”或逐项不可判断清单；如需说明范围，只保留一行简短的数据来源、市场和周期说明。
- 最终报告不得展示工具调用成功率、调用了几个工具、原始 JSON、evidence_map 表格或 source_summary 调试信息；这些只属于左侧执行时间线。
- 每个市场结论必须能追溯到 Sif 或 SellerSprite 的工具证据；每个 Hsia Fit 结论必须能追溯到工具证据或用户明确提供的 Hsia 品牌事实，并标明来源类型。
- Sif 和 SellerSprite 支撑市场级/关键词级/类目级判断。
- 不得编造销量、搜索量、市场规模、人口画像或平台级数据。可以引用 Sif/SellerSprite 返回的量化字段，但必须保留来源。
- Evidence Contract 的 warn 级或可降级 block 级缺口仅用于冻结相关结论和内部审计，不写入最终 HTML。
- `MarketReportData.data_gaps` 仅用于内部审批、调试和后续恢复；不得根据 evidence id 编号、调用顺序或已恢复失败自行推断缺口，也不得进入最终 HTML。
- P0 分析维度覆盖率只保留在运行元数据；最终 HTML 只披露实际使用数据的市场、周期、样本和去重范围。仅当 `deduplication.applied=true` 且 `scope=product_identity_only` 时，允许把 M09、M17 和文胸属性中的 `family_id` 数写成唯一商品家族数；不得据此声称关键词、评论或整个市场已去重。`applied=false` 时只能写原始样本量，也不得声明唯一商品数。MCP tool description 不得作为证据引用。
- M19 有至少4个真实且可排序的连续日期/月度点时，必须渲染 `external_search_trend` 折线图；数据缺失、标签无时间语义或点数不足时直接省略该图和依赖它的结论，不得拼接、插值或伪造趋势。图表和正文必须称为“Google 相对热度/指数”，不得写成绝对搜索量、销量或市场规模。
- P0 未全部覆盖或需要图表的任务缺少 `chart_status=ready` 时仍进入 HTML renderer；对应结论和缺图模块直接省略，不得伪造图表或显示缺口占位。`chart_status=text_only` 是有效呈现状态，必须按 `non_chart_presentations` 渲染为范围卡、定义列表或样本审计表。P1 任务未触发时同样不渲染空模块。
- 如果自动节点解析失败，报告必须写明尝试过的查询词和候选路径；不得笼统要求用户自行补充 `category_node_id`。
- 输出 Hsia 机会时必须包含：机会名称、VoM 证据、VoS 证据、二者关系、主解释、替代解释、Hsia Fit 证据、建议价格带/尺码/颜色或结构假设、风险、否决条件和下一步验证动作。
- 不得使用“需求旺盛 + 主力价格带集中 = Hsia 应做”这一类省略中间门禁的表达。市场容量、用户需求、进入门槛、产品适合度和 Hsia Fit 必须分段判断。
- 不得把“最大价格带”写成“推荐定价”；不得把“点击集中度高”写成“差异化空间大”；不得把“其他品牌份额”写成“市场空白”，除非有额外证据完成解释。
- 报告必须固定包含一张 `VoM–VoS 决策表`，列为：层级、指标、当前值、变化方向、周期/口径、解释、替代解释、状态、证据来源。
- 只有存在 Hsia 内部事实或用户明确品牌证据时才展示 `Hsia Fit 门禁表`；没有证据的适配维度省略，不得留空、显示缺口或自动判为通过。
- 文胸品类在样本达到30个去重商品家族时必须包含“文胸属性结构”章节、`bra_attribute_distribution` 100%堆叠比例图和属性占比明细表，八个核心属性轴缺一不可且未知项也必须显示。样本不足时整个章节及依赖它的结论直接省略；非文胸品类不生成该章节。
- 属性占比的业务解释必须进入产品适合度和 Hsia Fit：例如主流结构不等于可复制，销量加权占比高于商品家族占比表示该结构在样本中销售效率较高，但仍需排除品牌、价格和套装效应。

### HTML Report Style Reference

参考 LinkFox 市场报告风格，但只复用版式和写法，不复用示例中的真实数值、类目排名、ASIN、品牌判断或图表数据。

视觉与结构要求：

- 使用白底、轻边框、紫蓝主色、青/绿/橙/红作为图表或风险语义色；不要把所有内容做成厚重卡片。
- 不生成右侧目录、侧边栏、TOC 或锚点导航；页面采用单栏主内容布局，桌面端和移动端都以正文阅读为主。
- 顶部使用渐变报告头：报告标题、报告副标题、生成周期/数据源说明。
- KPI 采用横向轻量指标条，不使用大面积 KPI 卡片。每个 KPI 显示：指标名、数值、变化或来源。
- 正文用 `.content-section` 式分段，每段必须有一个明确问题：执行摘要、核心指标全景、子类目/关键词对标、关键发现与 So What、行动建议。
- 每个重要段落末尾显示数据源脚注：工具名、时间窗口、口径限制。
- 图表最终必须是 `chart_render` 注入的静态内联 SVG，不依赖外部 CDN；不得使用 JavaScript、Canvas、ECharts、Chart.js 或其他运行时绘图库。`html_render` 只为 `required_chart_ids` 放置带精确 `data-chart-id` 的空 SVG 占位，运行时必须在审批前用 Flint MCP 已校验 SVG 或确定性单图降级结果替换；最终 HTML 中不得保留空 SVG。

图表渲染要求：

- 只渲染 `market_report_data.chart_specs` 中 `quality_status=ready` 的图表。`summary_chart_ids` 选择 3-5 张优先靠前展示的图表，但它们仍是对应章节中唯一的图表解读块，不得另建“核心图表速览”画廊或在摘要与正文各放一份；其余 ready 图表必须进入后续“市场任务图谱”，不能因不在摘要区而省略。`bra_attribute_distribution` 不得进入 `summary_chart_ids` 或“市场任务图谱”；文胸样本达到30个去重商品家族时，它必须且只能在“文胸属性结构”章节出现一次，样本不足时省略该章节。不得从其他表格自行拼图。每张图必须用 `<figure class="chart-card" data-chart-id="{chart_id}">` 包裹，`data-chart-id` 必须与规格完全一致，并且在整份 HTML 中只出现一次。
- 摘要优先图表固定使用单列全宽布局：一行只能放一张图，不得在桌面端使用两列卡片；每张 `figure` 和内联 SVG 均占容器宽度100%，图表之间保留24px间距。后续“市场任务图谱”也必须保证每张图与其观察、解释相邻。
- `line` 只允许真实日期/月度序列且至少 4 个连续点；不同关键词或不同品牌的排名不得画折线。`donut` 只允许 3-7 个互斥份额项且总和约等于 100%；不满足时改用横向柱状图。长标签、Top 商品和关键词一律优先横向柱状图。
- 所有图使用统一组件：白底、1px `#E5E7EB` 边框、6px 圆角、无阴影、无 3D、无渐变填充、无动画。主色按 `#4F46E5`、`#0891B2`、`#16A34A`、`#D97706`、`#DC2626` 循环，不使用随机色。
- 图表宽度为容器 100%；桌面端绘图区高 300-360px，横向条形图按每行 34-40px 自适应但最高 380px；移动端高 260-320px。使用 SVG 时必须设置响应式 `viewBox` 和 `preserveAspectRatio`，文字不得超出绘图区。
- 每张图固定包含：标题、最多一行副标题、单位、清晰轴/基线、必要的数据标签、1-2 句商业判断、`source` 数据源脚注。每个必需图表的 `<figure>` 内必须包含已填充的 `<svg>` 和至少一个可见的 `path`、`rect`、`circle`、`line`、`polyline` 或 `polygon` 图形节点。数字统一格式化：千/百万缩写、百分比 1 位小数、货币带 `$`；同一坐标轴禁止混用销量、销售额、评论数和份额。`metric_group` 可用相互独立、各自标单位的小图并列。
- 横向柱状图最多 8 项并按数值排序，标签列宽稳定；折线图只标首点、末点、最高点和最低点；环形图标签放右侧图例，不把文字塞进扇区。重复标签、空标签、单点、全零或单位不明的规格不渲染。
- `bra_attribute_distribution` 使用 Flint 标准100%横向堆叠条形图：每个核心属性轴一行，直接展示该轴在全样本中的已识别属性值、未知和冲突占比；不再使用“可识别度 + 已识别构成”的双层定制图。
- 未知和冲突必须保留在分母中；图例和标签必须能区分各属性值，`未知`与`冲突`保持一致的数据质量语义。可识别度 ≥70% 才可作结构分析，30–69.9% 仅描述方向性样本，低于30%时省略该属性轴的结构结论。
- 小于10%的分段不得强塞文字；通过图例、轴标签或明细表保留完整数值，禁止出现重叠、`0.` 残缺标签或右侧裁切。
- 输出前做图表 QA：确认无标签重叠、无截断数值、无重复图例、无错误单位、无空白画布，并确认每张图能直接回答一个业务问题。数据不足时省略图表及其结论，不编造数据凑数量。

表格渲染要求：

- 数据足够时至少生成“核心指标对标表”和“Top ASIN/品牌/关键词明细表”，不得只输出 KPI 卡片和文字摘要。
- 核心指标表至少包含：指标、当前值、对标值、差异、商业解释、证据来源。Top 明细表只选择证据中实际存在的名称、ASIN/关键词、指标值、排名或份额、来源字段。
- 使用完整的 `<table>`、`<thead>`、`<tbody>` 和真实数据行，不用省略号代替内容；表头清晰，数值右对齐，移动端用横向滚动容器。
- 表格和图表只能使用 MarketReportData、chart_specs 和工具证据；必要表格字段缺失时显示 `—`，其余依赖缺失字段的内容直接省略，不推算未提供的指标。

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
    <p>Entry Timing：{timing_verdict} · 产品：{product_verdict} · Hsia Fit：{hsia_fit_verdict} · 最终：{final_verdict}</p>
  </div>
  <ul class="insight-list">
    <li class="priority-high"><strong>首要依据：</strong>{primary_evidence_chain}</li>
    <li class="priority-medium"><strong>首要阻断项：</strong>{primary_blocker}</li>
  </ul>
  <div class="data-source">数据源：{tool_name} · {time_range} · {limitation}</div>
</section>

<section class="content-section">
  <h2>VoM–VoS 入场时机判断</h2>
  <div class="table-wrapper">{vom_vos_decision_table}</div>
  <ul class="insight-list">
    <li class="priority-high"><strong>主解释：</strong>{primary_interpretation}</li>
    <li class="priority-medium"><strong>替代解释：</strong>{alternative_explanation}</li>
  </ul>
</section>

<section class="content-section">
  <h2>Hsia Fit 门禁</h2>
  <div class="table-wrapper">{hsia_fit_gate_table}</div>
  <p>{kill_conditions_and_next_validation}</p>
</section>

<section class="content-section">
  <h2>文胸属性结构</h2>
  <figure class="chart-card" data-chart-id="bra_attribute_distribution">{bra_attribute_stacked_chart}</figure>
  <div class="table-wrapper">{bra_attribute_share_table}</div>
  <p>{attribute_mix_implication_and_limit}</p>
</section>

<section class="content-section">
  <h2>市场任务图谱</h2>
  <div class="dimension-chart-grid">{all_non_summary_ready_dimension_charts}</div>
</section>
```

分析写法要求：

- 每个 `h3` 小节必须按“证据 → 解释 → 替代解释 → 决策影响 → 验证动作”组织；不要先给超出证据的结论。
- 对标分析必须说明“为什么这个对标对象重要”，例如体量、价格、利润、退货率、品牌数、评论门槛或流量份额中的一个或多个。
- 行动建议必须分优先级：`priority-high`、`priority-medium`、`priority-low`。
- SWOT 只能作为补充，不能替代 VoM–VoS 决策表和 Hsia Fit 门禁表；SWOT 中每条都必须来自工具证据或明确标注为待验证假设。

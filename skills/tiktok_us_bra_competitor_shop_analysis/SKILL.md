---
name: tiktok_us_bra_competitor_shop_analysis
description: Analyze TikTok Shop US bra competitor stores with FastMoss by scanning 50 external shop candidates and comparing the leading 10 on scale, bra product structure, trend, channels, creator structure, strengths, weak spots, and Hsia actions.
version: 0.2
owner: Hsia R&D Insight Agent
---

# TikTok Shop 美国文胸竞品店铺分析 Skill

## What It Does

为 Hsia 商品企划、TikTok Shop 运营和管理团队生成美国文胸竞品店铺分析。优先从 FastMoss 美国 Bras/女士文胸 L3 完整月店铺榜建立 50 家外部竞品候选池；若该范围已调用但返回空数据，才允许用美国 Women's Underwear/女士内衣 L2 最近完整周榜作为“候选宇宙”降级入口。随后对候选排名领先的 10 家店铺执行同口径标准分析，比较规模与增长、文胸商品结构、新品节奏、价格带、近期趋势、成交渠道、达人矩阵和三类集中度风险，最终回答“谁是真正威胁、共同打法是什么、哪些能力可学习、哪些弱点可攻击、Hsia 下一步验证什么”。

本 Skill 只做 50 家候选扫描和 10 家标准分析，不执行 Top 3 视频、直播、广告或单品爆发归因深拆。店铺榜和文胸商品结构属于 Bras 类目口径；店铺基础信息、渠道、趋势和达人分析默认属于全店口径，除非 FastMoss 明确返回更窄范围，二者不得混写。

## When To Use

- 用户要分析 TikTok Shop 美国文胸头部竞品店铺。
- 用户要比较哪些文胸店铺规模最大、增长最快或最值得关注。
- 用户要了解竞品店铺的商品、价格、渠道、达人和集中度结构。
- 用户要从文胸竞品店铺中提炼 Hsia 可学习打法、威胁和薄弱点。
- 用户输入类似“分析 TK 美国文胸前 10 家竞品店铺”或“先扫描 50 家，再比较 10 家”。

## Required Inputs

| 字段 | 说明 |
| --- | --- |

## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| brand | Hsia | 报告使用方；明确匹配 Hsia 的自有店铺不计入外部竞品候选 |
| marketplace | US | 固定 TikTok Shop 美国市场，FastMoss region 使用 US |
| category | 女士文胸 | 必须解析为 Bras/女士文胸 TikTok 商品 L3 类目 |
| category_node_id |  | Bras L3 category_id；缺省时自动解析 |
| time_range | 28d | 10 家店铺标准分析的统一窗口 |
| shop_candidate_size | 50 | 外部竞品候选池目标店铺数 |
| shop_analysis_count | 10 | 按类目期 GMV 排名执行标准分析的店铺数 |
| new_product_window | 30d | FastMoss 新品定义，用于店铺文胸新品节奏 |

## Missing Params

所有业务参数均有默认值，可直接执行，不要为了确认默认值而反问。用户明确指定非美国市场时，调用 `ask_user` 请其改用对应市场工作流；不得把其他市场店铺混入美国报告。

缺少 `category_node_id` 时，先调用 `mcp__fastmoss__search_category_by_words` 查询 `women's bras`、`bras`、`女士文胸` 和用户原始类目词。选择路径叶子明确为 Bras/女士文胸的 L3 节点作为店铺榜主类目，同时保留搜索结果中名称明确表示成品文胸的相关 L3 节点（例如女士无钢圈文胸）作为商品行本地分类集合；文胸配件、胸垫和其他非成品类目不进入该集合。`Women's Underwear / 女士内衣` L2 不能代替 L3 文胸商品范围，只能在 L3 月度店铺榜已返回空数据后充当候选店铺入口。

FastMoss MCP 未认证或额度不足时不得编造店铺，也不得口头承诺不存在的“断点续跑”。运行时返回 `needs_user_action` 后必须立即停止；只有结果包含 `pending.resume_supported=true` 才能告诉用户充值/认证后继续。继续运行时复用断点内已成功的完全相同调用，只补被阻塞或缺失的调用。空榜单或空分析结果只表示本轮数据未取回，不把缺失值写成 0；空结果不做长期缓存。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill、默认参数和分析边界 |
| ask_user | system | 仅在用户指定非美国市场或 L3 类目存在实质歧义时询问 |
| respond_to_user | system | 回答非任务型问题或解释当前状态 |
| build_tiktok_bra_competitor_shop_report_data | required | 按 seller_id 编译 50 家候选和 10 家同口径店铺证据，确定性计算趋势、价格带和观察样本集中度 |
| render_html_report | required | 只读取 TikTokBraCompetitorShopReportData 生成最终 HTML，不直接消费原始 FastMoss 结果 |
| synthesize_artifact | system | LangGraph 最终节点；发布 renderer 成功写出的报告，不由 Planner 调用 |
| mcp__fastmoss__search_category_by_words | required | 将女士文胸解析为 TikTok 标准 L3 category_id |
| mcp__fastmoss__shop_rank_top_selling | required | 优先用 US 已完成自然月文胸 L3 GMV 榜；空榜后才用女士内衣 L2 完整周榜建立候选宇宙 |
| mcp__fastmoss__shop_search | disallowed | 本 Skill 的 seller_id 必须来自受控店铺榜候选池，不做关键词店铺补数 |
| mcp__fastmoss__shop_base_info | required | 获取 10 家店铺身份、类型、评分和基础快照 |
| mcp__fastmoss__shop_product_analysis | required | 仅按 seller_id 获取有界店铺商品页，由 Builder 根据商品行 `category.l3.id` 本地筛选 Bras L3 商品 |
| mcp__fastmoss__shop_sale_analysis | required | 获取全店短视频、直播、商品卡、达人和自营成交结构 |
| mcp__fastmoss__shop_data_trends | required | 获取全店近 28 天 GMV、销量和经营动量趋势 |
| mcp__fastmoss__shop_creator_analysis | required | 获取全店近 28 天合作达人和达人销售结构 |
| mcp__fastmoss__fastmoss_detail_url_examples | required | 为店铺、商品和达人生成 FastMoss 站内详情链接 |
| mcp__fastmoss__shop_video_analysis | disallowed | 当前版本不做重点店铺视频深拆 |
| mcp__fastmoss__shop_live_analysis | disallowed | 当前版本不做重点店铺直播深拆 |
| mcp__fastmoss__shop_investment_analysis | disallowed | 当前版本不做广告投放深拆 |

## Recommended Tool Use

### 1. 先定义任务，再调用工具

严格按 CS01–CS09 执行。每次调用必须服务于一个任务和完成条件；工具返回成功但市场、类目、时间、seller_id 或样本数不符时，任务仍未完成。

### 2. CS01：锁定 Bras L3 类目

1. 调用 `mcp__fastmoss__search_category_by_words`，query 至少包含 `women's bras`、`bras`、`女士文胸` 和当前 `category`。
2. 只接受叶子名称为 Bras/女士文胸的 L3 category_id 作为店铺榜主类目并保留完整路径；同时记录名称包含 Bra/文胸且不含 Accessory/配件/胸垫的相关成品文胸 L3 id，供 Builder 对商品行做本地分类。
3. 未取得主 L3 文胸节点时停止。L2 不能代替后续文胸商品分类，也不得使用 Fashion 或关键词店铺搜索凑数。

### 3. CS02：建立 50 家外部竞品候选池

1. 首选范围使用最近一个已完成自然月：`filter.region=US`、`filter.category_id=<CS01 L3 id>`、`filter.date_type=month`、`filter.date_value=<上一个完整 YYYY-MM>`。
2. 首选范围 page=1 返回空数据后，才允许切换到受控兼容范围：`filter.region=US`、`filter.category_id=842888`（Women's Underwear/女士内衣 L2）、`filter.date_type=week`、`filter.date_value=<最近完整 YYYY-Www>`。若 L3 月榜有数据，不得使用 L2；不得使用无 category_id、day 或其他类目范围。
3. 调用 `mcp__fastmoss__shop_rank_top_selling`，统一使用 `orderby=[{"field":"usd_gmv","order":"desc"}]`、`pagesize=10`，从 page=1 顺序翻页。
4. 按 `seller_id` 去重。店铺名或品牌名明确匹配 `brand=Hsia` 的自有店铺只记录为被排除的本品牌参考，不计入外部竞品候选数。
5. 持续翻页直到取得 50 家不同外部店铺或榜单耗尽。通常至少读取 5 页；若前 5 页包含 Hsia 或重复店铺，再读取后续页补足，最多读取 10 页。候选池完成前不得启动 10 家店铺的高成本标准工具。
6. 候选排名只使用同一受控范围内的 `usd_gmv` 降序。不得把全店累计 GMV、销量或达人数量换成候选主排序。
7. L3 榜单不足 50 家时保留实际候选并标记范围；L2 降级范围必须明确称“女士内衣 L2 周榜候选样本”，不得宣称完整 Top 50 文胸店铺。文胸相关性只由后续 L3 `shop_product_analysis` 证明。

### 4. CS03：确定 10 家标准分析对象

1. 从 CS02 外部竞品候选中按类目期 GMV 顺序选择前 `shop_analysis_count=10` 个不同 `seller_id`。
2. 后续五个标准工具必须使用完全相同的这组 seller_id；不得因某个工具失败而静默换店。
3. FastMoss 类目榜说明该店在 Bras 范围有成交，不代表全店全部销售额来自文胸。

### 5. CS04：店铺身份与基础快照

对 10 个 seller_id 分别调用一次 `mcp__fastmoss__shop_base_info`，只传 `filter.seller_id`。保留店铺名称、seller_id、店铺类型、本土/跨境属性、评分、累计规模和商品/达人/视频/直播计数等实际字段。基础快照属于全店口径。

### 6. CS05：文胸商品与价格结构

对同一组 seller_id 分别调用 `mcp__fastmoss__shop_product_analysis` 获取店铺商品页。商品列表请求只按店铺定位，不把类目与周期参数传给列表子查询：

- `filter.seller_id=<seller_id>`
- `orderby=[{"field":"day28_gmv","order":"desc"}]`
- `page=1`、`pagesize=10`

禁止在该请求的 `filter` 中加入 `category_id`、`time_range_days`、`start_date` 或 `end_date`。第一页取得后，读取每条商品自身的 `category.l3.id`；若已取得至少 5 个不同的成品文胸商品、返回总数已耗尽或当前页少于 10 条则停止。否则按 page=2、page=3 顺序补页，最多 3 页；不得重复相同 seller_id+page，也不得超过 page=3。

Builder 合并同一 seller_id 的全部成功页，根据 CS01 保留的成品文胸 L3 id 本地筛选，只接受带有明确 `category.l3.id` 的商品，并按 `product_id` 去重。缺少 L3 id 的商品不默认归入文胸；文胸配件和其他非目标类目排除。保留 GMV 排名前 5 个商品用于报告，按 `<20`、`20–40`、`40–60`、`60–100`、`>100 USD` 分价格带；不要硬删 20 USD 以下或 100 USD 以上商品。上架不超过 30 天定义为新品。

Top1/Top3 商品集中度只有在分母覆盖完整店铺文胸 GMV 时才能称“文胸销售集中度”；如果只能用返回的 Top 商品行计算，必须写“返回商品样本内集中度”。

### 7. CS06：近期经营趋势

对同一组 seller_id 分别调用 `mcp__fastmoss__shop_data_trends`，使用 `filter.seller_id` 和 `filter.time_range_days=28`。用生成日前最近 14 个完整日计算 L7/P7：比值不低于 1.2 为加速，0.8–1.2 为平稳，低于 0.8 为回落；P7 为 0 且 L7 大于 0 标记新启动。少于 14 个完整日不得输出确定趋势。该趋势属于全店口径。

### 8. CS07：成交渠道与达人结构

1. 对同一组 seller_id 分别调用 `mcp__fastmoss__shop_sale_analysis`，使用 `filter.time_range_days=28`；保留视频、直播、商品卡，以及 affiliate、shop_account 等份额。最大渠道份额是全店渠道集中度。
2. 对同一组 seller_id 分别调用 `mcp__fastmoss__shop_creator_analysis`，使用 `filter.time_range_days=28`、`orderby=[{"field":"sale_amount","order":"desc"}]`、`page=1`、`pagesize=10`。
3. 头部达人份额若只基于返回的 Top 10 达人，必须写“返回达人样本内集中度”，不能冒充全店真实 Top3 贡献率。
4. 不按粉丝数判断带货能力；优先使用实际返回的销售额、销量和内容数量。

### 9. CS08：形成同口径判断

对每家店铺分别回答：规模与方向、文胸商品和价格打法、主导渠道、达人打法、可学习能力、难复制壁垒、可攻击弱点。重点检查：

- 爆品集中：是否依赖少数文胸商品。
- 达人集中：是否依赖少数头部达人。
- 渠道集中：是否依赖单一成交渠道。
- 新品接力：近 30 天是否形成第二增长曲线。
- 口径边界：文胸类目指标与全店指标是否被正确区分。

不得生成不透明的综合分。使用可解释的“规模威胁、增长威胁、产品重合、打法可复制性”四项判断，结论必须落在可学习、需防守、可攻击或待验证之一。

### 10. CS09：编译、渲染与发布

1. 调用 `mcp__fastmoss__fastmoss_detail_url_examples` 一次，为店铺、商品和达人构造 FastMoss 站内链接。
2. 源数据工具完成、失败或耗尽恢复策略后，Planner 停止发出工具调用。LangGraph 的 `report_data_builder` 节点必须调用 `build_tiktok_bra_competitor_shop_report_data`；不要调用 `build_market_report_data` 或新品整理器。
3. 整理器必须按 seller_id 去重、选择 50 家外部候选和前 10 家标准对象，检查五种标准工具是否对同一组 seller_id 均已尝试，并返回带有界 `metric_facts` 的 `tiktok_bra_competitor_shop_report_data.v1`。若返回未尝试的 seller_id 与工具组合，只补对应调用后重新编译；没有新增或修正证据时不得原样重试整理器。
4. 只有专用整理器成功后，LangGraph 才进入 `data_analysis`。LLM 只选择固定竞店指标并绑定 `fact_id`，脚本校验同店、同周期、正确分母与完整样本后计算；观察样本份额不得冒充完整市场 CR3。
5. `insight_synthesis` 随后只使用有界一级指标和 `status=calculated` 的二级指标，生成绑定真实 `evidence_ids` 的“观察 → 解释 → 业务影响 → 动作”文字结论；不支持的店铺或维度直接省略，缺失原因只保留在运行元数据。
6. 分析完成后进入 `chart_render`，只读取编译结果中的有界 `chart_specs`，固定调用本机 Flint MCP 并缓存经校验的静态 SVG；单图失败时确定性降级。随后 `html_render` 节点才调用通用 `HTML 渲染 Agent`。renderer 只读取编译结果、脚本计算的二级指标、`insight_narrative` 与已编译图表，`toolResults` 必须为空。
7. HTML 写出后同时进入事实 `report_review` 与独立 `report_red_team`，由 `approval_join` 等待并汇合。任一分支首轮未通过时由 `html_revision` 返工并同时开始第二轮；第二轮仍未通过时再返工一次并直接进入 `synthesize_artifact`，不发起第三轮审批或红队。Planner 不调用 builder、data_analysis、insight_synthesis、chart_render、renderer、review、red-team、approval_join、revision 或 `synthesize_artifact`。renderer 失败时本轮必须停止并返回 `pending.reason_type=retryable_tool_failure` 的可恢复断点；用户继续后复用同一份成功编译数据和图表缓存，只重试 renderer，不得重跑 FastMoss、绕过整理器或改用固定模板。
8. `report_red_team` 不获得源数据工具，只依据当前 HTML、完整裁剪后的 ReviewReportData 与本 Skill 合同在当轮给出 approve/revise；证据不足时收窄、改写或移除当前结论，补数建议仅留给下一次任务，不触发本轮 Builder 或报告链重跑。

### Analysis Dimension Coverage

| ID | 任务 | 任务到工具映射 | 完成条件 | 允许结论与限制 |
| --- | --- | --- | --- | --- |
| CS01 | Bras L3 边界 | `search_category_by_words` | 唯一 L3 category_id 和路径 | L2 女士内衣不能代替 |
| CS02 | 50 家外部候选 | `shop_rank_top_selling` 分页 | 首选 US/L3/完整月；空榜后兼容 US/L2/完整周；GMV降序；50家或榜单耗尽 | L2 降级只能称女士内衣候选宇宙，不能称文胸 Top 榜 |
| CS03 | 10 家标准对象 | CS02 结果内按 seller_id 去重和排名 | 固定同一组 10 个 seller_id | 不因局部失败换店 |
| CS04 | 身份与基础快照 | `shop_base_info` | 同一组 seller_id 均已尝试 | 属于全店口径 |
| CS05 | 文胸商品结构 | `shop_product_analysis` | 同一组 seller_id 均已执行 seller-only page=1；有更多商品且文胸样本不足时最多补到 page=3；Builder 已按商品 `category.l3.id` 筛选并去重 | 类目与周期不传给列表请求；价格不硬过滤；观察样本集中度不能冒充全店集中度 |
| CS06 | 近期趋势 | `shop_data_trends` | 同一组 seller_id 均已尝试，完整日数据可核对 | 属于全店口径；不足14日不判方向 |
| CS07 | 渠道与达人 | `shop_sale_analysis` + `shop_creator_analysis` | 同一组 seller_id 均已尝试 | 属于全店口径；不从粉丝量推导带货力 |
| CS08 | 横向判断 | CS04–CS07 编译结果 | 重要结论可追溯且口径一致 | 不生成不透明综合分或无证据因果 |
| CS09 | 编译、渲染、发布 | 专用 builder + renderer + synthesize | 版本化数据成功，HTML成功写出 | renderer 不读取原始 MCP 结果 |

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| bra_category | mcp__fastmoss__search_category_by_words | always | 1 | block | call_missing_tool | 缺少 Bras/女士文胸 L3 category_id 时不得调用店铺榜或生成竞品结论 |
| competitor_shop_ranking | mcp__fastmoss__shop_rank_top_selling | always | 5 | block | continue_with_gap | 首选 US/Bras L3/完整月；仅首选空榜后允许 US/女士内衣 L2/完整周；不足50家时只报告实际范围 |
| shop_base_snapshots | mcp__fastmoss__shop_base_info | always | param:shop_analysis_count | block | continue_with_gap | 缺失店铺不得补写类型、评分或全店基础规模 |
| bra_product_structures | mcp__fastmoss__shop_product_analysis | always | param:shop_analysis_count | block | continue_with_gap | 每店至少一次 seller-only 商品页请求；Builder 未取得带明确目标 L3 id 的商品时省略该店文胸商品、价格带、爆品集中和新品结论 |
| shop_trends | mcp__fastmoss__shop_data_trends | always | param:shop_analysis_count | block | continue_with_gap | 缺失店铺不得判断近期加速、平稳或回落 |
| shop_channels | mcp__fastmoss__shop_sale_analysis | always | param:shop_analysis_count | block | continue_with_gap | 缺失店铺不得判断视频、直播、商品卡、达人或自营成交依赖 |
| shop_creators | mcp__fastmoss__shop_creator_analysis | always | param:shop_analysis_count | block | continue_with_gap | 缺失店铺不得判断达人结构或达人集中度 |
| fastmoss_links | mcp__fastmoss__fastmoss_detail_url_examples | always | 1 | warn | continue_with_gap | 店铺和商品优先链接 FastMoss；模板失败时披露链接不可用 |
| compiled_competitor_shop_report | build_tiktok_bra_competitor_shop_report_data | always | 1 | block | call_missing_tool | renderer 前必须生成 tiktok_bra_competitor_shop_report_data.v1 |
| final_html_report | render_html_report | always | 1 | block | call_missing_tool | 最终 Artifact 必须来自 renderer 成功写出的 HTML 报告文件 |

## Output Rules

- 第一屏先给真正规模威胁、增长最快店铺、共同打法、最大脆弱点和 Hsia 优先动作；不要放任务覆盖率、P0缺失、执行审计或大面积警告框。
- 固定顺序：执行摘要 → 50家竞争面概览 → 10家同口径比较 → 商品与价格策略 → 渠道与达人打法 → 逐店优势/弱点 → Hsia行动矩阵 → 简短来源与口径。
- 50家候选表只展示榜单实际字段，至少包含排名、店铺、seller_id、店铺类型、类目期GMV、类目期销量、GMV增长和达人数量；缺失值写“未知”。
- 10家主比较表必须用独立列展示店铺名称和 `seller_id`，并展示类目期规模、趋势、文胸商品样本、新品、价格带、主导渠道、达人样本及三类观察集中度。
- 每个店铺名称优先使用返回的 `fastmoss_url`；缺少时使用 FastMoss shop URL 模板和 seller_id 构造，不链接 TikTok 店铺页。
- 数据来源说明必须写清 FastMoss、region=US、Bras L3 category_id/path、实际候选榜 category_id/层级/周期、是否触发 L2 降级、排序、28天标准分析窗口、候选数、分析数和采集时间。
- 店铺榜可称文胸类目口径；`shop_product_analysis` 只有 Builder 根据商品行 `category.l3.id` 筛选后的结果可称文胸商品样本，原始店铺商品页和分布字段不得称为文胸口径；`shop_base_info`、`shop_sale_analysis`、`shop_data_trends` 和 `shop_creator_analysis` 默认只能称全店口径。
- 不过滤低于20 USD或高于100 USD的文胸商品；将其放入价格带，作为低价或高价竞争信号。
- 商品和达人 Top1/Top3 份额如果分母只是返回列表，必须使用“观察样本集中度”，不得称全店真实集中度。
- GMV是滞后结果；没有达人/视频增量和时间对齐证据时，不得把增长归因于达人、内容、直播、折扣或广告。
- 只基于本轮工具证据输出结论，不得编造店铺、GMV、销量、价格、商品、达人、渠道份额、广告、市场规模、人口画像或因果关系。
- 每项 Hsia 建议必须属于“可学习、需防守、可攻击、待验证”之一，并附对应店铺和证据字段；广告预算、品牌资产、独家供应链和既有达人关系不能直接当成可复制打法。
- 局部字段缺失时省略依赖该字段的比较或结论，表格必要单元格使用 `—`；不生成数据缺口、不可判断清单、失败调用流水或执行审计。核心店铺榜完全不可用时停止生成该报告，不用空报告解释失败。

### HTML Report Style Reference

使用竞品战情室风格的单栏自包含 HTML：浅灰背景、白色内容区、深灰正文、莓果色强调威胁、蓝色表示结构事实、橙色表示风险。首页使用紧凑结论条和 KPI，不使用大 Hero、右侧目录或侧边栏。50家竞争面用可横向滚动的紧凑表格，10家主比较突出可扫读性；逐店结论使用“优势 / 脆弱点 / Hsia so-what”三列。来源与口径缩小字号放在末尾。只使用内联 CSS 和静态内联 SVG，不使用 JavaScript 或外部样式依赖。

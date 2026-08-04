---
name: tiktok_us_lingerie_new_product_insight
description: Find recently listed TikTok Shop US bras priced from USD 20 through USD 100 with FastMoss, strictly exclude shapewear and other women's-underwear products, rank the qualifying bras by sales, and analyze the highest-selling launches with shop identity.
version: 0.4
owner: Hsia R&D Insight Agent
---

# TikTok Shop 美国女士文胸新品洞察 Skill

## What It Does

生成面向 Hsia 商品企划、设计和 TikTok Shop 运营团队的美国女士文胸新品洞察报告。直接使用 FastMoss “女士文胸 / Bras” L3 标准类目新品榜建立最近 30 天上架商品池，先剔除塑身衣、女士内裤、袜类和其他非文胸商品，再剔除价格缺失、低于 20 USD 或高于 100 USD 的商品；对最终合格文胸按累计销量排序，并对头部新品补充商品资料与 28 天销售趋势。新品销量表必须展示店铺名称和 `shop_id`；不以关键词、店铺榜或市场大盘作为默认入口。

本 Skill 回答三个问题：最近有哪些女士文胸新品、哪些文胸新品销量最高、这些头部文胸的明确产品特点与销售趋势是什么。它不默认回答整个女士内衣类目的市场规模、搜索需求、店铺集中度或爆款归因。

## When To Use

- 用户要查看 TikTok Shop 美国女士文胸最近上架的新品。
- 用户要按销量寻找文胸新品榜中的头部商品。
- 用户要比较几个畅销新品的上架表现、产品特点和近期销量趋势。
- 用户提到新品雷达、新品监控、近期上新、Top 新品或 FastMoss 新品榜。

## Required Inputs

| 字段 | 说明 |
| --- | --- |

## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| brand | Hsia | 报告使用方；不作为商品适配或入场结论的证据 |
| marketplace | US | 固定分析 TikTok Shop 美国市场，FastMoss region 使用 US |
| category | 女士文胸 | 默认解析 Bras 对应的 TikTok 商品 L3 类目 |
| time_range | 28d | 头部新品销售趋势观察窗口 |
| listing_sample_size | 20 | 按累计销量获取的新品候选池目标商品数 |
| head_listing_count | 5 | 从候选池中按累计销量选出的深挖商品数 |
| new_product_window | 30d | FastMoss 新品定义，上架不超过 30 天 |
| category_node_id |  | FastMoss TikTok 商品 L3 category_id；缺省时自动解析 |

## Missing Params

所有业务参数均有默认值，可直接执行，不要为了确认默认值而询问用户。用户明确提供参数时，以用户值为准，但 `marketplace` 仅支持 `US`；用户指定其他市场时，先调用 `ask_user` 请其改用相应市场工作流。

缺少 `category_node_id` 时，先用 `mcp__fastmoss__search_category_by_words` 查询 `women's bras`、`bras`、`女士文胸` 和用户原始类目词，只选择路径叶子明确为“女士文胸 / Bras”的 L3 节点，并把 `category_id_level3` 记录为 `category_node_id`。`Women's Underwear / 女士内衣` L2 只能用于理解父子关系，不能作为最终新品榜筛选器。不要使用 `product_search` 关键词召回代替标准新品榜。若出现多个不同的文胸 L3 候选且会实质改变商品范围，再调用 `ask_user`；否则记录选择依据后继续。

FastMoss MCP 缺失、未认证、不可达或额度不足时，不得编造商品或销量。空榜单只表示本轮数据未取回；先核对 `region=US`、category_id 和允许的上架日期，再以同一业务边界重试一次。仍为空时保留可恢复任务状态，不发布空洞的缺口报告。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill 和默认参数 |
| ask_user | system | 仅在用户指定非美国市场或类目候选存在实质歧义时询问 |
| respond_to_user | system | 回答非任务型问题或解释当前状态 |
| build_tiktok_new_product_report_data | required | 合并新品榜、详情和完整趋势，确定性完成去重、Top 选择、关联与 L7/P7 计算 |
| render_html_report | required | 只基于 TikTokNewProductReportData 生成最终 HTML，不直接消费原始 FastMoss 结果 |
| synthesize_artifact | system | LangGraph 最终节点；发布 renderer 成功写出的产物，不由 Planner 调用 |
| mcp__fastmoss__search_category_by_words | required | 将女士文胸自然语言解析为 TikTok 标准 L3 类目 ID |
| mcp__fastmoss__product_rank_new_listed | required | 获取最近 30 天上架商品，并按累计销量建立新品候选池 |
| mcp__fastmoss__product_detail_info | required | 补充头部新品的商品名称、价格、图片、店铺和可见产品资料 |
| mcp__fastmoss__product_sales_trend | required | 获取头部新品的 28 天日销量和 GMV 趋势 |
| mcp__fastmoss__fastmoss_detail_url_examples | required | 生成每个商品的 FastMoss 站内详情链接 |
| mcp__fastmoss__product_overview | conditional | 用户明确要求销售渠道、广告或自然成交结构时补充 |
| mcp__fastmoss__product_creator_analysis | conditional | 用户明确要求达人结构或新品爆发原因时补充 |
| mcp__fastmoss__product_video_list | conditional | 用户明确要求内容动量、视频结构或新品爆发原因时补充 |
| mcp__fastmoss__product_sku | conditional | 用户明确要求尺码、颜色、SKU 或变体分析时补充 |

## Recommended Tool Use

### 1. 先定义任务，再调用工具

按 `NP01–NP06` 执行。每次工具调用必须服务于一个任务及其完成条件；工具调用成功但市场、类目、日期、商品 ID 或样本数量不符时，任务仍未完成。默认不调用关键词搜索、市场大盘、店铺榜、达人榜或店铺详情。

### 2. NP01：解析女士文胸 L3 标准类目

1. 调用 `mcp__fastmoss__search_category_by_words`，query 至少包含 `women's bras`、`bras`、`女士文胸` 和当前 `category`。
2. 只选择名称或完整路径叶子明确指向“女士文胸 / Bras”的 L3 节点，并保留 `category_id_level3`、层级和完整路径。
3. 不得把 `Women's Underwear / 女士内衣` L2、Women's Clothing、Fashion 或其他宽泛父类目当成最终筛选器。无法取得文胸 L3 节点时停止，不回退到父类目生成混合榜单。

### 3. NP02：建立新品候选池

1. 以运行时间为基准，把 `listing_end_date` 设为四天前；FastMoss 不允许今天或最近 1–3 天作为上架截止日。
2. 把 `listing_start_date` 设为截止日前 29 天，形成 30 天新品窗口；始终使用 `region=US` 和 `filter.category_l3_id=<NP01 category_id_level3>`，不要传 `category_l2_id` 代替。
3. 调用 `mcp__fastmoss__product_rank_new_listed`，设置 `orderby=[{"field":"total_units_sold","order":"desc"}]`、`pagesize=10`，从 page=1 依次翻页。
4. 每页返回后先检查商品的 `category.l3.id` 和 `category.l3.name`：只保留目标 L3 ID 且名称为 Bras/文胸的商品，明确排除 Shapewear/塑身衣、Panties/女士内裤、Socks/Tights/袜类和其他非文胸 L3；不得只靠标题含 `bra` 判断。
5. 再检查 `current_price`：只保留 `20 <= current_price <= 100` 且币种为 USD 的商品。20 USD 和 100 USD 均保留；价格缺失、低于 20 USD 或高于 100 USD 的商品全部剔除。类目与价格筛选都必须发生在去重、样本计数和销量排序之前。
6. 合并合格结果并按 `product_id` 去重；`listing_sample_size` 指通过 L3 文胸和 20–100 USD 双重筛选的商品数，不是接口原始返回数。继续翻页直到合格文胸达到目标或榜单耗尽。候选池必须保留商品名、上架日期、售价、首 3 天销量/GMV、累计销量/GMV、`shop_name`、`shop_id` 和图片等实际返回字段；缺少的店铺字段在表格对应单元格显示 `—`，但不得省略对应列。
7. 榜单为空时，只核对 `region=US`、`category_l3_id`、日期和价格字段并重试一次；不得改用关键词搜索、女士内衣 L2 或放宽价格范围凑数，也不得写成“美国女士文胸没有新品”。

### 4. NP03：按销量选出头部新品

1. 只在 NP02 通过 L3 文胸和 20–100 USD 双重筛选的商品池内，以 FastMoss 返回的 `total_units_sold` 为唯一主排序，降序选择 `head_listing_count` 个不同 product_id。非文胸或价格越界商品即使销量更高，也不得进入 Top。
2. 累计 GMV 仅作并列参考，不得用 GMV 偷换销量。保留原始榜单名次。
3. 同时展示上架天数和首 3 天销量，提醒累计销量会受上架时长影响。可计算 `累计销量 / 上架天数` 作为日均动销，但必须标为派生指标，不能改写主榜名次。

### 5. NP04–NP05：补全商品特点与销售趋势

对 NP03 选出的同一组 product_id 逐个执行：

1. 调用 `mcp__fastmoss__product_detail_info` 补充名称、价格、图片、店铺、评分、物流和可见商品资料。只能从标题、类目和明确字段提取特点；无法确认的特点直接省略。
2. 调用 `mcp__fastmoss__product_sales_trend`，使用 `filter.product_id` 和 `filter.time_range_days=28`，读取 `period_summary` 与 `daily_trend`。
3. 从生成日前的完整日数据计算最近 7 天销量 `L7` 与此前 7 天销量 `P7`。`L7/P7 >= 1.2` 标为加速，`0.8–1.2` 标为平稳，`< 0.8` 标为回落；P7 为 0 而 L7 大于 0 时标为新启动，不计算无限增长率。少于 14 个完整日点时标为观察期不足。
4. 产品特点只使用有证据的标签：产品类型、功能、结构、面料/表面、尺码包容性、套装数量和价格策略。不得仅凭长标题补出未出现的材料、罩杯结构、塑形效果或目标人群。
5. 某个商品详情或趋势失败时，继续处理其他头部商品；只冻结该商品缺失维度，不重跑整个市场流程。

### 6. NP06：编译、渲染并发布

1. 源数据调用完成或耗尽恢复策略后，Planner 停止发出工具调用。LangGraph 的 `report_data_builder` 节点必须调用 `build_tiktok_new_product_report_data`。不要调用 `build_market_report_data`，也不要复用旧的 FM01–FM12 市场洞察编译器。
2. 编译器必须先按 NP01 的女士文胸 L3 ID 和 20–100 USD（含边界）价格范围对所有分页行做硬筛选，分别统计被排除的非文胸、低价、高价和缺价商品，再按 product_id 去重、按累计销量选出 Top 文胸、保留 `shop_name`/`shop_id`、关联同一组商品详情与完整趋势，并输出有界 `metric_facts`。若返回尚未尝试的 Top 文胸详情或趋势 ID，先完成对应调用，再重新调用编译器。
3. 只有 `build_tiktok_new_product_report_data` 成功返回 `tiktok_new_product_report_data.v1` 后，LangGraph 才进入 `data_analysis`。LLM 只选择固定新品指标和绑定 `fact_id`，脚本负责计算 L7/P7、平均成交单价、单视频/单达人产出等可用指标，并拒绝周期或分母错配。
4. `insight_synthesis` 随后只使用有界一级指标和 `status=calculated` 的二级指标，生成绑定真实 `evidence_ids` 的“观察 → 解释 → 业务影响 → 动作”文字结论；没有证据支持的维度直接省略，缺失原因只保留在运行元数据。
5. 分析完成后进入 `chart_render`，只读取编译结果中的有界 `chart_specs`，固定调用本机 Flint MCP 并缓存经校验的静态 SVG；单图失败时确定性降级。随后 `html_render` 节点才调用通用 `HTML 渲染 Agent`。renderer 只读取编译结果、脚本输出的二级指标、`insight_narrative` 与已编译图表，不直接读取或压缩原始 FastMoss tool results。
6. HTML 写出后同时进入事实 `report_review` 与独立 `report_red_team`，由 `approval_join` 等待并汇合。任一分支首轮未通过时由 `html_revision` 返工并同时开始第二轮；第二轮仍未通过时再返工一次并直接进入 `synthesize_artifact`，不发起第三轮审批或红队。Planner 不调用 builder、data_analysis、insight_synthesis、chart_render、renderer、review、red-team、approval_join、revision 或 `synthesize_artifact`。
7. `report_red_team` 不获得源数据工具，只依据当前 HTML、完整裁剪后的 ReviewReportData 与本 Skill 合同在当轮给出 approve/revise；证据不足时收窄、改写或移除当前结论，补数建议仅留给下一次任务，不触发本轮 Builder 或报告链重跑。

## Analysis Dimension Coverage

| ID | 任务 | 任务到工具映射 | 完成条件 | 允许结论与限制 |
| --- | --- | --- | --- | --- |
| NP01 | 女士文胸类目边界 | `search_category_by_words` | 取得叶子为女士文胸/Bras 的 L3 `category_id_level3` 和路径 | L2 女士内衣不能代替 L3 文胸，不推导市场规模 |
| NP02 | 30 天文胸新品候选池 | `product_rank_new_listed` 分页 + L3/价格硬筛选 | US、`category_l3_id`、完整 30 天允许窗口；非文胸、缺价、低于 20 USD、高于 100 USD 的商品在去重和计数前剔除，合格样本达到目标或榜单耗尽 | 只能称 FastMoss 20–100 USD 文胸新品榜样本；空结果是未取回数据 |
| NP03 | 销量 Top 文胸新品 | NP02 合格结果内按 `total_units_sold` 排序 | 选出不同文胸 product_id，保留原榜名次、上架日期、`shop_name` 和 `shop_id` | 累计销量受上架天数影响；GMV 不等于销量 |
| NP04 | 头部新品特点 | `product_detail_info` | 同一组 Top product_id 均已尝试，字段可追溯 | 不从未知字段或常识补写产品功能 |
| NP05 | 头部新品趋势 | `product_sales_trend` | 同一组 Top product_id 均已尝试，L7/P7 来自完整日数据 | 数据点不足时不输出确定趋势 |
| NP06 | 编译、渲染、审批与发布 | `build_tiktok_new_product_report_data` + 通用 HTML 报告链路 | 专用编译结果成功，HTML 经最多两轮审批和必要返工后发布 | 不生成旧式 P0 覆盖首页或市场大盘结论 |

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| new_product_category | mcp__fastmoss__search_category_by_words | always | 1 | block | call_missing_tool | 缺少女士文胸/Bras L3 category_id 时不得调用类目新品榜或生成商品结论 |
| new_product_ranking | mcp__fastmoss__product_rank_new_listed | always | 1 | block | continue_with_gap | 缺少使用 category_l3_id 且能验证 20–100 USD 价格的有效文胸新品榜时停止销量排名与 Top 商品结论；空结果不得表述为市场为零 |
| top_product_details | mcp__fastmoss__product_detail_info | always | param:head_listing_count | block | continue_with_gap | 未完成的商品只展示榜单已返回字段，不得补写产品特点 |
| top_product_trends | mcp__fastmoss__product_sales_trend | always | param:head_listing_count | block | continue_with_gap | 未完成的商品不得判断加速、平稳、回落或新启动 |
| product_fastmoss_links | mcp__fastmoss__fastmoss_detail_url_examples | always | 1 | warn | continue_with_gap | 商品名称应链接到 FastMoss 详情页；缺少模板时披露链接不可用 |
| compiled_new_product_report | build_tiktok_new_product_report_data | always | 1 | block | call_missing_tool | renderer 前必须生成 tiktok_new_product_report_data.v1，不得把原始 MCP 结果直接交给 renderer |
| creator_evidence | mcp__fastmoss__product_creator_analysis | prompt_mentions:达人,creator,爆发原因,为什么爆 | param:head_listing_count | warn | continue_with_gap | 不得在缺少达人证据时归因新品销量增长 |
| video_evidence | mcp__fastmoss__product_video_list | prompt_mentions:视频,内容,爆发原因,为什么爆 | param:head_listing_count | warn | continue_with_gap | 不得在缺少视频证据时判断内容动量或爆发原因 |
| final_html_report | render_html_report | always | 1 | block | call_missing_tool | 最终 Artifact 必须来自 renderer 成功写出的 HTML 报告文件 |

## Output Rules

- 报告第一屏先给“文胸新品扫描数、可分析 Top 数、销量最高文胸新品、主要产品特点、趋势判断”，不要把数据完整性、P0 覆盖率或未完成任务放在顶部。
- 固定顺序为：执行摘要 → 新品销量榜 → Top 新品逐品分析 → 共性特点与产品启示 → 简短来源与口径。
- 新品销量榜默认展示最多 `listing_sample_size` 个商品，强制使用独立列展示：排名、商品链接、店铺名称、`shop_id`、上架日期、价格、首 3 天销量、累计销量、累计 GMV 和上架天数。店铺名称和 `shop_id` 不得合并、隐藏或省略；源字段缺失时在对应单元格显示 `—`。
- Top 新品逐品分析固定包含：事实卡、明确产品特点、首 3 天表现、累计表现、L7/P7 趋势、趋势解释、替代解释和下一步验证动作。
- 每个商品名称优先使用返回的 `fastmoss_url`；没有时使用 `fastmoss_detail_url_examples` 的 product 模板和 product_id 生成 FastMoss 站内链接，不链接 TikTok PDP。
- 数据来源说明必须写清：FastMoss、region=US、女士文胸 L3 路径/category_l3_id、20–100 USD（含边界）价格范围、上架窗口、排序字段、采集时间，以及被硬筛掉的非文胸和价格不合格商品数。币种使用 FastMoss 返回的 USD 口径。
- 报告商品池、Top 榜和共性特点只能包含 L3 Bras/女士文胸；不得展示或分析 Shapewear/塑身衣及其他女士内衣子类。若编译器报告 `excluded_non_bra_count > 0`，只在方法附录简短披露筛选数量，不把被排除商品列为候选。
- 报告商品池和 Top 榜只能包含 `20 <= current_price <= 100` 的商品；不得把价格缺失、低于 20 USD 或高于 100 USD 的商品恢复为候选。价格排除数量只在方法附录简短披露。
- 只基于本轮工具证据输出结论，不得编造销量、GMV、上架日期、价格、属性、达人、视频或市场规模。
- 累计销量回答“目前卖得最多”，首 3 天销量和日均动销回答“启动效率”，L7/P7 回答“近期方向”；三者不得混为一个综合分。
- 本 Skill 不以新品销量直接推导“值得跟卖”或“Hsia 应进入”。缺少成本、退货、供应链和内容证据时，只能给产品观察与验证建议。
- 局部字段缺失时省略依赖该字段的特点或结论，表格必要单元格使用 `—`；不生成数据缺口、执行审计、证据矩阵、不可判断清单或失败调用流水。核心新品榜完全不可用时停止生成该报告，不用空报告解释失败。

### HTML Report Style Reference

使用清爽的商品企划周报风格：浅色背景、深灰正文、酒红或莓果色作为强调色。第一屏用一行紧凑 KPI 和一句结论，不放大面积警告框。新品榜使用易扫读表格；Top 商品使用五张并列或分栏卡片，优先展示证据中已有的商品图。来源与口径缩小字号放在末尾。移动端允许横向滚动表格，禁止脚本和外部样式依赖。

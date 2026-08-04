---
name: hot_product_pain_analysis
description: Analyze user-specified top Amazon breakout products using only SellerSprite and Sif evidence, summarize reviews, attach product images when available, and extract review-backed pain points and R&D opportunities.
---

# 爆款痛点分析 Skill

## What It Does

仅使用 SellerSprite 和 Sif 工具抓取用户指定 Amazon 品类的头部爆款商品，对每个商品汇总商品图、价格、评分、评论量、卖点和评论样本，提炼高频痛点、用户喜欢点、证据强弱和 Hsia 可行动的研发机会。

这个 Skill 的目标不是做全量市场规模估算，而是把“前几名爆款为什么被买、哪里被骂、哪些结构/尺码/材料机会值得研发跟进”整理成可复核的竞品痛点报告。

## When To Use

- 用户要分析某个 Amazon 品类前几名爆款商品的用户痛点。
- 用户要求“爆款痛点分析”“评论痛点分析”“差评汇总”“每个商品评论总结”。
- 用户要求商品必须带图，或希望贴上评论图片。
- 用户输入类似“抓 Amazon US minimizer bra 前 10 名爆款，逐个汇总评论并分析痛点”。
- 用户输入类似“帮我看这个品类头部商品哪里被用户吐槽，输出 Hsia 的产品改进机会”。

## Required Inputs

| 字段 | 说明 |
| --- | --- |
| marketplace | 电商市场，例如 Amazon US / 美国站(com) |
| category | 研究品类或关键词，例如 minimizer bra |
| head_listing_count | 用户手动指定要分析的头部商品数量 |

## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| brand | Hsia / 遐 | 输出研发机会时默认面向的自有品牌 |
| listing_sample_size | 20 | 头部候选池下限；运行时至少取 `head_listing_count + 5` 个候选，供类目错配和评论空结果时顺延替换 |
| category_node_id |  | SellerSprite 节点级工具需要的 nodeIdPath；缺省时先自动解析，不要求用户手动提供 |
| review_sample_size | 30 | 每个最终商品的近期评论目标样本数；运行时按 1-3 星与 4-5 星分层抓取 |
| time_range | 180d | 默认只分析近 180 天评论；用户明确指定其他窗口时按用户要求 |

## Missing Params

如果缺少 `marketplace`、`category` 或 `head_listing_count`，先调用 `ask_user` 反问，不要执行数据工具。

如果用户说“前几名”但没有给数量，必须询问具体数量；不要自行假设为 Top 10。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill |
| ask_user | system | 缺参时询问用户 |
| respond_to_user | system | 回答非任务型问题或解释当前状态 |
| build_hot_product_pain_report_data | required | 将类目候选、评论、销量代理与关键词竞争证据编译为版本化、有界的 HotProductPainReportData |
| render_html_report | required | 用 LLM 只基于 HotProductPainReportData 与展示指令写最终 HTML 爆款痛点报告 |
| synthesize_artifact | system | LangGraph 最终节点；发布已渲染的爆款痛点分析产物，不由 Planner 调用 |
| sellersprite_product_node | required | 自动解析并校验目标类目的 SellerSprite nodeIdPath，防止关键词跨类目命中 |
| sellersprite_market_product_concentration | required | 在已校验节点内获取带缓冲的头部候选池、主图和排名证据 |
| sellersprite_review | required | 对每个最终入选 ASIN 获取近 180 天高低星平衡评论、评论图片和痛点证据 |
| sif_ops_get_asin_sales_list | required | 一次性校验最终 ASIN 列表的近 30 天销量代理，不只依赖 SellerSprite 估算 |
| sif_market_get_keyword_competition | required | 校验目标关键词下的 Top ASIN、流量份额和竞争相关性 |
| sellersprite_asin_detail | conditional | 标题/类目归属有歧义或评论为空时核验父体、变体和完整类目路径；评论适配器会自动完成必要的变体家族回退 |
| sellersprite_market_research | conditional | 仅在 product_node 无法解析或需要补充类目基线时使用，不作为正常头部商品来源 |
| sellersprite_product_research | conditional | 仅在节点级候选不足时补充商品候选；必须进行标题和类目路径相关性过滤 |
| sellersprite_competitor_lookup | conditional | 仅在节点级候选不足且已有明确 ASIN/品牌条件时补充，不得与关键词、品牌、ASIN 多条件盲目交叉过滤 |
| sellersprite_keyword_research | conditional | 需要关键词需求、搜索热度或关键词扩展时获取 SellerSprite 关键词证据 |
| sif_ops_get_asin_sales_trend | conditional | 用户要求销量趋势、季节性或近期销售变化时补充 Sif ASIN 趋势证据 |
| sif_market_get_asin_keyword_signals | conditional | 用户要求 ASIN 关键词流量、自然/广告信号时补充 Sif ASIN 关键词证据 |
| amazon_shelf | disallowed | 当前 Skill 仅使用 SellerSprite 和 Sif，不调用 Amazon shelf |
| reddit_voc | disallowed | 当前 Skill 仅使用 SellerSprite 和 Sif，不调用 Reddit |
| tiktok_social | disallowed | 当前 Skill 仅使用 SellerSprite 和 Sif，不调用 TikTok |
| media_rankings | disallowed | 当前 Skill 仅使用 SellerSprite 和 Sif，不调用媒体/网页抓取 |

## Recommended Tool Use

1. 先检查 Required Inputs。缺少 `marketplace`、`category` 或 `head_listing_count` 时，调用 `ask_user`。
2. 必须先调用 `sellersprite_product_node`。只有唯一高置信候选的末级 `nodeLabelPath` 与用户品类一致时才能继续；有歧义时用更短的 Amazon 正式类目词重试，不能直接采用第一条。
3. 调用 `sellersprite_market_product_concentration`。运行时会把 `topN` 扩大为带缓冲候选池，并在 `data.product_selection` 中按标题辨识词筛选相关商品。后续只能使用 `eligible_candidates`；`excluded` 中的商品即使 SellerSprite 给出排名也不得进入报告或评论调用。
4. 按 `product_selection` 排名顺序，对每个相关候选只调用一次 `sellersprite_review`，直到获得 `head_listing_count` 个不同 ASIN 的成功评论结果。不要自行传 `starList/typeList` 拆成多次调用，也不要重复调用已成功 ASIN；review 适配器默认：
   - 用 `startTimestamp/endTimestamp` 限定 `time_range`，默认近 180 天。
   - 将样本拆为 1-3 星和 4-5 星两组后合并，防止只看到好评或只看到差评。
   - 子 ASIN 返回 0 条时自动核验 parent/variation，并最多尝试受控的同家族评论 ASIN；成功时必须标注 `review_sampling.scope=variation_family`。
5. 某个相关候选及其变体家族仍无评论时，不把它算作已完成商品，按候选排名顺延到下一条；如果最终不足 `head_listing_count` 个评论成功商品，停止在 HTML renderer 之前。
6. 评论覆盖完成后，必须调用一次 `sif_ops_get_asin_sales_list`，传入最终评论成功的全部 ASIN；运行时默认使用近 30 天、按 ASIN 维度。随后调用 `sif_market_get_keyword_competition` 校验关键词竞争和 Top ASIN 相关性。Sif 返回空或失败时不得生成报告。
7. 不要在节点级候选成功后继续调用 `sellersprite_market_research`、`sellersprite_product_research` 或 `sellersprite_competitor_lookup`。这些只用于主链路失败后的候选补充，避免把皮肤精华、普通文胸或其他同词商品混入。
8. 将最终主分析对象严格限制在用户指定的 `head_listing_count` 个“类目相关且评论成功”的头部商品；不要把被排除商品或评论空商品写成完整痛点卡。
9. 对每个最终商品提取：
   - 商品主图字段，例如 `image_url`、`image`、`mainImage`、`top10Images`、`smallImage`。
   - 标题、品牌、ASIN、商品链接、价格、评分、评论量、上架/排名/类目字段。
   - 评论样本数量、星级分布线索、评论日期线索、评论文本痛点、典型原话、正向喜欢点。
   - 评论样本中如有 `media_urls`、`image_urls`、`images`、`review_media_urls`、`videos` 等字段，保留为评论图片/视频证据。
10. 不调用 `amazon_shelf`、`reddit_voc`、`tiktok_social`、`media_rankings` 或任何非 SellerSprite/Sif 工具。
11. 所有 block 级源证据成功后，Planner 停止发出工具调用，表示源数据阶段完成。LangGraph 自动执行 `report_data_builder`，用 `build_hot_product_pain_report_data` 生成含有界 `metric_facts` 与 `chart_specs` 的 HotProductPainReportData，再执行通用 `data_analysis -> insight_synthesis -> chart_render -> html_render ->（report_review 与 report_red_team 并行）-> approval_join -> 必要时 html_revision -> synthesize_artifact` 链路；`data_analysis` 中 LLM 只选择固定指标和绑定事实，脚本校验并计算；`insight_synthesis` 只把有证据的一级/二级指标写成“观察 → 解释 → 产品影响 → 研发动作”，并绑定真实 `evidence_ids`；`chart_render` 固定调用本机 Flint MCP，单图失败时确定性降级。`html_render` 以 `insight_narrative` 为正文分析主轴。Planner 不调用这些报告节点（包括 insight_synthesis、report_review、report_red_team 与 approval_join），也不得把原始 SellerSprite/Sif 工具结果直接交给图表或 HTML renderer。
12. 每份 HTML 的事实 `report_review` 与独立 `report_red_team` 同时执行，由 `approval_join` 汇合；最多并行审批两轮。任一分支首轮未通过时返工并同时开始第二轮，第二轮仍未通过时再返工一次并直接发布，不发起第三轮审批或红队。HTML 生成失败或校验失败时停止并暴露错误，不得继续生成固定脚本模板报告。
13. `report_red_team` 不获得源数据工具，只依据当前 HTML、完整裁剪后的 ReviewReportData 与本 Skill 合同在当轮给出 approve/revise；证据不足时收窄、改写或移除当前结论，补数建议仅留给下一次任务，不触发本轮 Builder 或报告链重跑。

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| sellersprite_category_node | sellersprite_product_node | always | 1 | block | call_missing_tool | 未完成唯一高置信类目节点校验时，不得选择头部商品 |
| sellersprite_candidate_pool | sellersprite_market_product_concentration | always | 1 | block | call_missing_tool | 缺少节点级候选池和相关性筛选时，不得生成爆款商品列表 |
| sellersprite_review_samples | sellersprite_review | always | param:head_listing_count | block | call_missing_tool | 必须取得与用户指定商品数相同的不同相关 ASIN 评论结果；不足时顺延候选或停止，不得带缺口生成报告 |
| sif_sales_proxy | sif_ops_get_asin_sales_list | always | 1 | block | call_missing_tool | 缺少 Sif 对最终 ASIN 列表的近 30 天销量代理校验时，不得生成爆款强度结论 |
| sif_keyword_competition | sif_market_get_keyword_competition | always | 1 | block | call_missing_tool | 缺少 Sif 关键词竞争与 Top ASIN 校验时，不得生成流量份额或竞争强度结论 |
| hot_product_pain_report_data | build_hot_product_pain_report_data | always | 1 | block | call_missing_tool | 最终 HTML 前必须先把源证据编译为 HotProductPainReportData，禁止原始 MCP 结果直送 renderer |
| final_html_report | render_html_report | always | 1 | block | call_missing_tool | 最终产物必须来自 LLM 只基于 HotProductPainReportData 写出的 HTML 报告，不得使用固定模板兜底 |
| sellersprite_product_images | sellersprite_market_product_concentration | always | 1 | warn | continue_with_gap | 最终报告必须展示候选池返回的可用商品主图；缺少图片字段的商品必须标注图片缺失，不得伪造替代图片 |
| sif_sales_trend | sif_ops_get_asin_sales_trend | prompt_mentions:销量趋势,季节性,近期销售,销售变化 | 1 | warn | continue_with_gap | 如果 Sif 销售趋势缺失，报告不得判断近期销量上升或下降 |
| sif_asin_keyword_signals | sif_market_get_asin_keyword_signals | prompt_mentions:ASIN关键词,关键词流量,自然流量,广告流量 | 1 | warn | continue_with_gap | 如果 Sif ASIN 关键词证据缺失，报告不得声称已验证 ASIN 关键词流量 |

## Output Rules

- 最终产物必须包含“逐商品爆款痛点卡”，每个商品一张卡。
- 最终 HTML 必须由 `render_html_report` 的 LLM 基于 `hot_product_pain_report_data.v1` 组织文案、结构和样式；不得接收原始 MCP/tool results，也不得使用固定 Python 模板、hot-product 专用 renderer 或旧通用 fallback。
- 商品卡只使用证据中的商品主图；`image_url` 缺失时省略图片容器，不使用无来源图片，也不生成图片缺失说明。
- 每张商品卡必须显示评论实际时间窗口、低星/高星样本数以及评论作用域；使用同一变体家族评论时必须明确写“变体家族评论”，不能伪装为当前子 ASIN 原评。
- 如果评论样本带图片或媒体 URL，在对应商品卡中贴出评论图片链接或缩略图；没有评论图片字段时直接省略媒体模块。
- 每个痛点必须附至少一条评论证据；没有证据的痛点直接省略，不要只给抽象标签。
- 横向痛点矩阵至少覆盖：尺码/版型、支撑、舒适度、材质/做工、耐穿/清洗、外观/颜色、物流/包装、价格感知。
- 区分“用户喜欢点”和“用户痛点”，不要只看差评。
- review count 只能作为公开热度代理，不能当成真实销量。
- SellerSprite `totalUnits/totalRevenue` 和 Sif 近 30 天购买量都属于第三方代理口径，不得用于精确财务预测；两者冲突时并列展示口径，不得择一伪装成真值。
- 报告只能包含 `product_selection.eligible_candidates` 中且 SellerSprite review 成功的前 `head_listing_count` 个不同 ASIN；类目错配、重复 ASIN和评论空结果不能占位。
- 当前 Skill 只能引用 SellerSprite 和 Sif 工具证据；不得引入 Amazon shelf、Reddit、TikTok、媒体文章或网页搜索证据。
- 不得编造销量、搜索量、人口画像、市场规模、评论原文、商品图片或评论图片。
- Evidence Contract 的 warn 级缺口只冻结依赖它的结论并保留在内部运行元数据，不进入最终 HTML。
- 输出 Hsia 机会时必须包含：机会名称、对应痛点、证据商品/评论、建议研发动作、优先级、验证动作。

### HTML Report Style Reference

爆款痛点报告要像商品企划会材料，而不是工具日志或数据表。

- 首屏先回答：这个品类头部爆款共同靠什么被买、最大差评痛点是什么、Hsia 最值得验证的 1-2 个研发机会是什么。
- 不生成右侧目录、侧边栏、TOC 或锚点导航；页面采用单栏主内容布局，桌面端和移动端都以正文阅读为主。页面保持白底、轻边框、清晰留白，少用厚重卡片。
- 逐商品卡片必须优先展示 ASIN、品牌、商品图、价格/评分/评论量、样本数量、3-5 条评论证据、评论媒体链接/缩略图和该商品的研发启发。
- 横向痛点矩阵必须按痛点维度组织，不按工具调用组织。至少覆盖：尺码/版型、支撑、舒适度、材质/做工、耐穿/清洗、外观/颜色、物流/包装、价格感知。
- 每个重要判断后给出证据锚点：工具名、ASIN、评论星级/标题/摘要或字段名。没有证据的判断直接省略，不要补故事或生成待验证/缺口段落。
- 把“用户喜欢点”和“用户痛点”分开；机会建议要写成研发动作，例如结构、材料、尺码、工艺、包装、Listing claim 或验证实验。
- 不展示工具调用成功率、原始 JSON、调试表、执行按钮或中间文件链接；这些只属于执行时间线。

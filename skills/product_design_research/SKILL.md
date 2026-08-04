---
name: product_design_research
description: Research a US product-development topic across Amazon demand, products, reviews, TikTok, and public brand sites, then produce an evidence-linked Markdown R&D brief for Hsia designers.
version: 0.1
owner: Hsia R&D Insight Agent
---

# 产品研发调研

## What It Does

围绕设计师提出的品类课题，先校验消费者需求词和 Amazon 市场边界，再研究头部商品、评论、TikTok 内容和公开品牌站，最终生成可追溯到关键词、ASIN、评论、视频或网页的 Markdown 产品研发任务书。

## When To Use

- 用户希望从品类调研进入产品设计方向，例如“调研美国 strapless bra 并给出研发任务书”。
- 用户希望把 Amazon 评论痛点、达人卖点和独立站产品结构转化为设计要求。
- 用户要求输出产品侧的结构、面料、颜色、尺码、价格和验证建议，而不是电商运营方案。

## Required Inputs

| 字段 | 说明 |
| --- | --- |
| category | 研究品类、功能或用户任务，例如 strapless bra、显小但不压胸 |
| design_goal | 本轮希望解决的研发问题或目标，例如“开发稳定不下滑且适合大胸的日常抹胸文胸” |

## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| brand | Hsia / 遐 | 研发建议面向的自有品牌 |
| marketplace | Amazon US | 目标市场和 Amazon 站点 |
| time_range | 180d | 评论和近期信号观察窗口 |
| listing_sample_size | 100 | SellerSprite 头部候选池目标规模 |
| head_listing_count | 10 | 目标深度分析商品数 |
| review_sample_size | 60 | 每个商品的评论采集目标，运行时平衡高低星 |
| tiktok_video_limit | 12 | TikTok 视频采集目标 |
| tiktok_comments_per_video | 20 | 每条视频的留言采集目标 |
| article_query_limit | 6 | 独立站和公开趋势网页搜索词数量 |
| article_results_per_query | 5 | 每个网页搜索词的候选结果数 |
| article_candidate_limit | 12 | 最终读取的公开网页候选上限 |
| target_user | 由研究识别 | 用户未指定时不预设人口画像，只从证据归纳使用任务和适配边界 |
| brand_site_urls |  | 用户提供的公开品牌站、商品页或 Best Sellers 页面，优先于自动发现结果 |
| trend_context |  | 用户提供的 WGSN、蝶讯等趋势摘要；只能标为人工输入、未经工具验证 |
| category_node_id |  | SellerSprite 正式类目节点；缺省时自动解析 |

## Missing Params

缺少 `category` 或 `design_goal` 时先调用 `ask_user`，不要执行数据工具。不要因为缺少 `category_node_id`、`target_user`、趋势材料或品牌站 URL 而中断；这些按工具解析或数据缺口处理。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill 和规范化参数 |
| ask_user | system | 缺少品类或研发目标时询问用户 |
| respond_to_user | system | 解释能力、状态或无法继续的原因 |
| synthesize_artifact | system | LangGraph 最终节点；发布已渲染的 Markdown 研发任务书，不由 Planner 调用 |
| sif_market_get_keyword_root_trend | required | 发现词根、场景词和相邻需求入口，避免把单一关键词当成完整市场 |
| sif_market_get_keyword_demand | required | 至少验证两个不同关键词入口的需求信号 |
| sif_market_get_keyword_history | required | 获取关键词历史、ABA 或近期变化证据 |
| sif_market_get_keyword_competition | required | 至少验证两个入口下的 Top ASIN 和竞争相关性 |
| sellersprite_product_node | required | 自动解析并校验 Amazon 正式末级类目节点 |
| sellersprite_market_research | required | 获取市场基线和相关商品证据 |
| sellersprite_aba_research_weekly | required | 获取近期消费者真实搜索词和增长词 |
| sellersprite_market_product_concentration | required | 在已校验节点内建立、过滤和去重头部候选池 |
| sellersprite_review | required | 为不同候选 ASIN 获取近 180 天平衡评论样本 |
| sellersprite_asin_detail | conditional | 节点有歧义或需要核验父子体、变体和产品属性时补充 |
| sellersprite_market_product_demand_trend | allowed | 有节点时补充需求趋势、退货率和商品总数 |
| sellersprite_market_brand_concentration | allowed | 补充品牌集中度 |
| sellersprite_market_price_distribution | allowed | 补充价格区间和销量占比 |
| sellersprite_market_ratings_count_distribution | allowed | 补充评论门槛和进入难度 |
| sellersprite_market_listing_date_distribution | allowed | 补充新品和老品结构 |
| sif_ops_get_asin_sales_list | conditional | 需要排序商品热度时补充销量代理，不得称为后台真实销量 |
| sif_ops_get_asin_sales_trend | conditional | 用户明确要求季节性或销量趋势时补充代理证据 |
| sif_market_get_asin_keyword_signals | conditional | 需要解释单品承接哪些需求词时补充 |
| tiktok_social | required | 获取达人卖点表达、使用场景、结构演示和消费者留言 |
| media_rankings | required | 发现并读取公开品牌站、商品页、Best Sellers 和公开趋势页面 |
| reddit_voc | conditional | 用户明确要求 Reddit 或社区 VOC 时补充，不作为默认主链路 |
| amazon_shelf | disallowed | Amazon 主证据统一使用 SellerSprite 和 Sif，避免重复口径和去重冲突 |
| build_product_design_brief_data | required | 将多来源工具结果编译为稳定的 ProductDesignBriefData |
| render_markdown_report | required | 只使用编译后证据生成最终 Markdown 报告 |
| render_html_report | disallowed | 本 Skill 固定输出 Markdown，不生成 HTML |

## Recommended Tool Use

1. 先确认 `category` 和 `design_goal`。将 `category` 视为研究起点，不视为已经成立的市场分类。
2. 先调用 `sif_market_get_keyword_root_trend` 和 `sellersprite_aba_research_weekly`，把词拆成品类词、用户问题词、功能/场景词和相邻词。只采用工具返回或用户明确给出的扩展词，不凭空编造搜索量。
3. 对原始词和至少一个证据支持的扩展入口分别调用 `sif_market_get_keyword_demand` 与 `sif_market_get_keyword_competition`。调用 `sif_market_get_keyword_history` 判断时间变化。两个入口的工具输入必须不同。
4. 调用 `sellersprite_product_node` 解析正式末级类目。宽泛父节点、名称不匹配或多候选时，用更精确的正式类目词重试；仍有歧义时用 Top ASIN 的 `sellersprite_asin_detail` 交叉验证。
5. 调用 `sellersprite_market_research` 和 `sellersprite_market_product_concentration`。只使用 `product_selection.eligible_candidates`；按 ASIN、可用 parent ASIN 和变体家族去重，类目错配商品必须进入 excluded。
6. 按排名顺序为不同候选调用一次 `sellersprite_review`，目标 10 个商品，至少取得 5 个不同商品的有效样本。不得重复调用已成功 ASIN；评论为空时允许适配器在同一变体家族内受控回退。
7. 评论分析按评分重新分层：1-2 星是失败机制和痛点，3 星是权衡、适配边界和“有用但不够好”，4-5 星是购买理由和已经验证的产品解法。不得把评论总量当成本轮分析样本数。
8. 调用 `tiktok_social`，提取达人如何演示结构、如何表达卖点、具体穿着场景和留言中的正负反馈。播放量、点赞和留言只能作为内容信号，不能解释成商品销量。
9. 调用 `media_rankings`。如果有 `brand_site_urls`，优先读取这些公开页面，再合并自动发现结果。提取产品定位、结构、面料、尺码、颜色、卖点和 Best Seller 信号；动态评论取不到时记录缺口。
10. 公开网页不能访问付费 WGSN/蝶讯正文时不要绕过权限。`trend_context` 只能作为“设计师提供的趋势背景”，不能独立支持产品结论。Pinterest 只输出建议搜索词，不声称完成图片采集或情绪板。
11. 数据工具完成后调用 `build_product_design_brief_data`。编译结果必须展示计划采集、实际采集和进入 LLM 的商品、评论、视频、留言和网页数量。
12. 编译成功后调用 `render_markdown_report`，不得把原始 tool results 再次传给 renderer。Markdown 成功写出后，Planner 停止发出工具调用，由 LangGraph 的 `synthesize_artifact` 终态节点发布 `.md` 文件。

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| keyword_roots | sif_market_get_keyword_root_trend | always | 1 | block | call_missing_tool | 缺少词根证据时不得声称已经界定消费者需求市场 |
| keyword_demand_boundary | sif_market_get_keyword_demand | always | 2 | block | call_missing_tool | 必须完成至少两个不同关键词入口的需求验证 |
| keyword_history | sif_market_get_keyword_history | always | 1 | block | call_missing_tool | 缺少历史数据时不得判断近期需求变化 |
| keyword_competition_boundary | sif_market_get_keyword_competition | always | 2 | block | call_missing_tool | 必须完成至少两个不同关键词入口的竞争和 Top ASIN 验证 |
| amazon_search_terms | sellersprite_aba_research_weekly | always | 1 | block | call_missing_tool | 缺少 Amazon 近期真实搜索词时不得完成市场边界判断 |
| category_node | sellersprite_product_node | always | 1 | block | call_missing_tool | 未完成正式类目节点校验时不得选择头部商品 |
| market_baseline | sellersprite_market_research | always | 1 | block | call_missing_tool | 缺少 Amazon 市场基线时不得生成研发任务书 |
| candidate_pool | sellersprite_market_product_concentration | always | 1 | block | call_missing_tool | 缺少节点内候选池、相关性过滤和去重时不得选择研究商品 |
| review_minimum | sellersprite_review | always | 5 | block | call_missing_tool | 少于 5 个不同有效商品的评论样本时不得生成研发任务书 |
| review_target | sellersprite_review | always | param:head_listing_count | warn | continue_with_gap | 不足目标商品数时必须展示实际覆盖并降低结论置信度 |
| tiktok_content | tiktok_social | always | 1 | warn | continue_with_gap | TikTok 失败时必须说明未完成达人表达和视频留言验证 |
| public_web | media_rankings | always | 1 | warn | continue_with_gap | 公开网页失败时必须说明独立站和公开趋势证据不足 |
| compiled_brief | build_product_design_brief_data | always | 1 | block | call_missing_tool | 必须先把原始工具结果编译为 ProductDesignBriefData |
| markdown_report | render_markdown_report | always | 1 | block | call_missing_tool | 最终 Artifact 必须来自 Markdown renderer |

## Output Rules

- 最终产物只能是 Markdown，固定包含以下 13 个二级标题：研发课题与研究范围；一句话研发方向；市场边界与消费者真实搜索词；趋势信号及其可信度；Amazon 头部商品与价格/结构分布；好评、差评和 3 星权衡点；TikTok 卖点表达与消费者反馈；品牌独立站对标；痛点→原因→产品解法矩阵；必须解决、值得探索、不建议照搬；结构、面料、颜色、尺码和价格建议；概念方向文字简报；验证动作、证据链和数据缺口。
- 每条研发方向、产品解法和设计建议必须带邻近证据 ID，例如 `[K03]`、`[P02]`、`[R08]`、`[T01]` 或 `[W03]`；证据链必须解释 ID 对应的关键词、ASIN、评论、视频或网页。
- 报告必须展示计划采集、实际采集、进入 LLM 分析三个口径，不能把评论总量、页面评论数或商品 review count 写成实际分析样本数。
- 只基于工具证据输出事实。用户提供的 `trend_context` 必须标记为“人工输入、未经工具验证”，且不能单独支持研发建议。
- 不得编造销量、搜索量、市场容量、人口画像、材料性能、结构效果、WGSN/蝶讯趋势、TikTok Shop 买家评价或 Pinterest 图片研究。
- 销量、播放量、评论量、BSR、徽章和媒体榜单均为方向性信号；报告必须说明其局限。
- 研发建议优先回答产品机制和验证动作，不输出 Listing SEO、广告投放、达人佣金、库存或店铺运营方案。
- 缺少动态独立站评价、TikTok Shop 买家评价、付费趋势报告、视觉灵感图或最终版型数据时，必须列入数据缺口。

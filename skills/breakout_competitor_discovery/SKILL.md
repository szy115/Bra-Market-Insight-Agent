---
name: breakout_competitor_discovery
description: Discover breakout competitor products from Amazon shelf evidence and optionally validate their social signal on TikTok.
version: 0.1
owner: Hsia R&D Insight Agent
---

# 爆款竞品发现 Skill

## What It Does

从 Amazon 货架信号发现值得拆解的爆款竞品，并用 TikTok 做社媒交叉验证。

这个 Skill 的目标不是找到所有竞品，而是找出“真正值得拆解”的外部爆款候选，并解释证据强弱、风险和下一步拆解动作。

## When To Use

- 用户想找竞品
- 用户想找爆款商品
- 用户想筛选值得拆解的产品
- 用户要求 TikTok 交叉验证
- 用户输入类似“帮我发现美国 Amazon 上真正值得拆解的 minimizer bra 爆款竞品”

## Required Inputs

| 字段 | 说明 |
| --- | --- |
| brand | 自有品牌，用于过滤和基准识别 |
| marketplace | 电商市场 |
| category | 研究品类 |

## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| exclude_own_brand | true | 是否过滤自有品牌 |
| listing_sample_size | 30 | Amazon 商品样本数 |
| tiktok_video_limit | 6 | TikTok 视频样本数 |

## Missing Params

如果缺少必填参数，先向用户反问，不要直接执行后续工具步骤。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill |
| ask_user | system | 缺参时询问用户 |
| respond_to_user | system | 回答非任务型问题或解释当前状态 |
| synthesize_artifact | system | 生成最终爆款竞品发现产物 |
| amazon_shelf | required | 获取 Amazon 商品、价格、评分、评论量、品牌和卖点证据 |
| tiktok_social | conditional | 用户要求爆款强度、社媒热度或交叉验证时获取 TikTok 视频和评论样本 |
| reddit_voc | allowed | 需要补充社区讨论、场景语言或品牌口碑时使用 |
| media_rankings | allowed | 需要补充公开榜单或媒体测评证据时使用 |
| sif_market_get_keyword_competition | conditional | 用户要求关键词竞争、Top ASIN 或流量份额时补充 Sif 竞争格局证据 |
| sif_market_get_asin_keyword_signals | conditional | 用户要求分析某 ASIN 关键词流量信号时补充 Sif ASIN 关键词证据 |
| sif_ops_get_asin_sales_list | conditional | 用户提供 ASIN 并要求销量代理、价格或变体销售数据时补充 Sif ASIN 销售列表证据 |
| sif_ops_get_asin_sales_trend | conditional | 用户提供 ASIN 并要求销量趋势或季节性时补充 Sif ASIN 销售趋势证据 |

## Recommended Tool Use

- 先检查 Required Inputs 是否完整；如果缺少必填参数，调用 `ask_user` 反问，不要执行数据工具。
- 优先调用 `amazon_shelf` 获取 Amazon 商品、价格、评分、评论量、品牌和卖点证据。
- 如果用户要求爆款强度、社媒热度或交叉验证，调用 `tiktok_social` 获取视频和详情页评论样本。
- 如用户只要求初筛，可先基于 Amazon 证据输出候选，并明确 TikTok 验证缺口。
- 证据足够后调用 `synthesize_artifact`，输出候选优先级、风险、不可照搬点和下一步拆解动作。

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| amazon_competitor_shelf | amazon_shelf | always | 1 | block | call_missing_tool | 缺少 Amazon 货架证据时，不得生成爆款竞品候选或优先级判断 |
| tiktok_cross_validation | tiktok_social | prompt_mentions:TikTok,社媒,交叉验证,热度,爆款强度 | 1 | warn | continue_with_gap | 如果 TikTok 证据缺失，候选必须标注为 Amazon-only 信号，不得声称已完成社媒验证 |
| reddit_brand_discussion | reddit_voc | prompt_mentions:Reddit,社区,口碑,用户讨论 | 1 | warn | continue_with_gap | 如果 Reddit 证据缺失，报告必须说明未验证社区口碑 |
| media_external_validation | media_rankings | prompt_mentions:媒体,榜单,测评,文章 | 1 | warn | continue_with_gap | 如果媒体或榜单证据缺失，报告必须说明未完成公开测评交叉验证 |
| sif_keyword_competition | sif_market_get_keyword_competition | prompt_mentions:竞争格局,Top ASIN,流量份额,关键词竞争 | 1 | warn | continue_with_gap | 如果 Sif 关键词竞争证据缺失，候选不得声称已验证关键词流量份额 |
| sif_asin_keyword_signals | sif_market_get_asin_keyword_signals | prompt_mentions:ASIN,关键词流量,流量信号 | 1 | warn | continue_with_gap | 如果 Sif ASIN 关键词信号缺失，报告必须说明未完成 ASIN 流量关键词验证 |
| sif_asin_sales_proxy | sif_ops_get_asin_sales_list | prompt_mentions:销量,销售,变体销量,销量代理 | 1 | warn | continue_with_gap | 如果 Sif 销售证据缺失，报告不得把 review count 当作真实销量 |

## Output Rules

- 最终候选应优先聚焦外部品牌。
- Hsia / 遐 只能作为自家基准或传播信号，不应列为竞品。
- review count 只能作为热度代理，不能当成真实销量。
- 如果 TikTok 没验证到候选品牌，必须标记为数据缺口。
- 如果 Evidence Contract 有 warn 级缺口，最终报告必须在候选风险或数据缺口中标注。

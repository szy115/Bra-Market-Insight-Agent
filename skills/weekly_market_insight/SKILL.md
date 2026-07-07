---
name: weekly_market_insight
description: Analyze recent US market changes for an ecommerce category and produce evidence-driven Hsia R&D opportunities.
version: 0.1
owner: Hsia R&D Insight Agent
---

# 市场洞察 Skill

## What It Does

分析一个美国电商品类最近市场变化，并输出 Hsia 下一步研发机会。

这个 Skill 面向 Hsia 商品企划、设计团队和研发负责人。它把 Reddit 用户讨论和 Amazon 商品货架信号合并成一个证据驱动的市场洞察报告。

## When To Use

- 用户想知道市场最近在变什么
- 用户想做趋势、机会、品类变化分析
- 用户要求输出 Hsia 下一步研发机会
- 用户输入类似“帮我分析美国 minimizer bra 市场最近在变什么”

## Required Inputs

| 字段 | 说明 |
| --- | --- |
| brand | 研究对象品牌 |
| marketplace | 电商市场 |
| category | 研究品类 |
| time_range | 用户讨论时间范围 |

## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| listing_sample_size | 30 | Amazon 商品样本数 |
| head_listing_count | 10 | 头部商品数量 |
| new_product_window | 180d | 新品定义 |
| reddit_post_limit | 30 | Reddit 帖子样本数 |

## Missing Params

如果缺少必填参数，先向用户反问，不要直接执行后续工具步骤。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill |
| ask_user | system | 缺参时询问用户 |
| respond_to_user | system | 回答非任务型问题或解释当前状态 |
| synthesize_artifact | system | 生成最终市场洞察产物 |
| reddit_voc | required | 获取用户痛点、尺码语言、穿着场景和品牌提及 |
| amazon_shelf | required | 获取商品货架、价格、评分、评论量、品牌和卖点信号 |
| media_rankings | conditional | 用户要求媒体、榜单、文章或行业报告时补充公开文章证据 |
| tiktok_social | conditional | 用户要求 TikTok、社媒热度或交叉验证时补充社媒证据 |
| sif_market_get_keyword_demand | conditional | 用户要求 ABA、搜索量、关键词需求阶段或需求量化时补充 Sif 关键词需求证据 |
| sif_market_get_keyword_history | conditional | 用户要求历史搜索量、ABA 排名或关键词趋势原始数字时补充 Sif 历史数据 |
| sif_market_get_keyword_root_trend | conditional | 用户要求判断关键词背后市场边界或 root demand 时补充 Sif 根词趋势证据 |
| sif_market_get_keyword_competition | conditional | 用户要求关键词竞争格局、Top ASIN 或流量份额时补充 Sif 竞争证据 |

## Recommended Tool Use

- 先检查 Required Inputs 是否完整；如果缺少必填参数，调用 `ask_user` 反问，不要执行数据工具。
- 优先调用 `reddit_voc` 获取用户痛点、尺码语言、穿着场景和品牌提及。
- 再调用 `amazon_shelf` 获取商品货架、价格、评分、评论量、品牌和卖点信号。
- 如果用户明确要求媒体、榜单或社媒交叉验证，可补充调用对应数据工具。
- 证据足够后调用 `synthesize_artifact`，输出市场变化、Hsia 机会、风险和下一步验证动作。

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| amazon_shelf_signal | amazon_shelf | always | 1 | block | call_missing_tool | 缺少 Amazon 货架证据时，不得生成市场变化、价格带或竞品品牌结论 |
| reddit_user_voc | reddit_voc | always | 1 | warn | continue_with_gap | 如果 Reddit 证据缺失，报告必须标注用户声音缺口，并避免下定论式描述用户痛点 |
| media_public_sources | media_rankings | prompt_mentions:媒体,榜单,文章,报告,行业研究,全网 | 1 | warn | continue_with_gap | 如果公开文章证据缺失，报告必须说明未完成媒体或榜单交叉验证 |
| tiktok_social_validation | tiktok_social | prompt_mentions:TikTok,社媒,交叉验证,热度,爆款强度 | 1 | warn | continue_with_gap | 如果 TikTok 证据缺失，报告必须说明未完成社媒交叉验证 |
| sif_keyword_demand | sif_market_get_keyword_demand | prompt_mentions:ABA,搜索量,需求量,搜索热度,关键词需求 | 1 | warn | continue_with_gap | 如果 Sif 关键词需求证据缺失，报告不得声称已验证搜索量或 ABA 需求阶段 |
| sif_keyword_history | sif_market_get_keyword_history | prompt_mentions:历史搜索量,ABA排名,关键词趋势,搜索趋势 | 1 | warn | continue_with_gap | 如果 Sif 历史数据缺失，报告必须说明未完成关键词历史趋势验证 |
| sif_keyword_competition | sif_market_get_keyword_competition | prompt_mentions:竞争格局,Top ASIN,流量份额,关键词竞争 | 1 | warn | continue_with_gap | 如果 Sif 竞争证据缺失，报告必须说明未完成关键词竞争格局验证 |

## Output Rules

- 只基于工具证据输出结论。
- 不得编造销量、搜索量或平台级市场规模。
- 公开数据只能作为方向性证据。
- 每个工具步骤都必须产出可点击的 JSON 文件。
- 如果 Evidence Contract 有 warn 级缺口，最终报告必须在“数据缺口/风险”中标注。

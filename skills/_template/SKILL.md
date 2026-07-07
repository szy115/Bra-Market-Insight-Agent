---
name: template_skill_id
description: One sentence explaining when the agent should use this Skill.
version: 0.1
owner: Hsia R&D Insight Agent
---

# Template Skill

## What It Does

Describe the business task this Skill completes and who uses the output.

## When To Use

- User intent example 1
- User intent example 2
- User wording example

## Required Inputs

| 字段 | 说明 |
| --- | --- |
| brand | 研究对象品牌 |
| marketplace | 电商市场 |
| category | 研究品类 |

## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| listing_sample_size | 30 | 商品样本数 |

## Missing Params

如果缺少必填参数，先向用户反问，不要直接执行后续工具步骤。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill |
| ask_user | system | 缺参时询问用户 |
| respond_to_user | system | 回答非任务型问题或解释当前状态 |
| synthesize_artifact | system | 生成最终产物 |
| reddit_voc | allowed | 获取用户声音和场景语言 |
| amazon_shelf | allowed | 获取商品货架、价格、评分、评论量和品牌信号 |
| sif_market_get_keyword_demand | conditional | 用户要求搜索量、ABA 或关键词需求量化时补充 Sif MCP 证据 |

## Recommended Tool Use

- 先检查 Required Inputs 是否完整；如果缺少必填参数，调用 `ask_user` 反问，不要执行数据工具。
- 按任务需要调用数据工具，记录每个工具结果。
- 证据足够后调用 `synthesize_artifact`，输出结论、风险和下一步验证动作。

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| primary_evidence | amazon_shelf | always | 1 | block | call_missing_tool | 缺少核心证据时不得生成最终结论 |
| user_voc | reddit_voc | prompt_mentions:用户,痛点,VOC,评论,Reddit | 1 | warn | continue_with_gap | 报告必须标注用户声音数据缺口 |
| sif_keyword_demand | sif_market_get_keyword_demand | prompt_mentions:Sif,ABA,搜索量,关键词需求 | 1 | warn | continue_with_gap | 报告必须标注未完成 Sif 关键词需求验证 |

## Output Rules

- 只基于工具证据输出结论。
- 不得编造销量、搜索量、人口画像或平台级市场规模。
- 公开数据只能作为方向性证据。
- 如果证据缺失或样本不足，必须在最终产物中明确标注。

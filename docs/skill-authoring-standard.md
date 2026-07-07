# Insight Agent Skill Authoring Standard

This project uses Markdown Skills to turn repeatable research workflows into reusable agent instructions.
Each Skill must be useful to the LLM and parseable by the runtime harness.

## File Layout

Each Skill lives in its own folder:

```text
skills/<skill_id>/
  SKILL.md
```

Use lowercase snake_case for `<skill_id>`. The folder name is the runtime `skill_id`.

## Required Structure

Every `SKILL.md` must include these sections in this order:

1. YAML frontmatter
2. H1 title
3. `What It Does`
4. `When To Use`
5. `Required Inputs`
6. `Optional Defaults`
7. `Missing Params`
8. `Tool Policy`
9. `Recommended Tool Use`
10. `Evidence Contract`
11. `Output Rules`

## Frontmatter

Use Agent Skills-compatible frontmatter. Keep it short because the catalog is shown to the model every turn.

```md
---
name: weekly_market_insight
description: Analyze recent US market changes for an ecommerce category and produce evidence-driven Hsia R&D opportunities.
version: 0.1
owner: Hsia R&D Insight Agent
---
```

Required fields:

| field | rule |
| --- | --- |
| name | Same as folder `skill_id` unless there is a strong reason otherwise |
| description | One sentence explaining when the agent should use this Skill |

Optional fields:

| field | rule |
| --- | --- |
| version | Skill content version |
| owner | Owning product or team |

## Required Inputs

Use a two-column Markdown table. The runtime currently parses this section.

```md
## Required Inputs

| 字段 | 说明 |
| --- | --- |
| brand | 研究对象品牌 |
| marketplace | 电商市场 |
| category | 研究品类 |
```

Rules:

- Use canonical parameter names where possible: `brand`, `marketplace`, `category`, `time_range`.
- Do not put default values here.
- If the user omits required inputs, the agent must ask the user before data tools when the missing field cannot be reasonably inferred.

## Optional Defaults

Use a three-column Markdown table. The runtime currently parses this section.

```md
## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| listing_sample_size | 30 | Amazon 商品样本数 |
```

Rules:

- Defaults should be conservative.
- Defaults should not silently change the user's explicit request.
- Prefer canonical names already supported by `src/insight_agent/agent_params.py`.

## Tool Policy

`Tool Policy` declares which tools the Skill expects. It is a harness-facing contract, not just prose.

```md
## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill |
| ask_user | system | 缺参时询问用户 |
| reddit_voc | required | 获取用户痛点和场景语言 |
| amazon_shelf | required | 获取货架、价格、评分、评论量和品牌信号 |
| sif_market_get_keyword_demand | conditional | 用户要求搜索量、ABA 或关键词需求量化时调用 Sif MCP |
| synthesize_artifact | system | 生成最终产物 |
```

Policy values:

| policy | meaning |
| --- | --- |
| system | Runtime control tool; generally always available |
| required | The Skill normally needs this data tool |
| allowed | The Skill may use this tool when useful |
| conditional | The Skill may use this tool only when the prompt or params require it |
| disallowed | The Skill should not use this tool |

The harness may use this section to limit or warn about tool use. Do not rely only on natural language in `Recommended Tool Use`.

MCP tools are normal data tools once they are registered in the runtime catalog. List the exact agent-facing tool name in `Tool Policy`, usually with a provider prefix such as `sif_` or `sellersprite_`.

Common Sif MCP tools currently exposed by this project:

| tool | typical use |
| --- | --- |
| `sif_market_get_keyword_demand` | Keyword demand / search-volume evidence |
| `sif_market_get_keyword_history` | Historical keyword trend / ABA rank evidence |
| `sif_market_get_keyword_root_trend` | Root keyword trend and market-boundary signals |
| `sif_market_get_keyword_competition` | Keyword competition, Top ASIN, and traffic-share evidence |
| `sif_market_get_asin_keyword_signals` | ASIN-level keyword traffic signals |
| `sif_ops_get_asin_sales_list` | ASIN sales-list / variant sales proxy evidence |
| `sif_ops_get_asin_sales_trend` | ASIN sales trend and seasonality evidence |

SellerSprite MCP tools are discovered dynamically after `SELLERSPRITE_MCP_SECRET_KEY` is configured. They are exposed with the `sellersprite_` prefix. Ask the Agent for available tools after setting the secret, then copy the exact tool names into `Tool Policy` and `Evidence Contract`.

## Evidence Contract

`Evidence Contract` is the generic Final Gate for this product. It does not define how to analyze; it defines what evidence must exist before the final Artifact is generated.

Use this exact table shape:

```md
## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| amazon_shelf | amazon_shelf | always | 1 | block | call_missing_tool | 缺少 Amazon 货架证据时不得生成市场结论 |
```

Fields:

| field | meaning |
| --- | --- |
| evidence_id | Stable id for the evidence requirement |
| tool | Tool expected to produce the evidence |
| required_when | Predicate that decides when this evidence is required |
| min_success | Minimum number of successful or partial-success tool results |
| severity | `block` or `warn` |
| if_missing | `call_missing_tool`, `continue_with_gap`, or `ask_user` |
| artifact_requirement | What the final report must do if this evidence is absent or partial |

Supported `required_when` predicates for the first harness version:

| predicate | meaning |
| --- | --- |
| always | Always required |
| prompt_mentions:word1,word2 | Required when the user prompt contains any listed word |
| param_present:name | Required when the normalized Skill params include `name` |
| param_equals:name=value | Required when normalized Skill param equals `value` |
| tool_called:tool_name | Required when a tool was already called |

Severity rules:

- `block`: do not generate the final Artifact until the evidence is collected or the user changes scope.
- `warn`: allow generation, but pass the gap into the Artifact and explicitly mark the limitation.

## Recommended Tool Use

This section is for the LLM. It can include ordering, analysis intent, and judgment rules.
Do not put machine-critical constraints only here; duplicate those constraints in `Tool Policy` or `Evidence Contract`.

## Output Rules

Output rules define final report quality and evidence discipline.

Every Skill should include:

- Only use tool evidence for conclusions.
- Do not invent sales volume, search volume, demographics, or market size.
- Public data is directional evidence, not ground truth.
- Mark data gaps clearly.

## Review Checklist

Before merging or using a new Skill:

- Frontmatter has `name` and `description`.
- Required input names are canonical.
- Optional defaults are conservative and parseable.
- Tool Policy lists every expected tool.
- Evidence Contract includes every must-have evidence source.
- Block/warn severity matches product risk.
- Output Rules forbid unsupported claims.
- The Skill can ask for missing inputs without running data tools first.

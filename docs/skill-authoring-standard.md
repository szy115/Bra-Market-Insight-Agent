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
| synthesize_artifact | system | LangGraph 最终节点；生成并发布最终产物，不暴露给 Planner 调用 |
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

## HTML Report Data Builder Requirement

Any Skill that declares `render_html_report` with `required`, `allowed`, or `conditional` policy must pair it with a compatible report-data builder. This is a hard authoring rule, not an optional optimization.

Use this execution chain:

```text
data tools -> build_<workflow>_report_data -> data_analysis -> insight_synthesis
  -> chart_render -> html_render -> (report_review || report_red_team) -> approval_join
  both approved -> synthesize_artifact
  first rejection from either parallel branch -> html_revision -> parallel review round 2
  second rejection from either parallel branch -> html_revision -> synthesize_artifact
```

The chain has two ownership zones:

- The Planner executes only the Skill's source-data tools. When the Skill's source evidence and recovery rules are satisfied, it stops issuing tool calls.
- LangGraph interprets that no-tool-call turn as the handoff and owns every report node after it: `report_data_builder`, `data_analysis`, `insight_synthesis`, `chart_render`, `html_render`, mandatory factual `report_review`, independent `report_red_team`, any review-triggered `html_revision`, and terminal `synthesize_artifact`.

For HTML-report Skills, the builder, renderer, and `synthesize_artifact` remain declared in `Tool Policy` and `Evidence Contract` as runtime contracts, but they are not Planner-callable tools. `data_analysis`, `insight_synthesis`, `chart_render`, `report_review`, `report_red_team`, `approval_join`, and `html_revision` are generic internal graph nodes shared by every HTML-report Skill and are also not Planner-callable. Do not tell the Planner to call any report node.

The builder is the deterministic boundary between evidence collection and presentation. It must:

- Validate the Skill's business scope, normalized parameters, stable identifiers, time windows, and inclusion/exclusion rules.
- Normalize, filter, deduplicate, and join raw tool results by stable ids instead of display names.
- Apply deterministic normalization, ranking, and evidence selection before the LLM writes prose.
- Emit bounded, typed `metric_facts.v1` records only for registered primary-metric semantics. Each fact must retain value, unit, period, scope/entity, evidence ids, denominator scope, sample-completeness status, and source path.
- Produce bounded downstream input: selected rows, metric facts, chart specifications, evidence references, report-quality fields, and explicit data gaps.
- Return a versioned schema such as `<workflow>_report_data.v1` so renderer and tests can verify compatibility.
- Preserve missing evidence as a gap; never manufacture a zero, trend, shop, product, review, or conclusion to fill it.

The renderer must consume only the builder's versioned report-data output plus the Skill's presentation instructions. Do not pass raw MCP results, the complete runtime `toolResults` array, unbounded reviews, or unfiltered media arrays directly to `render_html_report`. If an image, quote, or row is needed in the report, the builder must select, deduplicate, and retain its source metadata first.

`chart_render` is the fixed chart-compilation boundary between analysis and HTML:

- Input is limited to the builder's bounded `chart_specs`; it never reads raw MCP/tool results.
- Runtime code maps supported chart specs to Flint semantic chart inputs and fixed-calls the pinned local Flint MCP `render_chart` tool.
- The MCP server accepts inline rows only, returns static SVG, and has no network or arbitrary local-file input.
- Runtime code rejects active or externally linked SVG content, stores validated SVGs under the current run, and records chart-level status.
- Unsupported or failed charts fall back to the existing deterministic server renderer. A chart failure degrades that chart and does not block HTML rendering or publication.
- `html_render` and every `html_revision` place the cached SVG by exact `chart_id`; the LLM must explain the supplied chart beside it but may not redraw, relabel, alter, or derive new chart data.

`data_analysis` is the fixed secondary-metric boundary between the builder and renderer:

- Input is limited to the builder's `metric_facts`, the current Skill/task, and that Skill's registered secondary-metric catalog.
- The LLM may only choose a registered `metric_id`, bind named parameters to existing `fact_id` values, and explain relevance. It must not define formulas or supply calculated values.
- Deterministic code owns validation and calculation. It must reject unknown facts, wrong metric semantics, cross-entity numerator/denominator pairs, mismatched periods, zero denominators, incomplete denominators, and concentration computed from partial/TopN samples.
- The node returns calculated `derived_metrics`, rejected proposals, `metric_gaps`, and a calculation audit. No calculable metric is a valid degraded outcome and does not block rendering.
- The renderer may interpret only `status=calculated` secondary metrics and must not recalculate a rejected or missing metric from raw fields.

`insight_synthesis` is the fixed narrative-analysis boundary after `data_analysis`:

- Input is limited to the builder's bounded versioned data, calculated secondary metrics, the active Skill contract, and the current task.
- It emits `report_insight_narrative.v1` with cross-chart `sections` plus one unified `chart_insights` collection. Do not impose fixed limits on section count, section-insight count, total insight count, or charts per section.
- Every ready chart gets exactly one `chart_insight`. Its specific observation and bounded interpretation are required; conclusion, business implication, and action are optional. Business charts may explain decision significance, while descriptive, methodology, scope, or coverage charts should explain the visible structure, denominator, confidence, or conclusion boundary instead of forcing a recommendation.
- Deterministic validation drops incomplete, duplicate, untraceable, unknown-evidence, and missing-data prose before rendering.
- Unsupported dimensions, rejected metrics, data gaps, and unfinished tasks remain in internal run metadata for approval and debugging but are omitted from visible report prose.
- The renderer uses the validated narrative as the analytical spine and may not replace it with generic KPI captions or independently invent unsupported conclusions.
- `html_render` interleaves prose and charts inside the same semantic analysis section: observation leads into a full-width figure, followed underneath by interpretation and any supported conclusion, business implication, or action. The layout stays single-column at every viewport and compiled SVGs scale to the report width. Multiple charts may share a section, but every chart keeps its own `chart_insight` block and structured explanation underneath. Chart-only runs, side-by-side chart/explanation columns, and separate prose/chart batches are forbidden.

`report_review` and `report_red_team` are separate mandatory parallel approval nodes:

- `report_review` owns factual consistency plus chart/prose composition: numbers, denominator, period, scope, evidence traceability, required structure, binding accuracy, same-section adjacency, full-width chart-above-explanation order, and one complete observation-and-interpretation block for every chart.
- `report_red_team` independently challenges up to five load-bearing business conclusions using steelman, falsifiable fails-if conditions, current evidence ids, missing comparisons, and kill criteria. It runs concurrently with factual review rather than waiting for that branch to pass.
- `approval_join` waits for both branches, preserves both structured results, and approves the round only when both pass. Either branch may request revision. Both belong to the same review round; the whole report still gets at most two rounds.
- `report_red_team` receives no source-data tools. It must make an `approve` or `revise` decision from the current HTML, complete pruned ReviewReportData, and Skill contract. Missing comparisons may produce a future-run evidence action, while the current repair must narrow, rewrite, or remove the unsupported claim without rerunning the Builder or report chain.
- After a second-round rejection, run one final `html_revision` and publish without a third factual review or red-team call.

Declare both tools as required and put both in the Evidence Contract:

```md
## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| build_example_report_data | required | Compile evidence into example_report_data.v1 |
| render_html_report | required | Render only example_report_data.v1 into the final HTML file |

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| compiled_report_data | build_example_report_data | always | 1 | block | call_missing_tool | HTML rendering requires example_report_data.v1 |
| final_html_report | render_html_report | always | 1 | block | call_missing_tool | Publish only a successfully written HTML report file |
```

In `Recommended Tool Use`, state the ownership, order, and recovery behavior explicitly:

- Finish, fail, or exhaust the defined recovery strategy for planned source-data calls, then stop issuing tool calls.
- LangGraph calls the builder after that handoff. If the builder gate reports missing required item-level evidence, the Planner calls only the missing source-data tools and stops again.
- LangGraph calls `data_analysis` after a compatible versioned report-data result succeeds, then calls `insight_synthesis`, then `chart_render` with bounded `chart_specs`, then calls the renderer with builder data augmented by deterministic analysis, validated narrative, and chart bundle.
- If rendering fails, retry or expose the error using the same compiled data; never bypass the builder or fall back to raw tool results.
- Every successful HTML render starts factual `report_review` and independent tool-free `report_red_team` concurrently, then enters `approval_join`. A first rejection from either branch enters `html_revision` and starts the second parallel round. A second rejection enters one final `html_revision` and then publishes directly; do not start a third factual review or red-team call and do not block publication only because the review remains rejected.
- LangGraph enters terminal `synthesize_artifact` only after the generic review/revision chain finishes.

Runtime readiness is part of this rule. The builder must be registered in the tool catalog, accept canonical parameters and collected tool results through the runtime adapter, and have tests for filtering, joins, ranking, gaps, schema version, and builder-before-renderer behavior. Do not declare a builder in `SKILL.md` until the callable tool exists.

Prefer a workflow-specific name such as `build_tiktok_new_product_report_data`. A shared builder such as `build_market_report_data` is acceptable only when the Skill explicitly uses that builder's schema and business contract; do not reuse an unrelated builder merely to satisfy this rule.

Non-HTML Skills are not required to add a report-data builder, although deterministic compilation is still recommended when their output has complex joins or rankings. Any HTML Skill that renders raw tool results is a contract violation and must be migrated before it can be considered ready.

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
| min_success | Minimum number of distinct successful or partial-success tool results; use an integer or `param:<canonical_name>` when the required count comes from a Skill parameter |
| severity | `block` or `warn` |
| if_missing | `call_missing_tool`, `continue_with_gap`, or `ask_user`; controls recovery when the evidence is still missing |
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

- `block + call_missing_tool` or `block + ask_user`: do not generate the final Artifact until the evidence is collected or the user changes scope.
- `block + continue_with_gap`: block only the conclusion that depends on this evidence, then allow a visibly `degraded` Artifact that names the missing task and does not invent a substitute conclusion.
- `warn`: allow generation, but pass the gap into the Artifact and explicitly mark the limitation.

For per-item workflows, `min_success` may reference a numeric canonical parameter. Example: `param:head_listing_count` requires one distinct successful tool input for every requested head listing. Repeating the same ASIN or keyword does not increase the observed count.

## Recommended Tool Use

This section is for the LLM. It can include ordering, analysis intent, and judgment rules.
Do not put machine-critical constraints only here; duplicate those constraints in `Tool Policy` or `Evidence Contract`.

## Output Rules

Output rules define final report quality and evidence discipline.

Every Skill should include:

- Only use tool evidence for conclusions.
- Do not invent sales volume, search volume, demographics, or market size.
- Public data is directional evidence, not ground truth.
- Omit unsupported conclusions from the visible Artifact; retain data gaps in internal run metadata for audit and recovery.

## Review Checklist

Before merging or using a new Skill:

- Frontmatter has `name` and `description`.
- Required input names are canonical.
- Optional defaults are conservative and parseable.
- Tool Policy lists every expected tool.
- Every HTML-report Skill declares a compatible required report-data builder before `render_html_report`.
- Every HTML-report builder emits bounded `metric_facts`, and the Skill has a registered fixed secondary-metric profile.
- `data_analysis` runs after the builder; the LLM only selects metrics/bindings and deterministic code validates and calculates.
- `insight_synthesis` runs after `data_analysis` and before charts/rendering; it emits only evidence-linked supported narrative and omits gap prose.
- `chart_render` runs after analysis and before HTML rendering; it fixed-calls the local Flint MCP and degrades per chart without blocking the report.
- The renderer consumes only versioned, bounded builder output and never raw MCP/tool results.
- Every HTML-report Skill uses parallel factual `report_review` and independent tool-free `report_red_team`, followed by `approval_join` and any required `html_revision`, with at most two review rounds.
- Evidence Contract includes every must-have evidence source.
- HTML-report Evidence Contracts block on both compiled report data and the final rendered HTML file.
- Block/warn severity matches product risk.
- Output Rules forbid unsupported claims.
- The Skill can ask for missing inputs without running data tools first.

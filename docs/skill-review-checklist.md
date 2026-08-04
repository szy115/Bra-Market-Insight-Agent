# Insight Agent Skill Review Checklist

Use this checklist whenever a successful chain is summarized into a Skill or an existing Skill is updated.

## Structure

- `SKILL.md` has YAML frontmatter with `name` and `description`.
- Folder name matches the runtime `skill_id`.
- Sections follow `docs/skill-authoring-standard.md`.
- The Skill title is clear to business users.

## Inputs

- Required inputs use canonical names such as `brand`, `marketplace`, `category`, and `time_range`.
- Optional defaults are conservative and do not override explicit user intent.
- Missing parameter behavior is explicit.

## Tools

- `Tool Policy` includes all system tools the Skill expects.
- Data tools are marked as `required`, `allowed`, `conditional`, or `disallowed`.
- `Recommended Tool Use` explains the intended order and evidence purpose.
- If `render_html_report` is allowed or required, a compatible `build_<workflow>_report_data` tool is declared as `required`.
- HTML execution order is explicit: data tools -> builder -> `data_analysis` -> `insight_synthesis` -> `chart_render` -> `html_render` -> parallel factual `report_review` and independent `report_red_team` -> `approval_join` -> any rejection-triggered `html_revision` -> `synthesize_artifact`.
- HTML ownership is explicit: Planner stops after source-data tools; LangGraph alone runs builder, fixed-metric analysis, insight synthesis, local MCP chart rendering, HTML rendering, factual review, red-team, any revision, and terminal `synthesize_artifact`.
- Review policy is explicit: at most two parallel review rounds; `approval_join` requires both branches to pass, while any rejection triggers revision; after a second rejection, run one final revision and publish without a third review.
- Red-team scope is explicit: `report_red_team` receives no source-data tools, decides only from the current HTML, complete pruned ReviewReportData, and Skill contract, and never triggers an in-run Builder/report-chain rerun.
- The Skill never instructs the Planner to call builder, `data_analysis`, `insight_synthesis`, `chart_render`, renderer, approval/red-team nodes, or `synthesize_artifact`.
- A generic builder is reused only when its versioned schema and business scope explicitly match this Skill.

## Evidence Contract

- Every final-report-critical evidence source has a row.
- HTML-report Skills have separate blocking evidence rows for compiled report data and the final HTML report.
- `required_when` uses supported predicates.
- `severity=block` is used only when the report would be misleading without that evidence.
- `severity=warn` includes a clear `artifact_requirement`.

## Output

- Output rules forbid invented sales, search volume, market size, and demographics.
- Unsupported conclusions and missing-data prose are omitted from the visible Artifact; gaps remain available in internal run metadata.
- Product or R&D recommendations must trace back to tool evidence.
- `render_html_report` is instructed to consume only versioned, bounded builder output; raw MCP/tool results and unbounded media/reviews are excluded.

## Runtime Readiness

- The existing parser can still read `Required Inputs` and `Optional Defaults`.
- The Skill remains useful to the LLM when loaded as plain Markdown.
- The Skill does not depend on hidden code or undocumented parameters.
- The declared report-data builder exists in the runtime tool catalog and accepts canonical parameters plus collected tool results.
- Builder tests cover scope filters, stable-id joins, deterministic ranking, data gaps, schema version, and builder-before-renderer ordering.
- The builder emits bounded, typed `metric_facts`; the Skill's fixed secondary-metric profile is registered and tested.
- `data_analysis` tests cover wrong denominators, mismatched periods, incomplete samples, deterministic values, and analysis-before-renderer ordering.
- `insight_synthesis` tests cover evidence-id validation, gap-prose removal, duplicate removal, one unified `chart_insight` per ready chart, optional business implications, absence of section/insight/chart-count caps, structured narrative, and insight-before-chart ordering.
- `chart_render` tests cover chart-spec adaptation, local MCP failure, unsafe SVG rejection, per-chart fallback, and chart-render-before-HTML ordering.
- Renderer/review tests require every chart and its own observation/interpretation in the same semantic insight block, with a full-width chart above its explanation at every viewport and no side-by-side layout or prose/chart batch. Business implication and action are required only when supported; descriptive, scope, confidence, and methodology interpretations are valid.
- Renderer failure is retried or exposed using compiled data; it never bypasses the builder or falls back to raw results.
- Generic factual `report_review`, independent tool-free `report_red_team`, `approval_join`, and `html_revision` nodes are registered and exercised for the Skill; their user-visible labels contain no workflow-specific business name.
- `synthesize_artifact` is a terminal graph node and is not exposed as a Planner-callable tool.

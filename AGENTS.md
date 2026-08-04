# Insight Agent Project Instructions

When adding, summarizing, or updating Insight Agent Skills:

- Follow `docs/skill-authoring-standard.md`.
- Start from `skills/_template/SKILL.md` for new Skills.
- Use `docs/skill-review-checklist.md` before considering a Skill ready.
- Keep Skill files as Markdown `SKILL.md`; do not add a separate JSON execution spec.
- Preserve canonical parameter names used by `src/insight_agent/agent_params.py`.
- Any Skill that allows or requires `render_html_report` must also declare a compatible report-data builder as `required` and enforce `data tools -> builder -> data_analysis -> insight_synthesis -> chart_render -> html_render -> (report_review || report_red_team) -> approval_join -> (html_revision when rejected) -> synthesize_artifact`.
- For HTML-report Skills, the Planner runs source-data tools and then stops issuing tool calls; LangGraph alone owns the builder, fixed-metric analysis, evidence-linked insight synthesis, local MCP chart renderer, HTML renderer, mandatory factual review, independent strategy red-team, any review-triggered HTML revision, and terminal `synthesize_artifact` nodes. Never instruct the Planner to call those report nodes.
- Every HTML report gets at most two parallel review rounds. Each round runs factual `report_review` and strategy `report_red_team` concurrently, then `approval_join` combines both results. A first-round rejection from either branch routes through `html_revision` and reruns both branches; a second-round rejection routes through one final `html_revision` and then publishes without a third review.
- `report_red_team` has no source-data tool access and must finish each review from the current HTML, complete pruned ReviewReportData, and Skill contract. Missing comparisons may narrow or remove a current claim and may be recorded as a future-run evidence action, but they never trigger in-run data calls or a Builder/report-chain rerun.
- The builder must emit bounded `metric_facts`; `data_analysis` may select only registered Skill-compatible secondary metrics and must let deterministic code validate bindings and calculate values.
- `insight_synthesis` consumes only bounded builder data plus calculated secondary metrics, emits uncapped cross-chart sections plus exactly one unified `chart_insight` for every ready chart, and silently omits unsupported dimensions. Every chart insight requires a specific observation and bounded interpretation; business implication and action are optional. Missing-data and unfinished-task prose stays in internal run metadata rather than the visible HTML.
- `chart_render` is a generic internal node. It may consume only bounded builder `chart_specs`, calls the pinned local Flint MCP `render_chart` tool, caches validated static SVGs, and degrades per chart to the deterministic server renderer without blocking the report.
- The HTML renderer may consume only the builder's versioned, bounded report-data output augmented by deterministic analysis and validated insight-synthesis results, plus presentation instructions; never pass raw MCP/tool results directly to the renderer.
- Prefer a workflow-specific `build_<workflow>_report_data` tool. Reuse a generic builder only when its schema and business scope explicitly match the Skill, and register and test the builder before considering the Skill ready.

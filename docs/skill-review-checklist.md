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

## Evidence Contract

- Every final-report-critical evidence source has a row.
- `required_when` uses supported predicates.
- `severity=block` is used only when the report would be misleading without that evidence.
- `severity=warn` includes a clear `artifact_requirement`.

## Output

- Output rules forbid invented sales, search volume, market size, and demographics.
- Data gaps are explicitly required in the final Artifact.
- Product or R&D recommendations must trace back to tool evidence.

## Runtime Readiness

- The existing parser can still read `Required Inputs` and `Optional Defaults`.
- The Skill remains useful to the LLM when loaded as plain Markdown.
- The Skill does not depend on hidden code or undocumented parameters.

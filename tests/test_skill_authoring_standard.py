import re
from pathlib import Path

from insight_agent.agent_skill_harness import parse_evidence_contract, parse_tool_policy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_BUILDER_PATTERN = re.compile(r"^build_[a-z0-9_]+report_data$")
LEGACY_HTML_SKILLS_WITHOUT_BUILDERS: set[str] = set()


def read_project_file(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_project_rules_require_builder_before_html_renderer() -> None:
    agents = read_project_file("AGENTS.md")
    standard = read_project_file("docs/skill-authoring-standard.md")

    assert (
        "data tools -> builder -> data_analysis -> insight_synthesis -> chart_render -> "
        "html_render -> (report_review || report_red_team) -> approval_join -> "
        "(html_revision when rejected) -> synthesize_artifact"
    ) in agents
    assert (
        "LangGraph alone owns the builder, fixed-metric analysis, evidence-linked insight synthesis, "
        "local MCP chart renderer, HTML renderer, mandatory factual review, independent strategy red-team"
    ) in agents
    assert "terminal `synthesize_artifact` nodes" in agents
    assert "never pass raw MCP/tool results directly to the renderer" in agents
    assert "`report_red_team` has no source-data tool access" in agents
    assert "red_team_evidence" not in agents
    assert "validate_red_team_evidence" not in agents
    assert (
        "data tools -> build_<workflow>_report_data -> data_analysis -> insight_synthesis\n"
        "  -> chart_render -> html_render -> (report_review || report_red_team) -> approval_join"
    ) in standard
    assert "LLM may only choose a registered `metric_id`" in standard
    assert "concentration computed from partial/TopN samples" in standard
    assert (
        "second rejection from either parallel branch -> html_revision -> synthesize_artifact"
        in standard
    )
    assert "Do not declare a builder in `SKILL.md` until the callable tool exists." in standard
    assert "Any HTML Skill that renders raw tool results is a contract violation" in standard


def test_template_and_review_checklist_keep_html_builder_gate() -> None:
    template = read_project_file("skills/_template/SKILL.md")
    checklist = read_project_file("docs/skill-review-checklist.md")

    assert "不得只声明 renderer" in template
    assert "compiled_report_data -> build_<workflow>_report_data" in template
    assert "HTML execution order is explicit" in checklist
    assert "`data_analysis`" in checklist
    assert "`chart_render`" in checklist
    assert "builder-before-renderer ordering" in checklist


def test_all_html_skills_declare_a_required_builder_before_renderer() -> None:
    observed_legacy: set[str] = set()

    for skill_path in sorted((PROJECT_ROOT / "skills").glob("*/SKILL.md")):
        skill_id = skill_path.parent.name
        if skill_id.startswith("_"):
            continue

        markdown = skill_path.read_text(encoding="utf-8")
        policies = {row["tool"]: row for row in parse_tool_policy(markdown)}
        renderer = policies.get("render_html_report")
        if not renderer or renderer["policy"] == "disallowed":
            continue

        assert "Planner" in markdown and "不调用" in markdown and "synthesize_artifact" in markdown, (
            f"{skill_id} must hand the report chain to LangGraph instead of asking the Planner "
            "to call report nodes"
        )
        builders = {
            tool
            for tool, row in policies.items()
            if REPORT_BUILDER_PATTERN.fullmatch(tool) and row["policy"] == "required"
        }
        if not builders:
            observed_legacy.add(skill_id)
            continue

        evidence = parse_evidence_contract(markdown)
        blocking_tools = {
            row["tool"]
            for row in evidence
            if row["severity"] == "block" and row["if_missing"] == "call_missing_tool"
        }
        assert builders <= blocking_tools, f"{skill_id} builder must block HTML rendering"
        assert "render_html_report" in blocking_tools, (
            f"{skill_id} final HTML evidence must block artifact publication"
        )
        assert "report_review" in markdown and "html_revision" in markdown, (
            f"{skill_id} must use the generic HTML review and revision graph nodes"
        )
        assert "data_analysis" in markdown, (
            f"{skill_id} must use the generic fixed-metric analysis graph node"
        )
        assert "insight_synthesis" in markdown, (
            f"{skill_id} must use the evidence-linked insight synthesis graph node"
        )
        assert "report_red_team" in markdown, (
            f"{skill_id} must use the independent report red-team graph node"
        )
        assert "red_team_evidence" not in markdown, (
            f"{skill_id} must not expose the removed red-team evidence branch"
        )
        assert "validate_red_team_evidence" not in markdown, (
            f"{skill_id} must not expose the removed red-team evidence gate"
        )

    assert observed_legacy == LEGACY_HTML_SKILLS_WITHOUT_BUILDERS

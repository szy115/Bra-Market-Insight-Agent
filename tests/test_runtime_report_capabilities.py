from __future__ import annotations

from types import MethodType, SimpleNamespace

from insight_agent import server as server_module
from insight_agent.agent_runtime import LangGraphAgentRuntime
from insight_agent.tool_capabilities import InvocationScope
from insight_agent.tool_capabilities.runtime_report import RUNTIME_REPORT_CAPABILITY_IDS


def test_report_preparation_capabilities_are_runtime_internal_only() -> None:
    registry = server_module.AGENT_TOOL_CAPABILITY_REGISTRY

    runtime_catalog = registry.catalog(InvocationScope.RUNTIME_INTERNAL)
    planner_catalog = server_module.planner_agent_tool_catalog()

    assert set(runtime_catalog) == RUNTIME_REPORT_CAPABILITY_IDS
    assert RUNTIME_REPORT_CAPABILITY_IDS.isdisjoint(planner_catalog)
    for capability_id in RUNTIME_REPORT_CAPABILITY_IDS:
        metadata = runtime_catalog[capability_id]
        assert metadata["invocation_scope"] == "runtime_internal"
        assert metadata["recovery"] == {
            "retryable": False,
            "default_timeout_seconds": 600,
            "default_retry_attempts": 0,
        }


def test_market_report_builder_executes_through_the_registry(monkeypatch) -> None:
    calls: list[dict] = []

    def build(payload):
        calls.append(payload)
        return {
            "schema_version": "market_report_data.v1",
            "source_summary": {"successful_tool_count": 2},
            "market_kpis": [{"id": "kpi-1"}],
            "evidence_map": [{"id": "evidence-1"}],
        }

    monkeypatch.setattr(server_module, "build_market_report_data", build)
    monkeypatch.setattr(
        server_module,
        "attach_metric_facts",
        lambda report_data: {**report_data, "metric_facts": [{"metric_id": "m1"}]},
    )

    result = server_module.execute_agent_tool(
        "build_market_report_data",
        "minimizer bra",
        {"toolResults": [{"name": "reddit_voc", "status": "ok"}]},
    )

    assert calls[0]["category"] == "minimizer bra"
    assert result["status"] == "ok"
    assert result["summary"] == (
        "MarketReportData compiled from 2 successful tool(s), 1 KPI(s), 1 evidence item(s)."
    )
    assert result["data"]["metric_facts"] == [{"metric_id": "m1"}]


def test_internal_analysis_adapter_returns_data_without_public_envelope(monkeypatch) -> None:
    monkeypatch.setattr(
        server_module,
        "analyze_market_report_node",
        lambda payload: {
            "schema_version": "derived_metric_data.v1",
            "status": "ok",
            "derived_metrics": [{"metric_id": "share"}],
            "input_echo": payload,
        },
    )

    result = server_module.execute_runtime_report_capability(
        "analyze_market_report",
        {"reportData": {"metric_facts": []}},
    )

    assert result["derived_metrics"] == [{"metric_id": "share"}]
    assert result["input_echo"] == {"reportData": {"metric_facts": []}}


def test_run_agent_internal_nodes_execute_through_runtime_registry(monkeypatch) -> None:
    from insight_agent import agent_runtime as runtime_module

    calls: list[tuple[str, dict]] = []

    def execute(capability_id, payload):
        calls.append((capability_id, payload))
        return {"capability_id": capability_id}

    class CapturingRuntime:
        def __init__(self, deps):
            self.deps = deps

        def run(self, _payload, emit_event=None):
            assert emit_event is None
            return {
                "analysis": self.deps.analyze_market_report({"step": "analysis"}),
                "insights": self.deps.synthesize_report_insights({"step": "insights"}),
                "charts": self.deps.render_report_charts({"step": "charts"}),
            }

    monkeypatch.setattr(server_module, "execute_runtime_report_capability", execute)
    monkeypatch.setattr(runtime_module, "LangGraphAgentRuntime", CapturingRuntime)

    result = server_module.run_agent({"prompt": "fixture"})

    assert calls == [
        ("analyze_market_report", {"step": "analysis"}),
        ("synthesize_report_insights", {"step": "insights"}),
        ("render_report_charts", {"step": "charts"}),
    ]
    assert result["charts"] == {"capability_id": "render_report_charts"}


def test_html_renderer_preserves_structured_generation_error(monkeypatch) -> None:
    def fail(_payload):
        raise server_module.HtmlReportGenerationError(
            "generation failed",
            {"status": "error", "provider": "fixture"},
        )

    monkeypatch.setattr(server_module, "render_html_report_tool", fail)

    result = server_module.execute_agent_tool("render_html_report", "bras", {})

    assert result["status"] == "error"
    assert result["summary"] == "generation failed"
    assert result["data"] == {"html_analysis": {"status": "error", "provider": "fixture"}}


def test_fixed_html_report_phase_order_is_unchanged() -> None:
    route = LangGraphAgentRuntime._route_after_runtime_step

    assert route(object(), {"report_pipeline_phase": "builder"}) == "report_data_builder"
    assert route(object(), {"report_pipeline_phase": "analysis"}) == "data_analysis"
    assert route(object(), {"report_pipeline_phase": "insights"}) == "insight_synthesis"
    assert route(object(), {"report_pipeline_phase": "charts"}) == "chart_render"
    assert route(object(), {"report_pipeline_phase": "render"}) == "html_render"


def test_runtime_internal_capabilities_are_filtered_from_planner_definitions() -> None:
    runtime = object.__new__(LangGraphAgentRuntime)
    runtime.deps = SimpleNamespace(
        tool_catalog=lambda: {
            "reddit_voc": {"invocation_scope": "planner", "description": "source"},
            "analyze_market_report": {
                "invocation_scope": "runtime_internal",
                "description": "internal",
            },
        }
    )

    assert runtime._planner_tool_catalog() == {
        "reddit_voc": {"invocation_scope": "planner", "description": "source"}
    }


def test_markdown_report_preparation_is_owned_by_runtime_nodes() -> None:
    runtime = object.__new__(LangGraphAgentRuntime)
    runtime._required_report_data_builder = MethodType(
        lambda _self, _state: "build_product_design_brief_data", runtime
    )
    runtime._required_report_tool = MethodType(
        lambda _self, _state: "render_markdown_report", runtime
    )
    runtime._check_evidence_gate_before_report_builder = MethodType(
        lambda _self, _state, _builder: {"status": "pass"}, runtime
    )
    runtime._builder_is_current = MethodType(lambda _self, _state, _builder: False, runtime)
    runtime._add_event = MethodType(lambda _self, *_args, **_kwargs: None, runtime)

    state = {"tools": [], "report_pipeline_phase": ""}
    scheduled = runtime._start_report_pipeline(state)

    assert scheduled["renderer"] == "render_markdown_report"
    assert state["report_pipeline_builder"] == "build_product_design_brief_data"
    assert state["report_pipeline_renderer"] == "render_markdown_report"
    assert state["report_pipeline_phase"] == "builder"

    runtime._run_data_tool = MethodType(lambda _self, *_args, **_kwargs: {"status": "ok"}, runtime)
    runtime._report_data_builder_node(state)
    assert state["report_pipeline_phase"] == "render"

    runtime._latest_successful_tool = MethodType(
        lambda _self, _state, name: {"name": name, "status": "ok"}, runtime
    )
    runtime._run_data_tool = MethodType(
        lambda _self, *_args, **_kwargs: {
            "status": "ok",
            "data": {"markdown": "# Brief", "report_file_path": "report.md"},
        },
        runtime,
    )
    runtime._html_render_node(state)
    assert state["report_pipeline_phase"] == "synthesize"


def test_product_design_brief_builder_activates_the_runtime_pipeline() -> None:
    runtime = object.__new__(LangGraphAgentRuntime)
    runtime.deps = SimpleNamespace(tool_catalog=server_module.agent_tool_catalog)
    state = {
        "selected_skill": server_module.AGENT_SKILL_REGISTRY["product_design_research"],
        "selected_skill_id": "product_design_research",
    }

    assert runtime._required_report_data_builder(state) == "build_product_design_brief_data"
    assert runtime._required_report_tool(state) == "render_markdown_report"
    assert runtime._uses_langgraph_report_pipeline(state) is True

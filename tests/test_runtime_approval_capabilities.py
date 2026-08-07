from __future__ import annotations

from types import SimpleNamespace

import pytest

from insight_agent import server as server_module
from insight_agent.agent_runtime import LangGraphAgentRuntime
from insight_agent.tool_capabilities import InvocationScope
from insight_agent.tool_capabilities.runtime_approval import (
    RUNTIME_APPROVAL_CAPABILITY_IDS,
)


def test_approval_capabilities_are_runtime_internal_only() -> None:
    registry = server_module.AGENT_TOOL_CAPABILITY_REGISTRY

    runtime_catalog = registry.catalog(InvocationScope.RUNTIME_INTERNAL)
    planner_catalog = server_module.planner_agent_tool_catalog()

    assert RUNTIME_APPROVAL_CAPABILITY_IDS.issubset(runtime_catalog)
    assert RUNTIME_APPROVAL_CAPABILITY_IDS.isdisjoint(planner_catalog)
    for capability_id in RUNTIME_APPROVAL_CAPABILITY_IDS:
        assert runtime_catalog[capability_id]["recovery"] == {
            "retryable": False,
            "default_timeout_seconds": 600,
            "default_retry_attempts": 0,
        }
        assert runtime_catalog[capability_id]["input_schema"]["additionalProperties"] is False

    assert set(runtime_catalog["review_html_report"]["input_schema"]["properties"]) == {
        "html",
        "reportData",
        "skillMarkdown",
        "skillHtmlTemplate",
        "reviewRound",
    }
    assert set(runtime_catalog["synthesize_artifact"]["input_schema"]["properties"]) == {
        "run_id",
        "approval_status",
        "use_llm",
    }


def test_factual_review_executes_through_the_registry(monkeypatch) -> None:
    monkeypatch.setattr(
        server_module,
        "review_html_report_node",
        lambda payload: {
            "status": "ok",
            "decision": "approve",
            "approved": True,
            "summary": "facts pass",
            "input_echo": payload,
        },
    )

    result = server_module.execute_runtime_capability(
        "review_html_report", {"html": "<html></html>", "reviewRound": 1}
    )

    assert result["approved"] is True
    assert result["input_echo"]["reviewRound"] == 1


def test_approval_join_requires_both_independent_branches() -> None:
    approved = server_module.execute_runtime_capability(
        "join_report_approval",
        {
            "review_round": 1,
            "factual_review": {"approved": True},
            "red_team_review": {"approved": True},
        },
    )
    rejected = server_module.execute_runtime_capability(
        "join_report_approval",
        {
            "review_round": 2,
            "factual_review": {"approved": True},
            "red_team_review": {"approved": False},
        },
    )

    assert approved["both_approved"] is True
    assert approved["next_phase"] == "publish"
    assert rejected["both_approved"] is False
    assert rejected["next_phase"] == "revision"


def test_terminal_artifact_operation_executes_inside_the_registry() -> None:
    calls: list[dict] = []

    def synthesize(payload):
        calls.append(payload)
        return {
            "status": "published",
            "published": True,
            "output_files": [{"name": "report.html", "path": "C:/fixture/report.html"}],
        }

    result = server_module.execute_runtime_capability(
        "synthesize_artifact",
        {"run_id": "fixture-run", "approval_status": "approved", "use_llm": True},
        runtime_adapter=synthesize,
    )

    assert calls == [
        {"run_id": "fixture-run", "approval_status": "approved", "use_llm": True}
    ]
    assert result["published"] is True
    assert result["output_files"] == [
        {"name": "report.html", "path": "C:/fixture/report.html"}
    ]


def test_terminal_artifact_capability_requires_its_owning_runtime_operation() -> None:
    with pytest.raises(RuntimeError, match="runtime operation missing"):
        server_module.execute_runtime_capability(
            "synthesize_artifact",
            {"run_id": "fixture-run", "approval_status": "approved", "use_llm": False},
        )


def test_artifact_graph_node_runs_stateful_synthesis_inside_registry_adapter() -> None:
    sequence: list[tuple[str, object]] = []
    result_state = {
        "run_id": "fixture-run",
        "response": {
            "response_type": "artifact",
            "output_files": [{"path": "C:/fixture/report.html"}],
        },
    }

    def execute(capability_id, payload, runtime_adapter):
        sequence.append(("registry", capability_id))
        return runtime_adapter(payload)

    runtime = object.__new__(LangGraphAgentRuntime)
    runtime.deps = SimpleNamespace(execute_runtime_capability=execute)
    runtime._synthesize_artifact_operation = lambda state: (
        sequence.append(("operation", state)) or result_state
    )
    state = {
        "run_id": "fixture-run",
        "use_llm": True,
        "planner": {"report_approval": {"status": "approved_round_1"}},
    }

    result = runtime._synthesize_artifact_node(state)

    assert result is result_state
    assert sequence == [
        ("registry", "synthesize_artifact"),
        ("operation", state),
    ]


def test_run_agent_approval_nodes_execute_through_runtime_registry(monkeypatch) -> None:
    from insight_agent import agent_runtime as runtime_module

    calls: list[str] = []

    def execute(capability_id, payload, runtime_adapter=None):
        calls.append(capability_id)
        if runtime_adapter:
            return runtime_adapter(payload)
        return {"capability_id": capability_id}

    class CapturingRuntime:
        def __init__(self, deps):
            self.deps = deps

        def run(self, _payload, emit_event=None):
            assert emit_event is None
            self.deps.review_html_report({})
            self.deps.red_team_html_report({})
            self.deps.join_report_approval({})
            self.deps.revise_html_report({})
            return self.deps.execute_runtime_capability(
                "synthesize_artifact",
                {"run_id": "fixture-run", "use_llm": False},
                lambda _payload: {"capability_id": "synthesize_artifact"},
            )

    monkeypatch.setattr(server_module, "execute_runtime_capability", execute)
    monkeypatch.setattr(runtime_module, "LangGraphAgentRuntime", CapturingRuntime)

    result = server_module.run_agent({"prompt": "fixture"})

    assert calls == [
        "review_html_report",
        "red_team_html_report",
        "join_report_approval",
        "revise_html_report",
        "synthesize_artifact",
    ]
    assert result == {"capability_id": "synthesize_artifact"}


def test_parallel_and_two_round_routes_are_unchanged() -> None:
    route = LangGraphAgentRuntime._route_after_runtime_step

    assert route(object(), {"report_approval_phase": "parallel_review"}) == [
        "report_review",
        "report_red_team",
    ]
    assert route(object(), {"report_approval_phase": "revision"}) == "html_revision"
    assert route(object(), {"report_approval_phase": "publish"}) == "synthesize_artifact"

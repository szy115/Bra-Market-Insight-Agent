from __future__ import annotations

import pytest

from insight_agent import server as server_module
from insight_agent.tool_capabilities import (
    InvalidToolCapability,
    InvocationScope,
    RecoveryTraits,
    ResultContract,
    ToolCapability,
    ToolCapabilityRegistry,
)


def sample_capability(**overrides) -> ToolCapability:
    values = {
        "capability_id": "sample_tool",
        "label": "Sample tool",
        "description": "Return a deterministic sample result.",
        "input_schema": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": [],
            "additionalProperties": True,
        },
        "invocation_scope": InvocationScope.PLANNER,
        "normalize_input": lambda category, payload: {"category": category, **payload},
        "adapter": lambda invocation: {"value": invocation.tool_input["category"]},
        "shape_result": lambda raw: raw,
        "shape_error": lambda _exc: {},
        "summarize": lambda raw: f"Sampled {raw['value']}",
        "result_contract": ResultContract(
            contract_id="sample_result.v1",
            validate=lambda result: None
            if isinstance(result.get("value"), str)
            else (_ for _ in ()).throw(ValueError("value must be a string")),
        ),
        "recovery": RecoveryTraits(
            retryable=True,
            default_timeout_seconds=600,
            default_retry_attempts=2,
        ),
        "output_kind": "generic_json",
    }
    values.update(overrides)
    return ToolCapability(**values)


def test_registry_composes_an_immutable_tool_capability() -> None:
    registry = ToolCapabilityRegistry([sample_capability()])

    capability = registry.get("sample_tool")

    assert capability.capability_id == "sample_tool"
    assert registry.catalog()["sample_tool"] == {
        "label": "Sample tool",
        "description": "Return a deterministic sample result.",
        "input_schema": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": [],
            "additionalProperties": True,
        },
        "invocation_scope": "planner",
        "result_contract": "sample_result.v1",
        "recovery": {
            "retryable": True,
            "default_timeout_seconds": 600,
            "default_retry_attempts": 2,
        },
        "output_kind": "generic_json",
    }
    with pytest.raises(TypeError):
        registry.capabilities["other"] = sample_capability(capability_id="other")
    with pytest.raises(TypeError):
        capability.input_schema["type"] = "array"


def test_registry_composition_does_not_probe_tool_adapters() -> None:
    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("composition must not execute capability callbacks")

    registry = ToolCapabilityRegistry(
        [
            sample_capability(
                normalize_input=unexpected_call,
                adapter=unexpected_call,
                shape_result=unexpected_call,
                shape_error=unexpected_call,
                summarize=unexpected_call,
            )
        ]
    )

    assert tuple(registry.capabilities) == ("sample_tool",)


def test_registry_freezes_non_reserved_catalog_metadata() -> None:
    registry = ToolCapabilityRegistry(
        [sample_capability(catalog_metadata={"source": "local_fixture"})]
    )

    capability = registry.get("sample_tool")

    assert registry.catalog()["sample_tool"]["source"] == "local_fixture"
    with pytest.raises(TypeError):
        capability.catalog_metadata["source"] = "changed"


def test_registry_executes_a_capability_through_the_common_result_envelope() -> None:
    ticks = iter([10.0, 10.012])
    registry = ToolCapabilityRegistry([sample_capability()], clock=lambda: next(ticks))

    result = registry.execute("sample_tool", "minimizer bra", {"limit": 3})

    assert result == {
        "name": "sample_tool",
        "label": "Sample tool",
        "status": "ok",
        "summary": "Sampled minimizer bra",
        "duration_ms": 12,
        "input": {"category": "minimizer bra", "limit": 3},
        "data": {"value": "minimizer bra"},
    }


def test_registry_accepts_a_runtime_bound_adapter_for_stateful_operations() -> None:
    static_calls: list[dict] = []
    runtime_calls: list[dict] = []
    registry = ToolCapabilityRegistry(
        [
            sample_capability(
                adapter=lambda invocation: static_calls.append(invocation.tool_input)
                or {"value": "static"}
            )
        ]
    )

    result = registry.execute(
        "sample_tool",
        "fixture",
        {"limit": 3},
        runtime_adapter=lambda invocation: runtime_calls.append(invocation.tool_input)
        or {"value": "runtime"},
    )

    assert static_calls == []
    assert runtime_calls == [{"category": "fixture", "limit": 3}]
    assert result["status"] == "ok"
    assert result["data"] == {"value": "runtime"}


def test_registry_reports_a_result_contract_mismatch() -> None:
    registry = ToolCapabilityRegistry(
        [sample_capability(shape_result=lambda _raw: {"value": 42})]
    )

    result = registry.execute("sample_tool", "minimizer bra", {})

    assert result["status"] == "error"
    assert result["summary"] == "sample_result.v1 contract violation: value must be a string"
    assert result["data"] == {}


def test_registry_preserves_normalized_input_when_an_adapter_fails() -> None:
    def unavailable_adapter(_invocation):
        raise RuntimeError("temporary provider unavailable")

    ticks = iter([20.0, 20.5])
    registry = ToolCapabilityRegistry(
        [sample_capability(adapter=unavailable_adapter)],
        clock=lambda: next(ticks),
    )

    result = registry.execute("sample_tool", "minimizer bra", {"limit": 3})

    assert result == {
        "name": "sample_tool",
        "label": "Sample tool",
        "status": "error",
        "summary": "temporary provider unavailable",
        "duration_ms": 500,
        "input": {"category": "minimizer bra", "limit": 3},
        "data": {},
    }


@pytest.mark.parametrize(
    ("capabilities", "message"),
    [
        (
            [sample_capability(), sample_capability()],
            "Duplicate Tool Capability id: sample_tool",
        ),
        (
            [sample_capability(input_schema={"type": "array"})],
            "input_schema.type must be object",
        ),
        (
            [sample_capability(invocation_scope="planner")],
            "invocation_scope must be an InvocationScope",
        ),
        (
            [sample_capability(adapter=None)],
            "adapter must be callable",
        ),
        (
            [sample_capability(shape_error=None)],
            "shape_error must be callable",
        ),
        (
            [sample_capability(output_kind="")],
            "output_kind must be a non-empty string",
        ),
        (
            [sample_capability(result_contract="sample_result.v1")],
            "result_contract must be a ResultContract",
        ),
        (
            [sample_capability(catalog_metadata={"label": "override"})],
            "catalog_metadata cannot override registry fields",
        ),
    ],
)
def test_registry_rejects_incomplete_or_duplicate_capabilities(capabilities, message) -> None:
    with pytest.raises(InvalidToolCapability, match=message):
        ToolCapabilityRegistry(capabilities)


def test_reddit_voc_executes_end_to_end_through_the_registry(monkeypatch) -> None:
    raw_result = {
        "coverage": {"posts": 1},
        "data_volume": {"collected_comments": 1},
        "market_signal": {"level": "emerging"},
        "sentiment": {"negative": 1},
        "pain_points": [{"topic": "Fit and sizing"}],
        "brands": [{"name": "Example"}],
        "sizes": [{"name": "34G"}],
        "posts": [
            {
                "id": "post-1",
                "title": "Need a comfortable minimizer",
                "url": "https://www.reddit.com/r/ABraThatFits/comments/test/post/",
                "subreddit": "ABraThatFits",
                "score": 12,
                "comments": 1,
                "excerpt": "The straps dig in.",
                "comment_items": [
                    {"author": "user-a", "text": "Side support matters.", "score": 3},
                    {"author": "user-b", "text": "", "score": 0},
                ],
            }
        ],
    }
    monkeypatch.setattr(server_module, "analyze_category", lambda tool_input: raw_result)

    result = server_module.execute_agent_tool(
        "reddit_voc",
        "fallback",
        {
            "params": {
                "category": "minimizer bra",
                "time_range": "90d",
                "reddit_post_limit": 45,
                "reddit_detail_limit": 8,
                "reddit_comments_per_post": 12,
            }
        },
    )

    assert result["name"] == "reddit_voc"
    assert result["label"] == "Reddit VOC"
    assert result["status"] == "ok"
    assert result["summary"] == "1 Reddit posts, 1 comments."
    assert isinstance(result["duration_ms"], int)
    assert result["input"] == {
        "category": "minimizer bra",
        "timeRange": "90d",
        "limit": 45,
        "mode": "auto",
        "useLlm": False,
        "redditDetailLimit": 8,
        "redditCommentsPerPost": 12,
        "bypassCache": False,
    }
    assert result["data"] == {
        "coverage": {"posts": 1},
        "market_signal": {"level": "emerging"},
        "sentiment": {"negative": 1},
        "pain_points": [{"topic": "Fit and sizing"}],
        "brands": [{"name": "Example"}],
        "sizes": [{"name": "34G"}],
        "posts": [
            {
                "id": "post-1",
                "title": "Need a comfortable minimizer",
                "url": "https://www.reddit.com/r/ABraThatFits/comments/test/post/",
                "subreddit": "ABraThatFits",
                "score": 12,
                "comments": 1,
                "comment_sample_count": 1,
                "comment_items": [
                    {"author": "user-a", "text": "Side support matters.", "score": 3}
                ],
                "excerpt": "The straps dig in.",
            }
        ],
    }
    assert "output_kind" not in result

    metadata = server_module.agent_tool_catalog()["reddit_voc"]
    assert metadata["invocation_scope"] == "planner"
    assert metadata["result_contract"] == "reddit_voc_result.v1"
    assert metadata["recovery"] == {
        "retryable": True,
        "default_timeout_seconds": 600,
        "default_retry_attempts": 2,
    }
    assert metadata["output_kind"] == "reddit_voc"


def test_reddit_voc_preserves_the_legacy_error_envelope(monkeypatch) -> None:
    def unavailable(_tool_input):
        raise RuntimeError("temporary provider unavailable")

    monkeypatch.setattr(server_module, "analyze_category", unavailable)

    result = server_module.execute_agent_tool(
        "reddit_voc",
        "minimizer bra",
        {"params": {"reddit_post_limit": 15}},
    )

    assert result["name"] == "reddit_voc"
    assert result["label"] == "Reddit VOC"
    assert result["status"] == "error"
    assert result["summary"] == "temporary provider unavailable"
    assert isinstance(result["duration_ms"], int)
    assert result["input"] == {
        "category": "minimizer bra",
        "timeRange": "year",
        "limit": 15,
        "mode": "auto",
        "useLlm": False,
        "redditDetailLimit": 5,
        "redditCommentsPerPost": 10,
        "bypassCache": False,
    }
    assert result["data"] == {}
    assert "output_kind" not in result


def test_runtime_defaults_come_from_the_registered_recovery_traits(monkeypatch) -> None:
    registry = ToolCapabilityRegistry(
        [
            sample_capability(
                capability_id="reddit_voc",
                recovery=RecoveryTraits(
                    retryable=False,
                    default_timeout_seconds=77,
                    default_retry_attempts=1,
                ),
            )
        ]
    )
    monkeypatch.setattr(server_module, "AGENT_TOOL_CAPABILITY_REGISTRY", registry)

    timeout_seconds, retry_attempts, retryable = server_module.agent_tool_recovery_defaults(
        "reddit_voc"
    )

    assert timeout_seconds == 77
    assert retry_attempts == 1
    assert retryable is False

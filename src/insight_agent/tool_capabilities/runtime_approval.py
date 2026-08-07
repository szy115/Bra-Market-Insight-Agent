from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .registry import InvocationScope, RecoveryTraits, ResultContract, ToolCapability

RuntimeNormalizer = Callable[[str, dict[str, Any]], dict[str, Any]]
RuntimeAdapter = Callable[[dict[str, Any]], dict[str, Any]]

REPORT_REVIEW_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "html": {"type": "string"},
        "reportData": {"type": "object", "additionalProperties": True},
        "skillMarkdown": {"type": "string"},
        "skillHtmlTemplate": {"type": "string"},
        "reviewRound": {"type": "integer", "minimum": 1},
    },
    "required": ["html", "reportData", "skillMarkdown", "reviewRound"],
    "additionalProperties": False,
}

REPORT_RED_TEAM_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "html": {"type": "string"},
        "reportData": {"type": "object", "additionalProperties": True},
        "skillMarkdown": {"type": "string"},
        "reviewRound": {"type": "integer", "minimum": 1},
    },
    "required": ["html", "reportData", "skillMarkdown", "reviewRound"],
    "additionalProperties": False,
}

APPROVAL_JOIN_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "review_round": {"type": "integer", "minimum": 1},
        "factual_review": {"type": "object", "additionalProperties": True},
        "red_team_review": {"type": "object", "additionalProperties": True},
    },
    "required": ["review_round", "factual_review", "red_team_review"],
    "additionalProperties": False,
}

HTML_REVISION_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "html": {"type": "string"},
        "reportData": {"type": "object", "additionalProperties": True},
        "skillMarkdown": {"type": "string"},
        "skillHtmlTemplate": {"type": "string"},
        "review": {"type": "object", "additionalProperties": True},
        "revisionRound": {"type": "integer", "minimum": 1},
        "chartRenderBundle": {"type": "object", "additionalProperties": True},
    },
    "required": [
        "html",
        "reportData",
        "skillMarkdown",
        "review",
        "revisionRound",
        "chartRenderBundle",
    ],
    "additionalProperties": False,
}

ARTIFACT_SYNTHESIS_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string"},
        "approval_status": {"type": ["string", "null"]},
        "use_llm": {"type": "boolean"},
    },
    "required": ["run_id", "use_llm"],
    "additionalProperties": False,
}

RUNTIME_APPROVAL_CAPABILITY_IDS = frozenset(
    {
        "review_html_report",
        "red_team_html_report",
        "join_report_approval",
        "revise_html_report",
        "synthesize_artifact",
    }
)


def build_runtime_approval_capability(
    *,
    capability_id: str,
    label: str,
    description: str,
    adapter: RuntimeAdapter,
    summarize: Callable[[dict[str, Any]], str],
    output_kind: str,
    input_schema: Mapping[str, Any],
    normalize_input: RuntimeNormalizer = lambda _category, payload: dict(payload),
) -> ToolCapability:
    if capability_id not in RUNTIME_APPROVAL_CAPABILITY_IDS:
        raise ValueError(f"Unknown runtime approval capability: {capability_id}")
    return ToolCapability(
        capability_id=capability_id,
        label=label,
        description=description,
        input_schema=input_schema,
        invocation_scope=InvocationScope.RUNTIME_INTERNAL,
        normalize_input=normalize_input,
        adapter=lambda invocation: adapter(invocation.tool_input),
        shape_result=lambda result: result,
        shape_error=lambda _exc: {},
        summarize=summarize,
        result_contract=ResultContract(
            contract_id=f"{capability_id}_result.v1",
            validate=validate_mapping_result,
        ),
        recovery=RecoveryTraits(
            retryable=False,
            default_timeout_seconds=600,
            default_retry_attempts=0,
        ),
        output_kind=output_kind,
    )


def validate_mapping_result(result: Mapping[str, Any]) -> None:
    if not isinstance(result, Mapping):
        raise ValueError("result must be a mapping")


def join_report_approval_result(payload: dict[str, Any]) -> dict[str, Any]:
    review_round = max(1, int(payload.get("review_round") or 1))
    review = dict(payload.get("factual_review") or {})
    red_team = dict(payload.get("red_team_review") or {})
    factual_approved = bool(review.get("approved"))
    red_team_approved = bool(red_team.get("approved"))
    both_approved = factual_approved and red_team_approved
    failed_labels = [
        label
        for label, approved in (
            ("事实审批", factual_approved),
            ("红队审批", red_team_approved),
        )
        if not approved
    ]
    return {
        "review_round": review_round,
        "factual_review": review,
        "red_team_review": red_team,
        "both_approved": both_approved,
        "next_phase": "publish" if both_approved else "revision",
        "outcome": "parallel_approval_passed" if both_approved else "revision_requested",
        "summary": (
            f"第 {review_round} 轮事实审批与红队审批均通过。"
            if both_approved
            else f"第 {review_round} 轮并行审批完成，{'、'.join(failed_labels)}要求返工。"
        ),
    }


def synthesize_artifact_result(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(payload.get("run_id") or "").strip()
    raise RuntimeError(f"Artifact synthesis runtime operation missing for run: {run_id}")


def artifact_publication_result(response: dict[str, Any]) -> dict[str, Any]:
    output_files = (
        response.get("output_files") if isinstance(response.get("output_files"), list) else []
    )
    published = bool(
        response.get("response_type") == "artifact"
        and any(isinstance(item, dict) and item.get("path") for item in output_files)
    )
    return {
        "status": "published" if published else "error",
        "published": published,
        "output_files": output_files,
    }


def summarize_review(result: dict[str, Any]) -> str:
    return str(result.get("summary") or result.get("decision") or "Review completed.")


def summarize_revision(result: dict[str, Any]) -> str:
    revision = result.get("revision") if isinstance(result.get("revision"), dict) else {}
    return str(revision.get("message") or revision.get("status") or "Revision completed.")


def summarize_approval_join(result: dict[str, Any]) -> str:
    return str(result.get("summary") or "Approval branches joined.")


def summarize_artifact(result: dict[str, Any]) -> str:
    return (
        "Final Artifact published."
        if result.get("published")
        else "Final Artifact was not published."
    )

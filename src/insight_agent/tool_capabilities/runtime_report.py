from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .registry import (
    InvocationScope,
    RecoveryTraits,
    ResultContract,
    ToolCapability,
)

RuntimeNormalizer = Callable[[str, dict[str, Any]], dict[str, Any]]
RuntimeAdapter = Callable[[dict[str, Any]], dict[str, Any]]

EMPTY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

RUNTIME_REPORT_CAPABILITY_IDS = frozenset(
    {
        "build_market_report_data",
        "build_tiktok_new_product_report_data",
        "build_tiktok_bra_competitor_shop_report_data",
        "build_trend_report_data",
        "build_competitor_product_report_data",
        "build_hot_product_pain_report_data",
        "build_product_design_brief_data",
        "analyze_market_report",
        "synthesize_report_insights",
        "render_report_charts",
        "render_html_report",
        "render_markdown_report",
    }
)


def build_runtime_report_capability(
    *,
    capability_id: str,
    label: str,
    description: str,
    normalize_input: RuntimeNormalizer,
    adapter: RuntimeAdapter,
    summarize: Callable[[dict[str, Any]], str],
    output_kind: str,
    input_schema: Mapping[str, Any] = EMPTY_INPUT_SCHEMA,
    shape_error: Callable[[Exception], dict[str, Any]] | None = None,
) -> ToolCapability:
    if capability_id not in RUNTIME_REPORT_CAPABILITY_IDS:
        raise ValueError(f"Unknown runtime report capability: {capability_id}")
    return ToolCapability(
        capability_id=capability_id,
        label=label,
        description=description,
        input_schema=input_schema,
        invocation_scope=InvocationScope.RUNTIME_INTERNAL,
        normalize_input=normalize_input,
        adapter=lambda invocation: adapter(invocation.tool_input),
        shape_result=lambda result: result,
        shape_error=shape_error or (lambda _exc: {}),
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


def summarize_market_report_data(result: dict[str, Any]) -> str:
    summary = result.get("source_summary") if isinstance(result.get("source_summary"), dict) else {}
    return (
        f"MarketReportData compiled from {summary.get('successful_tool_count', 0)} successful tool(s), "
        f"{len(result.get('market_kpis') or [])} KPI(s), "
        f"{len(result.get('evidence_map') or [])} evidence item(s)."
    )


def summarize_tiktok_new_product_report_data(result: dict[str, Any]) -> str:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    return (
        "TikTokNewProductReportData compiled "
        f"{summary.get('candidate_count', 0)} candidate(s) and "
        f"{summary.get('head_product_count', 0)} head product(s); "
        f"details {summary.get('detail_success_count', 0)}/"
        f"{summary.get('head_product_count', 0)}, trends "
        f"{summary.get('trend_success_count', 0)}/"
        f"{summary.get('head_product_count', 0)}."
    )


def summarize_tiktok_competitor_report_data(result: dict[str, Any]) -> str:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    return (
        "TikTokBraCompetitorShopReportData compiled "
        f"{summary.get('candidate_count', 0)} competitor candidate(s) and "
        f"{summary.get('analyzed_shop_count', 0)} standard shop analysis row(s); "
        f"{summary.get('complete_shop_count', 0)} complete."
    )


def summarize_trend_report_data(result: dict[str, Any]) -> str:
    summary = result.get("source_summary") if isinstance(result.get("source_summary"), dict) else {}
    visual = (
        result.get("visual_coverage") if isinstance(result.get("visual_coverage"), dict) else {}
    )
    return (
        f"TrendReportData compiled from {summary.get('readable_pages', 0)} readable page(s), "
        f"{summary.get('recent_pages', 0)} within the requested window, "
        f"and {visual.get('selected_for_report', 0)} visual evidence item(s)."
    )


def summarize_evidence_report_data(result: dict[str, Any]) -> str:
    summary = result.get("source_summary") if isinstance(result.get("source_summary"), dict) else {}
    return (
        f"{result.get('schema_version') or 'ReportData'} compiled from "
        f"{summary.get('successful_tool_count', 0)} successful tool result(s) and "
        f"{len(result.get('evidence_sources') or [])} bounded evidence source(s)."
    )


def summarize_product_design_brief_data(result: dict[str, Any]) -> str:
    summary = result.get("source_summary") if isinstance(result.get("source_summary"), dict) else {}
    volume = result.get("data_volume") if isinstance(result.get("data_volume"), dict) else {}
    actual = volume.get("actual") if isinstance(volume.get("actual"), dict) else {}
    return (
        f"ProductDesignBriefData compiled from {summary.get('successful_tool_count', 0)} successful tool(s), "
        f"{actual.get('unique_products', 0)} product(s), {actual.get('reviews', 0)} review(s), "
        f"and {len(result.get('evidence_map') or [])} evidence item(s)."
    )


def summarize_html_report(result: dict[str, Any]) -> str:
    return f"Rendered HTML report: {result.get('title') or 'HTML report'}."


def summarize_markdown_report(result: dict[str, Any]) -> str:
    return f"Rendered Markdown report: {result.get('title') or 'Markdown report'}."


def summarize_internal_data(result: dict[str, Any]) -> str:
    return str(result.get("summary") or result.get("status") or "Runtime report step completed.")


def html_error_data(exc: Exception) -> dict[str, Any]:
    analysis = getattr(exc, "analysis", None)
    return {"html_analysis": analysis} if isinstance(analysis, dict) else {}


def markdown_error_data(exc: Exception) -> dict[str, Any]:
    analysis = getattr(exc, "analysis", None)
    return {"markdown_analysis": analysis} if isinstance(analysis, dict) else {}

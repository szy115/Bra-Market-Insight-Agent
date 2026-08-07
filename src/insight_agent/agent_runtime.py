from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .agent_skill_harness import (
    allowed_data_tools_for_skill,
    evaluate_tool_policy,
    validate_evidence_contract,
)
from .fastmoss_competitor_shop_report import (
    PRODUCT_TOOL as FASTMOSS_COMPETITOR_PRODUCT_TOOL,
)
from .fastmoss_competitor_shop_report import (
    RANKING_TOOL as FASTMOSS_COMPETITOR_RANKING_TOOL,
)
from .fastmoss_competitor_shop_report import (
    STANDARD_SHOP_TOOLS as FASTMOSS_COMPETITOR_STANDARD_SHOP_TOOLS,
)
from .fastmoss_competitor_shop_report import (
    WOMENS_UNDERWEAR_CATEGORY_ID,
    competitor_shop_ranking_preflight,
    resolved_bra_category_ids,
)
from .market_product_identity import (
    DEFAULT_ASIN_DETAIL_BUDGET,
    find_product_identity_enrichment_candidates,
)
from .tool_capabilities.runtime_approval import (
    artifact_publication_result,
    join_report_approval_result,
)

SUCCESS_TOOL_STATUSES = {"ok", "partial_ok"}
CONVERSATION_CONTEXT_MAX_CHARS = 36_000
REPORT_APPROVAL_MAX_ROUNDS = 2
# Historical runs may still contain this removed internal node. Keep its name only
# in source-data filters so a continued legacy run cannot feed its audit JSON to a Builder.
LEGACY_INTERNAL_REPORT_TOOL_NAMES = frozenset({"validate_red_team_evidence"})
DEFAULT_RECURSION_LIMIT = 80
LARGE_WORKFLOW_RECURSION_LIMITS = {
    "tiktok_us_bra_competitor_shop_analysis": 180,
}


def compact_for_event(text: str, limit: int = 240) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def build_conversation_run_context(run: dict[str, Any]) -> str:
    """Build bounded context that supports questions, new work, and task resumption."""
    compiled_reports: list[dict[str, Any]] = []
    tool_summaries: list[dict[str, Any]] = []
    successful_tools: list[str] = []
    failed_tools: list[dict[str, Any]] = []
    for tool in run.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "")
        status = str(tool.get("status") or "")
        tool_summaries.append(
            {
                "name": name,
                "status": status,
                "summary": tool.get("summary"),
                "input": tool.get("input") if isinstance(tool.get("input"), dict) else {},
            }
        )
        if status in SUCCESS_TOOL_STATUSES:
            successful_tools.append(name)
        else:
            failed_tools.append(
                {
                    "name": name,
                    "status": status,
                    "summary": tool.get("summary"),
                }
            )
        if (
            name.startswith("build_")
            and status in SUCCESS_TOOL_STATUSES
            and isinstance(tool.get("data"), dict)
        ):
            compiled_reports.append({"name": name, "data": tool["data"]})

    message = run.get("message") if isinstance(run.get("message"), dict) else {}
    skill = run.get("skill") if isinstance(run.get("skill"), dict) else {}
    pending = run.get("pending") if isinstance(run.get("pending"), dict) else {}
    skill_id = str(skill.get("skill_id") or pending.get("skill_id") or "")
    context = {
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "prompt": run.get("prompt"),
        "category": run.get("category"),
        "resume_candidate": {
            "available": bool(skill_id and successful_tools),
            "skill_id": skill_id or None,
            "successful_tools": successful_tools,
            "failed_tools": failed_tools,
            "instruction": (
                "If the user wants to retry, continue, regenerate, or reuse this work, call "
                "resume_previous_run before any data or report tool."
            ),
        },
        "skill": skill,
        "artifact": run.get("artifact") if isinstance(run.get("artifact"), dict) else {},
        "assistant_message": message.get("content"),
        "tool_summaries": tool_summaries[-80:],
        "output_files": run.get("output_files") or [],
        "compiled_report_data": compiled_reports,
    }
    serialized = json.dumps(context, ensure_ascii=False, default=str)
    if len(serialized) <= CONVERSATION_CONTEXT_MAX_CHARS:
        return serialized
    return (
        serialized[:CONVERSATION_CONTEXT_MAX_CHARS].rstrip()
        + "\n[上一轮任务上下文已按长度上限截断]"
    )


def llm_failure_user_message(exc: BaseException, completed_tool_count: int) -> str:
    text = str(exc)
    lowered = text.lower()
    if "api key is not configured" in lowered or "http 401" in lowered or "http 403" in lowered:
        reason = "LLM API key 或权限配置不可用"
        advice = "请在设置里检查 API key、模型名和 Base URL。"
    elif (
        "unexpected_eof_while_reading" in lowered
        or "eof occurred in violation of protocol" in lowered
        or "ssl" in lowered
    ):
        reason = "LLM 连接在 SSL/TLS 读取响应时被中断"
        advice = "这通常是网络、代理、供应商连接或长时间任务后的临时传输问题，不代表 API key 一定错误；可以直接重试，或检查代理/网络稳定性并适当调高超时时间。"
    elif "timeout" in lowered or "timed out" in lowered:
        reason = "LLM 请求超时"
        advice = "可以重试，或在设置里调高超时时间。"
    else:
        reason = "LLM 请求失败"
        advice = "请稍后重试；如果反复出现，再检查 Base URL、模型名、网络和 API key。"
    if completed_tool_count > 0:
        progress = f"本轮已经完成 {completed_tool_count} 个数据工具调用，但下一轮模型规划/生成失败，所以还不能继续生成最终报告。"
    else:
        progress = "Agent 还没有执行数据工具。"
    return f"无法继续执行：{reason}（{text}）。{progress}{advice}"


class AgentRuntimeState(TypedDict, total=False):
    payload: dict[str, Any]
    prompt: str
    run_id: str
    generated_at: str
    mode: str
    category: str
    locale: str
    use_llm: bool
    messages: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]]
    forced_skill_id: str | None
    selected_skill_id: str | None
    selected_skill: dict[str, Any] | None
    skill_params: dict[str, Any]
    missing_params: list[str]
    clarification: dict[str, Any]
    skill_file_path: str
    events: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    artifact: dict[str, Any]
    assistant_message: dict[str, Any]
    llm_analysis: dict[str, Any]
    output_files: list[dict[str, str]]
    evidence_gaps: list[dict[str, Any]]
    product_identity_detail_lookup_asins: list[str]
    capability_inspected: bool
    planner: dict[str, Any]
    response: dict[str, Any]
    checkpoint_source_run_id: str
    checkpoint_restored_tool_count: int
    context_source_run_id: str
    follow_up_result_context: str
    context_run_status: str
    resumed_task_prompt: str
    report_pipeline_phase: str
    report_pipeline_builder: str
    report_pipeline_renderer: str
    report_approval_phase: str
    report_review_round: int
    report_render_version: int
    report_reviews: list[dict[str, Any]]
    report_red_teams: list[dict[str, Any]]
    report_revisions: list[dict[str, Any]]
    report_review_branch: dict[str, Any]
    report_red_team_branch: dict[str, Any]


@dataclass
class AgentRuntimeDeps:
    now_iso: Callable[[], str]
    load_agent_run: Callable[[str], dict[str, Any] | None]
    write_json: Callable[[str, str, Any], str]
    write_text: Callable[[str, str, str], str]
    agent_event: Callable[..., dict[str, Any]]
    category_from_payload: Callable[[dict[str, Any]], str]
    call_chat: Callable[..., dict[str, Any]]
    skill_registry: Callable[[], dict[str, dict[str, Any]]]
    skill_manifests: Callable[[], list[dict[str, Any]]]
    resolve_skill_params: Callable[
        [dict[str, Any], dict[str, Any], dict[str, Any]],
        tuple[dict[str, Any], list[str]],
    ]
    payload_with_skill_params: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    tool_input_payload: Callable[[str, str, dict[str, Any]], dict[str, Any]]
    execute_tool: Callable[[str, str, dict[str, Any]], dict[str, Any]]
    build_clarification: Callable[
        [dict[str, Any], list[str], dict[str, Any], str],
        dict[str, Any],
    ]
    build_clarification_artifact: Callable[
        [str, str, str, dict[str, Any], str],
        dict[str, Any],
    ]
    tool_catalog: Callable[[], dict[str, dict[str, Any]]]
    cache_dir: Callable[[], Path]
    render_html_report: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    analyze_market_report: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    synthesize_report_insights: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    render_report_charts: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    available_report_metrics: Callable[[str], list[dict[str, Any]]] | None = None
    review_html_report: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    red_team_html_report: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    revise_html_report: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    join_report_approval: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    execute_runtime_capability: Callable[
        [
            str,
            dict[str, Any],
            Callable[[dict[str, Any]], dict[str, Any]] | None,
        ],
        dict[str, Any],
    ] | None = None


class LangGraphAgentRuntime:
    """Native tool-calling harness for Hsia's Insight Agent.

    The model chooses tools through OpenAI-compatible `tool_calls`.
    The harness only executes tools, records observations, handles human
    interruption, and persists artifacts.
    """

    def __init__(self, deps: AgentRuntimeDeps) -> None:
        self.deps = deps
        self._emit_event: Callable[[dict[str, Any]], None] | None = None
        self._last_state: AgentRuntimeState | None = None
        self._event_sequence_lock = threading.Lock()
        self._event_sequence = 0
        self._event_sequences_by_id: dict[str, int] = {}
        self._graph = self._build_graph()

    def run(
        self,
        payload: dict[str, Any],
        emit_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        self._emit_event = emit_event
        with self._event_sequence_lock:
            self._event_sequence = 0
            self._event_sequences_by_id = {}
        initial = self._initial_state(dict(payload))
        self._last_state = initial
        recursion_limit = LARGE_WORKFLOW_RECURSION_LIMITS.get(
            str(initial.get("forced_skill_id") or ""),
            DEFAULT_RECURSION_LIMIT,
        )
        try:
            result = self._graph.invoke(
                initial,
                config={
                    "recursion_limit": recursion_limit,
                    "configurable": {"thread_id": initial["run_id"]},
                },
            )
        except Exception as exc:
            self._write_progress(self._last_state or initial, status="error", error=str(exc))
            raise
        return result["response"]

    def _build_graph(self):
        builder = StateGraph(AgentRuntimeState)
        builder.add_node("agent", self._agent_node)
        builder.add_node("tools", self._tools_node)
        builder.add_node("report_data_builder", self._report_data_builder_node)
        builder.add_node("data_analysis", self._data_analysis_node)
        builder.add_node("insight_synthesis", self._insight_synthesis_node)
        builder.add_node("chart_render", self._chart_render_node)
        builder.add_node("html_render", self._html_render_node)
        builder.add_node("report_review", self._report_review_node)
        builder.add_node("report_red_team", self._report_red_team_node)
        builder.add_node("approval_join", self._approval_join_node)
        builder.add_node("html_revision", self._html_revision_node)
        builder.add_node("synthesize_artifact", self._synthesize_artifact_node)
        builder.add_edge(START, "agent")
        builder.add_conditional_edges(
            "agent",
            self._route_after_agent,
            {
                "tools": "tools",
                "agent": "agent",
                "report_data_builder": "report_data_builder",
                "data_analysis": "data_analysis",
                "insight_synthesis": "insight_synthesis",
                "chart_render": "chart_render",
                "html_render": "html_render",
                "report_review": "report_review",
                "report_red_team": "report_red_team",
                "approval_join": "approval_join",
                "html_revision": "html_revision",
                "synthesize_artifact": "synthesize_artifact",
                "end": END,
            },
        )
        runtime_routes = {
            "agent": "agent",
            "report_data_builder": "report_data_builder",
            "data_analysis": "data_analysis",
            "insight_synthesis": "insight_synthesis",
            "chart_render": "chart_render",
            "html_render": "html_render",
            "report_review": "report_review",
            "report_red_team": "report_red_team",
            "approval_join": "approval_join",
            "html_revision": "html_revision",
            "synthesize_artifact": "synthesize_artifact",
            "end": END,
        }
        for node in (
            "tools",
            "report_data_builder",
            "data_analysis",
            "insight_synthesis",
            "chart_render",
            "html_render",
            "approval_join",
            "html_revision",
            "synthesize_artifact",
        ):
            builder.add_conditional_edges(node, self._route_after_runtime_step, runtime_routes)
        builder.add_edge(["report_review", "report_red_team"], "approval_join")
        return builder.compile(checkpointer=MemorySaver())

    def _route_after_agent(self, state: AgentRuntimeState) -> str:
        if state.get("pending_tool_calls"):
            return "tools"
        return self._route_after_runtime_step(state)

    def _route_after_runtime_step(self, state: AgentRuntimeState) -> str | list[str]:
        if state.get("response"):
            return "end"
        report_phase = str(state.get("report_pipeline_phase") or "")
        if report_phase == "builder":
            return "report_data_builder"
        if report_phase == "analysis":
            return "data_analysis"
        if report_phase == "insights":
            return "insight_synthesis"
        if report_phase == "charts":
            return "chart_render"
        if report_phase == "render":
            return "html_render"
        if report_phase == "synthesize":
            return "synthesize_artifact"
        phase = str(state.get("report_approval_phase") or "")
        if phase == "parallel_review":
            return ["report_review", "report_red_team"]
        if phase == "revision":
            return "html_revision"
        if phase == "publish":
            return "synthesize_artifact"
        return "agent"

    def _initial_state(self, payload: dict[str, Any]) -> AgentRuntimeState:
        user_prompt = str(payload.get("prompt") or "").strip()
        if not user_prompt:
            raise ValueError("prompt is required")

        continuation_run = self.deps.load_agent_run(str(payload.get("continueRunId") or "").strip())
        context_run = None
        if not continuation_run:
            context_run = self.deps.load_agent_run(
                str(payload.get("contextRunId") or "").strip()
            )
        forced_skill_id = str(payload.get("skillId") or "").strip() or None
        continuation_context = ""
        context_source_run_id = ""
        follow_up_result_context = ""
        context_run_status = ""
        restored_tools: list[dict[str, Any]] = []
        restored_evidence_gaps: list[dict[str, Any]] = []
        checkpoint_source_run_id = ""
        restored_skill_id: str | None = None
        restored_skill: dict[str, Any] | None = None
        restored_skill_params: dict[str, Any] = {}
        restored_skill_file_path = ""
        if continuation_run:
            previous_skill = (
                continuation_run.get("skill")
                if isinstance(continuation_run.get("skill"), dict)
                else {}
            )
            previous_pending = (
                continuation_run.get("pending")
                if isinstance(continuation_run.get("pending"), dict)
                else {}
            )
            forced_skill_id = (
                forced_skill_id
                or str(
                    previous_skill.get("skill_id") or previous_pending.get("skill_id") or ""
                ).strip()
                or None
            )
            previous_params = (
                previous_pending.get("resolved_params")
                if isinstance(previous_pending.get("resolved_params"), dict)
                else previous_skill.get("params")
            )
            previous_missing = (
                previous_pending.get("missing_params")
                if isinstance(previous_pending.get("missing_params"), list)
                else previous_skill.get("missing_params")
                if isinstance(previous_skill.get("missing_params"), list)
                else []
            )
            previous_questions = (
                previous_pending.get("questions")
                if isinstance(previous_pending.get("questions"), list)
                else []
            )
            checkpoint_resume = bool(
                previous_pending.get("resume_supported")
                and str(previous_pending.get("reason_type") or "")
                in {"external_action", "retryable_tool_failure"}
            )
            if checkpoint_resume:
                restored_tools = [
                    dict(tool)
                    for tool in continuation_run.get("tools") or []
                    if isinstance(tool, dict)
                ]
                restored_evidence_gaps = [
                    dict(gap)
                    for gap in continuation_run.get("evidence_gaps") or []
                    if isinstance(gap, dict)
                ]
                checkpoint_source_run_id = str(continuation_run.get("run_id") or "")
            merged_params = dict(previous_params or {})
            payload_params = (
                payload.get("params") if isinstance(payload.get("params"), dict) else {}
            )
            merged_params.update(
                {
                    key: value
                    for key, value in payload_params.items()
                    if value is not None and value != ""
                }
            )
            payload["params"] = merged_params
            if checkpoint_resume and forced_skill_id:
                restored_skill_id = forced_skill_id
                restored_skill = self.deps.skill_registry().get(forced_skill_id)
                restored_skill_params = merged_params
                restored_skill_file_path = str(previous_skill.get("file_path") or "")
            previous_prompt = str(continuation_run.get("prompt") or "").strip()
            prompt = (
                f"{previous_prompt}\n\n用户补充参数：{user_prompt}"
                if previous_prompt
                else user_prompt
            )
            payload.setdefault("agentMode", continuation_run.get("mode"))
            if checkpoint_resume:
                successful_checkpoint_tools = [
                    str(tool.get("name") or "")
                    for tool in restored_tools
                    if str(tool.get("status") or "") in SUCCESS_TOOL_STATUSES
                ]
                continuation_context = (
                    "\n这是上一轮因外部操作而暂停的真实断点继续执行。"
                    f"\n断点来源 run_id：{checkpoint_source_run_id}"
                    f"\n已恢复 {len(restored_tools)} 个工具记录，其中成功 {len(successful_checkpoint_tools)} 个。"
                    f"\n已完成工具：{json.dumps(successful_checkpoint_tools, ensure_ascii=False)}"
                    f"\n上一轮被阻塞工具：{previous_pending.get('blocked_tool') or ''}"
                    "\n必须复用已恢复的成功结果；只重试被阻塞或仍缺失的调用，不得从头重复执行。"
                )
            else:
                continuation_context = (
                    "\n这是上一轮 needs_input 的继续执行。"
                    f"\n上一轮已解析参数：{json.dumps(previous_params or {}, ensure_ascii=False)}"
                    f"\n上一轮缺少参数：{json.dumps(previous_missing, ensure_ascii=False)}"
                    f"\n上一轮向用户提出的问题：{json.dumps(previous_questions, ensure_ascii=False)}"
                    "\n请从“用户补充参数”中抽取新参数并放入 load_skill.extracted_params。"
                )
        else:
            prompt = user_prompt
            if context_run:
                context_source_run_id = str(context_run.get("run_id") or "")
                context_run_status = str(context_run.get("status") or "")
                follow_up_result_context = build_conversation_run_context(context_run)
                payload.setdefault("agentMode", context_run.get("mode"))
                payload.setdefault("category", context_run.get("category"))
                continuation_context = (
                    "\n当前对话带有上一轮任务上下文，但这不会限制本轮只能追问。"
                    f"\n上一轮任务 run_id：{context_source_run_id}"
                    f"\n上一轮任务状态：{context_run_status or 'unknown'}"
                    "\n上一轮任务上下文："
                    f"\n{follow_up_result_context}"
                    "\n请根据用户当前意图自主选择："
                    "\n1) 询问或解释上一轮结果：直接回复文本；"
                    "\n2) 发起新的或扩展的调研：加载最合适的 Skill 并调用工具；"
                    "\n3) 继续、重试或重新渲染上一轮任务：先调用 resume_previous_run 恢复成功工具和 Skill，再只执行失败或缺失步骤。"
                )

        generated_at = self.deps.now_iso()
        requested_run_id = str(payload.get("runId") or "").strip().lower()
        run_id = (
            requested_run_id
            if re.fullmatch(r"[a-f0-9]{12}", requested_run_id)
            else hashlib.sha1(f"{prompt}-{generated_at}".encode()).hexdigest()[:12]
        )
        mode = str(payload.get("agentMode") or payload.get("mode") or "market").strip().lower()
        if mode not in {"market", "competitor"}:
            mode = "market"
        category = self.deps.category_from_payload(payload)
        locale = str(payload.get("locale") or "zh")
        use_llm = payload.get("useLlm", True) is not False
        state: AgentRuntimeState = {
            "payload": payload,
            "prompt": prompt,
            "run_id": run_id,
            "generated_at": generated_at,
            "mode": mode,
            "category": category,
            "locale": locale,
            "use_llm": use_llm,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"用户任务：{prompt}\n"
                        f"UI 模式：{mode}\n"
                        f"显式传入品类：{category or '未提供'}\n"
                        f"已知参数：{json.dumps(payload.get('params') or {}, ensure_ascii=False)}"
                        f"{continuation_context}"
                    ),
                }
            ],
            "pending_tool_calls": [],
            "forced_skill_id": forced_skill_id,
            "selected_skill_id": restored_skill_id,
            "selected_skill": restored_skill,
            "skill_params": restored_skill_params,
            "missing_params": [],
            "clarification": {},
            "skill_file_path": restored_skill_file_path,
            "events": [],
            "tools": restored_tools,
            "evidence_gaps": restored_evidence_gaps,
            "output_files": [],
            "assistant_message": {},
            "capability_inspected": False,
            "checkpoint_source_run_id": checkpoint_source_run_id,
            "checkpoint_restored_tool_count": len(restored_tools),
            "context_source_run_id": context_source_run_id,
            "follow_up_result_context": follow_up_result_context,
            "context_run_status": context_run_status,
            "resumed_task_prompt": "",
            "report_pipeline_phase": "",
            "report_pipeline_builder": "",
            "report_pipeline_renderer": "",
            "report_approval_phase": "",
            "report_review_round": 0,
            "report_render_version": 0,
            "report_reviews": [],
            "report_red_teams": [],
            "report_revisions": [],
            "report_review_branch": {},
            "report_red_team_branch": {},
            "planner": {
                "enabled": use_llm,
                "status": "running" if use_llm else "not_requested",
                "message": "Native tool-calling runtime.",
                "native_tool_calls": True,
                "planned_tools": [],
                "selected_skill_id": restored_skill_id,
            },
        }
        self._add_event(
            state,
            "input",
            "ok",
            "接收用户输入",
            "已收到你的输入，正在判断是直接回复、补齐参数，还是调用工具执行任务。",
            data={"mode": mode, "category": category, "prompt_chars": len(prompt)},
            input_params={
                "prompt": prompt,
                "agentMode": mode,
                "category": category,
                "locale": locale,
                "useLlm": use_llm,
            },
        )
        return state

    def _agent_node(self, state: AgentRuntimeState) -> AgentRuntimeState:
        if not state.get("use_llm"):
            self._add_event(
                state,
                "tool",
                "skipped",
                "没有调用模型",
                "useLlm=false，无法由模型选择 Skill 或工具。",
                output={"summary": "Native tool calling skipped because LLM is disabled."},
            )
            return self._respond_to_user(
                state,
                "无法生成最终 HTML 分析报告：当前没有启用 LLM，Agent 不能选择 Skill 和数据工具。请开启 LLM 后重新运行。",
            )

        try:
            response = self.deps.call_chat(
                [{"role": "system", "content": self._system_prompt(state)}]
                + list(state.get("messages") or []),
                tools=self._tool_definitions(state),
            )
        except Exception as exc:  # noqa: BLE001
            planner = dict(state.get("planner") or {})
            planner.update({"status": "unavailable", "message": str(exc)})
            state["planner"] = planner
            completed_tool_count = len(state.get("tools") or [])
            self._add_event(
                state,
                "skill",
                "error",
                "模型不可用",
                f"无法通过原生 tool calling 选择 Skill：{exc}",
                output={"summary": str(exc)},
            )
            self._add_event(
                state,
                "tool",
                "skipped",
                "没有可执行工具",
                "模型不可用，无法继续选择下一步工具或生成最终报告。",
                output={
                    "summary": "No further data tools ran.",
                    "completed_tool_count": completed_tool_count,
                },
            )
            return self._respond_to_user(state, llm_failure_user_message(exc, completed_tool_count))

        message = response.get("message") if isinstance(response.get("message"), dict) else {}
        assistant_message = {
            "role": "assistant",
            "content": message.get("content") or "",
        }
        if message.get("tool_calls"):
            assistant_message["tool_calls"] = message["tool_calls"]
        messages = list(state.get("messages") or [])
        messages.append(assistant_message)
        state["messages"] = messages
        planner = dict(state.get("planner") or {})
        planner.update(
            {
                "status": "ok",
                "provider": response.get("provider"),
                "model": response.get("model"),
                "usage": response.get("usage") or {},
            }
        )
        state["planner"] = planner

        tool_calls = (
            message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
        )
        state["pending_tool_calls"] = tool_calls
        if not tool_calls:
            content = str(message.get("content") or "").strip()
            if self._uses_langgraph_report_pipeline(state):
                pipeline = self._start_report_pipeline(state)
                if pipeline.get("status") == "scheduled":
                    return state
                if pipeline.get("outcome") == "report_pipeline_not_configured":
                    return self._respond_to_user(
                        state,
                        str(pipeline.get("summary") or "HTML report pipeline is not configured."),
                        response_status="error",
                        event_status="error",
                    )
                if pipeline.get("status") == "blocked":
                    state["messages"] = list(state.get("messages") or []) + [
                        {
                            "role": "system",
                            "content": json.dumps(pipeline, ensure_ascii=False, default=str),
                        }
                    ]
                    return state
            if content:
                if self._should_force_capability_inspection(state):
                    synthetic_call = self._synthetic_tool_call(
                        "inspect-agent-capabilities",
                        "inspect_agent_capabilities",
                        {"focus": state.get("prompt") or ""},
                    )
                    state["messages"] = list(state.get("messages") or []) + [
                        {"role": "assistant", "content": "", "tool_calls": [synthetic_call]}
                    ]
                    state["pending_tool_calls"] = [synthetic_call]
                    return state
                return self._respond_to_user(state, content)
            if not state.get("selected_skill_id") and not state.get("tools"):
                return self._respond_to_user(state, "")
            state["report_pipeline_phase"] = "synthesize"
            return state
        return state

    def _tools_node(self, state: AgentRuntimeState) -> AgentRuntimeState:
        tool_messages: list[dict[str, Any]] = []
        for tool_call in state.get("pending_tool_calls") or []:
            name, args = self._tool_call_name_args(tool_call)
            tool_call_id = str(tool_call.get("id") or f"tool-{len(tool_messages) + 1}")
            if name == "load_skill":
                content = self._run_load_skill(state, args)
            elif name == "resume_previous_run":
                content = self._run_resume_previous_run(state, args)
            elif name == "ask_user":
                if state.get("selected_skill_id") and not state.get("missing_params"):
                    content = {
                        "status": "ignored",
                        "summary": (
                            "load_skill already resolved all required inputs. "
                            "Do not pause to confirm resolved parameters; continue with source data tools."
                        ),
                        "resolved_params": state.get("skill_params") or {},
                    }
                else:
                    self._run_ask_user(state, args)
                    return state
            elif name == "respond_to_user":
                response_message = str(args.get("message") or "")
                if self._should_force_capability_inspection(state):
                    tool_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": name,
                            "content": json.dumps(
                                {
                                    "status": "ignored",
                                    "summary": (
                                        "Capability questions must inspect the runtime tool inventory before answering."
                                    ),
                                },
                                ensure_ascii=False,
                            ),
                        }
                    )
                    synthetic_call = self._synthetic_tool_call(
                        "inspect-agent-capabilities",
                        "inspect_agent_capabilities",
                        {"focus": state.get("prompt") or ""},
                    )
                    content = self._inspect_agent_capabilities(
                        state, {"focus": state.get("prompt") or ""}
                    )
                    state["messages"] = (
                        list(state.get("messages") or [])
                        + tool_messages
                        + [
                            {"role": "assistant", "content": "", "tool_calls": [synthetic_call]},
                            {
                                "role": "tool",
                                "tool_call_id": "inspect-agent-capabilities",
                                "name": "inspect_agent_capabilities",
                                "content": json.dumps(content, ensure_ascii=False, default=str),
                            },
                        ]
                    )
                    state["pending_tool_calls"] = []
                    return state
                if (
                    self._uses_langgraph_report_pipeline(state)
                    and state.get("selected_skill_id")
                    and state.get("tools")
                    and any(
                        token in response_message.casefold()
                        for token in (
                            "自动进入报告",
                            "进入报告构建",
                            "开始生成报告",
                            "生成 html",
                            "继续执行修订",
                            "最终发布",
                            "即将产出",
                            "report pipeline",
                            "generate the report",
                        )
                    )
                ):
                    pipeline = self._start_report_pipeline(state)
                    if pipeline.get("status") == "scheduled":
                        state["pending_tool_calls"] = []
                        return state
                self._respond_to_user(state, response_message)
                return state
            elif name == "inspect_agent_capabilities":
                content = self._inspect_agent_capabilities(state, args)
            elif name == "synthesize_artifact":
                if self._uses_langgraph_report_pipeline(state):
                    content = {
                        "status": "ignored",
                        "outcome": "terminal_node_owned_by_langgraph",
                        "summary": (
                            "synthesize_artifact is the terminal LangGraph node, not a planner "
                            "signal for ending data collection."
                        ),
                        "instruction": (
                            "Finish the remaining source-data calls, then stop issuing tool calls. "
                            "LangGraph will enter report_data_builder automatically."
                        ),
                    }
                    tool_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": name,
                            "content": json.dumps(content, ensure_ascii=False, default=str),
                        }
                    )
                    state["messages"] = list(state.get("messages") or []) + tool_messages
                    state["pending_tool_calls"] = []
                    return state
                content = self._check_evidence_gate_before_synthesis(state)
                if content.get("status") == "blocked":
                    tool_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": name,
                            "content": json.dumps(content, ensure_ascii=False, default=str),
                        }
                    )
                    continue
                state["report_pipeline_phase"] = "synthesize"
                state["messages"] = list(state.get("messages") or []) + tool_messages
                state["pending_tool_calls"] = []
                return state
            elif name in self.deps.tool_catalog():
                if self._uses_langgraph_report_pipeline(state) and name in {
                    self._required_report_data_builder(state),
                    self._required_report_tool(state),
                }:
                    content = {
                        "status": "ignored",
                        "outcome": "report_node_owned_by_langgraph",
                        "planner_tool_call_ignored": name,
                        "summary": (
                            f"Planner call to {name} was intercepted. "
                            "The generic LangGraph report nodes own builder and renderer execution."
                        ),
                        "instruction": (
                            "Finish source-data collection, then stop issuing tool calls so LangGraph "
                            "can enter report_data_builder automatically."
                        ),
                    }
                    tool_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": name,
                            "content": json.dumps(content, ensure_ascii=False, default=str),
                        }
                    )
                    state["messages"] = list(state.get("messages") or []) + tool_messages
                    state["pending_tool_calls"] = []
                    return state
                content = self._run_data_tool(state, name, args)
                if str(content.get("status") or "") == "needs_user_action":
                    return self._pause_for_external_action(state, name, content)
                if (
                    name in {"render_html_report", "render_markdown_report"}
                    and str(content.get("status") or "") not in SUCCESS_TOOL_STATUSES
                ):
                    if state.get("selected_skill_id") == (
                        "tiktok_us_bra_competitor_shop_analysis"
                    ):
                        return self._pause_for_external_action(
                            state,
                            name,
                            content,
                            reason_type="retryable_tool_failure",
                        )
                    report_label = "HTML" if name == "render_html_report" else "Markdown"
                    summary = str(
                        content.get("summary") or f"{report_label} report rendering failed."
                    )
                    return self._respond_to_user(
                        state,
                        (
                            f"{report_label} 报告生成失败，已停止本轮任务，避免重复调用 renderer。"
                            f"失败原因：{summary}"
                        ),
                        response_status="error",
                        event_status="error",
                    )
            else:
                content = {"status": "error", "summary": f"Unknown tool: {name}"}
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": name,
                    "content": json.dumps(content, ensure_ascii=False, default=str),
                }
            )
        state["messages"] = list(state.get("messages") or []) + tool_messages
        state["pending_tool_calls"] = []
        return state

    def _planner_tool_catalog(self) -> dict[str, dict[str, Any]]:
        return {
            name: metadata
            for name, metadata in self.deps.tool_catalog().items()
            if str(metadata.get("invocation_scope") or "planner") != "runtime_internal"
        }

    def _start_report_pipeline(self, state: AgentRuntimeState) -> dict[str, Any]:
        builder_name = self._required_report_data_builder(state)
        renderer_name = self._required_report_tool(state)
        if not builder_name:
            return {
                "status": "blocked",
                "outcome": "report_pipeline_not_configured",
                "summary": (
                    "The selected HTML Skill does not declare one blocking report-data builder."
                ),
                "instruction": (
                    "Add a required build_<workflow>_report_data tool before using the generic "
                    "LangGraph report pipeline."
                ),
            }
        gate = self._check_evidence_gate_before_report_builder(state, builder_name)
        if gate.get("status") == "blocked":
            state["report_pipeline_phase"] = ""
            return gate
        state["report_pipeline_builder"] = builder_name
        state["report_pipeline_renderer"] = renderer_name
        state["report_pipeline_phase"] = (
            ("analysis" if renderer_name == "render_html_report" else "render")
            if self._builder_is_current(state, builder_name)
            else "builder"
        )
        html_pipeline = renderer_name == "render_html_report"
        content = {
            "status": "scheduled",
            "outcome": "langgraph_report_pipeline_started",
            "summary": (
                "Data collection is complete. LangGraph will now execute the declared report-data "
                + (
                    "builder, deterministic metric analysis, evidence-linked insight synthesis, "
                    "local MCP chart rendering, and HTML renderer as independent nodes."
                    if html_pipeline
                    else "builder and Markdown renderer as independent runtime nodes."
                )
            ),
            "builder": builder_name,
            "analysis": "analyze_market_report",
            "insight_synthesis": "synthesize_report_insights",
            "chart_renderer": "render_report_charts",
            "renderer": renderer_name,
            "next_node": (
                "data_analysis"
                if state["report_pipeline_phase"] == "analysis"
                else "html_render"
                if state["report_pipeline_phase"] == "render"
                else "report_data_builder"
            ),
        }
        self._add_event(
            state,
            "tool",
            "ok",
            "进入通用报告流水线",
            content["summary"],
            data={
                "langgraph_node": True,
                "graph_node": "planner_executor",
                "next_node": content["next_node"],
                "builder": builder_name,
                "analysis": "analyze_market_report",
                "insight_synthesis": "synthesize_report_insights",
                "chart_renderer": "render_report_charts",
                "renderer": renderer_name,
            },
            output=content,
        )
        return content

    def _builder_is_current(self, state: AgentRuntimeState, builder_name: str) -> bool:
        tools = list(state.get("tools") or [])
        builder_index = -1
        source_index = -1
        for index, tool in enumerate(tools):
            if not isinstance(tool, dict) or str(tool.get("status") or "") not in SUCCESS_TOOL_STATUSES:
                continue
            name = str(tool.get("name") or "")
            if name == builder_name:
                builder_index = index
            elif not (
                name.startswith("build_")
                or name
                in {
                    "render_html_report",
                    "render_markdown_report",
                    "analyze_market_report",
                    "synthesize_report_insights",
                    "render_report_charts",
                    "review_html_report",
                    "red_team_html_report",
                    "join_report_approval",
                    *LEGACY_INTERNAL_REPORT_TOOL_NAMES,
                    "revise_html_report",
                }
            ):
                source_index = index
        return builder_index >= 0 and builder_index > source_index

    def _report_data_builder_node(self, state: AgentRuntimeState) -> AgentRuntimeState:
        builder_name = str(
            state.get("report_pipeline_builder") or self._required_report_data_builder(state)
        )
        if not builder_name:
            state["report_pipeline_phase"] = ""
            return self._respond_to_user(
                state,
                "HTML 报告流水线配置错误：当前 Skill 没有声明唯一且必需的 reportData Builder。",
                response_status="error",
                event_status="error",
            )
        gate = self._check_evidence_gate_before_report_builder(state, builder_name)
        if gate.get("status") == "blocked":
            state["report_pipeline_phase"] = ""
            state["messages"] = list(state.get("messages") or []) + [
                {
                    "role": "system",
                    "content": json.dumps(gate, ensure_ascii=False, default=str),
                }
            ]
            return state
        result = self._run_data_tool(
            state,
            builder_name,
            {},
            runtime_node="report_data_builder",
        )
        status = str(result.get("status") or "")
        if status == "needs_user_action":
            state["report_pipeline_phase"] = ""
            return self._pause_for_external_action(state, builder_name, result)
        if status not in SUCCESS_TOOL_STATUSES:
            state["report_pipeline_phase"] = ""
            state["messages"] = list(state.get("messages") or []) + [
                {
                    "role": "system",
                    "content": json.dumps(
                        {
                            **result,
                            "instruction": (
                                "The report-data builder node failed. Recover missing or invalid source "
                                "evidence, then stop issuing tool calls so LangGraph can retry the "
                                "report pipeline."
                            ),
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                }
            ]
            return state
        state["report_pipeline_phase"] = (
            "analysis"
            if str(state.get("report_pipeline_renderer") or "render_html_report")
            == "render_html_report"
            else "render"
        )
        return state

    def _analysis_is_current(self, state: AgentRuntimeState, builder_name: str) -> bool:
        builder_index = -1
        analysis_index = -1
        for index, tool in enumerate(state.get("tools") or []):
            if (
                not isinstance(tool, dict)
                or str(tool.get("status") or "") not in SUCCESS_TOOL_STATUSES
            ):
                continue
            name = str(tool.get("name") or "")
            if name == builder_name:
                builder_index = index
            elif name == "analyze_market_report":
                analysis_index = index
        return builder_index >= 0 and analysis_index > builder_index

    def _data_analysis_node(self, state: AgentRuntimeState) -> AgentRuntimeState:
        builder_name = str(
            state.get("report_pipeline_builder") or self._required_report_data_builder(state)
        )
        builder_tool = (
            self._latest_successful_tool(state, builder_name) if builder_name else None
        )
        if not builder_tool:
            state["report_pipeline_phase"] = "builder"
            return state
        if self._analysis_is_current(state, builder_name):
            state["report_pipeline_phase"] = "insights"
            return state
        report_data = (
            builder_tool.get("data") if isinstance(builder_tool.get("data"), dict) else {}
        )
        skill_id = str(state.get("selected_skill_id") or "")
        available_metrics = (
            self.deps.available_report_metrics(skill_id)
            if self.deps.available_report_metrics
            else []
        )
        input_payload = {
            "reportData": report_data,
            "availableMetrics": available_metrics,
            "skill": {
                "skill_id": skill_id,
                "params": state.get("skill_params") or {},
                "prompt": str(state.get("resumed_task_prompt") or state.get("prompt") or ""),
            },
            "useLlm": bool(state.get("use_llm")),
        }
        started = time.time()
        event_id = f"tool-analyze_market_report-{len(state.get('tools') or []) + 1}"
        if self._emit_event:
            self._add_event(
                state,
                "tool",
                "running",
                "调用工具：数据分析 Agent",
                "正在从固定指标目录选择可解释的二级指标，并校验分母、周期与样本完整性。",
                tool="analyze_market_report",
                input_params=input_payload,
                data={
                    "label": "数据分析 Agent",
                    "status": "running",
                    "native_tool": "analyze_market_report",
                    "langgraph_node": True,
                    "graph_node": "data_analysis",
                    "timeout_scope": "independent_node",
                },
                event_id=event_id,
                stream_only=True,
            )
        try:
            if not self.deps.analyze_market_report:
                raise RuntimeError("analyze_market_report dependency is not configured")
            analysis = self.deps.analyze_market_report(input_payload)
            derived = (
                analysis.get("derived_metrics")
                if isinstance(analysis.get("derived_metrics"), list)
                else []
            )
            rejected = (
                analysis.get("rejected_metric_proposals")
                if isinstance(analysis.get("rejected_metric_proposals"), list)
                else []
            )
            status = "ok" if derived else "partial_ok"
            outcome = "calculated" if derived else "no_calculable_metrics"
            summary = (
                f"已计算 {len(derived)} 个二级指标；"
                f"{len(rejected)} 个提案因分母、周期、范围或样本约束未通过。"
            )
        except Exception as exc:  # noqa: BLE001
            analysis = {
                "schema_version": "derived_metric_data.v1",
                "skill_id": skill_id,
                "available_metrics": available_metrics,
                "metric_facts": report_data.get("metric_facts")
                if isinstance(report_data.get("metric_facts"), list)
                else [],
                "derived_metrics": [],
                "rejected_metric_proposals": [],
                "metric_gaps": [
                    {
                        "metric_id": None,
                        "reason_code": "analysis_node_error",
                        "message": str(exc),
                    }
                ],
                "calculation_audit": {
                    "calculator": "deterministic_metric_contracts",
                    "llm_can_calculate_values": False,
                    "status": "error",
                },
            }
            status = "partial_ok"
            outcome = "analysis_degraded"
            summary = (
                "二级指标节点执行失败，已记录缺口并继续渲染；"
                f"报告不得据此声称已获得二级指标：{exc}"
            )
        self._record_internal_tool_result(
            state,
            name="analyze_market_report",
            label="数据分析 Agent",
            status=status,
            outcome=outcome,
            summary=summary,
            input_payload=input_payload,
            data=analysis,
            duration_ms=int((time.time() - started) * 1000),
            event_id=event_id,
        )
        state["report_pipeline_phase"] = "insights"
        return state

    def _insight_synthesis_is_current(
        self, state: AgentRuntimeState, builder_name: str
    ) -> bool:
        builder_index = -1
        analysis_index = -1
        insight_index = -1
        for index, tool in enumerate(state.get("tools") or []):
            if (
                not isinstance(tool, dict)
                or str(tool.get("status") or "") not in SUCCESS_TOOL_STATUSES
            ):
                continue
            name = str(tool.get("name") or "")
            if name == builder_name:
                builder_index = index
            elif name == "analyze_market_report":
                analysis_index = index
            elif name == "synthesize_report_insights":
                insight_index = index
        return (
            builder_index >= 0
            and analysis_index > builder_index
            and insight_index > analysis_index
        )

    def _insight_synthesis_node(self, state: AgentRuntimeState) -> AgentRuntimeState:
        builder_name = str(
            state.get("report_pipeline_builder") or self._required_report_data_builder(state)
        )
        builder_tool = (
            self._latest_successful_tool(state, builder_name) if builder_name else None
        )
        if not builder_tool:
            state["report_pipeline_phase"] = "builder"
            return state
        if not self._analysis_is_current(state, builder_name):
            state["report_pipeline_phase"] = "analysis"
            return state
        if self._insight_synthesis_is_current(state, builder_name):
            state["report_pipeline_phase"] = "charts"
            return state

        report_data = (
            dict(builder_tool.get("data"))
            if isinstance(builder_tool.get("data"), dict)
            else {}
        )
        analysis_tool = self._latest_successful_tool(state, "analyze_market_report")
        analysis_data = (
            analysis_tool.get("data")
            if analysis_tool and isinstance(analysis_tool.get("data"), dict)
            else {}
        )
        if analysis_data:
            report_data["derived_metrics"] = (
                analysis_data.get("derived_metrics")
                if isinstance(analysis_data.get("derived_metrics"), list)
                else []
            )
            report_data["metric_gaps"] = (
                analysis_data.get("metric_gaps")
                if isinstance(analysis_data.get("metric_gaps"), list)
                else []
            )
            report_data["metric_analysis"] = {
                key: value
                for key, value in analysis_data.items()
                if key not in {"metric_facts", "derived_metrics", "metric_gaps"}
            }
        skill_id = str(state.get("selected_skill_id") or "")
        input_payload = {
            "reportData": report_data,
            "skill": {
                "skill_id": skill_id,
                "params": state.get("skill_params") or {},
                "prompt": str(state.get("resumed_task_prompt") or state.get("prompt") or ""),
            },
            "skillMarkdown": str((state.get("selected_skill") or {}).get("markdown") or ""),
            "useLlm": bool(state.get("use_llm")),
        }
        started = time.time()
        event_id = f"tool-synthesize_report_insights-{len(state.get('tools') or []) + 1}"
        if self._emit_event:
            self._add_event(
                state,
                "tool",
                "running",
                "调用工具：洞察生成 Agent",
                "正在把可用一级指标和已校验二级指标转写为有证据引用的业务结论。",
                tool="synthesize_report_insights",
                input_params={
                    "skill": input_payload["skill"],
                    "derived_metric_count": len(report_data.get("derived_metrics") or []),
                },
                data={
                    "label": "洞察生成 Agent",
                    "status": "running",
                    "native_tool": "synthesize_report_insights",
                    "langgraph_node": True,
                    "graph_node": "insight_synthesis",
                    "timeout_scope": "independent_node",
                },
                event_id=event_id,
                stream_only=True,
            )
        try:
            if not self.deps.synthesize_report_insights:
                raise RuntimeError("synthesize_report_insights dependency is not configured")
            narrative = self.deps.synthesize_report_insights(input_payload)
            sections = (
                narrative.get("sections")
                if isinstance(narrative, dict) and isinstance(narrative.get("sections"), list)
                else []
            )
            section_insight_count = sum(
                len(section.get("insights") or [])
                for section in sections
                if isinstance(section, dict)
            )
            chart_insights = (
                narrative.get("chart_insights")
                if isinstance(narrative, dict)
                and isinstance(narrative.get("chart_insights"), list)
                else []
            )
            insight_count = section_insight_count + len(chart_insights)
            internal_audit = (
                narrative.get("internal_audit")
                if isinstance(narrative, dict)
                and isinstance(narrative.get("internal_audit"), dict)
                else {}
            )
            displayed_chart_count = int(internal_audit.get("bound_chart_id_count") or 0)
            renderer_commentary_count = len(internal_audit.get("unbound_chart_ids") or [])
            status = "ok" if insight_count else "partial_ok"
            outcome = "insights_synthesized" if insight_count else "no_supported_insights"
            summary = (
                f"已生成 {len(sections)} 个综合章节、{section_insight_count} 条跨图结论、"
                f"{len(chart_insights)} 条逐图解读；"
                f"{displayed_chart_count} 张图表已有结构化解读，{renderer_commentary_count} 张图表需由 "
                "HTML Render 根据 chart_spec 补充解读。"
            )
        except Exception as exc:  # noqa: BLE001
            narrative = {
                "schema_version": "report_insight_narrative.v1",
                "skill_id": skill_id,
                "status": "error",
                "sections": [],
                "chart_insights": [],
                "internal_audit": {
                    "unsupported_dimensions_visible": False,
                    "error": str(exc),
                },
            }
            status = "partial_ok"
            outcome = "insight_synthesis_degraded"
            summary = (
                "洞察生成节点执行失败，HTML 仍可基于结构化证据生成；"
                f"不得把内部缺口转写到报告正文：{exc}"
            )
        self._record_internal_tool_result(
            state,
            name="synthesize_report_insights",
            label="洞察生成 Agent",
            status=status,
            outcome=outcome,
            summary=summary,
            input_payload={
                "skill": input_payload["skill"],
                "derived_metric_count": len(report_data.get("derived_metrics") or []),
            },
            data=narrative,
            duration_ms=int((time.time() - started) * 1000),
            event_id=event_id,
        )
        state["report_pipeline_phase"] = "charts"
        return state

    def _chart_render_is_current(self, state: AgentRuntimeState, builder_name: str) -> bool:
        builder_index = -1
        analysis_index = -1
        insight_index = -1
        chart_render_index = -1
        for index, tool in enumerate(state.get("tools") or []):
            if (
                not isinstance(tool, dict)
                or str(tool.get("status") or "") not in SUCCESS_TOOL_STATUSES
            ):
                continue
            name = str(tool.get("name") or "")
            if name == builder_name:
                builder_index = index
            elif name == "analyze_market_report":
                analysis_index = index
            elif name == "synthesize_report_insights":
                insight_index = index
            elif name == "render_report_charts":
                chart_render_index = index
        return (
            builder_index >= 0
            and analysis_index > builder_index
            and insight_index > analysis_index
            and chart_render_index > insight_index
        )

    def _chart_render_node(self, state: AgentRuntimeState) -> AgentRuntimeState:
        builder_name = str(
            state.get("report_pipeline_builder") or self._required_report_data_builder(state)
        )
        builder_tool = (
            self._latest_successful_tool(state, builder_name) if builder_name else None
        )
        if not builder_tool:
            state["report_pipeline_phase"] = "builder"
            return state
        if not self._analysis_is_current(state, builder_name):
            state["report_pipeline_phase"] = "analysis"
            return state
        if not self._insight_synthesis_is_current(state, builder_name):
            state["report_pipeline_phase"] = "insights"
            return state
        if self._chart_render_is_current(state, builder_name):
            state["report_pipeline_phase"] = "render"
            return state

        report_data = (
            dict(builder_tool.get("data"))
            if isinstance(builder_tool.get("data"), dict)
            else {}
        )
        analysis_tool = self._latest_successful_tool(state, "analyze_market_report")
        analysis_data = (
            analysis_tool.get("data")
            if analysis_tool and isinstance(analysis_tool.get("data"), dict)
            else {}
        )
        if analysis_data:
            report_data["derived_metrics"] = (
                analysis_data.get("derived_metrics")
                if isinstance(analysis_data.get("derived_metrics"), list)
                else []
            )
            report_data["metric_gaps"] = (
                analysis_data.get("metric_gaps")
                if isinstance(analysis_data.get("metric_gaps"), list)
                else []
            )
        output_dir = (
            self.deps.cache_dir()
            / "agent-runs"
            / str(state["run_id"])
            / "charts"
        )
        input_payload = {
            "reportData": report_data,
            "outputDir": str(output_dir),
            "skill": {
                "skill_id": str(state.get("selected_skill_id") or ""),
                "prompt": str(state.get("resumed_task_prompt") or state.get("prompt") or ""),
            },
        }
        started = time.time()
        event_id = f"tool-render_report_charts-{len(state.get('tools') or []) + 1}"
        if self._emit_event:
            self._add_event(
                state,
                "tool",
                "running",
                "调用工具：图表渲染",
                "正在把 Builder 的图表规格交给本机 Flint MCP 编译为静态 SVG。",
                tool="render_report_charts",
                input_params={
                    "chart_count": len(report_data.get("chart_specs") or []),
                    "skill": input_payload["skill"],
                },
                data={
                    "label": "图表渲染",
                    "status": "running",
                    "native_tool": "render_chart",
                    "langgraph_node": True,
                    "graph_node": "chart_render",
                    "timeout_scope": "independent_node",
                },
                event_id=event_id,
                stream_only=True,
            )
        try:
            if not self.deps.render_report_charts:
                raise RuntimeError("render_report_charts dependency is not configured")
            bundle = self.deps.render_report_charts(input_payload)
            summary_data = (
                bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}
            )
            rendered_count = int(summary_data.get("rendered_count") or 0)
            failed_count = int(summary_data.get("failed_count") or 0)
            skipped_count = int(summary_data.get("skipped_count") or 0)
            status = "ok" if rendered_count and not failed_count else "partial_ok"
            outcome = "charts_rendered" if rendered_count else "chart_render_degraded"
            summary = (
                f"Flint MCP 已渲染 {rendered_count} 张图；"
                f"{failed_count} 张失败，{skipped_count} 张由现有确定性渲染器处理。"
            )
        except Exception as exc:  # noqa: BLE001
            bundle = {
                "schema_version": "chart_render_bundle.v1",
                "renderer": "flint-mcp",
                "native_tool": "render_chart",
                "status": "partial_ok",
                "summary": {
                    "chart_spec_count": len(report_data.get("chart_specs") or []),
                    "requested_count": 0,
                    "rendered_count": 0,
                    "failed_count": len(report_data.get("chart_specs") or []),
                    "skipped_count": 0,
                },
                "charts": [],
                "skipped_charts": [
                    {
                        "chart_id": str(chart.get("id") or ""),
                        "status": "skipped",
                        "reason": "flint_mcp_unavailable",
                    }
                    for chart in report_data.get("chart_specs") or []
                    if isinstance(chart, dict) and chart.get("id")
                ],
                "error": str(exc),
                "fallback_policy": "existing deterministic server chart renderer",
            }
            status = "partial_ok"
            outcome = "chart_render_degraded"
            summary = (
                "本机 Flint MCP 图表渲染失败，已切换到现有确定性图表降级链路，"
                f"不会阻断报告发布：{exc}"
            )
        self._record_internal_tool_result(
            state,
            name="render_report_charts",
            label="图表渲染",
            status=status,
            outcome=outcome,
            summary=summary,
            input_payload={
                "chart_count": len(report_data.get("chart_specs") or []),
                "skill": input_payload["skill"],
            },
            data=bundle,
            duration_ms=int((time.time() - started) * 1000),
            event_id=event_id,
            native_tool="render_chart",
        )
        state["report_pipeline_phase"] = "render"
        return state

    def _html_render_node(self, state: AgentRuntimeState) -> AgentRuntimeState:
        builder_name = str(
            state.get("report_pipeline_builder") or self._required_report_data_builder(state)
        )
        renderer_name = str(
            state.get("report_pipeline_renderer") or self._required_report_tool(state)
        )
        if not builder_name or not self._latest_successful_tool(state, builder_name):
            state["report_pipeline_phase"] = "builder"
            return state
        if renderer_name == "render_html_report" and not self._analysis_is_current(
            state, builder_name
        ):
            state["report_pipeline_phase"] = "analysis"
            return state
        if renderer_name == "render_html_report" and not self._chart_render_is_current(
            state, builder_name
        ):
            state["report_pipeline_phase"] = "charts"
            return state
        result = self._run_data_tool(
            state,
            renderer_name,
            {},
            runtime_node="html_render",
        )
        status = str(result.get("status") or "")
        if status == "needs_user_action":
            state["report_pipeline_phase"] = ""
            return self._pause_for_external_action(state, renderer_name, result)
        if status not in SUCCESS_TOOL_STATUSES:
            state["report_pipeline_phase"] = ""
            if state.get("selected_skill_id") == "tiktok_us_bra_competitor_shop_analysis":
                return self._pause_for_external_action(
                    state,
                    renderer_name,
                    result,
                    reason_type="retryable_tool_failure",
                )
            report_label = "HTML" if renderer_name == "render_html_report" else "Markdown"
            summary = str(result.get("summary") or f"{report_label} report rendering failed.")
            return self._respond_to_user(
                state,
                (
                    f"{report_label} 报告生成失败，已停止本轮任务，避免重复调用 renderer。"
                    f"失败原因：{summary}"
                ),
                response_status="error",
                event_status="error",
            )
        rendered_data = result.get("data") if isinstance(result.get("data"), dict) else {}
        content_key = "html" if renderer_name == "render_html_report" else "markdown"
        if not (
            isinstance(rendered_data.get(content_key), str)
            and rendered_data.get(content_key)
            and rendered_data.get("report_file_path")
        ):
            state["report_pipeline_phase"] = ""
            self._add_event(
                state,
                "artifact",
                "error",
                f"{renderer_name} 未生成可发布产物",
                f"renderer 返回成功状态，但没有生成 {content_key} 内容或报告文件。",
                data={"langgraph_node": True, "graph_node": "html_render"},
                output={
                    "status": status,
                    "summary": result.get("summary"),
                    "data": rendered_data,
                },
            )
            return self._respond_to_user(
                state,
                (
                    f"{content_key.upper()} 报告生成失败：renderer 虽返回成功状态，但没有生成可发布文件。"
                    "已停止本轮任务，避免把空产物标记为成功，也不会再改用固定模板。"
                ),
                response_status="error",
                event_status="error",
            )
        state["report_pipeline_phase"] = (
            "" if renderer_name == "render_html_report" else "synthesize"
        )
        return state

    def _latest_html_report_tool(
        self, state: AgentRuntimeState
    ) -> dict[str, Any] | None:
        for tool in reversed(state.get("tools") or []):
            if (
                str(tool.get("name") or "")
                in {"render_html_report", "revise_html_report"}
                and str(tool.get("status") or "") in SUCCESS_TOOL_STATUSES
                and isinstance(tool.get("data"), dict)
                and isinstance(tool["data"].get("html"), str)
                and tool["data"].get("html")
            ):
                return tool
        return None

    @staticmethod
    def _report_data_from_rendered_result(rendered_data: dict[str, Any]) -> dict[str, Any]:
        for key in (
            "competitor_product_report_data",
            "hot_product_pain_report_data",
            "tiktok_competitor_shop_report_data",
            "tiktok_new_product_report_data",
            "market_report_data",
            "trend_report_data",
        ):
            value = rendered_data.get(key)
            if isinstance(value, dict) and value:
                return value
        return {}

    def _report_approval_metadata(
        self,
        state: AgentRuntimeState,
        *,
        status: str,
        approved: bool,
        published_without_approval: bool,
    ) -> dict[str, Any]:
        reviews = list(state.get("report_reviews") or [])
        red_teams = list(state.get("report_red_teams") or [])
        revisions = list(state.get("report_revisions") or [])
        return {
            "enabled": True,
            "policy": "two_parallel_review_rounds",
            "orchestrator": "langgraph_nodes",
            "status": status,
            "approved": approved,
            "published_without_approval": published_without_approval,
            "review_count": len(reviews),
            "red_team_count": len(red_teams),
            "revision_count": len(revisions),
            "render_version_count": int(state.get("report_render_version") or 1),
            "reviews": reviews,
            "red_teams": red_teams,
            "revisions": revisions,
        }

    def _finalize_html_report(
        self,
        state: AgentRuntimeState,
        *,
        status: str,
        approved: bool,
        published_without_approval: bool,
    ) -> dict[str, Any]:
        report_tool = self._latest_html_report_tool(state)
        if not report_tool:
            state["report_approval_phase"] = ""
            return {}
        data = dict(report_tool.get("data") or {})
        html_content = str(data.get("html") or "")
        report_file_path = self.deps.write_text(state["run_id"], "report.html", html_content)
        approval = self._report_approval_metadata(
            state,
            status=status,
            approved=approved,
            published_without_approval=published_without_approval,
        )
        html_analysis = (
            dict(data.get("html_analysis"))
            if isinstance(data.get("html_analysis"), dict)
            else {"enabled": True, "status": "ok"}
        )
        html_analysis["approval"] = approval
        data["html_analysis"] = html_analysis
        data["report_file_path"] = report_file_path
        data["approval"] = approval
        report_tool["data"] = data
        report_tool["report_file_path"] = report_file_path
        state["report_approval_phase"] = "publish"
        planner = dict(state.get("planner") or {})
        planner["report_approval"] = approval
        state["planner"] = planner
        return approval

    def _record_internal_tool_result(
        self,
        state: AgentRuntimeState,
        *,
        name: str,
        label: str,
        status: str,
        outcome: str,
        summary: str,
        input_payload: dict[str, Any],
        data: dict[str, Any],
        duration_ms: int,
        event_id: str,
        native_tool: str = "",
    ) -> dict[str, Any]:
        tool_index = len(state.get("tools") or []) + 1
        graph_node = {
            "analyze_market_report": "data_analysis",
            "synthesize_report_insights": "insight_synthesis",
            "render_report_charts": "chart_render",
            "review_html_report": "report_review",
            "red_team_html_report": "report_red_team",
            "join_report_approval": "approval_join",
            "revise_html_report": "html_revision",
        }.get(name, name)
        result = {
            "name": name,
            "label": label,
            "status": status,
            "outcome": outcome,
            "summary": summary,
            "duration_ms": duration_ms,
            "input": input_payload,
            "data": data,
            "runtime": {
                "engine": "langgraph",
                "node": graph_node,
                "timeout_scope": "independent_node",
            },
        }
        result["file_path"] = self.deps.write_json(
            state["run_id"],
            f"tool-{tool_index:02d}-{name}.json",
            result,
        )
        tools = list(state.get("tools") or [])
        tools.append(result)
        state["tools"] = tools
        planner = dict(state.get("planner") or {})
        planner["planned_tools"] = [str(tool.get("name")) for tool in tools if tool.get("name")]
        state["planner"] = planner
        event_status = "ok" if status in SUCCESS_TOOL_STATUSES else "error"
        self._add_event(
            state,
            "tool",
            event_status,
            f"调用工具：{label}",
            summary,
            tool=name,
            duration_ms=duration_ms,
            data={
                "label": label,
                "status": status,
                "outcome": outcome,
                "native_tool": native_tool or name,
                "langgraph_node": True,
                "graph_node": graph_node,
                "timeout_scope": "independent_node",
            },
            input_params=input_payload,
            output={
                "status": status,
                "outcome": outcome,
                "summary": summary,
                "data": data,
            },
            file_path=str(result.get("file_path") or ""),
            event_id=event_id if self._emit_event else None,
        )
        return result

    def _parallel_approval_tool_result(
        self,
        state: AgentRuntimeState,
        *,
        name: str,
        label: str,
        graph_node: str,
        status: str,
        outcome: str,
        summary: str,
        input_payload: dict[str, Any],
        data: dict[str, Any],
        duration_ms: int,
        event_id: str,
        tool_index: int,
    ) -> dict[str, Any]:
        result = {
            "name": name,
            "label": label,
            "status": status,
            "outcome": outcome,
            "summary": summary,
            "duration_ms": duration_ms,
            "input": input_payload,
            "data": data,
            "runtime": {
                "engine": "langgraph",
                "node": graph_node,
                "timeout_scope": "independent_node",
                "parallel_group": f"report_approval_round_{input_payload['review_round']}",
            },
        }
        result["file_path"] = self.deps.write_json(
            state["run_id"],
            f"tool-{tool_index:02d}-{name}.json",
            result,
        )
        event = self._add_event(
            state,
            "tool",
            "ok" if status in SUCCESS_TOOL_STATUSES else "error",
            f"调用工具：{label}",
            summary,
            tool=name,
            duration_ms=duration_ms,
            data={
                "label": label,
                "status": status,
                "outcome": outcome,
                "native_tool": name,
                "langgraph_node": True,
                "graph_node": graph_node,
                "timeout_scope": "independent_node",
                "parallel_group": f"report_approval_round_{input_payload['review_round']}",
            },
            input_params=input_payload,
            output={
                "status": status,
                "outcome": outcome,
                "summary": summary,
                "data": data,
            },
            file_path=str(result.get("file_path") or ""),
            event_id=event_id,
            stream_only=True,
        )
        return {"tool": result, "event": event}

    def _report_review_node(self, state: AgentRuntimeState) -> AgentRuntimeState:
        report_tool = self._latest_html_report_tool(state)
        review_round = max(1, int(state.get("report_review_round") or 1))
        render_version = max(1, int(state.get("report_render_version") or 1))
        report_data = dict((report_tool or {}).get("data") or {})
        input_payload = {
            "review_round": review_round,
            "render_version": render_version,
            "source_tool": (report_tool or {}).get("name"),
            "source_report_file": report_data.get("report_file_path"),
            "graph_node": "report_review",
            "timeout_scope": "independent_node",
            "parallel_group": f"report_approval_round_{review_round}",
        }
        event_id = f"tool-review_html_report-r{review_round}-v{render_version}"
        self._add_event(
            state,
            "tool",
            "running",
            "调用工具：报告事实审批 Agent",
            f"正在核对 HTML V{render_version} 的数字、证据、范围和图文一致性（第 {review_round} 轮）。",
            tool="review_html_report",
            input_params=input_payload,
            data={
                "status": "running",
                "native_tool": "review_html_report",
                "langgraph_node": True,
                "graph_node": "report_review",
                "timeout_scope": "independent_node",
                "parallel_group": f"report_approval_round_{review_round}",
            },
            event_id=event_id,
            stream_only=True,
        )
        started = time.perf_counter()
        try:
            if not report_tool:
                raise RuntimeError("没有找到可审批的 HTML 版本")
            if not self.deps.review_html_report:
                raise RuntimeError("审批 Agent 未配置")
            review = self.deps.review_html_report(
                {
                    "html": report_data.get("html") or "",
                    "reportData": self._report_data_from_rendered_result(report_data),
                    "skillMarkdown": str((state.get("selected_skill") or {}).get("markdown") or ""),
                    "skillHtmlTemplate": str(
                        (state.get("selected_skill") or {}).get("html_template") or ""
                    ),
                    "reviewRound": review_round,
                }
            )
        except Exception as exc:  # noqa: BLE001
            review = {
                "round": review_round,
                "status": "error",
                "decision": "revise",
                "approved": False,
                "summary": f"审批 Agent 调用失败，按未通过进入返工：{compact_for_event(str(exc))}",
                "issues": [
                    {
                        "severity": "major",
                        "category": "approval_unavailable",
                        "location": "whole_report",
                        "repair_instruction": "重新检查整份报告后输出下一版本。",
                    }
                ],
            }
        if not isinstance(review, dict):
            review = {
                "round": review_round,
                "status": "invalid_response",
                "decision": "revise",
                "approved": False,
                "summary": "审批 Agent 未返回结构化结果，按未通过进入返工。",
                "issues": [],
            }
        approved = bool(review.get("approved")) or str(review.get("decision") or "").lower() in {
            "approve",
            "approved",
            "pass",
            "passed",
        }
        review["approved"] = approved
        review["decision"] = "approve" if approved else "revise"
        review["round"] = review_round
        review["review_type"] = "factual_consistency"
        outcome = "factual_audit_passed" if approved else "revision_requested"
        tool_status = "ok" if str(review.get("status") or "") == "ok" else "partial_ok"
        summary = str(
            review.get("summary")
            or ("审批通过。" if approved else f"第 {review_round} 轮审批未通过，进入返工。")
        )
        branch = self._parallel_approval_tool_result(
            state,
            name="review_html_report",
            label="报告事实审批 Agent",
            graph_node="report_review",
            status=tool_status,
            outcome=outcome,
            summary=summary,
            input_payload=input_payload,
            data={"review": review},
            duration_ms=int((time.perf_counter() - started) * 1000),
            event_id=event_id,
            tool_index=len(state.get("tools") or []) + 1,
        )
        return {"report_review_branch": {"review": review, **branch}}

    def _report_red_team_node(self, state: AgentRuntimeState) -> AgentRuntimeState:
        report_tool = self._latest_html_report_tool(state)
        review_round = max(1, int(state.get("report_review_round") or 1))
        render_version = max(1, int(state.get("report_render_version") or 1))
        report_data = dict((report_tool or {}).get("data") or {})
        input_payload = {
            "review_round": review_round,
            "render_version": render_version,
            "source_tool": (report_tool or {}).get("name"),
            "source_report_file": report_data.get("report_file_path"),
            "graph_node": "report_red_team",
            "timeout_scope": "independent_node",
            "parallel_group": f"report_approval_round_{review_round}",
        }
        event_id = f"tool-red_team_html_report-r{review_round}-v{render_version}"
        self._add_event(
            state,
            "tool",
            "running",
            "调用工具：报告红队 Agent",
            f"正在挑战 HTML V{render_version} 的关键业务结论（第 {review_round} 轮）。",
            tool="red_team_html_report",
            input_params=input_payload,
            data={
                "status": "running",
                "native_tool": "red_team_html_report",
                "langgraph_node": True,
                "graph_node": "report_red_team",
                "timeout_scope": "independent_node",
                "parallel_group": f"report_approval_round_{review_round}",
            },
            event_id=event_id,
            stream_only=True,
        )
        started = time.perf_counter()
        try:
            if not report_tool:
                raise RuntimeError("没有找到可审查的 HTML 版本")
            if not self.deps.red_team_html_report:
                raise RuntimeError("报告红队 Agent 未配置")
            red_team = self.deps.red_team_html_report(
                {
                    "html": report_data.get("html") or "",
                    "reportData": self._report_data_from_rendered_result(report_data),
                    "skillMarkdown": str(
                        (state.get("selected_skill") or {}).get("markdown") or ""
                    ),
                    "reviewRound": review_round,
                }
            )
        except Exception as exc:  # noqa: BLE001
            red_team = {
                "schema_version": "report_red_team_review.v1",
                "round": review_round,
                "status": "error",
                "decision": "revise",
                "approved": False,
                "summary": (
                    "报告红队 Agent 调用失败，按未通过进入返工："
                    f"{compact_for_event(str(exc))}"
                ),
                "findings": [],
                "issues": [
                    {
                        "severity": "major",
                        "category": "red_team_unavailable",
                        "location": "whole_report",
                        "repair_instruction": "仅保留证据链最完整的关键结论并删除无证据扩展。",
                    }
                ],
            }
        if not isinstance(red_team, dict):
            red_team = {
                "schema_version": "report_red_team_review.v1",
                "round": review_round,
                "status": "invalid_response",
                "decision": "revise",
                "approved": False,
                "summary": "报告红队 Agent 未返回结构化结果，按未通过进入返工。",
                "findings": [],
                "issues": [],
            }
        raw_decision = str(red_team.get("decision") or "").lower()
        approved = bool(red_team.get("approved")) or raw_decision in {
            "approve",
            "approved",
            "pass",
            "passed",
        }
        red_team.pop("evidence_requests", None)
        red_team["approved"] = approved
        red_team["decision"] = "approve" if approved else "revise"
        red_team["round"] = review_round
        red_team["review_type"] = "strategy_red_team"
        outcome = "red_team_passed" if approved else "revision_requested"
        tool_status = "ok" if str(red_team.get("status") or "") == "ok" else "partial_ok"
        summary = str(
            red_team.get("summary")
            or ("红队审查通过。" if approved else f"第 {review_round} 轮红队未通过，进入返工。")
        )
        branch = self._parallel_approval_tool_result(
            state,
            name="red_team_html_report",
            label="报告红队 Agent",
            graph_node="report_red_team",
            status=tool_status,
            outcome=outcome,
            summary=summary,
            input_payload=input_payload,
            data={"red_team": red_team},
            duration_ms=int((time.perf_counter() - started) * 1000),
            event_id=event_id,
            tool_index=len(state.get("tools") or []) + 2,
        )
        return {"report_red_team_branch": {"red_team": red_team, **branch}}

    def _approval_join_node(self, state: AgentRuntimeState) -> AgentRuntimeState:
        review_round = max(1, int(state.get("report_review_round") or 1))
        review_branch = dict(state.get("report_review_branch") or {})
        red_team_branch = dict(state.get("report_red_team_branch") or {})
        review = (
            dict(review_branch.get("review"))
            if isinstance(review_branch.get("review"), dict)
            else {
                "round": review_round,
                "status": "missing",
                "decision": "revise",
                "approved": False,
                "review_type": "factual_consistency",
                "summary": "事实审批分支没有返回结果。",
                "issues": [],
            }
        )
        red_team = (
            dict(red_team_branch.get("red_team"))
            if isinstance(red_team_branch.get("red_team"), dict)
            else {
                "round": review_round,
                "status": "missing",
                "decision": "revise",
                "approved": False,
                "review_type": "strategy_red_team",
                "summary": "红队审批分支没有返回结果。",
                "issues": [],
                "findings": [],
            }
        )
        branch_tools = [
            item
            for item in (review_branch.get("tool"), red_team_branch.get("tool"))
            if isinstance(item, dict)
        ]
        tools = [*(state.get("tools") or []), *branch_tools]
        state["tools"] = tools
        branch_events = [
            item
            for item in (review_branch.get("event"), red_team_branch.get("event"))
            if isinstance(item, dict)
        ]
        existing_events = list(state.get("events") or [])
        existing_event_ids = {str(item.get("id") or "") for item in existing_events}
        existing_events.extend(
            event
            for event in branch_events
            if str(event.get("id") or "") not in existing_event_ids
        )
        state["events"] = sorted(existing_events, key=lambda item: int(item.get("seq") or 0))
        planner = dict(state.get("planner") or {})
        planner["planned_tools"] = [str(tool.get("name")) for tool in tools if tool.get("name")]
        state["planner"] = planner
        state["report_review_branch"] = {}
        state["report_red_team_branch"] = {}

        return self._complete_parallel_approval_decision(
            state,
            review=review,
            red_team=red_team,
            review_round=review_round,
        )

    def _complete_parallel_approval_decision(
        self,
        state: AgentRuntimeState,
        *,
        review: dict[str, Any],
        red_team: dict[str, Any],
        review_round: int,
        event_suffix: str = "",
    ) -> AgentRuntimeState:
        state["report_reviews"] = [*(state.get("report_reviews") or []), review]
        state["report_red_teams"] = [*(state.get("report_red_teams") or []), red_team]
        if self.deps.join_report_approval:
            decision = self.deps.join_report_approval(
                {
                    "review_round": review_round,
                    "factual_review": review,
                    "red_team_review": red_team,
                }
            )
        else:
            decision = join_report_approval_result(
                {
                    "review_round": review_round,
                    "factual_review": review,
                    "red_team_review": red_team,
                }
            )
        both_approved = bool(decision.get("both_approved"))
        approval: dict[str, Any] = {}
        if both_approved:
            approval = self._finalize_html_report(
                state,
                status=f"approved_round_{review_round}",
                approved=True,
                published_without_approval=False,
            )
        else:
            state["report_approval_phase"] = "revision"
        outcome = str(
            decision.get("outcome")
            or ("parallel_approval_passed" if both_approved else "revision_requested")
        )
        summary = str(decision.get("summary") or "并行审批已汇合。")
        self._record_internal_tool_result(
            state,
            name="join_report_approval",
            label="报告审批汇合",
            status="ok",
            outcome=outcome,
            summary=summary,
            input_payload={
                "review_round": review_round,
                "factual_decision": review.get("decision"),
                "red_team_decision": red_team.get("decision"),
                "graph_node": "approval_join",
                "parallel_group": f"report_approval_round_{review_round}",
            },
            data={
                "factual_review": review,
                "red_team_review": red_team,
                "approval": approval,
            },
            duration_ms=0,
            event_id=f"tool-join_report_approval-r{review_round}{event_suffix}",
        )
        return state

    def _html_revision_node(self, state: AgentRuntimeState) -> AgentRuntimeState:
        report_tool = self._latest_html_report_tool(state)
        if not report_tool:
            state["report_approval_phase"] = ""
            return self._respond_to_user(
                state,
                "HTML 返工无法继续：没有找到上一版 HTML。",
                response_status="error",
                event_status="error",
            )
        revision_round = max(1, int(state.get("report_review_round") or 1))
        source_version = max(1, int(state.get("report_render_version") or 1))
        next_version = source_version + 1
        report_data = dict(report_tool.get("data") or {})
        reviews = list(state.get("report_reviews") or [])
        red_teams = list(state.get("report_red_teams") or [])
        fact_review = reviews[-1] if reviews else {}
        red_team = red_teams[-1] if red_teams else {}
        active_feedback = [
            item
            for item in (fact_review, red_team)
            if isinstance(item, dict)
            and int(item.get("round") or 0) == revision_round
            and not bool(item.get("approved"))
        ]
        if not active_feedback:
            active_feedback = [fact_review] if fact_review else []
        review = {
            "round": revision_round,
            "decision": "revise",
            "approved": False,
            "summary": "；".join(
                str(item.get("summary") or "") for item in active_feedback if item.get("summary")
            ),
            "issues": [
                issue
                for item in active_feedback
                for issue in (
                    item.get("issues")
                    if isinstance(item.get("issues"), list)
                    else item.get("findings")
                    if isinstance(item.get("findings"), list)
                    else []
                )
                if isinstance(issue, dict)
            ],
            "feedback_sources": [
                str(item.get("review_type") or "factual_consistency")
                for item in active_feedback
            ],
        }
        input_payload = {
            "revision_round": revision_round,
            "source_render_version": source_version,
            "target_render_version": next_version,
            "source_tool": report_tool.get("name"),
            "review_decision": review.get("decision"),
            "review_issue_count": len(review.get("issues") or []),
            "graph_node": "html_revision",
            "timeout_scope": "independent_node",
        }
        event_id = f"tool-revise_html_report-{len(state.get('tools') or []) + 1}"
        if self._emit_event:
            self._add_event(
                state,
                "tool",
                "running",
                "调用工具：HTML 渲染 Agent",
                f"正在根据第 {revision_round} 轮审批意见生成 HTML V{next_version}。",
                tool="revise_html_report",
                input_params=input_payload,
                data={
                    "status": "running",
                    "native_tool": "revise_html_report",
                    "langgraph_node": True,
                    "graph_node": "html_revision",
                    "timeout_scope": "independent_node",
                },
                event_id=event_id,
                stream_only=True,
            )
        started = time.perf_counter()
        try:
            if not self.deps.revise_html_report:
                raise RuntimeError("渲染 Agent 未配置")
            revision_output = self.deps.revise_html_report(
                {
                    "html": report_data.get("html") or "",
                    "reportData": self._report_data_from_rendered_result(report_data),
                    "skillMarkdown": str((state.get("selected_skill") or {}).get("markdown") or ""),
                    "skillHtmlTemplate": str(
                        (state.get("selected_skill") or {}).get("html_template") or ""
                    ),
                    "review": review,
                    "revisionRound": revision_round,
                    "chartRenderBundle": (
                        report_data.get("chart_render_bundle")
                        if isinstance(report_data.get("chart_render_bundle"), dict)
                        else {}
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001
            revision_output = {
                "html": report_data.get("html") or "",
                "revision": {
                    "round": revision_round,
                    "status": "error",
                    "applied": False,
                    "message": (
                        "渲染 Agent 调用失败，保留上一版有效 HTML："
                        f"{compact_for_event(str(exc))}"
                    ),
                },
            }
        if not isinstance(revision_output, dict):
            revision_output = {
                "html": report_data.get("html") or "",
                "revision": {
                    "round": revision_round,
                    "status": "invalid_response",
                    "applied": False,
                    "message": "渲染 Agent 未返回结构化结果，保留上一版有效 HTML。",
                },
            }
        revised_html = str(revision_output.get("html") or report_data.get("html") or "")
        revision = (
            dict(revision_output.get("revision"))
            if isinstance(revision_output.get("revision"), dict)
            else {}
        )
        revision["round"] = revision_round
        revision["render_version"] = next_version
        revisions = list(state.get("report_revisions") or [])
        revisions.append(revision)
        state["report_revisions"] = revisions
        state["report_render_version"] = next_version
        next_data = {
            **report_data,
            "html": revised_html,
            "renderer": "llm-html-revision",
        }
        version_file_path = self.deps.write_text(
            state["run_id"], f"report-v{next_version}.html", revised_html
        )
        next_data["report_file_path"] = version_file_path
        applied = bool(revision.get("applied"))
        summary = (
            f"已生成 HTML V{next_version}。"
            if applied
            else f"HTML V{next_version} 返工未应用，保留上一版有效内容继续流程。"
        )
        tool_status = "ok" if applied else "partial_ok"
        outcome = "revision_applied" if applied else "previous_html_retained"
        if revision_round >= REPORT_APPROVAL_MAX_ROUNDS:
            state["report_approval_phase"] = "complete"
        else:
            state["report_review_round"] = revision_round + 1
            state["report_approval_phase"] = "parallel_review"
            state["report_review_branch"] = {}
            state["report_red_team_branch"] = {}
        result = self._record_internal_tool_result(
            state,
            name="revise_html_report",
            label="HTML 渲染 Agent",
            status=tool_status,
            outcome=outcome,
            summary=summary,
            input_payload=input_payload,
            data=next_data,
            duration_ms=int((time.perf_counter() - started) * 1000),
            event_id=event_id,
        )
        if revision_round >= REPORT_APPROVAL_MAX_ROUNDS:
            approval = self._finalize_html_report(
                state,
                status="published_after_round_2_rejection",
                approved=False,
                published_without_approval=True,
            )
            result_data = dict(result.get("data") or {})
            result_data["approval"] = approval
            result["data"] = result_data
        return state

    def _synthesize_artifact_node(self, state: AgentRuntimeState) -> AgentRuntimeState:
        approval_status = (
            (state.get("planner") or {}).get("report_approval", {}).get("status")
        )
        if self.deps.execute_runtime_capability:
            operation_state: AgentRuntimeState | None = None

            def execute_operation(_payload: dict[str, Any]) -> dict[str, Any]:
                nonlocal operation_state
                operation_state = self._synthesize_artifact_operation(state)
                response = operation_state.get("response")
                return artifact_publication_result(
                    response if isinstance(response, dict) else {}
                )

            self.deps.execute_runtime_capability(
                "synthesize_artifact",
                {
                    "run_id": str(state.get("run_id") or ""),
                    "approval_status": approval_status,
                    "use_llm": bool(state.get("use_llm")),
                },
                execute_operation,
            )
            if operation_state is None:
                raise RuntimeError("Artifact synthesis runtime operation did not execute")
            return operation_state
        return self._synthesize_artifact_operation(state)

    def _synthesize_artifact_operation(self, state: AgentRuntimeState) -> AgentRuntimeState:
        state["report_pipeline_phase"] = ""
        state["report_approval_phase"] = "complete"
        evidence_gate = self._check_evidence_gate_before_synthesis(state)
        if evidence_gate.get("status") == "blocked":
            return self._respond_to_user(
                state,
                (
                    "最终 Artifact 生成被 Evidence Contract 阻止。"
                    f"{evidence_gate.get('summary') or ''}"
                ),
                response_status="error",
                event_status="error",
            )

        planner = dict(state.get("planner") or {})
        synthesize_meta = {
            "status": "running",
            "orchestrator": "langgraph_node",
            "graph_node": "synthesize_artifact",
        }
        planner["synthesize_artifact"] = synthesize_meta
        state["planner"] = planner
        self._add_event(
            state,
            "tool",
            "running",
            "调用工具：生成 Artifact",
            "报告数据、渲染和审批阶段已经结束，正在生成并挂载最终 Artifact。",
            tool="synthesize_artifact",
            data={
                "langgraph_node": True,
                "graph_node": "synthesize_artifact",
                "timeout_scope": "independent_node",
            },
            input_params={
                "approval_status": (
                    (state.get("planner") or {})
                    .get("report_approval", {})
                    .get("status")
                )
            },
            stream_only=True,
        )
        result = self._synthesize(state, llm_enabled=bool(state.get("use_llm")))
        response = result.get("response")
        publication = artifact_publication_result(
            response if isinstance(response, dict) else {}
        )
        output_files = (
            publication.get("output_files")
            if isinstance(publication.get("output_files"), list)
            else []
        )
        published = bool(publication.get("published"))
        synthesize_meta = {
            "status": str(publication.get("status") or ("published" if published else "error")),
            "orchestrator": "langgraph_node",
            "graph_node": "synthesize_artifact",
        }
        planner = dict(result.get("planner") or {})
        planner["synthesize_artifact"] = synthesize_meta
        result["planner"] = planner
        self._add_event(
            result,
            "tool",
            "ok" if published else "error",
            "调用工具：生成 Artifact",
            (
                "最终 Artifact 已生成并挂载报告产物。"
                if published
                else "最终 Artifact 节点未能挂载报告产物。"
            ),
            tool="synthesize_artifact",
            data={
                "langgraph_node": True,
                "graph_node": "synthesize_artifact",
                "timeout_scope": "independent_node",
            },
            output={
                "status": synthesize_meta["status"],
                "output_files": output_files,
            },
            file_path=str(
                next(
                    (
                        item.get("path")
                        for item in output_files
                        if isinstance(item, dict) and item.get("path")
                    ),
                    "",
                )
            ),
        )
        if isinstance(response, dict):
            response_planner = dict(response.get("planner") or {})
            response_planner["synthesize_artifact"] = synthesize_meta
            response["planner"] = response_planner
            response["events"] = result.get("events") or []
            self.deps.write_json(result["run_id"], "run.json", response)
        return result

    def _run_resume_previous_run(
        self, state: AgentRuntimeState, args: dict[str, Any]
    ) -> dict[str, Any]:
        started = time.time()
        source_run_id = str(
            args.get("run_id") or state.get("context_source_run_id") or ""
        ).strip()
        if not source_run_id:
            return {
                "status": "error",
                "summary": "No previous run is available in the current conversation context.",
                "instruction": "Answer normally or load a Skill for a new research task.",
            }
        source_run = self.deps.load_agent_run(source_run_id)
        if not source_run:
            return {
                "status": "error",
                "summary": f"Previous run was not found: {source_run_id}",
                "instruction": "Ask the user which saved task should be continued.",
            }
        previous_skill = (
            source_run.get("skill") if isinstance(source_run.get("skill"), dict) else {}
        )
        previous_pending = (
            source_run.get("pending") if isinstance(source_run.get("pending"), dict) else {}
        )
        skill_id = str(
            previous_skill.get("skill_id") or previous_pending.get("skill_id") or ""
        ).strip()
        selected_skill = self.deps.skill_registry().get(skill_id)
        if not skill_id or not selected_skill:
            return {
                "status": "error",
                "summary": "The previous run does not contain a reusable registered Skill.",
                "source_run_id": source_run_id,
                "instruction": (
                    "If the user wants new research, load the appropriate Skill. "
                    "Otherwise explain that this result has no resumable workflow."
                ),
            }

        previous_params = (
            previous_pending.get("resolved_params")
            if isinstance(previous_pending.get("resolved_params"), dict)
            else previous_skill.get("params")
            if isinstance(previous_skill.get("params"), dict)
            else {}
        )
        restored_tools = [
            dict(tool) for tool in source_run.get("tools") or [] if isinstance(tool, dict)
        ]
        restored_evidence_gaps = [
            dict(gap)
            for gap in source_run.get("evidence_gaps") or []
            if isinstance(gap, dict)
        ]
        successful_tools = [
            str(tool.get("name") or "")
            for tool in restored_tools
            if str(tool.get("status") or "") in SUCCESS_TOOL_STATUSES
        ]
        failed_tools = [
            {
                "name": str(tool.get("name") or ""),
                "status": str(tool.get("status") or ""),
                "summary": str(tool.get("summary") or ""),
            }
            for tool in restored_tools
            if str(tool.get("status") or "") not in SUCCESS_TOOL_STATUSES
        ]
        source_prompt = str(source_run.get("prompt") or "").strip()
        current_instruction = str(state.get("prompt") or "").strip()
        state["resumed_task_prompt"] = (
            f"{source_prompt}\n\n用户继续指令：{current_instruction}"
            if source_prompt
            else current_instruction
        )
        state["selected_skill_id"] = skill_id
        state["selected_skill"] = selected_skill
        state["skill_params"] = dict(previous_params or {})
        state["missing_params"] = []
        state["tools"] = restored_tools
        state["evidence_gaps"] = restored_evidence_gaps
        state["checkpoint_source_run_id"] = source_run_id
        state["checkpoint_restored_tool_count"] = len(restored_tools)
        source_category = str(
            (previous_params or {}).get("category") or source_run.get("category") or ""
        ).strip()
        if source_category:
            state["category"] = source_category
            state["payload"]["category"] = source_category
        source_mode = str(source_run.get("mode") or "").strip().lower()
        if source_mode in {"market", "competitor"}:
            state["mode"] = source_mode
            state["payload"]["agentMode"] = source_mode
        merged_params = dict(previous_params or {})
        payload_params = (
            state["payload"].get("params")
            if isinstance(state["payload"].get("params"), dict)
            else {}
        )
        merged_params.update(
            {
                key: value
                for key, value in payload_params.items()
                if value is not None and value != ""
            }
        )
        state["skill_params"] = merged_params
        state["payload"]["params"] = merged_params
        skill_file_path = self.deps.write_text(
            state["run_id"],
            f"skill-{skill_id}.md",
            str(selected_skill.get("markdown") or ""),
        )
        state["skill_file_path"] = skill_file_path
        planner = dict(state.get("planner") or {})
        planner["selected_skill_id"] = skill_id
        planner["resumed_from_run_id"] = source_run_id
        state["planner"] = planner
        summary = (
            f"已从任务 {source_run_id} 恢复 Skill 和 {len(restored_tools)} 个工具记录，"
            f"其中 {len(successful_tools)} 个成功；后续只执行失败或缺失步骤。"
        )
        self._add_event(
            state,
            "skill",
            "ok",
            f"恢复任务：{selected_skill.get('name')}",
            summary,
            duration_ms=int((time.time() - started) * 1000),
            data={
                "skill_id": skill_id,
                "source_run_id": source_run_id,
                "native_tool": "resume_previous_run",
            },
            input_params=args,
            output={
                "restored_tool_count": len(restored_tools),
                "successful_tools": successful_tools,
                "failed_tools": failed_tools,
            },
            file_path=skill_file_path,
        )
        return {
            "status": "ok",
            "outcome": "previous_run_restored",
            "summary": summary,
            "source_run_id": source_run_id,
            "source_status": source_run.get("status"),
            "skill_id": skill_id,
            "resolved_params": merged_params,
            "successful_tools": successful_tools,
            "failed_tools": failed_tools,
            "instruction": (
                "The previous Skill and tool records are restored. Do not repeat successful calls. "
                "Retry the failed report tool or collect only evidence that is still missing, then publish normally."
            ),
        }

    def _run_load_skill(self, state: AgentRuntimeState, args: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        skill_id = str(args.get("skill_id") or state.get("forced_skill_id") or "").strip()
        registry = self.deps.skill_registry()
        selected_skill = registry.get(skill_id)
        if not selected_skill:
            return {
                "status": "error",
                "summary": f"Skill not found: {skill_id}",
                "available_skills": list(registry.keys()),
            }
        if (
            state.get("checkpoint_source_run_id")
            and state.get("selected_skill_id") == skill_id
            and state.get("selected_skill")
        ):
            return {
                "status": "ok",
                "outcome": "checkpoint_skill_reuse",
                "skill_id": skill_id,
                "skill_name": selected_skill.get("name"),
                "resolved_params": state.get("skill_params") or {},
                "missing_params": [],
                "instruction": (
                    "The checkpoint already restored this Skill and its parameters. "
                    "Continue with only the blocked or missing tool calls."
                ),
                "tool_policy": selected_skill.get("tool_policy") or [],
                "evidence_contract": selected_skill.get("evidence_contract") or [],
            }
        extracted_params = (
            args.get("extracted_params") if isinstance(args.get("extracted_params"), dict) else {}
        )
        skill_params, missing_params = self.deps.resolve_skill_params(
            selected_skill,
            state["payload"],
            extracted_params,
        )
        state["selected_skill_id"] = skill_id
        state["selected_skill"] = selected_skill
        state["skill_params"] = skill_params
        state["missing_params"] = missing_params
        resolved_category = str(skill_params.get("category") or "").strip()
        if resolved_category:
            state["category"] = resolved_category
        skill_file_path = self.deps.write_text(
            state["run_id"],
            f"skill-{skill_id}.md",
            str(selected_skill.get("markdown") or ""),
        )
        state["skill_file_path"] = skill_file_path
        if missing_params:
            state["clarification"] = self.deps.build_clarification(
                selected_skill,
                missing_params,
                skill_params,
                state["locale"],
            )
        else:
            state["clarification"] = {}
        status = "needs_input" if missing_params else "ok"
        message = (
            (state.get("clarification") or {}).get("message")
            if missing_params
            else f"已加载 {selected_skill.get('name')}。"
        )
        self._add_event(
            state,
            "skill",
            status,
            f"调用 Skill：{selected_skill.get('name')}",
            message or "",
            duration_ms=int((time.time() - started) * 1000),
            data={"skill_id": skill_id, "native_tool": "load_skill"},
            input_params=args,
            output={
                "selected_skill_id": skill_id,
                "resolved_params": skill_params,
                "missing_params": missing_params,
            },
            file_path=skill_file_path,
            event_id="skill" if self._emit_event else None,
        )
        planner = dict(state.get("planner") or {})
        planner["selected_skill_id"] = skill_id
        planner["missing_params"] = missing_params
        state["planner"] = planner
        return {
            "status": status,
            "skill_id": skill_id,
            "skill_name": selected_skill.get("name"),
            "resolved_params": skill_params,
            "missing_params": missing_params,
            "instruction": (
                "Required inputs are missing. Call ask_user before any data tool."
                if missing_params
                else "Skill loaded. Choose the next data tool or synthesize when evidence is enough."
            ),
            "skill_markdown": selected_skill.get("markdown"),
            "tool_policy": selected_skill.get("tool_policy") or [],
            "evidence_contract": selected_skill.get("evidence_contract") or [],
        }

    def _run_ask_user(self, state: AgentRuntimeState, args: dict[str, Any]) -> None:
        clarification = self._clarification_from_tool_args(state, args)
        state["clarification"] = clarification
        run_file_path = str(
            (self.deps.cache_dir() / "agent-runs" / state["run_id"] / "run.json").resolve()
        )
        output_files = self._build_pending_output_files(state, None)
        message_parts = [str(clarification.get("message") or "需要补齐参数后继续执行。")]
        questions = [
            str(question.get("question") or question.get("label") or question.get("field") or "")
            for question in clarification.get("questions", [])
            if isinstance(question, dict)
        ]
        if questions:
            message_parts.append("\n".join(f"- {question}" for question in questions if question))
        assistant_message = {
            "role": "assistant",
            "content": "\n".join(part for part in message_parts if part).strip(),
        }
        response = {
            "run_id": state["run_id"],
            "generated_at": state["generated_at"],
            "status": "needs_input",
            "mode": state["mode"],
            "category": state["category"],
            "prompt": state["prompt"],
            "planner": state.get("planner") or {},
            "events": state.get("events") or [],
            "tools": [],
            "message": assistant_message,
            "llm_analysis": {
                "enabled": state["use_llm"],
                "status": "not_requested",
                "message": "Waiting for required skill inputs.",
            },
            "file_path": run_file_path,
            "skill": {
                "skill_id": state.get("selected_skill_id"),
                "name": (state.get("selected_skill") or {}).get("name"),
                "status": "needs_input",
                "params": state.get("skill_params") or {},
                "missing_params": clarification.get("missing_params")
                or state.get("missing_params")
                or [],
                "file_path": state.get("skill_file_path") or "",
            },
            "pending": {
                "continue_run_id": state["run_id"],
                "skill_id": state.get("selected_skill_id"),
                "resolved_params": state.get("skill_params") or {},
                "missing_params": clarification.get("missing_params")
                or state.get("missing_params")
                or [],
                "questions": clarification.get("questions", []),
                "message": clarification.get("message"),
            },
            "output_files": output_files,
            "response_type": "needs_input",
            "runtime": {"engine": "langgraph", "pattern": "native_tool_call_loop"},
        }
        self.deps.write_json(state["run_id"], "run.json", response)
        state["assistant_message"] = assistant_message
        state["output_files"] = output_files
        state["response"] = response

    def _pause_for_external_action(
        self,
        state: AgentRuntimeState,
        tool_name: str,
        content: dict[str, Any],
        *,
        reason_type: str = "external_action",
    ) -> AgentRuntimeState:
        tools = [tool for tool in state.get("tools") or [] if isinstance(tool, dict)]
        blocked_result = next(
            (
                tool
                for tool in reversed(tools)
                if str(tool.get("name") or "") == tool_name
                and str(tool.get("status") or "") == "needs_user_action"
            ),
            {},
        )
        summary = str(
            content.get("summary")
            or blocked_result.get("summary")
            or "The external data provider requires user action."
        )
        if reason_type == "retryable_tool_failure":
            message = (
                f"报告生成已在可恢复断点暂停：{summary}"
                "请在当前结果上继续并回复“重试报告生成”；系统会恢复已完成的数据与整理结果，"
                "只重试失败的报告工具。"
            )
            question = "请回复“重试报告生成”从当前断点继续。"
            planner_status = "waiting_for_retry"
            llm_message = "Waiting to retry a failed report tool from checkpoint."
        else:
            message = (
                f"任务已在真实断点暂停：{summary}"
                "完成充值或认证后，在当前结果上继续并回复“已完成”；系统会恢复已完成的工具结果，"
                "只重试被阻塞或缺失的调用。"
            )
            question = "完成 FastMoss 充值或认证后，请回复“已完成”继续。"
            planner_status = "waiting_for_user_action"
            llm_message = "Waiting for external provider action before checkpoint resume."
        successful_tool_count = sum(
            str(tool.get("status") or "") in SUCCESS_TOOL_STATUSES for tool in tools
        )
        planner = dict(state.get("planner") or {})
        planner.update(
            {
                "status": planner_status,
                "message": summary,
                "planned_tools": [str(tool.get("name")) for tool in tools if tool.get("name")],
            }
        )
        state["planner"] = planner
        self._add_event(
            state,
            "message",
            "needs_input",
            "等待重试报告工具"
            if reason_type == "retryable_tool_failure"
            else "等待外部操作",
            compact_for_event(message),
            output={"message": message, "blocked_tool": tool_name},
        )
        run_file_path = str(
            (self.deps.cache_dir() / "agent-runs" / state["run_id"] / "run.json").resolve()
        )
        output_files = self._build_pending_output_files(state, None)
        assistant_message = {"role": "assistant", "content": message}
        response = {
            "run_id": state["run_id"],
            "generated_at": state["generated_at"],
            "status": "needs_input",
            "response_type": "needs_input",
            "mode": state["mode"],
            "category": state["category"],
            "prompt": state["prompt"],
            "planner": planner,
            "events": state.get("events") or [],
            "tools": tools,
            "evidence_gaps": state.get("evidence_gaps") or [],
            "message": assistant_message,
            "llm_analysis": {
                "enabled": state["use_llm"],
                "status": "not_requested",
                "message": llm_message,
            },
            "file_path": run_file_path,
            "skill": {
                "skill_id": state.get("selected_skill_id"),
                "name": (state.get("selected_skill") or {}).get("name"),
                "status": "needs_input",
                "params": state.get("skill_params") or {},
                "missing_params": [],
                "file_path": state.get("skill_file_path") or "",
            },
            "pending": {
                "continue_run_id": state["run_id"],
                "skill_id": state.get("selected_skill_id"),
                "resolved_params": state.get("skill_params") or {},
                "missing_params": [],
                "questions": [
                    {
                        "field": reason_type,
                        "question": question,
                    }
                ],
                "message": message,
                "reason_type": reason_type,
                "resume_supported": True,
                "blocked_tool": tool_name,
                "blocked_tool_input": blocked_result.get("input") or {},
                "completed_tool_count": successful_tool_count,
                "recorded_tool_count": len(tools),
            },
            "output_files": output_files,
            "runtime": {"engine": "langgraph", "pattern": "native_tool_call_loop"},
        }
        if state.get("context_source_run_id"):
            response["context_source_run_id"] = state["context_source_run_id"]
        if state.get("checkpoint_source_run_id"):
            response["resumed_from_run_id"] = state["checkpoint_source_run_id"]
        self.deps.write_json(state["run_id"], "run.json", response)
        state["assistant_message"] = assistant_message
        state["output_files"] = output_files
        state["response"] = response
        state["pending_tool_calls"] = []
        return state

    def _check_tool_policy(self, state: AgentRuntimeState, tool_name: str) -> dict[str, Any] | None:
        selected_skill = state.get("selected_skill")
        if not selected_skill:
            return None
        decision = evaluate_tool_policy(selected_skill, tool_name, is_data_tool=True)
        if decision.allowed:
            return None
        content = {
            "status": "blocked",
            "outcome": "tool_policy_blocked",
            "summary": decision.summary,
            "tool_policy": decision.to_dict(),
            "instruction": "Choose a tool allowed by the selected Skill's Tool Policy, or load a more appropriate Skill.",
        }
        self._add_event(
            state,
            "tool",
            "skipped",
            "Tool Policy 阻止工具调用",
            decision.summary,
            tool=tool_name,
            data={"native_tool": tool_name, "outcome": "tool_policy_blocked"},
            input_params={"tool": tool_name, "skill_id": state.get("selected_skill_id")},
            output=content,
        )
        return content

    def _tool_scope_block(
        self,
        state: AgentRuntimeState,
        tool_name: str,
        summary: str,
        *,
        outcome: str = "scope_preflight_blocked",
    ) -> dict[str, Any]:
        content = {
            "status": "blocked",
            "outcome": outcome,
            "summary": summary,
            "instruction": "Correct the scope or collect the prerequisite evidence before retrying.",
        }
        self._add_event(
            state,
            "tool",
            "skipped",
            "调用前范围检查阻止工具",
            summary,
            tool=tool_name,
            data={"native_tool": tool_name, "outcome": outcome},
            input_params={"tool": tool_name, "skill_id": state.get("selected_skill_id")},
            output=content,
        )
        return content

    def _check_tiktok_competitor_scope(
        self,
        state: AgentRuntimeState,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any] | None:
        if state.get("selected_skill_id") != "tiktok_us_bra_competitor_shop_analysis":
            return None
        def integer(value: Any, default: int = 0) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        filters = tool_input.get("filter") if isinstance(tool_input.get("filter"), dict) else {}
        category_id = str(filters.get("category_id") or "").strip()
        region = str(filters.get("region") or "").strip().upper()
        date_type = str(filters.get("date_type") or "").strip().lower()
        date_value = str(filters.get("date_value") or "").strip()
        bra_category_ids = resolved_bra_category_ids(list(state.get("tools") or []))

        if tool_name == FASTMOSS_COMPETITOR_RANKING_TOOL:
            if not bra_category_ids:
                return self._tool_scope_block(
                    state,
                    tool_name,
                    "Resolve a FastMoss L3 Bras category before requesting shop rankings.",
                )
            if region != "US":
                return self._tool_scope_block(
                    state, tool_name, "Competitor shop rankings must use filter.region=US."
                )
            if category_id in bra_category_ids and date_type == "month":
                if not re.fullmatch(r"\d{4}-\d{2}", date_value):
                    return self._tool_scope_block(
                        state,
                        tool_name,
                        "The preferred Bras L3 ranking requires a completed-month date_value in YYYY-MM format.",
                    )
                return None
            if category_id == WOMENS_UNDERWEAR_CATEGORY_ID and date_type == "week":
                preferred_empty = False
                for previous in state.get("tools") or []:
                    if not isinstance(previous, dict) or str(previous.get("name") or "") != tool_name:
                        continue
                    previous_input = (
                        previous.get("input") if isinstance(previous.get("input"), dict) else {}
                    )
                    previous_filter = (
                        previous_input.get("filter")
                        if isinstance(previous_input.get("filter"), dict)
                        else {}
                    )
                    if (
                        str(previous_filter.get("region") or "").upper() == "US"
                        and str(previous_filter.get("category_id") or "") in bra_category_ids
                        and str(previous_filter.get("date_type") or "").lower() == "month"
                        and str(previous.get("status") or "") == "empty"
                    ):
                        preferred_empty = True
                        break
                if not preferred_empty:
                    return self._tool_scope_block(
                        state,
                        tool_name,
                        "Women's Underwear L2 weekly ranking is allowed only after the US Bras L3 completed-month ranking returned empty.",
                    )
                if not re.fullmatch(r"\d{4}-W\d{2}", date_value):
                    return self._tool_scope_block(
                        state,
                        tool_name,
                        "The controlled L2 fallback requires a completed-week date_value in YYYY-Www format.",
                    )
                return None
            return self._tool_scope_block(
                state,
                tool_name,
                "Allowed ranking scopes are US Bras L3 completed month, or the controlled US Women's Underwear L2 completed-week fallback after an empty L3 result.",
            )

        if tool_name not in FASTMOSS_COMPETITOR_STANDARD_SHOP_TOOLS:
            return None
        params = state.get("skill_params") or {}
        candidate_limit = integer(params.get("shop_candidate_size"), 50)
        analysis_limit = integer(params.get("shop_analysis_count"), 10)
        try:
            preflight = competitor_shop_ranking_preflight(
                list(state.get("tools") or []),
                candidate_limit=candidate_limit,
                brand=str(params.get("brand") or "Hsia"),
            )
        except ValueError as exc:
            return self._tool_scope_block(state, tool_name, str(exc))
        candidates = [
            row for row in preflight.get("candidates") or [] if isinstance(row, dict)
        ]
        ranking_scope = (
            preflight.get("ranking_scope")
            if isinstance(preflight.get("ranking_scope"), dict)
            else {}
        )
        available_total = integer(ranking_scope.get("available_total"))
        raw_row_count = integer(ranking_scope.get("raw_row_count"))
        pages_collected = ranking_scope.get("pages_collected") or []
        candidate_pool_complete = (
            len(candidates) >= candidate_limit
            or (available_total > 0 and raw_row_count >= available_total)
            or (available_total == 0 and len(pages_collected) >= 5)
        )
        if len(candidates) < min(analysis_limit, candidate_limit) or not candidate_pool_complete:
            return self._tool_scope_block(
                state,
                tool_name,
                f"Complete the candidate ranking pool before the expensive shop analysis: "
                f"currently {len(candidates)}/{candidate_limit} external candidates across "
                f"{len(pages_collected)} accepted page(s).",
                outcome="candidate_pool_incomplete",
            )
        selected_ids = {
            str(row.get("seller_id") or "") for row in candidates[:analysis_limit]
        }
        seller_id = str(filters.get("seller_id") or tool_input.get("seller_id") or "").strip()
        if not seller_id or seller_id not in selected_ids:
            return self._tool_scope_block(
                state,
                tool_name,
                f"seller_id must be one of the fixed Top {analysis_limit} candidate shops: "
                + ", ".join(sorted(selected_ids)),
                outcome="seller_selection_mismatch",
            )
        if tool_name == FASTMOSS_COMPETITOR_PRODUCT_TOOL:
            page = max(1, integer(tool_input.get("page"), 1))
            pagesize = integer(tool_input.get("pagesize"), 10)
            orderby = (
                tool_input.get("orderby")
                if isinstance(tool_input.get("orderby"), list)
                else []
            )
            primary_sort = orderby[0] if orderby and isinstance(orderby[0], dict) else {}
            forbidden_filters = {
                key
                for key in ("category_id", "time_range_days", "start_date", "end_date")
                if filters.get(key) not in (None, "")
            }
            if forbidden_filters:
                return self._tool_scope_block(
                    state,
                    tool_name,
                    "shop_product_analysis product-list requests must be seller-only; "
                    "omit category_id, time_range_days, start_date, and end_date so the "
                    "Builder can classify returned rows by category.l3.id.",
                    outcome="product_scope_mismatch",
                )
            if (
                page > 3
                or pagesize != 10
                or str(primary_sort.get("field") or "") != "day28_gmv"
                or str(primary_sort.get("order") or "").lower() != "desc"
            ):
                return self._tool_scope_block(
                    state,
                    tool_name,
                    "shop_product_analysis must use pagesize=10, day28_gmv desc, "
                    "and bounded sequential pages 1-3.",
                    outcome="product_pagination_mismatch",
                )
        elif tool_name != "mcp__fastmoss__shop_base_info" and integer(
            filters.get("time_range_days")
        ) != 28:
            return self._tool_scope_block(
                state,
                tool_name,
                f"{tool_name.split('__')[-1]} must use time_range_days=28 for the fixed comparison window.",
                outcome="time_window_mismatch",
            )
        return None

    def _check_evidence_gate_before_synthesis(self, state: AgentRuntimeState) -> dict[str, Any]:
        gate = validate_evidence_contract(
            state.get("selected_skill"),
            prompt=state["prompt"],
            params=state.get("skill_params") or {},
            tools=state.get("tools") or [],
            success_statuses=SUCCESS_TOOL_STATUSES,
        )
        warn_gaps = gate.get("warn_gaps") or []
        block_gaps = gate.get("block_gaps") or []
        degradable_gaps = [
            gap for gap in block_gaps if str(gap.get("if_missing") or "") == "continue_with_gap"
        ]
        hard_block_gaps = [gap for gap in block_gaps if gap not in degradable_gaps]
        state["evidence_gaps"] = [*warn_gaps, *degradable_gaps]
        if gate.get("status") != "blocked":
            return gate
        if not hard_block_gaps:
            missing_tools = sorted(
                {str(gap.get("tool") or "") for gap in degradable_gaps if gap.get("tool")}
            )
            summary = (
                "Evidence Contract found missing evidence; the Artifact will be published in degraded mode: "
                + ", ".join(missing_tools)
            )
            content = {
                **gate,
                "status": "degraded",
                "outcome": "evidence_contract_degraded",
                "summary": summary,
                "degraded_evidence": degradable_gaps,
                "warn_evidence": warn_gaps,
                "recommended_tool_calls": missing_tools,
                "instruction": "Publish the available report and disclose all missing evidence.",
            }
            self._add_event(
                state,
                "artifact",
                "ok",
                "Evidence Contract 允许降级 Artifact",
                summary,
                input_params={
                    "skill_id": state.get("selected_skill_id"),
                    "tool_count": len(state.get("tools") or []),
                },
                output=content,
            )
            return content
        missing_tools = sorted(
            {str(gap.get("tool") or "") for gap in hard_block_gaps if gap.get("tool")}
        )
        summary = "Evidence Contract blocked synthesis. Missing required evidence: " + ", ".join(
            missing_tools
        )
        content = {
            "status": "blocked",
            "outcome": "evidence_contract_blocked",
            "summary": summary,
            "missing_evidence": hard_block_gaps,
            "degraded_evidence": degradable_gaps,
            "warn_evidence": warn_gaps,
            "recommended_tool_calls": missing_tools,
            "instruction": (
                "Call the missing data tool(s). When the evidence contract is satisfied, stop "
                "issuing tool calls so LangGraph can continue to the terminal Artifact node."
            ),
        }
        self._add_event(
            state,
            "artifact",
            "skipped",
            "Evidence Contract 阻止生成 Artifact",
            summary,
            input_params={
                "skill_id": state.get("selected_skill_id"),
                "tool_count": len(state.get("tools") or []),
            },
            output=content,
        )
        return content

    def _check_evidence_gate_before_html_render(self, state: AgentRuntimeState) -> dict[str, Any]:
        selected_skill = state.get("selected_skill")
        if not isinstance(selected_skill, dict):
            return {"status": "pass", "gaps": [], "block_gaps": [], "warn_gaps": []}
        source_rules = [
            rule
            for rule in selected_skill.get("evidence_contract") or []
            if isinstance(rule, dict) and str(rule.get("tool") or "") != "render_html_report"
        ]
        gate = validate_evidence_contract(
            {**selected_skill, "evidence_contract": source_rules},
            prompt=state["prompt"],
            params=state.get("skill_params") or {},
            tools=state.get("tools") or [],
            success_statuses=SUCCESS_TOOL_STATUSES,
        )
        warn_gaps = gate.get("warn_gaps") or []
        block_gaps = gate.get("block_gaps") or []
        degradable_gaps = [
            gap for gap in block_gaps if str(gap.get("if_missing") or "") == "continue_with_gap"
        ]
        hard_block_gaps = [gap for gap in block_gaps if gap not in degradable_gaps]
        state["evidence_gaps"] = [*warn_gaps, *degradable_gaps]
        if gate.get("status") != "blocked":
            return gate
        if not hard_block_gaps:
            missing_tools = sorted(
                {str(gap.get("tool") or "") for gap in degradable_gaps if gap.get("tool")}
            )
            summary = (
                "Evidence Contract found missing evidence; HTML rendering will continue in degraded mode: "
                + ", ".join(missing_tools)
            )
            content = {
                **gate,
                "status": "degraded",
                "outcome": "evidence_contract_degraded",
                "summary": summary,
                "degraded_evidence": degradable_gaps,
                "warn_evidence": warn_gaps,
                "recommended_tool_calls": missing_tools,
                "instruction": "Generate the report, disclose these gaps, and suppress only dependent conclusions.",
            }
            self._add_event(
                state,
                "tool",
                "ok",
                "Evidence Contract 降级生成 HTML 报告",
                summary,
                tool="render_html_report",
                input_params={
                    "skill_id": state.get("selected_skill_id"),
                    "tool_count": len(state.get("tools") or []),
                },
                output=content,
            )
            return content
        missing_tools = sorted(
            {str(gap.get("tool") or "") for gap in hard_block_gaps if gap.get("tool")}
        )
        summary = (
            "Evidence Contract blocked HTML rendering. Missing required evidence: "
            + ", ".join(missing_tools)
        )
        content = {
            "status": "blocked",
            "outcome": "evidence_contract_blocked",
            "summary": summary,
            "missing_evidence": hard_block_gaps,
            "degraded_evidence": degradable_gaps,
            "warn_evidence": warn_gaps,
            "recommended_tool_calls": missing_tools,
            "instruction": "Call the missing data tool(s) successfully before render_html_report.",
        }
        self._add_event(
            state,
            "tool",
            "skipped",
            "Evidence Contract 阻止 HTML renderer",
            summary,
            tool="render_html_report",
            input_params={
                "skill_id": state.get("selected_skill_id"),
                "tool_count": len(state.get("tools") or []),
            },
            output=content,
        )
        return content

    def _check_evidence_gate_before_report_builder(
        self,
        state: AgentRuntimeState,
        builder_name: str,
    ) -> dict[str, Any]:
        selected_skill = state.get("selected_skill")
        if not isinstance(selected_skill, dict):
            return {"status": "pass", "gaps": [], "block_gaps": [], "warn_gaps": []}
        pipeline_tools = {builder_name, self._required_report_tool(state)}
        source_rules = [
            rule
            for rule in selected_skill.get("evidence_contract") or []
            if isinstance(rule, dict) and str(rule.get("tool") or "") not in pipeline_tools
        ]
        gate = validate_evidence_contract(
            {**selected_skill, "evidence_contract": source_rules},
            prompt=state["prompt"],
            params=state.get("skill_params") or {},
            tools=state.get("tools") or [],
            success_statuses=SUCCESS_TOOL_STATUSES,
        )
        warn_gaps = gate.get("warn_gaps") or []
        block_gaps = gate.get("block_gaps") or []
        degradable_gaps = [
            gap for gap in block_gaps if str(gap.get("if_missing") or "") == "continue_with_gap"
        ]
        attempted_tools = {
            str(tool.get("name") or "")
            for tool in state.get("tools") or []
            if isinstance(tool, dict)
        }
        source_tool_names = {
            str(rule.get("tool") or "")
            for rule in source_rules
            if isinstance(rule, dict)
        }
        has_attempted_source = bool(attempted_tools & source_tool_names)
        unattempted_degradable_gaps = [
            gap
            for gap in degradable_gaps
            if not has_attempted_source
            and str(gap.get("tool") or "") not in attempted_tools
        ]
        attempted_degradable_gaps = [
            gap for gap in degradable_gaps if gap not in unattempted_degradable_gaps
        ]
        hard_block_gaps = [
            gap for gap in block_gaps if gap not in degradable_gaps
        ] + unattempted_degradable_gaps
        state["evidence_gaps"] = [*warn_gaps, *attempted_degradable_gaps]
        if gate.get("status") != "blocked":
            return gate
        missing_tools = sorted(
            {
                str(gap.get("tool") or "")
                for gap in (hard_block_gaps or attempted_degradable_gaps)
                if gap.get("tool")
            }
        )
        if not hard_block_gaps:
            return {
                **gate,
                "status": "degraded",
                "outcome": "evidence_contract_degraded",
                "summary": (
                    "Evidence Contract found missing source evidence; report-data building will "
                    "continue in degraded mode: " + ", ".join(missing_tools)
                ),
                "degraded_evidence": attempted_degradable_gaps,
                "warn_evidence": warn_gaps,
                "recommended_tool_calls": missing_tools,
            }
        content = {
            "status": "blocked",
            "outcome": "report_builder_source_evidence_blocked",
            "summary": (
                "Evidence Contract blocked report-data building. Missing required source evidence: "
                + ", ".join(missing_tools)
            ),
            "missing_evidence": hard_block_gaps,
            "degraded_evidence": attempted_degradable_gaps,
            "warn_evidence": warn_gaps,
            "recommended_tool_calls": missing_tools,
            "instruction": (
                "Call the missing source data tool(s), then stop issuing tool calls. "
                "Do not call the builder, renderer, or synthesize_artifact directly."
            ),
        }
        self._add_event(
            state,
            "tool",
            "skipped",
            "Evidence Contract 阻止 reportData Builder",
            content["summary"],
            tool=builder_name,
            data={
                "langgraph_node": True,
                "graph_node": "report_data_builder",
                "next_node": "planner_executor",
            },
            output=content,
        )
        self._add_event(
            state,
            "artifact",
            "skipped",
            "Evidence Contract 阻止生成 Artifact",
            content["summary"],
            data={
                "langgraph_node": True,
                "graph_node": "report_data_builder",
                "next_node": "planner_executor",
            },
            output=content,
        )
        return content

    def _check_evidence_gate_before_markdown_render(
        self, state: AgentRuntimeState
    ) -> dict[str, Any]:
        selected_skill = state.get("selected_skill")
        if not isinstance(selected_skill, dict):
            return {"status": "pass", "gaps": [], "block_gaps": [], "warn_gaps": []}
        source_rules = [
            rule
            for rule in selected_skill.get("evidence_contract") or []
            if isinstance(rule, dict) and str(rule.get("tool") or "") != "render_markdown_report"
        ]
        gate = validate_evidence_contract(
            {**selected_skill, "evidence_contract": source_rules},
            prompt=state["prompt"],
            params=state.get("skill_params") or {},
            tools=state.get("tools") or [],
            success_statuses=SUCCESS_TOOL_STATUSES,
        )
        warn_gaps = gate.get("warn_gaps") or []
        block_gaps = gate.get("block_gaps") or []
        degradable_gaps = [
            gap for gap in block_gaps if str(gap.get("if_missing") or "") == "continue_with_gap"
        ]
        hard_block_gaps = [gap for gap in block_gaps if gap not in degradable_gaps]
        state["evidence_gaps"] = [*warn_gaps, *degradable_gaps]
        if gate.get("status") != "blocked":
            return gate
        if not hard_block_gaps:
            missing_tools = sorted(
                {str(gap.get("tool") or "") for gap in degradable_gaps if gap.get("tool")}
            )
            summary = (
                "Evidence Contract found missing evidence; Markdown rendering will continue in degraded mode: "
                + ", ".join(missing_tools)
            )
            content = {
                **gate,
                "status": "degraded",
                "outcome": "evidence_contract_degraded",
                "summary": summary,
                "degraded_evidence": degradable_gaps,
                "warn_evidence": warn_gaps,
                "recommended_tool_calls": missing_tools,
                "instruction": "Generate the report, disclose these gaps, and suppress only dependent conclusions.",
            }
            self._add_event(
                state,
                "tool",
                "ok",
                "Evidence Contract 降级生成 Markdown 报告",
                summary,
                tool="render_markdown_report",
                input_params={
                    "skill_id": state.get("selected_skill_id"),
                    "tool_count": len(state.get("tools") or []),
                },
                output=content,
            )
            return content
        missing_tools = sorted(
            {str(gap.get("tool") or "") for gap in hard_block_gaps if gap.get("tool")}
        )
        summary = (
            "Evidence Contract blocked Markdown rendering. Missing required evidence: "
            + ", ".join(missing_tools)
        )
        content = {
            "status": "blocked",
            "outcome": "evidence_contract_blocked",
            "summary": summary,
            "missing_evidence": hard_block_gaps,
            "degraded_evidence": degradable_gaps,
            "warn_evidence": warn_gaps,
            "recommended_tool_calls": missing_tools,
            "instruction": "Call the missing data tool(s) successfully before render_markdown_report.",
        }
        self._add_event(
            state,
            "tool",
            "skipped",
            "Evidence Contract 阻止 Markdown renderer",
            summary,
            tool="render_markdown_report",
            input_params={
                "skill_id": state.get("selected_skill_id"),
                "tool_count": len(state.get("tools") or []),
            },
            output=content,
        )
        return content

    def _tool_results_for_synthesis(self, state: AgentRuntimeState) -> list[dict[str, Any]]:
        tool_results = list(state.get("tools") or [])
        evidence_gaps = state.get("evidence_gaps") or []
        if evidence_gaps:
            tool_results.append(
                {
                    "name": "evidence_gate",
                    "label": "Evidence Contract",
                    "status": "partial_ok",
                    "summary": f"{len(evidence_gaps)} evidence gap(s) must be disclosed in the final Artifact.",
                    "duration_ms": 0,
                    "input": {"skill_id": state.get("selected_skill_id")},
                    "data": {"gaps": evidence_gaps},
                }
            )
        return tool_results

    def _latest_successful_tool(
        self, state: AgentRuntimeState, tool_name: str
    ) -> dict[str, Any] | None:
        for tool in reversed(state.get("tools") or []):
            if (
                str(tool.get("name") or "") == tool_name
                and str(tool.get("status") or "") in SUCCESS_TOOL_STATUSES
            ):
                return tool
        return None

    def _apply_resolved_tool_params(
        self,
        state: AgentRuntimeState,
        tool_name: str,
        result: dict[str, Any],
    ) -> None:
        if str(result.get("status") or "") not in SUCCESS_TOOL_STATUSES:
            return
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        resolved = (
            data.get("resolved_params") if isinstance(data.get("resolved_params"), dict) else {}
        )
        skill_params = dict(state.get("skill_params") or {})
        updated = False
        if tool_name in {"sellersprite_product_node", "sellersprite_asin_detail"}:
            node_id_path = str(resolved.get("category_node_id") or "").strip()
            if re.fullmatch(r"\d+(?::\d+)*", node_id_path):
                skill_params["category_node_id"] = node_id_path
                node_label_path = str(resolved.get("category_node_label_path") or "").strip()
                if node_label_path:
                    skill_params["category_node_label_path"] = node_label_path
                resolution_mode = str(resolved.get("category_node_resolution_mode") or "").strip()
                if resolution_mode:
                    skill_params["category_node_resolution_mode"] = resolution_mode
                    skill_params["category_node_is_proxy"] = bool(
                        resolved.get("category_node_is_proxy")
                    )
                requested_query = str(resolved.get("category_node_requested_query") or "").strip()
                if requested_query:
                    skill_params["category_node_requested_query"] = requested_query
                updated = True
        elif tool_name == "sellersprite_market_product_concentration":
            for key in ("selected_product_asins", "candidate_product_asins"):
                values = resolved.get(key) if isinstance(resolved.get(key), list) else []
                normalized = [
                    str(value).strip().upper()
                    for value in values
                    if re.fullmatch(r"[A-Z0-9]{10}", str(value).strip().upper())
                ]
                if normalized:
                    skill_params[key] = list(dict.fromkeys(normalized))
                    updated = True
        elif tool_name == "sellersprite_review":
            input_payload = result.get("input") if isinstance(result.get("input"), dict) else {}
            asin = str(input_payload.get("asin") or "").strip().upper()
            candidate_asins = (
                skill_params.get("candidate_product_asins")
                if isinstance(skill_params.get("candidate_product_asins"), list)
                else []
            )
            if re.fullmatch(r"[A-Z0-9]{10}", asin) and (
                not candidate_asins or asin in candidate_asins
            ):
                reviewed = (
                    skill_params.get("reviewed_product_asins")
                    if isinstance(skill_params.get("reviewed_product_asins"), list)
                    else []
                )
                skill_params["reviewed_product_asins"] = list(dict.fromkeys([*reviewed, asin]))
                updated = True
        if not updated:
            return
        state["skill_params"] = skill_params

        planner = dict(state.get("planner") or {})
        planner["resolved_params"] = skill_params
        state["planner"] = planner

    def _required_html_report_tool(self, state: AgentRuntimeState) -> str:
        skill = state.get("selected_skill")
        rules = skill.get("evidence_contract") if isinstance(skill, dict) else []
        if not isinstance(rules, list):
            return ""
        for rule in rules:
            if (
                isinstance(rule, dict)
                and str(rule.get("tool") or "") == "render_html_report"
                and str(rule.get("severity") or "").lower() == "block"
            ):
                return "render_html_report"
        return ""

    def _required_report_data_builder(self, state: AgentRuntimeState) -> str:
        skill = state.get("selected_skill")
        rules = skill.get("evidence_contract") if isinstance(skill, dict) else []
        if not isinstance(rules, list):
            return ""
        candidates = {
            str(rule.get("tool") or "")
            for rule in rules
            if isinstance(rule, dict)
            and str(rule.get("tool") or "").startswith("build_")
            and str(rule.get("tool") or "").endswith(
                ("report_data", "brief_data")
            )
            and str(rule.get("severity") or "").lower() == "block"
        }
        if len(candidates) != 1:
            return ""
        builder_name = next(iter(candidates))
        if builder_name not in self.deps.tool_catalog():
            return ""
        policy = evaluate_tool_policy(state.get("selected_skill"), builder_name)
        return builder_name if policy.allowed and policy.policy == "required" else ""

    def _uses_langgraph_html_report_pipeline(self, state: AgentRuntimeState) -> bool:
        return bool(self._required_html_report_tool(state))

    def _uses_langgraph_report_pipeline(self, state: AgentRuntimeState) -> bool:
        return bool(self._required_report_data_builder(state)) and self._required_report_tool(
            state
        ) in {"render_html_report", "render_markdown_report"}

    def _required_report_tool(self, state: AgentRuntimeState) -> str:
        skill = state.get("selected_skill")
        rules = skill.get("evidence_contract") if isinstance(skill, dict) else []
        if isinstance(rules, list):
            for renderer in ("render_markdown_report", "render_html_report"):
                if any(
                    isinstance(rule, dict)
                    and str(rule.get("tool") or "") == renderer
                    and str(rule.get("severity") or "").lower() == "block"
                    for rule in rules
                ):
                    return renderer
        return "render_html_report"

    def _apply_evidence_gaps_to_artifact(
        self, state: AgentRuntimeState, artifact: dict[str, Any]
    ) -> dict[str, Any]:
        evidence_gaps = state.get("evidence_gaps") or []
        if not evidence_gaps:
            return artifact
        next_artifact = dict(artifact)
        gap_notes = [
            str(gap.get("artifact_requirement") or f"缺少 {gap.get('tool')} 证据。")
            for gap in evidence_gaps
            if isinstance(gap, dict)
        ]
        existing_risks = (
            next_artifact.get("risks") if isinstance(next_artifact.get("risks"), list) else []
        )
        next_artifact["risks"] = [*existing_risks, *gap_notes]
        next_artifact["evidence_gaps"] = evidence_gaps
        return next_artifact

    def _enrich_weekly_market_product_identity(self, state: AgentRuntimeState) -> None:
        if state.get("selected_skill_id") != "weekly_market_insight":
            return
        marketplace = (
            str(
                (state.get("skill_params") or {}).get("marketplace")
                or (state.get("payload") or {}).get("marketplace")
                or "US"
            )
            .strip()
            .upper()
        )
        candidates = find_product_identity_enrichment_candidates(
            list(state.get("tools") or []),
            marketplace=marketplace,
        )
        attempted_asins: set[str] = set()
        for tool in state.get("tools") or []:
            if (
                not isinstance(tool, dict)
                or str(tool.get("name") or "") != "sellersprite_asin_detail"
            ):
                continue
            tool_input = tool.get("input") if isinstance(tool.get("input"), dict) else {}
            request = (
                tool_input.get("request")
                if isinstance(tool_input.get("request"), dict)
                else tool_input
            )
            asin = str(request.get("asin") or tool_input.get("asin") or "").strip().upper()
            if asin:
                attempted_asins.add(asin)

        automatic_lookup_asins = {
            str(asin).strip().upper()
            for asin in state.get("product_identity_detail_lookup_asins") or []
            if str(asin).strip()
        }
        for candidate in candidates:
            asin = str(candidate.get("asin") or "").strip().upper()
            if not asin or asin in attempted_asins:
                continue
            if len(automatic_lookup_asins) >= DEFAULT_ASIN_DETAIL_BUDGET:
                break
            self._run_data_tool(state, "sellersprite_asin_detail", {"asin": asin})
            attempted_asins.add(asin)
            automatic_lookup_asins.add(asin)
            state["product_identity_detail_lookup_asins"] = sorted(automatic_lookup_asins)

    def _run_data_tool(
        self,
        state: AgentRuntimeState,
        tool_name: str,
        args: dict[str, Any],
        *,
        runtime_node: str = "",
    ) -> dict[str, Any]:
        if state.get("missing_params"):
            return {
                "status": "blocked",
                "summary": "Required Skill inputs are missing. Call ask_user before data tools.",
                "missing_params": state.get("missing_params"),
            }
        policy_block = self._check_tool_policy(state, tool_name)
        if policy_block:
            return policy_block
        if tool_name == "render_html_report":
            evidence_gate = self._check_evidence_gate_before_html_render(state)
            if evidence_gate.get("status") == "blocked":
                return evidence_gate
        if tool_name == "render_markdown_report":
            evidence_gate = self._check_evidence_gate_before_markdown_render(state)
            if evidence_gate.get("status") == "blocked":
                return evidence_gate
        if tool_name == "build_market_report_data":
            self._enrich_weekly_market_product_identity(state)
        if tool_name == "sellersprite_product_node":
            resolved_node = str(
                (state.get("skill_params") or {}).get("category_node_id") or ""
            ).strip()
            has_successful_resolution = False
            for tool in state.get("tools") or []:
                if not isinstance(tool, dict):
                    continue
                if str(tool.get("name") or "") not in {
                    "sellersprite_product_node",
                    "sellersprite_asin_detail",
                }:
                    continue
                if str(tool.get("status") or "") not in SUCCESS_TOOL_STATUSES:
                    continue
                data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
                tool_resolved = (
                    data.get("resolved_params")
                    if isinstance(data.get("resolved_params"), dict)
                    else {}
                )
                if str(tool_resolved.get("category_node_id") or "").strip() == resolved_node:
                    has_successful_resolution = True
                    break
            if resolved_node and has_successful_resolution:
                return {
                    "status": "ok",
                    "outcome": "already_resolved",
                    "summary": (
                        f"Category node `{resolved_node}` is already resolved; reuse it and do not call "
                        "sellersprite_product_node again."
                    ),
                    "data": {"resolved_params": {"category_node_id": resolved_node}},
                }
        started_index = len(state.get("tools") or []) + 1
        tool_catalog = self.deps.tool_catalog()
        label = tool_catalog.get(tool_name, {}).get("label", tool_name)
        tool_payload = self._payload_with_tool_args(state, tool_name, args)
        tool_category = str(tool_payload.get("category") or state["category"])
        tool_input = self.deps.tool_input_payload(tool_name, tool_category, tool_payload)
        scope_block = self._check_tiktok_competitor_scope(state, tool_name, tool_input)
        if scope_block:
            return scope_block
        if tool_name.startswith("build_"):
            restored_count = int(state.get("checkpoint_restored_tool_count") or 0)
            tools = [tool for tool in state.get("tools") or [] if isinstance(tool, dict)]
            new_source_tools = [
                tool
                for tool in tools[restored_count:]
                if not str(tool.get("name") or "").startswith("build_")
                and str(tool.get("name") or "")
                not in {
                    "render_html_report",
                    "render_markdown_report",
                    "analyze_market_report",
                    "synthesize_report_insights",
                    "render_report_charts",
                    "review_html_report",
                    "red_team_html_report",
                    "join_report_approval",
                    *LEGACY_INTERNAL_REPORT_TOOL_NAMES,
                    "revise_html_report",
                }
            ]
            successful_builder = next(
                (
                    tool
                    for tool in reversed(tools)
                    if str(tool.get("name") or "") == tool_name
                    and str(tool.get("status") or "") in SUCCESS_TOOL_STATUSES
                ),
                None,
            )
            if (
                state.get("checkpoint_source_run_id")
                and successful_builder is not None
                and not new_source_tools
            ):
                summary = (
                    f"Checkpoint reuse from run {state.get('checkpoint_source_run_id')}: "
                    f"{tool_name} already compiled the unchanged evidence; the builder was not rerun."
                )
                content = {
                    "status": successful_builder.get("status"),
                    "outcome": "checkpoint_reuse",
                    "summary": summary,
                    "file_path": successful_builder.get("file_path"),
                    "data": successful_builder.get("data"),
                    "recovery": {"checkpoint_reused": True, "tool_execution_skipped": True},
                }
                self._add_event(
                    state,
                    "tool",
                    "ok",
                    (
                        f"调用工具：{label}（复用断点）"
                        if runtime_node == "report_data_builder"
                        else "复用断点整理结果"
                    ),
                    summary,
                    tool=tool_name,
                    data={
                        "native_tool": tool_name,
                        "outcome": "checkpoint_reuse",
                        **(
                            {"langgraph_node": True, "graph_node": runtime_node}
                            if runtime_node
                            else {}
                        ),
                    },
                    input_params=tool_input,
                    output=content,
                    file_path=str(successful_builder.get("file_path") or ""),
                )
                return content
            canonical_input = json.dumps(
                tool_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
            )
            unchanged_failed_builder = next(
                (
                    tool
                    for tool in reversed(tools)
                    if str(tool.get("name") or "") == tool_name
                    and str(tool.get("status") or "") not in SUCCESS_TOOL_STATUSES
                    and json.dumps(
                        tool.get("input") if isinstance(tool.get("input"), dict) else {},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    )
                    == canonical_input
                ),
                None,
            )
            if unchanged_failed_builder is not None:
                return self._tool_scope_block(
                    state,
                    tool_name,
                    "The deterministic builder already failed with identical evidence and inputs. "
                    "Collect or correct the missing evidence before compiling again.",
                    outcome="unchanged_builder_retry_blocked",
                )
        if state.get("checkpoint_source_run_id") and tool_name.startswith("mcp__fastmoss__"):
            canonical_input = json.dumps(
                tool_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
            )
            checkpoint_match = next(
                (
                    tool
                    for tool in reversed(state.get("tools") or [])
                    if isinstance(tool, dict)
                    and str(tool.get("name") or "") == tool_name
                    and str(tool.get("status") or "") in SUCCESS_TOOL_STATUSES
                    and json.dumps(
                        tool.get("input") if isinstance(tool.get("input"), dict) else {},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    )
                    == canonical_input
                ),
                None,
            )
            if checkpoint_match is not None:
                summary = (
                    f"Checkpoint reuse from run {state.get('checkpoint_source_run_id')}: "
                    f"{tool_name} with identical inputs already succeeded; no remote API call was made."
                )
                content = {
                    "status": checkpoint_match.get("status"),
                    "outcome": "checkpoint_reuse",
                    "summary": summary,
                    "file_path": checkpoint_match.get("file_path"),
                    "data": checkpoint_match.get("data"),
                    "recovery": {"checkpoint_reused": True, "remote_call_made": False},
                }
                self._add_event(
                    state,
                    "tool",
                    "ok",
                    "复用断点工具结果",
                    summary,
                    tool=tool_name,
                    data={"native_tool": tool_name, "outcome": "checkpoint_reuse"},
                    input_params=tool_input,
                    output=content,
                    file_path=str(checkpoint_match.get("file_path") or ""),
                )
                return content
        if tool_name == "sellersprite_review" and state.get("selected_skill_id") in {
            "hot_product_pain_analysis",
            "product_design_research",
        }:
            candidate_asins = (state.get("skill_params") or {}).get("candidate_product_asins")
            requested_asin = str(tool_input.get("asin") or "").strip().upper()
            if not isinstance(candidate_asins, list) or not candidate_asins:
                return {
                    "status": "blocked",
                    "outcome": "candidate_selection_required",
                    "summary": "Call sellersprite_market_product_concentration first and use its relevant candidate ASINs.",
                }
            if requested_asin not in candidate_asins:
                return {
                    "status": "blocked",
                    "outcome": "category_mismatch_blocked",
                    "summary": f"ASIN {requested_asin or '(missing)'} is not in the category-validated candidate pool.",
                    "candidate_product_asins": candidate_asins,
                }
            reviewed_asins = (state.get("skill_params") or {}).get("reviewed_product_asins")
            if isinstance(reviewed_asins, list) and requested_asin in reviewed_asins:
                return {
                    "status": "blocked",
                    "outcome": "duplicate_review_blocked",
                    "summary": f"ASIN {requested_asin} already has a successful balanced review sample; continue with the next candidate.",
                }
        tool_event_id = f"tool-{tool_name}-{started_index}"
        event_title = f"调用工具：{label}"
        if self._emit_event:
            self._add_event(
                state,
                "tool",
                "running",
                event_title,
                f"正在执行 {label}，整理输入参数并等待数据返回。",
                tool=tool_name,
                input_params=tool_input,
                data={
                    "label": label,
                    "status": "running",
                    "native_tool": tool_name,
                    **(
                        {"langgraph_node": True, "graph_node": runtime_node}
                        if runtime_node
                        else {}
                    ),
                },
                event_id=tool_event_id,
                stream_only=True,
            )
        result = self.deps.execute_tool(tool_name, tool_category, tool_payload)
        if runtime_node:
            result = dict(result)
            result["runtime"] = {
                "engine": "langgraph",
                "node": runtime_node,
                "timeout_scope": "independent_node",
            }
        if (
            tool_name == "render_html_report"
            and str(result.get("status") or "") in SUCCESS_TOOL_STATUSES
        ):
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            html_content = data.get("html") if isinstance(data.get("html"), str) else ""
            if html_content:
                target_render_version = 1
                report_file_path = self.deps.write_text(
                    state["run_id"],
                    f"report-v{target_render_version}.html",
                    html_content,
                )
                data["report_file_path"] = report_file_path
                html_analysis = (
                    dict(data.get("html_analysis"))
                    if isinstance(data.get("html_analysis"), dict)
                    else {"enabled": True, "status": "ok"}
                )
                html_analysis["approval"] = {
                    "enabled": True,
                    "policy": "two_parallel_review_rounds",
                    "orchestrator": "langgraph_nodes",
                    "status": "pending_langgraph_review",
                    "approved": False,
                    "published_without_approval": False,
                    "review_count": len(state.get("report_reviews") or []),
                    "red_team_count": len(state.get("report_red_teams") or []),
                    "revision_count": len(state.get("report_revisions") or []),
                    "render_version_count": target_render_version,
                    "reviews": list(state.get("report_reviews") or []),
                    "red_teams": list(state.get("report_red_teams") or []),
                    "revisions": list(state.get("report_revisions") or []),
                }
                data["html_analysis"] = html_analysis
                result["data"] = data
                result["report_file_path"] = report_file_path
        if (
            tool_name == "render_markdown_report"
            and str(result.get("status") or "") in SUCCESS_TOOL_STATUSES
        ):
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            markdown_content = data.get("markdown") if isinstance(data.get("markdown"), str) else ""
            if markdown_content:
                report_file_path = self.deps.write_text(
                    state["run_id"], "report.md", markdown_content
                )
                data["report_file_path"] = report_file_path
                result["data"] = data
                result["report_file_path"] = report_file_path
        self._apply_resolved_tool_params(state, tool_name, result)
        result["file_path"] = self.deps.write_json(
            state["run_id"],
            f"tool-{started_index:02d}-{tool_name}.json",
            result,
        )
        tools = list(state.get("tools") or [])
        tools.append(result)
        state["tools"] = tools
        if (
            tool_name == "render_html_report"
            and str(result.get("status") or "") in SUCCESS_TOOL_STATUSES
            and isinstance((result.get("data") or {}).get("html"), str)
            and (result.get("data") or {}).get("html")
        ):
            state["report_approval_phase"] = "parallel_review"
            state["report_review_round"] = 1
            state["report_render_version"] = 1
            state["report_reviews"] = []
            state["report_red_teams"] = []
            state["report_revisions"] = []
            state["report_review_branch"] = {}
            state["report_red_team_branch"] = {}
        planner = dict(state.get("planner") or {})
        planned_tools = [str(tool.get("name")) for tool in tools if tool.get("name")]
        planner["planned_tools"] = planned_tools
        state["planner"] = planner
        result_status = str(result.get("status") or "")
        event_status = (
            "ok"
            if result_status in SUCCESS_TOOL_STATUSES
            else "skipped"
            if result_status == "empty"
            else "error"
        )
        self._add_event(
            state,
            "tool",
            event_status,
            event_title,
            str(result.get("summary") or ""),
            tool=tool_name,
            duration_ms=int(result.get("duration_ms") or 0),
            data={
                "label": label,
                "status": result.get("status"),
                "outcome": result.get("outcome"),
                "native_tool": tool_name,
                **(
                    {"langgraph_node": True, "graph_node": runtime_node}
                    if runtime_node
                    else {}
                ),
            },
            input_params=result.get("input") or tool_input,
            output={
                "status": result.get("status"),
                "outcome": result.get("outcome"),
                "summary": result.get("summary"),
                "data": result.get("data"),
                "recovery": result.get("recovery"),
            },
            file_path=str(result.get("file_path") or ""),
            event_id=tool_event_id if self._emit_event else None,
        )
        return {
            "status": result.get("status"),
            "outcome": result.get("outcome"),
            "summary": result.get("summary"),
            "file_path": result.get("file_path"),
            "data": result.get("data"),
            "recovery": result.get("recovery"),
        }

    def _synthesize(
        self,
        state: AgentRuntimeState,
        *,
        llm_enabled: bool,
    ) -> AgentRuntimeState:
        ok_tools = [
            tool for tool in state.get("tools") or [] if tool.get("status") in SUCCESS_TOOL_STATUSES
        ]
        if not ok_tools:
            self._add_event(
                state,
                "artifact",
                "skipped",
                "未生成最终 Artifact",
                "没有成功的数据工具结果，不能生成最终 HTML 分析报告。",
                input_params={
                    "tool_count": len(state.get("tools") or []),
                    "successful_tool_count": 0,
                    "useLlm": llm_enabled,
                    "locale": state["locale"],
                },
                output={"summary": "No successful tool evidence."},
            )
            return self._respond_to_user(
                state,
                "还没有成功的数据工具结果，所以我不能生成最终 HTML 分析报告。请先让 Agent 成功调用 Sif、SellerSprite、Reddit、TikTok 或媒体等数据工具，或检查 LLM/API 配置后重试。",
            )
        required_report_tool = self._required_report_tool(state)
        report_format = "Markdown" if required_report_tool == "render_markdown_report" else "HTML"
        rendered_report_tool = (
            self._latest_html_report_tool(state)
            if required_report_tool == "render_html_report"
            else self._latest_successful_tool(state, required_report_tool)
        )
        rendered_data = (
            rendered_report_tool.get("data")
            if rendered_report_tool and isinstance(rendered_report_tool.get("data"), dict)
            else {}
        )
        if not rendered_data.get("report_file_path"):
            render_attempt = next(
                (
                    tool
                    for tool in reversed(state.get("tools") or [])
                    if str(tool.get("name") or "")
                    in (
                        {"render_html_report", "revise_html_report"}
                        if required_report_tool == "render_html_report"
                        else {required_report_tool}
                    )
                ),
                None,
            )
            reason = (
                str(render_attempt.get("summary") or "")
                if isinstance(render_attempt, dict)
                else f"{required_report_tool} was not completed."
            )
            renderer_was_called = isinstance(render_attempt, dict)
            instruction = (
                f"修复 LLM {report_format} 生成失败原因后重试；系统不提供通用报告 fallback。"
                if renderer_was_called
                else (
                    f"检查所选 Skill 的 Tool Policy 和图节点执行顺序；{required_report_tool} "
                    "应由 LangGraph 报告节点执行，成功后才会进入 synthesize_artifact 终态节点。"
                )
            )
            self._add_event(
                state,
                "artifact",
                "error",
                "未生成最终 Artifact",
                f"最终 {report_format} 必须来自 {required_report_tool}，但该工具没有成功产出报告文件。",
                input_params={
                    "skill_id": state.get("selected_skill_id"),
                    "required_tool": required_report_tool,
                    "tool_count": len(state.get("tools") or []),
                    "useLlm": llm_enabled,
                },
                output={
                    "summary": reason,
                    "instruction": instruction,
                },
                event_id="artifact" if self._emit_event else None,
            )
            user_message = (
                f"最终 {report_format} 报告没有生成：`{required_report_tool}` 没有成功写出报告文件。"
                f"请修复 LLM {report_format} 生成失败原因后重试；系统不会再改用固定模板生成报告。"
                if renderer_was_called
                else (
                    f"最终 {report_format} 报告没有生成：LangGraph 报告节点未成功执行 "
                    f"`{required_report_tool}`，因此没有进入 `synthesize_artifact` 终态节点。"
                )
            )
            return self._respond_to_user(
                state,
                user_message,
                response_status="error",
                event_status="error",
            )
        if rendered_data.get("report_file_path"):
            artifact = (
                rendered_data.get("artifact")
                if isinstance(rendered_data.get("artifact"), dict)
                else {}
            )
            if not artifact:
                artifact = {
                    "title": rendered_data.get("title") or f"{report_format} 报告",
                    "executive_summary": f"已基于当前 Skill 的工具证据生成 LLM-authored {report_format} 报告。",
                    "key_findings": [],
                    "opportunity_pool": [],
                    "risks": [],
                    "next_steps": [],
                }
            artifact = self._apply_evidence_gaps_to_artifact(state, artifact)
            analysis_key = (
                "markdown_analysis"
                if required_report_tool == "render_markdown_report"
                else "html_analysis"
            )
            report_analysis = (
                rendered_data.get(analysis_key)
                if isinstance(rendered_data.get(analysis_key), dict)
                else {}
            )
            renderer_name = rendered_data.get("renderer") or "unknown"
            llm_analysis = {
                "enabled": llm_enabled,
                "status": "ok",
                "provider": report_analysis.get("provider")
                or f"llm-{report_format.lower()}-renderer",
                "model": report_analysis.get("model") or f"llm-authored-{report_format.lower()}.v1",
                "message": f"Published the Skill-driven LLM-authored {report_format} report.",
                "usage": report_analysis.get("usage") or {},
                "renderer": renderer_name,
            }
            if isinstance(report_analysis.get("approval"), dict):
                llm_analysis["approval"] = report_analysis["approval"]
            generation_status_key = (
                "markdown_generation_status"
                if required_report_tool == "render_markdown_report"
                else "html_generation_status"
            )
            llm_analysis[generation_status_key] = report_analysis.get("status") or "not_requested"
            report_file_path = str(rendered_data.get("report_file_path") or "")
        run_file_path = str(
            (self.deps.cache_dir() / "agent-runs" / state["run_id"] / "run.json").resolve()
        )
        output_files = self._build_output_files(state, report_file_path)
        planner = dict(state.get("planner") or {})
        planner["planned_tools"] = [
            str(tool.get("name")) for tool in state.get("tools") or [] if tool.get("name")
        ]
        state["planner"] = planner
        response = {
            "run_id": state["run_id"],
            "generated_at": state["generated_at"],
            "status": "ok",
            "response_type": "artifact",
            "mode": state["mode"],
            "category": state["category"],
            "prompt": state["prompt"],
            "planner": planner,
            "events": state.get("events") or [],
            "tools": state.get("tools") or [],
            "evidence_gaps": state.get("evidence_gaps") or [],
            "artifact": artifact,
            "llm_analysis": llm_analysis,
            "file_path": run_file_path,
            "skill": {
                "skill_id": state.get("selected_skill_id"),
                "name": (state.get("selected_skill") or {}).get("name"),
                "status": "ok" if state.get("selected_skill_id") else planner.get("status"),
                "params": state.get("skill_params") or {},
                "missing_params": state.get("missing_params") or [],
                "file_path": state.get("skill_file_path") or "",
            },
            "output_files": output_files,
            "runtime": {"engine": "langgraph", "pattern": "native_tool_call_loop"},
        }
        if state.get("context_source_run_id"):
            response["context_source_run_id"] = state["context_source_run_id"]
        if state.get("checkpoint_source_run_id"):
            response["resumed_from_run_id"] = state["checkpoint_source_run_id"]
        self.deps.write_json(state["run_id"], "run.json", response)
        state["artifact"] = artifact
        state["llm_analysis"] = llm_analysis
        state["output_files"] = output_files
        state["response"] = response
        state["pending_tool_calls"] = []
        return state

    def _respond_to_user(
        self,
        state: AgentRuntimeState,
        message: str,
        *,
        response_status: str = "ok",
        event_status: str = "ok",
    ) -> AgentRuntimeState:
        content = self._normalize_chat_response(state, message.strip())
        self._add_event(
            state,
            "message",
            event_status,
            "回复用户",
            compact_for_event(content),
            output={"message": content},
        )
        run_file_path = str(
            (self.deps.cache_dir() / "agent-runs" / state["run_id"] / "run.json").resolve()
        )
        output_files: list[dict[str, str]] = []
        planner = dict(state.get("planner") or {})
        planner["planned_tools"] = [
            str(tool.get("name")) for tool in state.get("tools") or [] if tool.get("name")
        ]
        state["planner"] = planner
        assistant_message = {"role": "assistant", "content": content}
        response = {
            "run_id": state["run_id"],
            "generated_at": state["generated_at"],
            "status": response_status,
            "response_type": "message",
            "mode": state["mode"],
            "category": state["category"],
            "prompt": state["prompt"],
            "planner": planner,
            "events": state.get("events") or [],
            "tools": state.get("tools") or [],
            "evidence_gaps": state.get("evidence_gaps") or [],
            "message": assistant_message,
            "llm_analysis": {
                "enabled": state["use_llm"],
                "status": "unavailable" if planner.get("status") == "unavailable" else "ok",
                "message": planner.get("message"),
                "provider": planner.get("provider"),
                "model": planner.get("model"),
                "usage": planner.get("usage") or {},
            },
            "file_path": run_file_path,
            "skill": {
                "skill_id": state.get("selected_skill_id"),
                "name": (state.get("selected_skill") or {}).get("name"),
                "status": "ok" if state.get("selected_skill_id") else planner.get("status"),
                "params": state.get("skill_params") or {},
                "missing_params": state.get("missing_params") or [],
                "file_path": state.get("skill_file_path") or "",
            },
            "output_files": output_files,
            "runtime": {"engine": "langgraph", "pattern": "native_tool_call_loop"},
        }
        if state.get("context_source_run_id"):
            response["context_source_run_id"] = state["context_source_run_id"]
        self.deps.write_json(state["run_id"], "run.json", response)
        state["assistant_message"] = assistant_message
        state["output_files"] = output_files
        state["response"] = response
        state["pending_tool_calls"] = []
        return state

    def _normalize_chat_response(self, state: AgentRuntimeState, message: str) -> str:
        if not message:
            return self._default_chat_response(state)
        return message

    def _default_chat_response(self, state: AgentRuntimeState) -> str:
        prompt = str(state.get("prompt") or "")
        if self._looks_like_capability_question(prompt):
            return self._capability_summary(state, self._capability_snapshot(state, prompt))
        if state.get("locale") == "en":
            return (
                "Hi, I can help with evidence-driven market insight, hot product pain analysis, "
                "and R&D opportunity analysis. You can ask a general question or give me a research task."
            )
        return "你好，我可以回答通用问题，也可以调用已接入的数据工具做市场洞察、爆款痛点分析和研发机会分析。"

    def _looks_like_capability_question(self, prompt: str) -> bool:
        lowered = prompt.lower()
        terms = [
            "能调用",
            "能用",
            "有哪些工具",
            "工具有哪些",
            "调用的工具",
            "可以调用的工具",
            "什么工具",
            "工具吗",
            "mcp",
            "sif",
            "能力",
            "can you call",
            "available tools",
            "what tools",
            "capabilities",
        ]
        return any(term in lowered for term in terms)

    def _capability_snapshot(self, state: AgentRuntimeState, focus: str = "") -> dict[str, Any]:
        catalog = self._planner_tool_catalog()
        skills = [
            {
                "skill_id": str(item.get("skill_id") or ""),
                "name": str(item.get("name") or ""),
                "description": str(item.get("description") or ""),
            }
            for item in self.deps.skill_manifests()
        ]
        tools: list[dict[str, Any]] = []
        source_counts: dict[str, int] = {}
        source_groups: dict[str, dict[str, Any]] = {}
        for name, meta in sorted(catalog.items()):
            source = str(meta.get("source") or "built_in")
            source_counts[source] = source_counts.get(source, 0) + 1
            auth_env_names = [
                str(item)
                for item in (
                    meta.get("auth_env_names")
                    if isinstance(meta.get("auth_env_names"), list)
                    else []
                )
                if str(item)
            ]
            tools.append(
                {
                    "name": name,
                    "label": str(meta.get("label") or name),
                    "description": str(meta.get("description") or ""),
                    "source": source,
                    "mcp_tool": str(meta.get("mcp_tool") or ""),
                    "requires_auth": bool(auth_env_names),
                    "auth_env_names": auth_env_names,
                }
            )
            if source != "built_in":
                group = source_groups.setdefault(
                    source,
                    {
                        "name": self._source_display_name(source),
                        "source": source,
                        "registered": True,
                        "tool_count": 0,
                        "auth_env_names": [],
                        "tools": [],
                    },
                )
                group["tool_count"] += 1
                group["tools"].append(name)
                for env_name in auth_env_names:
                    if env_name not in group["auth_env_names"]:
                        group["auth_env_names"].append(env_name)
        for group in source_groups.values():
            env_names = (
                group.get("auth_env_names") if isinstance(group.get("auth_env_names"), list) else []
            )
            group["auth_configured"] = (
                any(os.getenv(str(env_name)) for env_name in env_names) if env_names else None
            )
        focus_lower = str(focus or "").lower()

        def source_sort_key(group: dict[str, Any]) -> tuple[int, str]:
            searchable = " ".join(
                [
                    str(group.get("name") or ""),
                    str(group.get("source") or ""),
                    " ".join(str(item) for item in group.get("tools", []) if item),
                ]
            ).lower()
            return (
                0 if focus_lower and focus_lower in searchable else 1,
                str(group.get("source") or ""),
            )

        return {
            "focus": focus,
            "skills": skills,
            "tools": tools,
            "tool_count": len(tools),
            "source_counts": source_counts,
            "tool_sources": sorted(source_groups.values(), key=source_sort_key),
        }

    def _capability_summary(self, state: AgentRuntimeState, snapshot: dict[str, Any]) -> str:
        source_counts = (
            snapshot.get("source_counts") if isinstance(snapshot.get("source_counts"), dict) else {}
        )
        built_in_count = int(source_counts.get("built_in") or 0)
        external_sources = [
            item
            for item in snapshot.get("tool_sources", [])
            if isinstance(item, dict) and item.get("registered")
        ]
        source_line = self._capability_source_line(state, external_sources)
        tool_table = self._capability_tool_table(state, snapshot)
        if state.get("locale") == "en":
            return (
                "I can answer general questions and run agent tasks through the native tool-calling loop. "
                f"The current catalog has {snapshot.get('tool_count', 0)} data tools, including {built_in_count} built-in tools. "
                f"{source_line}\n\n{tool_table}"
            )
        return (
            "可以回答通用问题，也可以通过原生 tool calling 执行任务。"
            f"当前工具目录共有 {snapshot.get('tool_count', 0)} 个数据工具，其中内置工具 {built_in_count} 个。"
            f"{source_line}\n\n{tool_table}"
        )

    def _source_display_name(self, source: str) -> str:
        parts = [part for part in str(source or "").split("_") if part]
        if not parts:
            return "Unknown"
        return " ".join(
            part.upper() if part.lower() == "mcp" else part.capitalize() for part in parts
        )

    def _capability_source_line(
        self, state: AgentRuntimeState, sources: list[dict[str, Any]]
    ) -> str:
        if state.get("locale") == "en":
            if not sources:
                return "No external tool source is currently registered."
            chunks = []
            for source in sources:
                auth_configured = source.get("auth_configured")
                if auth_configured is True:
                    auth_text = "credentials detected"
                elif auth_configured is False:
                    auth_text = "credentials not detected"
                else:
                    auth_text = "no credential metadata"
                chunks.append(
                    f"{source.get('name')} ({source.get('tool_count', 0)} tools, {auth_text})"
                )
            return "Registered external tool sources: " + "; ".join(chunks) + "."
        if not sources:
            return "当前未注册外部工具源。"
        chunks = []
        for source in sources:
            auth_configured = source.get("auth_configured")
            if auth_configured is True:
                auth_text = "已检测到密钥"
            elif auth_configured is False:
                auth_text = "未检测到密钥"
            else:
                auth_text = "未声明密钥要求"
            chunks.append(
                f"{source.get('name')}（{source.get('tool_count', 0)} 个工具，{auth_text}）"
            )
        return "已注册外部工具源：" + "；".join(chunks) + "。"

    def _capability_tool_table(self, state: AgentRuntimeState, snapshot: dict[str, Any]) -> str:
        tools = [tool for tool in snapshot.get("tools", []) if isinstance(tool, dict)]
        if state.get("locale") == "en":
            lines = [
                "| Tool | Source | Purpose |",
                "| --- | --- | --- |",
            ]
            for tool in tools:
                lines.append(
                    f"| `{tool.get('name')}` | {tool.get('source') or 'built_in'} | {compact_for_event(str(tool.get('description') or ''), 96)} |"
                )
            return "\n".join(lines)
        lines = [
            "| 工具 | 来源 | 用途 |",
            "| --- | --- | --- |",
        ]
        for tool in tools:
            lines.append(
                f"| `{tool.get('name')}` | {tool.get('source') or 'built_in'} | {compact_for_event(str(tool.get('description') or ''), 96)} |"
            )
        return "\n".join(lines)

    def _inspect_agent_capabilities(
        self, state: AgentRuntimeState, args: dict[str, Any]
    ) -> dict[str, Any]:
        started = time.time()
        state["capability_inspected"] = True
        focus = str(args.get("focus") or state.get("prompt") or "").strip()
        snapshot = self._capability_snapshot(state, focus)
        summary = self._capability_summary(state, snapshot)
        self._add_event(
            state,
            "message",
            "ok",
            "检查 Agent 能力",
            compact_for_event(summary),
            duration_ms=int((time.time() - started) * 1000),
            input_params=args,
            output={"summary": summary},
            data=snapshot,
        )
        return {"status": "ok", "summary": summary, **snapshot}

    def _system_prompt(self, state: AgentRuntimeState) -> str:
        active_category = str(
            (state.get("skill_params") or {}).get("category") or state.get("category") or ""
        ).strip()
        active_marketplace = str(
            (state.get("skill_params") or {}).get("marketplace")
            or (state.get("payload") or {}).get("marketplace")
            or ((state.get("payload") or {}).get("params") or {}).get("marketplace")
            or ""
        ).strip()
        category_instruction = (
            f"Current requested category: {active_category}.\n"
            if active_category
            else "Current requested category: unresolved; infer it from the user's wording or ask if the Skill requires it.\n"
        )
        marketplace_instruction = (
            f"Current requested marketplace: {active_marketplace}.\n" if active_marketplace else ""
        )
        timestamp_instruction = f"Current run timestamp: {state.get('generated_at')}.\n"
        skill_lines = [
            f"- {item.get('skill_id')}: {item.get('name')} — {item.get('description')}"
            for item in self.deps.skill_manifests()
        ]
        tool_catalog = self._planner_tool_catalog()
        available_data_tools = allowed_data_tools_for_skill(
            state.get("selected_skill"),
            list(tool_catalog.keys()),
        )
        if self._uses_langgraph_html_report_pipeline(state):
            report_pipeline_tools = {
                self._required_report_data_builder(state),
                "render_html_report",
            }
            available_data_tools = [
                name for name in available_data_tools if name not in report_pipeline_tools
            ]
        tool_lines = [
            f"- {name} ({tool_catalog[name].get('source') or 'built_in'}): {tool_catalog[name].get('description')}"
            for name in available_data_tools
        ]
        forced = (
            f"\nForced skill from pending run: {state.get('forced_skill_id')}"
            if state.get("forced_skill_id")
            else ""
        )
        checkpoint_instruction = (
            "\nCheckpoint continuation is active. The original Skill and resolved parameters are already loaded; "
            "do not select or load a Skill again. Continue only the blocked or missing tool calls."
            if state.get("checkpoint_source_run_id")
            else ""
        )
        conversation_context_instruction = (
            "\nPrevious-run context is available, but it does not impose a follow-up-only mode. "
            "Infer the user's current intent. For a question about the prior result, answer from context "
            "without loading a Skill. For a new or expanded research request, load the most relevant Skill "
            "and execute it. For an explicit retry, continuation, regeneration, or re-render request, call "
            "resume_previous_run first so successful tool results are restored and not repeated. Never tell "
            "the user to start a new task merely because previous-run context exists."
            if state.get("context_source_run_id")
            and not state.get("checkpoint_source_run_id")
            else ""
        )
        return (
            "You are Hsia R&D Insight Agent for evidence-driven ecommerce market research.\n"
            + category_instruction
            + marketplace_instruction
            + timestamp_instruction
            + "Treat explicit UI params and the user's wording as authoritative; never replace them with an example category.\n"
            "You operate through native OpenAI tool calls. The harness executes tools and returns observations.\n"
            "Use tools step by step; do not describe a tool call when you can call the tool.\n\n"
            "Available Skills:\n"
            + "\n".join(skill_lines)
            + "\n\nData tools:\n"
            + "\n".join(tool_lines)
            + forced
            + checkpoint_instruction
            + conversation_context_instruction
            + "\n\nRules:\n"
            "- First call load_skill when a new research request matches a Skill, except when checkpoint continuation already restored selected_skill_id or resume_previous_run is the correct action. Do not run data tools before a relevant Skill is available.\n"
            "- Previous-run context is evidence and resumable state, not a fixed conversation mode. Decide independently whether the user wants a text answer, a new Skill workflow, or continuation of prior work.\n"
            "- For retry/continue/regenerate/re-render intent, call resume_previous_run before any data or report tool, reuse successful tools, and execute only failed or missing stages.\n"
            "- When calling load_skill, extract brand, marketplace, category, time_range, and other required inputs from the user task into extracted_params.\n"
            "- Category is an open product/category phrase. Copy it from the user's wording or explicit UI params; do not copy examples from Skill descriptions.\n"
            "- For greetings or small talk, call respond_to_user with a normal chat answer.\n"
            "- For questions about what the agent can do, which tools/MCPs are available, or whether Sif/MCP can be called, first call inspect_agent_capabilities, then call respond_to_user using that observation.\n"
            "- load_skill may return missing_required_inputs. If that happens, call ask_user before any data tool.\n"
            "- After a Skill is loaded, the harness enforces its Tool Policy; use only available data tools.\n"
            "- For an HTML Skill with a declared report-data builder, finish the required source-data calls and then stop issuing tool calls. That no-tool-call handoff lets LangGraph run report_data_builder -> data_analysis -> insight_synthesis -> chart_render -> html_render -> parallel report_review and report_red_team -> approval_join -> any required html_revision -> synthesize_artifact automatically; never call those report nodes from the planner.\n"
            "- If the report pipeline returns blocked, call only the listed missing source tools and then stop issuing tool calls again.\n"
            "- For weekly market insight and TikTok Shop US market insight reports, collect all required source evidence; MarketReportData construction and HTML rendering are automatic LangGraph nodes.\n"
            "- Every HTML-report Skill automatically runs report_review and report_red_team concurrently after html_render, then approval_join combines both results. A first-round rejection from either branch routes to html_revision and a second parallel round; a second-round rejection routes to one final revision and direct publication without a third review.\n"
            "- For TikTok Shop US women's-bra new-product insight, query the exact L3 Bras category, keep only products priced from USD 20 through USD 100 inclusive, and exclude every non-bra, missing-price, or out-of-range row before selecting Top products. Preserve shop_name and shop_id as separate required ranking columns. Finish all Top-product detail and trend attempts, then stop issuing tool calls. Do not send raw FastMoss results to the renderer.\n"
            "- For TikTok Shop US bra competitor-shop analysis, resolve the exact L3 Bras category and first try the US completed-month L3 shop ranking. If and only if that preferred scope returns empty, use the US Women's Underwear L2 completed-week ranking as a clearly labeled candidate-universe fallback; never call an unscoped ranking. Finish the 50-shop candidate pool before running the same base, L3 Bras product, 28-day trend, channel, and creator tools for the fixed 10 seller_ids. Then stop issuing tool calls. Never send raw FastMoss results to the renderer.\n"
            "- For fashion trend reports, call trend_platforms, then stop issuing tool calls. The automatic builder and renderer treat the result as a visual design-inspiration editorial: use WGSN and Diexun for macro direction, use Pinterest for visual development, keep source/date notes compact, and preserve the visual URL whitelist.\n"
            "- For hot-product pain analysis, resolve the SellerSprite product node, use the category-validated concentration candidate pool, collect one successful recent balanced review result per requested product, then require Sif sales-list and keyword-competition evidence before ending data collection.\n"
            "- For product-design research, validate more than one keyword entrance, resolve the category node, and collect at least five distinct reviewed products. Then stop issuing tool calls; LangGraph owns build_product_design_brief_data and render_markdown_report.\n"
            "- Do not directly generate a final report in chat; the renderer declared by the loaded Skill owns final report composition.\n"
            "- Do not call ask_user merely to confirm parameters that load_skill already resolved.\n"
            "- Use only tool evidence for conclusions. Do not invent sales volume, search volume, demographics, or market size.\n"
            "- Call data tools one at a time unless the next calls are clearly independent.\n"
            "- If a tool returns needs_user_action, the harness pauses immediately and saves a resumable checkpoint. Never promise checkpoint resume unless the response actually contains pending.resume_supported=true.\n"
            "- Deterministic build_* tools are not retryable with unchanged evidence; collect or correct the missing evidence before calling the builder again.\n"
            "- When evidence is enough, stop issuing tool calls. For report workflows, LangGraph owns the remaining builder, renderer, approval, and Artifact nodes.\n"
        )

    def _tool_definitions(self, state: AgentRuntimeState) -> list[dict[str, Any]]:
        tool_defs = [
            {
                "type": "function",
                "function": {
                    "name": "load_skill",
                    "description": (
                        "Load a Markdown Skill by id and register task parameters extracted from the user's task. "
                        "For category, copy the user's actual product/category phrase; never use examples from Skill text."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_id": {
                                "type": "string",
                                "description": "One of the available Skill ids.",
                            },
                            "extracted_params": {
                                "type": "object",
                                "description": (
                                    "Parameters extracted from the user task. Include category only when the user names a "
                                    "product/category phrase or the UI provided one; leave it absent when unclear."
                                ),
                                "additionalProperties": True,
                            },
                        },
                        "required": ["skill_id"],
                    },
                },
            },
            *(
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "resume_previous_run",
                            "description": (
                                "Restore the Skill, resolved parameters, successful tool results, failed "
                                "tool records, and evidence gaps from a previous run in the current context. "
                                "Use when the user asks to continue, retry, regenerate, re-render, or reuse "
                                "the prior task. Do not use for a question that can be answered from context "
                                "or for an unrelated new research request."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "run_id": {
                                        "type": "string",
                                        "description": (
                                            "The previous run id from conversation context. Omit to use "
                                            "the current context source run."
                                        ),
                                    },
                                    "reason": {
                                        "type": "string",
                                        "description": "Why resuming prior work matches the user's intent.",
                                    },
                                },
                                "required": [],
                            },
                        },
                    }
                ]
                if state.get("context_source_run_id")
                and not state.get("checkpoint_source_run_id")
                else []
            ),
            {
                "type": "function",
                "function": {
                    "name": "ask_user",
                    "description": "Ask the user for missing required inputs and pause this run. Use only when load_skill reports missing_params.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {"type": "string"},
                            "missing_params": {"type": "array", "items": {"type": "string"}},
                            "questions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "field": {"type": "string"},
                                        "label": {"type": "string"},
                                        "question": {"type": "string"},
                                        "suggestions": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                    },
                                    "required": ["field", "question"],
                                },
                            },
                        },
                        "required": ["reason", "questions"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "respond_to_user",
                    "description": "Return a normal conversational assistant message without generating an Artifact.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "The assistant message to show in the chat.",
                            },
                        },
                        "required": ["message"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "inspect_agent_capabilities",
                    "description": (
                        "Inspect currently registered Skills, data tools, MCP integrations, and credential hints. "
                        "Use before answering questions about tool availability or agent capabilities."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "focus": {
                                "type": "string",
                                "description": "The user capability question or integration name to inspect.",
                            }
                        },
                        "required": [],
                    },
                },
            },
        ]
        tool_catalog = self._planner_tool_catalog()
        available_data_tools = allowed_data_tools_for_skill(
            state.get("selected_skill"),
            list(tool_catalog.keys()),
        )
        if self._uses_langgraph_html_report_pipeline(state):
            report_pipeline_tools = {
                self._required_report_data_builder(state),
                "render_html_report",
            }
            available_data_tools = [
                name for name in available_data_tools if name not in report_pipeline_tools
            ]
        for name in available_data_tools:
            meta = tool_catalog[name]
            tool_defs.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": meta.get("description") or name,
                        "parameters": meta.get("input_schema")
                        if isinstance(meta.get("input_schema"), dict)
                        else {
                            "type": "object",
                            "properties": {
                                "category": {"type": "string"},
                                "timeRange": {"type": "string"},
                                "time_range": {"type": "string"},
                                "limit": {"type": "integer"},
                                "bypassCache": {"type": "boolean"},
                            },
                            "required": [],
                            "additionalProperties": True,
                        },
                    },
                }
            )
        return tool_defs

    def _tool_call_name_args(self, tool_call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
        name = str(function.get("name") or tool_call.get("name") or "")
        raw_args = (
            function.get("arguments") if "arguments" in function else tool_call.get("arguments")
        )
        if isinstance(raw_args, dict):
            return name, raw_args
        if not raw_args:
            return name, {}
        try:
            parsed = json.loads(str(raw_args))
        except json.JSONDecodeError:
            return name, {}
        return name, parsed if isinstance(parsed, dict) else {}

    def _synthetic_tool_call(self, call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
        }

    def _should_force_capability_inspection(self, state: AgentRuntimeState) -> bool:
        if state.get("capability_inspected"):
            return False
        if not self._looks_like_capability_question(str(state.get("prompt") or "")):
            return False
        return not state.get("selected_skill_id") and not state.get("tools")

    def _payload_with_tool_args(
        self,
        state: AgentRuntimeState,
        tool_name: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self.deps.payload_with_skill_params(
            state["payload"], state.get("skill_params") or {}
        )
        task_prompt = str(state.get("resumed_task_prompt") or state["prompt"])
        payload["skillId"] = state.get("selected_skill_id") or payload.get("skillId")
        payload["generatedAt"] = state.get("generated_at")
        for key, value in args.items():
            if value is None or value == "":
                continue
            if key == "time_range":
                payload["timeRange"] = value
            elif key == "limit" and tool_name == "reddit_voc":
                payload["redditLimit"] = value
            elif key == "limit" and tool_name == "amazon_shelf":
                payload["amazonLimit"] = value
            elif key == "limit" and tool_name == "tiktok_social":
                payload["tiktokLimit"] = value
            else:
                payload[key] = value
        if tool_name == "build_market_report_data":
            payload["toolResults"] = [
                tool
                for tool in state.get("tools") or []
                if str(tool.get("name") or "")
                not in {
                    "build_market_report_data",
                    "build_tiktok_new_product_report_data",
                    "build_tiktok_bra_competitor_shop_report_data",
                    "build_market_report_charts",
                    "build_trend_report_data",
                    "build_competitor_product_report_data",
                    "build_hot_product_pain_report_data",
                    "build_product_design_brief_data",
                    "render_html_report",
                    "render_markdown_report",
                    "analyze_market_report",
                    "synthesize_report_insights",
                    "render_report_charts",
                "review_html_report",
                "red_team_html_report",
                "join_report_approval",
                *LEGACY_INTERNAL_REPORT_TOOL_NAMES,
                "revise_html_report",
                }
            ]
            payload["prompt"] = task_prompt
            payload["agentMode"] = state["mode"]
            payload["mode"] = state["mode"]
            payload["category"] = state["category"]
            payload["generatedAt"] = state["generated_at"]
            payload["evidenceGaps"] = state.get("evidence_gaps") or []
            payload["productIdentityDetailLookupAsins"] = (
                state.get("product_identity_detail_lookup_asins") or []
            )
        elif tool_name == "build_tiktok_new_product_report_data":
            payload["toolResults"] = [
                tool
                for tool in state.get("tools") or []
                if str(tool.get("name") or "")
                not in {
                    "build_market_report_data",
                    "build_tiktok_new_product_report_data",
                    "build_tiktok_bra_competitor_shop_report_data",
                    "build_market_report_charts",
                    "build_trend_report_data",
                    "build_competitor_product_report_data",
                    "build_hot_product_pain_report_data",
                    "build_product_design_brief_data",
                    "render_html_report",
                    "render_markdown_report",
                    "analyze_market_report",
                    "synthesize_report_insights",
                    "render_report_charts",
                "review_html_report",
                "red_team_html_report",
                "join_report_approval",
                *LEGACY_INTERNAL_REPORT_TOOL_NAMES,
                "revise_html_report",
                }
            ]
            payload["prompt"] = task_prompt
            payload["agentMode"] = state["mode"]
            payload["mode"] = state["mode"]
            payload["category"] = state["category"]
            payload["generatedAt"] = state["generated_at"]
            payload["evidenceGaps"] = state.get("evidence_gaps") or []
        elif tool_name == "build_tiktok_bra_competitor_shop_report_data":
            payload["toolResults"] = [
                tool
                for tool in state.get("tools") or []
                if str(tool.get("name") or "")
                not in {
                    "build_market_report_data",
                    "build_tiktok_new_product_report_data",
                    "build_tiktok_bra_competitor_shop_report_data",
                    "build_market_report_charts",
                    "build_trend_report_data",
                    "build_competitor_product_report_data",
                    "build_hot_product_pain_report_data",
                    "build_product_design_brief_data",
                    "render_html_report",
                    "render_markdown_report",
                    "analyze_market_report",
                    "synthesize_report_insights",
                    "render_report_charts",
                "review_html_report",
                "red_team_html_report",
                "join_report_approval",
                *LEGACY_INTERNAL_REPORT_TOOL_NAMES,
                "revise_html_report",
                }
            ]
            payload["prompt"] = task_prompt
            payload["agentMode"] = state["mode"]
            payload["mode"] = state["mode"]
            payload["category"] = state["category"]
            payload["generatedAt"] = state["generated_at"]
            payload["evidenceGaps"] = state.get("evidence_gaps") or []
        elif tool_name == "build_trend_report_data":
            payload["toolResults"] = [
                tool
                for tool in state.get("tools") or []
                if str(tool.get("name") or "")
                not in {
                    "build_market_report_data",
                    "build_tiktok_new_product_report_data",
                    "build_tiktok_bra_competitor_shop_report_data",
                    "build_trend_report_data",
                    "build_competitor_product_report_data",
                    "build_hot_product_pain_report_data",
                    "build_product_design_brief_data",
                    "render_html_report",
                    "render_markdown_report",
                    "analyze_market_report",
                    "synthesize_report_insights",
                    "render_report_charts",
                "review_html_report",
                "red_team_html_report",
                "join_report_approval",
                *LEGACY_INTERNAL_REPORT_TOOL_NAMES,
                "revise_html_report",
                }
            ]
            payload["prompt"] = task_prompt
            payload["agentMode"] = state["mode"]
            payload["mode"] = state["mode"]
            payload["category"] = state["category"]
            payload["generatedAt"] = state["generated_at"]
            payload["evidenceGaps"] = state.get("evidence_gaps") or []
        elif tool_name in {
            "build_competitor_product_report_data",
            "build_hot_product_pain_report_data",
        }:
            payload["toolResults"] = [
                tool
                for tool in state.get("tools") or []
                if not str(tool.get("name") or "").startswith("build_")
                and str(tool.get("name") or "")
                not in {
                    "render_html_report",
                    "render_markdown_report",
                    "analyze_market_report",
                    "synthesize_report_insights",
                    "render_report_charts",
                    "review_html_report",
                    "red_team_html_report",
                    "join_report_approval",
                    *LEGACY_INTERNAL_REPORT_TOOL_NAMES,
                    "revise_html_report",
                }
            ]
            payload["prompt"] = task_prompt
            payload["agentMode"] = state["mode"]
            payload["mode"] = state["mode"]
            payload["category"] = state["category"]
            payload["generatedAt"] = state["generated_at"]
            payload["evidenceGaps"] = state.get("evidence_gaps") or []
        elif tool_name == "build_product_design_brief_data":
            payload["toolResults"] = [
                tool
                for tool in state.get("tools") or []
                if str(tool.get("name") or "")
                not in {
                    "build_market_report_data",
                    "build_tiktok_new_product_report_data",
                    "build_tiktok_bra_competitor_shop_report_data",
                    "build_trend_report_data",
                    "build_competitor_product_report_data",
                    "build_hot_product_pain_report_data",
                    "build_product_design_brief_data",
                    "render_html_report",
                    "render_markdown_report",
                    "analyze_market_report",
                    "synthesize_report_insights",
                    "render_report_charts",
                "review_html_report",
                "red_team_html_report",
                "join_report_approval",
                *LEGACY_INTERNAL_REPORT_TOOL_NAMES,
                "revise_html_report",
                }
            ]
            payload["prompt"] = task_prompt
            payload["agentMode"] = state["mode"]
            payload["mode"] = state["mode"]
            payload["category"] = state["category"]
            payload["generatedAt"] = state["generated_at"]
            payload["evidenceGaps"] = state.get("evidence_gaps") or []
        elif tool_name == "render_html_report":
            report_data_tool = self._latest_successful_tool(state, "build_market_report_data")
            report_data = (
                (
                    report_data_tool.get("data")
                    if isinstance(report_data_tool.get("data"), dict)
                    else {}
                )
                if report_data_tool
                else {}
            )
            tiktok_new_product_data_tool = self._latest_successful_tool(
                state, "build_tiktok_new_product_report_data"
            )
            tiktok_new_product_data = (
                (
                    tiktok_new_product_data_tool.get("data")
                    if isinstance(tiktok_new_product_data_tool.get("data"), dict)
                    else {}
                )
                if tiktok_new_product_data_tool
                else {}
            )
            tiktok_competitor_shop_data_tool = self._latest_successful_tool(
                state, "build_tiktok_bra_competitor_shop_report_data"
            )
            tiktok_competitor_shop_data = (
                (
                    tiktok_competitor_shop_data_tool.get("data")
                    if isinstance(tiktok_competitor_shop_data_tool.get("data"), dict)
                    else {}
                )
                if tiktok_competitor_shop_data_tool
                else {}
            )
            trend_report_data_tool = self._latest_successful_tool(state, "build_trend_report_data")
            trend_report_data = (
                (
                    trend_report_data_tool.get("data")
                    if isinstance(trend_report_data_tool.get("data"), dict)
                    else {}
                )
                if trend_report_data_tool
                else {}
            )
            competitor_product_data_tool = self._latest_successful_tool(
                state, "build_competitor_product_report_data"
            )
            competitor_product_data = (
                (
                    competitor_product_data_tool.get("data")
                    if isinstance(competitor_product_data_tool.get("data"), dict)
                    else {}
                )
                if competitor_product_data_tool
                else {}
            )
            hot_product_pain_data_tool = self._latest_successful_tool(
                state, "build_hot_product_pain_report_data"
            )
            hot_product_pain_data = (
                (
                    hot_product_pain_data_tool.get("data")
                    if isinstance(hot_product_pain_data_tool.get("data"), dict)
                    else {}
                )
                if hot_product_pain_data_tool
                else {}
            )
            active_builder = str(
                state.get("report_pipeline_builder") or self._required_report_data_builder(state)
            )
            report_data = report_data if active_builder == "build_market_report_data" else {}
            tiktok_new_product_data = (
                tiktok_new_product_data
                if active_builder == "build_tiktok_new_product_report_data"
                else {}
            )
            tiktok_competitor_shop_data = (
                tiktok_competitor_shop_data
                if active_builder == "build_tiktok_bra_competitor_shop_report_data"
                else {}
            )
            trend_report_data = (
                trend_report_data if active_builder == "build_trend_report_data" else {}
            )
            competitor_product_data = (
                competitor_product_data
                if active_builder == "build_competitor_product_report_data"
                else {}
            )
            hot_product_pain_data = (
                hot_product_pain_data
                if active_builder == "build_hot_product_pain_report_data"
                else {}
            )
            analysis_tool = self._latest_successful_tool(state, "analyze_market_report")
            analysis_data = (
                analysis_tool.get("data")
                if analysis_tool and isinstance(analysis_tool.get("data"), dict)
                else {}
            )
            insight_tool = self._latest_successful_tool(
                state, "synthesize_report_insights"
            )
            insight_narrative = (
                insight_tool.get("data")
                if insight_tool and isinstance(insight_tool.get("data"), dict)
                else {}
            )
            chart_render_tool = self._latest_successful_tool(
                state, "render_report_charts"
            )
            chart_render_bundle = (
                chart_render_tool.get("data")
                if chart_render_tool and isinstance(chart_render_tool.get("data"), dict)
                else {}
            )

            def with_report_analysis(report_data: dict[str, Any]) -> dict[str, Any]:
                if not report_data:
                    return report_data
                metric_analysis = {
                    key: value
                    for key, value in analysis_data.items()
                    if key
                    not in {
                        "metric_facts",
                        "derived_metrics",
                        "metric_gaps",
                    }
                }
                return {
                    **report_data,
                    **(
                        {
                            "metric_facts": analysis_data.get("metric_facts")
                            if isinstance(analysis_data.get("metric_facts"), list)
                            else report_data.get("metric_facts") or [],
                            "derived_metrics": analysis_data.get("derived_metrics")
                            if isinstance(analysis_data.get("derived_metrics"), list)
                            else [],
                            "metric_gaps": analysis_data.get("metric_gaps")
                            if isinstance(analysis_data.get("metric_gaps"), list)
                            else [],
                            "metric_analysis": metric_analysis,
                        }
                        if analysis_data
                        else {}
                    ),
                    **(
                        {"insight_narrative": insight_narrative}
                        if insight_narrative
                        else {}
                    ),
                }

            report_data = with_report_analysis(report_data)
            tiktok_new_product_data = with_report_analysis(tiktok_new_product_data)
            tiktok_competitor_shop_data = with_report_analysis(
                tiktok_competitor_shop_data
            )
            trend_report_data = with_report_analysis(trend_report_data)
            competitor_product_data = with_report_analysis(competitor_product_data)
            hot_product_pain_data = with_report_analysis(hot_product_pain_data)
            payload["marketReportData"] = report_data
            payload["tiktokNewProductReportData"] = tiktok_new_product_data
            payload["tiktokCompetitorShopReportData"] = tiktok_competitor_shop_data
            payload["trendReportData"] = trend_report_data
            payload["competitorProductReportData"] = competitor_product_data
            payload["hotProductPainReportData"] = hot_product_pain_data
            payload["chartRenderBundle"] = chart_render_bundle
            payload["toolResults"] = (
                []
                if (
                    report_data
                    or tiktok_new_product_data
                    or tiktok_competitor_shop_data
                    or trend_report_data
                    or competitor_product_data
                    or hot_product_pain_data
                )
                else [
                    tool
                    for tool in state.get("tools") or []
                    if str(tool.get("name") or "") != "render_html_report"
                ]
            )
            payload["prompt"] = task_prompt
            payload["agentMode"] = state["mode"]
            payload["mode"] = state["mode"]
            payload["category"] = state["category"]
            payload["generatedAt"] = state["generated_at"]
            payload["evidenceGaps"] = state.get("evidence_gaps") or []
            payload["useLlm"] = bool(state.get("use_llm"))
            payload["skillId"] = state.get("selected_skill_id")
            payload["skillMarkdown"] = str(
                (state.get("selected_skill") or {}).get("markdown") or ""
            )
            payload["skillHtmlTemplate"] = str(
                (state.get("selected_skill") or {}).get("html_template") or ""
            )
        elif tool_name == "render_markdown_report":
            brief_data_tool = self._latest_successful_tool(state, "build_product_design_brief_data")
            brief_data = (
                (
                    brief_data_tool.get("data")
                    if isinstance(brief_data_tool.get("data"), dict)
                    else {}
                )
                if brief_data_tool
                else {}
            )
            payload["productDesignBriefData"] = brief_data
            payload["toolResults"] = []
            payload["prompt"] = task_prompt
            payload["agentMode"] = state["mode"]
            payload["mode"] = state["mode"]
            payload["category"] = state["category"]
            payload["generatedAt"] = state["generated_at"]
            payload["evidenceGaps"] = state.get("evidence_gaps") or []
            payload["useLlm"] = bool(state.get("use_llm"))
            payload["skillId"] = state.get("selected_skill_id")
            payload["skillMarkdown"] = str(
                (state.get("selected_skill") or {}).get("markdown") or ""
            )
        return payload

    def _clarification_from_tool_args(
        self,
        state: AgentRuntimeState,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        questions = args.get("questions") if isinstance(args.get("questions"), list) else []
        missing = (
            args.get("missing_params")
            if isinstance(args.get("missing_params"), list)
            else state.get("missing_params") or []
        )
        normalized_questions: list[dict[str, Any]] = []
        for question in questions:
            if isinstance(question, dict):
                field = str(
                    question.get("field") or question.get("label") or question.get("question") or ""
                )
                normalized_questions.append(
                    {
                        "field": field,
                        "label": str(question.get("label") or field),
                        "question": str(question.get("question") or field),
                        "suggestions": question.get("suggestions")
                        if isinstance(question.get("suggestions"), list)
                        else [],
                    }
                )
                continue
            normalized_questions.append(
                {
                    "field": str(question),
                    "label": str(question),
                    "question": str(question),
                    "suggestions": [],
                }
            )
        return {
            "status": "needs_input",
            "message": args.get("reason")
            or (state.get("clarification") or {}).get("message")
            or "需要补齐参数后继续执行。",
            "missing_params": [str(item) for item in missing],
            "resolved_params": state.get("skill_params") or {},
            "questions": normalized_questions,
        }

    def _build_pending_output_files(
        self,
        state: AgentRuntimeState,
        report_file_path: str | None,
    ) -> list[dict[str, str]]:
        output_files: list[dict[str, str]] = []
        selected_skill = state.get("selected_skill") or {}
        if state.get("skill_file_path"):
            output_files.append(
                {
                    "type": "skill",
                    "label": str(
                        selected_skill.get("name") or state.get("selected_skill_id") or "Skill"
                    ),
                    "name": Path(str(state.get("skill_file_path"))).name,
                    "path": str(state.get("skill_file_path")),
                    "summary": str(selected_skill.get("description") or ""),
                }
            )
        if report_file_path:
            report_name = Path(report_file_path).name
            report_label = (
                "Markdown report"
                if Path(report_file_path).suffix.lower() == ".md"
                else "HTML report"
            )
            output_files.append(
                {
                    "type": "report",
                    "label": report_label,
                    "name": report_name,
                    "path": report_file_path,
                    "summary": str((state.get("artifact") or {}).get("title") or ""),
                }
            )
        return output_files

    def _build_output_files(
        self,
        state: AgentRuntimeState,
        report_file_path: str | None,
    ) -> list[dict[str, str]]:
        if not report_file_path:
            return []
        report_name = Path(report_file_path).name
        report_label = (
            "Markdown report" if Path(report_file_path).suffix.lower() == ".md" else "HTML report"
        )
        return [
            {
                "type": "report",
                "label": report_label,
                "name": report_name,
                "path": report_file_path,
                "summary": str((state.get("artifact") or {}).get("title") or ""),
            }
        ]

    def _add_event(
        self,
        state: AgentRuntimeState,
        event_type: str,
        status: str,
        title: str,
        message: str = "",
        *,
        tool: str | None = None,
        duration_ms: int | None = None,
        data: dict[str, Any] | None = None,
        input_params: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        file_path: str | None = None,
        event_id: str | None = None,
        stream_only: bool = False,
    ) -> dict[str, Any]:
        events = list(state.get("events") or [])
        with self._event_sequence_lock:
            sequence = self._event_sequences_by_id.get(event_id or "")
            if sequence is None:
                self._event_sequence += 1
                sequence = self._event_sequence
                if event_id:
                    self._event_sequences_by_id[event_id] = sequence
        event = self.deps.agent_event(
            sequence,
            event_type,
            status,
            title,
            message,
            tool=tool,
            duration_ms=duration_ms,
            data=data,
            input_params=input_params,
            output=output,
            file_path=file_path,
            event_id=event_id,
        )
        event["run_id"] = state["run_id"]
        if not stream_only:
            events.append(event)
            state["events"] = events
            self._last_state = state
            self._write_progress(state)
        if self._emit_event:
            self._emit_event(event)
        return event

    @staticmethod
    def _compact_progress_value(value: Any, depth: int = 0) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value if len(value) <= 1200 else f"{value[:1199]}..."
        if depth >= 2:
            if isinstance(value, list):
                return {"item_count": len(value)}
            if isinstance(value, dict):
                return {"field_count": len(value)}
            return compact_for_event(str(value), 240)
        if isinstance(value, list):
            return [
                LangGraphAgentRuntime._compact_progress_value(item, depth + 1)
                for item in value[:20]
            ]
        if isinstance(value, dict):
            return {
                str(key): LangGraphAgentRuntime._compact_progress_value(item, depth + 1)
                for key, item in list(value.items())[:30]
            }
        return compact_for_event(str(value), 240)

    def _write_progress(
        self,
        state: AgentRuntimeState,
        *,
        status: str = "running",
        error: str = "",
    ) -> None:
        run_id = str(state.get("run_id") or "")
        if not run_id:
            return
        events = [
            self._compact_progress_value(event)
            for event in list(state.get("events") or [])
            if isinstance(event, dict)
        ]
        tools = []
        for tool in list(state.get("tools") or []):
            if not isinstance(tool, dict):
                continue
            tools.append(
                self._compact_progress_value(
                    {key: value for key, value in tool.items() if key != "data"}
                )
            )
        payload = {
            "run_id": run_id,
            "generated_at": state.get("generated_at"),
            "updated_at": self.deps.now_iso(),
            "status": status,
            "response_type": "progress",
            "mode": state.get("mode"),
            "category": state.get("category"),
            "prompt": state.get("prompt"),
            "events": events,
            "tools": tools,
            "output_files": self._compact_progress_value(state.get("output_files") or []),
        }
        if error:
            payload["error"] = compact_for_event(error, 1200)
        try:
            self.deps.write_json(run_id, "progress.json", payload)
        except OSError:
            pass


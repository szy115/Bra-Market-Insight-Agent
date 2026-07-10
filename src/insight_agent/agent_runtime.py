from __future__ import annotations

import hashlib
import json
import os
import re
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

SUCCESS_TOOL_STATUSES = {"ok", "partial_ok"}


def compact_for_event(text: str, limit: int = 240) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def llm_failure_user_message(exc: BaseException, completed_tool_count: int) -> str:
    text = str(exc)
    lowered = text.lower()
    if "api key is not configured" in lowered or "http 401" in lowered or "http 403" in lowered:
        reason = "LLM API key 或权限配置不可用"
        advice = "请在设置里检查 API key、模型名和 Base URL。"
    elif "unexpected_eof_while_reading" in lowered or "eof occurred in violation of protocol" in lowered or "ssl" in lowered:
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
    capability_inspected: bool
    planner: dict[str, Any]
    response: dict[str, Any]


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
        self._graph = self._build_graph()

    def run(
        self,
        payload: dict[str, Any],
        emit_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        self._emit_event = emit_event
        initial = self._initial_state(dict(payload))
        self._last_state = initial
        try:
            result = self._graph.invoke(
                initial,
                config={
                    "recursion_limit": 80,
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
        builder.add_edge(START, "agent")
        builder.add_conditional_edges(
            "agent",
            lambda state: "tools" if state.get("pending_tool_calls") else "end",
            {"tools": "tools", "end": END},
        )
        builder.add_conditional_edges(
            "tools",
            lambda state: "end" if state.get("response") else "agent",
            {"agent": "agent", "end": END},
        )
        return builder.compile(checkpointer=MemorySaver())

    def _initial_state(self, payload: dict[str, Any]) -> AgentRuntimeState:
        user_prompt = str(payload.get("prompt") or "").strip()
        if not user_prompt:
            raise ValueError("prompt is required")

        continuation_run = self.deps.load_agent_run(str(payload.get("continueRunId") or "").strip())
        forced_skill_id = str(payload.get("skillId") or "").strip() or None
        continuation_context = ""
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
                or str(previous_skill.get("skill_id") or previous_pending.get("skill_id") or "").strip()
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
            merged_params = dict(previous_params or {})
            payload_params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
            merged_params.update(
                {key: value for key, value in payload_params.items() if value is not None and value != ""}
            )
            payload["params"] = merged_params
            previous_prompt = str(continuation_run.get("prompt") or "").strip()
            prompt = f"{previous_prompt}\n\n用户补充参数：{user_prompt}" if previous_prompt else user_prompt
            payload.setdefault("agentMode", continuation_run.get("mode"))
            continuation_context = (
                "\n这是上一轮 needs_input 的继续执行。"
                f"\n上一轮已解析参数：{json.dumps(previous_params or {}, ensure_ascii=False)}"
                f"\n上一轮缺少参数：{json.dumps(previous_missing, ensure_ascii=False)}"
                f"\n上一轮向用户提出的问题：{json.dumps(previous_questions, ensure_ascii=False)}"
                "\n请从“用户补充参数”中抽取新参数并放入 load_skill.extracted_params。"
            )
        else:
            prompt = user_prompt

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
            "selected_skill_id": None,
            "selected_skill": None,
            "skill_params": {},
            "missing_params": [],
            "clarification": {},
            "skill_file_path": "",
            "events": [],
            "tools": [],
            "evidence_gaps": [],
            "output_files": [],
            "assistant_message": {},
            "capability_inspected": False,
            "planner": {
                "enabled": use_llm,
                "status": "running" if use_llm else "not_requested",
                "message": "Native tool-calling runtime.",
                "native_tool_calls": True,
                "planned_tools": [],
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
                [{"role": "system", "content": self._system_prompt(state)}] + list(state.get("messages") or []),
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
                output={"summary": "No further data tools ran.", "completed_tool_count": completed_tool_count},
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

        tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
        state["pending_tool_calls"] = tool_calls
        if not tool_calls:
            content = str(message.get("content") or "").strip()
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
            return self._synthesize(state, llm_enabled=True)
        return state

    def _tools_node(self, state: AgentRuntimeState) -> AgentRuntimeState:
        tool_messages: list[dict[str, Any]] = []
        for tool_call in state.get("pending_tool_calls") or []:
            name, args = self._tool_call_name_args(tool_call)
            tool_call_id = str(tool_call.get("id") or f"tool-{len(tool_messages) + 1}")
            if name == "load_skill":
                content = self._run_load_skill(state, args)
            elif name == "ask_user":
                if state.get("selected_skill_id") and not state.get("missing_params"):
                    content = {
                        "status": "ignored",
                        "summary": (
                            "load_skill already resolved all required inputs. "
                            "Do not pause to confirm resolved parameters; continue with data tools or synthesize."
                        ),
                        "resolved_params": state.get("skill_params") or {},
                    }
                else:
                    self._run_ask_user(state, args)
                    return state
            elif name == "respond_to_user":
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
                    content = self._inspect_agent_capabilities(state, {"focus": state.get("prompt") or ""})
                    state["messages"] = list(state.get("messages") or []) + tool_messages + [
                        {"role": "assistant", "content": "", "tool_calls": [synthetic_call]},
                        {
                            "role": "tool",
                            "tool_call_id": "inspect-agent-capabilities",
                            "name": "inspect_agent_capabilities",
                            "content": json.dumps(content, ensure_ascii=False, default=str),
                        },
                    ]
                    state["pending_tool_calls"] = []
                    return state
                self._respond_to_user(state, str(args.get("message") or ""))
                return state
            elif name == "inspect_agent_capabilities":
                content = self._inspect_agent_capabilities(state, args)
            elif name == "synthesize_artifact":
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
                self._synthesize(state, llm_enabled=bool(state.get("use_llm")))
                return state
            elif name in self.deps.tool_catalog():
                content = self._run_data_tool(state, name, args)
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
        extracted_params = args.get("extracted_params") if isinstance(args.get("extracted_params"), dict) else {}
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
        run_file_path = str((self.deps.cache_dir() / "agent-runs" / state["run_id"] / "run.json").resolve())
        output_files = self._build_pending_output_files(state, None)
        message_parts = [str(clarification.get("message") or "需要补齐参数后继续执行。")]
        questions = [
            str(question.get("question") or question.get("label") or question.get("field") or "")
            for question in clarification.get("questions", [])
            if isinstance(question, dict)
        ]
        if questions:
            message_parts.append("\n".join(f"- {question}" for question in questions if question))
        assistant_message = {"role": "assistant", "content": "\n".join(part for part in message_parts if part).strip()}
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
                "missing_params": clarification.get("missing_params") or state.get("missing_params") or [],
                "file_path": state.get("skill_file_path") or "",
            },
            "pending": {
                "continue_run_id": state["run_id"],
                "skill_id": state.get("selected_skill_id"),
                "resolved_params": state.get("skill_params") or {},
                "missing_params": clarification.get("missing_params") or state.get("missing_params") or [],
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

    def _check_evidence_gate_before_synthesis(self, state: AgentRuntimeState) -> dict[str, Any]:
        gate = validate_evidence_contract(
            state.get("selected_skill"),
            prompt=state["prompt"],
            params=state.get("skill_params") or {},
            tools=state.get("tools") or [],
            success_statuses=SUCCESS_TOOL_STATUSES,
        )
        state["evidence_gaps"] = gate.get("warn_gaps") or []
        if gate.get("status") != "blocked":
            return gate
        block_gaps = gate.get("block_gaps") or []
        missing_tools = sorted({str(gap.get("tool") or "") for gap in block_gaps if gap.get("tool")})
        summary = "Evidence Contract blocked synthesis. Missing required evidence: " + ", ".join(missing_tools)
        content = {
            "status": "blocked",
            "outcome": "evidence_contract_blocked",
            "summary": summary,
            "missing_evidence": block_gaps,
            "warn_evidence": gate.get("warn_gaps") or [],
            "recommended_tool_calls": missing_tools,
            "instruction": "Call the missing data tool(s) before calling synthesize_artifact again.",
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
        state["evidence_gaps"] = gate.get("warn_gaps") or []
        if gate.get("status") != "blocked":
            return gate
        block_gaps = gate.get("block_gaps") or []
        missing_tools = sorted({str(gap.get("tool") or "") for gap in block_gaps if gap.get("tool")})
        summary = "Evidence Contract blocked HTML rendering. Missing required evidence: " + ", ".join(missing_tools)
        content = {
            "status": "blocked",
            "outcome": "evidence_contract_blocked",
            "summary": summary,
            "missing_evidence": block_gaps,
            "warn_evidence": gate.get("warn_gaps") or [],
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

    def _tool_results_for_synthesis(self, state: AgentRuntimeState) -> list[dict[str, Any]]:
        tool_results = list(state.get("tools") or [])
        evidence_gaps = state.get("evidence_gaps") or []
        if evidence_gaps:
            tool_results.append(
                {
                    "name": "evidence_gate",
                    "label": "Evidence Contract",
                    "status": "partial_ok",
                    "summary": f"{len(evidence_gaps)} warn-level evidence gap(s) must be disclosed in the final Artifact.",
                    "duration_ms": 0,
                    "input": {"skill_id": state.get("selected_skill_id")},
                    "data": {"gaps": evidence_gaps},
                }
            )
        return tool_results

    def _latest_successful_tool(self, state: AgentRuntimeState, tool_name: str) -> dict[str, Any] | None:
        for tool in reversed(state.get("tools") or []):
            if str(tool.get("name") or "") == tool_name and str(tool.get("status") or "") in SUCCESS_TOOL_STATUSES:
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
        resolved = data.get("resolved_params") if isinstance(data.get("resolved_params"), dict) else {}
        skill_params = dict(state.get("skill_params") or {})
        updated = False
        if tool_name == "sellersprite_product_node":
            node_id_path = str(resolved.get("category_node_id") or "").strip()
            if re.fullmatch(r"\d+(?::\d+)*", node_id_path):
                skill_params["category_node_id"] = node_id_path
                node_label_path = str(resolved.get("category_node_label_path") or "").strip()
                if node_label_path:
                    skill_params["category_node_label_path"] = node_label_path
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
            candidate_asins = skill_params.get("candidate_product_asins") if isinstance(skill_params.get("candidate_product_asins"), list) else []
            if re.fullmatch(r"[A-Z0-9]{10}", asin) and (not candidate_asins or asin in candidate_asins):
                reviewed = skill_params.get("reviewed_product_asins") if isinstance(skill_params.get("reviewed_product_asins"), list) else []
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

    def _apply_evidence_gaps_to_artifact(self, state: AgentRuntimeState, artifact: dict[str, Any]) -> dict[str, Any]:
        evidence_gaps = state.get("evidence_gaps") or []
        if not evidence_gaps:
            return artifact
        next_artifact = dict(artifact)
        gap_notes = [
            str(gap.get("artifact_requirement") or f"缺少 {gap.get('tool')} 证据。")
            for gap in evidence_gaps
            if isinstance(gap, dict)
        ]
        existing_risks = next_artifact.get("risks") if isinstance(next_artifact.get("risks"), list) else []
        next_artifact["risks"] = [*existing_risks, *gap_notes]
        next_artifact["evidence_gaps"] = evidence_gaps
        return next_artifact

    def _run_data_tool(
        self,
        state: AgentRuntimeState,
        tool_name: str,
        args: dict[str, Any],
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
        started_index = len(state.get("tools") or []) + 1
        tool_catalog = self.deps.tool_catalog()
        label = tool_catalog.get(tool_name, {}).get("label", tool_name)
        tool_payload = self._payload_with_tool_args(state, tool_name, args)
        tool_category = str(tool_payload.get("category") or state["category"])
        tool_input = self.deps.tool_input_payload(tool_name, tool_category, tool_payload)
        if tool_name == "sellersprite_review" and state.get("selected_skill_id") == "hot_product_pain_analysis":
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
        if self._emit_event:
            self._add_event(
                state,
                "tool",
                "running",
                f"调用工具：{label}",
                f"正在执行 {label}，整理输入参数并等待数据返回。",
                tool=tool_name,
                input_params=tool_input,
                data={"label": label, "status": "running", "native_tool": tool_name},
                event_id=tool_event_id,
                stream_only=True,
            )
        result = self.deps.execute_tool(tool_name, tool_category, tool_payload)
        if tool_name == "render_html_report" and str(result.get("status") or "") in SUCCESS_TOOL_STATUSES:
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            html_content = data.get("html") if isinstance(data.get("html"), str) else ""
            if html_content:
                report_file_path = self.deps.write_text(state["run_id"], "report.html", html_content)
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
        planner = dict(state.get("planner") or {})
        planned_tools = [str(tool.get("name")) for tool in tools if tool.get("name")]
        planner["planned_tools"] = planned_tools
        state["planner"] = planner
        result_status = str(result.get("status") or "")
        event_status = "ok" if result_status in SUCCESS_TOOL_STATUSES else "skipped" if result_status == "empty" else "error"
        self._add_event(
            state,
            "tool",
            event_status,
            f"调用工具：{label}",
            str(result.get("summary") or ""),
            tool=tool_name,
            duration_ms=int(result.get("duration_ms") or 0),
            data={
                "label": label,
                "status": result.get("status"),
                "outcome": result.get("outcome"),
                "native_tool": tool_name,
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
        ok_tools = [tool for tool in state.get("tools") or [] if tool.get("status") in SUCCESS_TOOL_STATUSES]
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
        artifact_started = time.time()
        if self._emit_event:
            self._add_event(
                state,
                "artifact",
                "running",
                "生成 Artifact",
                "正在基于工具证据生成结构化产出。",
                input_params={
                    "tool_count": len(state.get("tools") or []),
                    "useLlm": llm_enabled,
                    "locale": state["locale"],
                },
                event_id="artifact",
                stream_only=True,
            )
        required_html_tool = self._required_html_report_tool(state)
        rendered_report_tool = self._latest_successful_tool(state, "render_html_report")
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
                    if str(tool.get("name") or "") == "render_html_report"
                ),
                None,
            )
            reason = (
                str(render_attempt.get("summary") or "")
                if isinstance(render_attempt, dict)
                else "render_html_report was not completed."
            )
            required_tool_label = required_html_tool or "render_html_report"
            self._add_event(
                state,
                "artifact",
                "error",
                "未生成最终 Artifact",
                f"最终 HTML 必须来自 {required_tool_label}，但该工具没有成功产出报告文件。",
                input_params={
                    "skill_id": state.get("selected_skill_id"),
                    "required_tool": required_tool_label,
                    "tool_count": len(state.get("tools") or []),
                    "useLlm": llm_enabled,
                },
                output={
                    "summary": reason,
                    "instruction": "修复 LLM HTML 生成失败原因后重试；系统不再提供固定 HTML 模板 fallback。",
                },
                event_id="artifact" if self._emit_event else None,
            )
            return self._respond_to_user(
                state,
                f"最终 HTML 报告没有生成：`{required_tool_label}` 没有成功写出报告文件。请修复 LLM HTML 生成失败原因后重试；系统不会再改用固定模板生成报告。",
            )
        if rendered_data.get("report_file_path"):
            artifact = (
                rendered_data.get("artifact")
                if isinstance(rendered_data.get("artifact"), dict)
                else {}
            )
            if not artifact:
                artifact = {
                    "title": rendered_data.get("title") or "HTML 报告",
                    "executive_summary": "已基于当前 Skill 的工具证据生成 LLM-authored HTML 报告。",
                    "key_findings": [],
                    "opportunity_pool": [],
                    "risks": [],
                    "next_steps": [],
                }
            artifact = self._apply_evidence_gaps_to_artifact(state, artifact)
            html_analysis = rendered_data.get("html_analysis") if isinstance(rendered_data.get("html_analysis"), dict) else {}
            llm_analysis = {
                "enabled": llm_enabled,
                "status": "ok",
                "provider": html_analysis.get("provider") or "llm-html-renderer",
                "model": html_analysis.get("model") or "llm-authored-html.v1",
                "message": "Published the Skill-driven LLM-authored HTML report.",
                "usage": html_analysis.get("usage") or {},
                "html_generation_status": html_analysis.get("status") or "not_requested",
                "renderer": rendered_data.get("renderer") or "unknown",
            }
            report_file_path = str(rendered_data.get("report_file_path") or "")
        analysis_status = (
            "ok"
            if llm_analysis.get("status") == "ok"
            else "error"
            if llm_analysis.get("status") == "unavailable"
            else "skipped"
        )
        self._add_event(
            state,
            "artifact",
            analysis_status,
            "生成 Artifact",
            artifact.get("title") or "Artifact 已生成。",
            duration_ms=int((time.time() - artifact_started) * 1000),
            data={
                "status": llm_analysis.get("status"),
                "provider": llm_analysis.get("provider"),
                "model": llm_analysis.get("model"),
            },
            input_params={
                "tool_count": len(state.get("tools") or []),
                "useLlm": llm_enabled,
                "locale": state["locale"],
            },
            output={
                "title": artifact.get("title"),
                "executive_summary": artifact.get("executive_summary"),
                "key_findings": artifact.get("key_findings", [])[:6],
            },
            file_path=report_file_path,
            event_id="artifact" if self._emit_event else None,
        )
        run_file_path = str((self.deps.cache_dir() / "agent-runs" / state["run_id"] / "run.json").resolve())
        output_files = self._build_output_files(state, report_file_path)
        planner = dict(state.get("planner") or {})
        planner["planned_tools"] = [str(tool.get("name")) for tool in state.get("tools") or [] if tool.get("name")]
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
        self.deps.write_json(state["run_id"], "run.json", response)
        state["artifact"] = artifact
        state["llm_analysis"] = llm_analysis
        state["output_files"] = output_files
        state["response"] = response
        state["pending_tool_calls"] = []
        return state

    def _respond_to_user(self, state: AgentRuntimeState, message: str) -> AgentRuntimeState:
        content = self._normalize_chat_response(state, message.strip())
        self._add_event(
            state,
            "message",
            "ok",
            "回复用户",
            compact_for_event(content),
            output={"message": content},
        )
        run_file_path = str((self.deps.cache_dir() / "agent-runs" / state["run_id"] / "run.json").resolve())
        output_files: list[dict[str, str]] = []
        planner = dict(state.get("planner") or {})
        planner["planned_tools"] = [str(tool.get("name")) for tool in state.get("tools") or [] if tool.get("name")]
        state["planner"] = planner
        assistant_message = {"role": "assistant", "content": content}
        response = {
            "run_id": state["run_id"],
            "generated_at": state["generated_at"],
            "status": "ok",
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
        catalog = self.deps.tool_catalog()
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
                for item in (meta.get("auth_env_names") if isinstance(meta.get("auth_env_names"), list) else [])
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
            env_names = group.get("auth_env_names") if isinstance(group.get("auth_env_names"), list) else []
            group["auth_configured"] = any(os.getenv(str(env_name)) for env_name in env_names) if env_names else None
        focus_lower = str(focus or "").lower()

        def source_sort_key(group: dict[str, Any]) -> tuple[int, str]:
            searchable = " ".join(
                [
                    str(group.get("name") or ""),
                    str(group.get("source") or ""),
                    " ".join(str(item) for item in group.get("tools", []) if item),
                ]
            ).lower()
            return (0 if focus_lower and focus_lower in searchable else 1, str(group.get("source") or ""))

        return {
            "focus": focus,
            "skills": skills,
            "tools": tools,
            "tool_count": len(tools),
            "source_counts": source_counts,
            "tool_sources": sorted(source_groups.values(), key=source_sort_key),
        }

    def _capability_summary(self, state: AgentRuntimeState, snapshot: dict[str, Any]) -> str:
        source_counts = snapshot.get("source_counts") if isinstance(snapshot.get("source_counts"), dict) else {}
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
        return " ".join(part.upper() if part.lower() == "mcp" else part.capitalize() for part in parts)

    def _capability_source_line(self, state: AgentRuntimeState, sources: list[dict[str, Any]]) -> str:
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
                chunks.append(f"{source.get('name')} ({source.get('tool_count', 0)} tools, {auth_text})")
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
            chunks.append(f"{source.get('name')}（{source.get('tool_count', 0)} 个工具，{auth_text}）")
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

    def _inspect_agent_capabilities(self, state: AgentRuntimeState, args: dict[str, Any]) -> dict[str, Any]:
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
        active_category = str((state.get("skill_params") or {}).get("category") or state.get("category") or "").strip()
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
        marketplace_instruction = f"Current requested marketplace: {active_marketplace}.\n" if active_marketplace else ""
        skill_lines = [
            f"- {item.get('skill_id')}: {item.get('name')} — {item.get('description')}"
            for item in self.deps.skill_manifests()
        ]
        tool_catalog = self.deps.tool_catalog()
        available_data_tools = allowed_data_tools_for_skill(
            state.get("selected_skill"),
            list(tool_catalog.keys()),
        )
        tool_lines = [
            f"- {name} ({tool_catalog[name].get('source') or 'built_in'}): {tool_catalog[name].get('description')}"
            for name in available_data_tools
        ]
        forced = f"\nForced skill from pending run: {state.get('forced_skill_id')}" if state.get("forced_skill_id") else ""
        return (
            "You are Hsia R&D Insight Agent for evidence-driven ecommerce market research.\n"
            + category_instruction
            + marketplace_instruction
            + "Treat explicit UI params and the user's wording as authoritative; never replace them with an example category.\n"
            "You operate through native OpenAI tool calls. The harness executes tools and returns observations.\n"
            "Use tools step by step; do not describe a tool call when you can call the tool.\n\n"
            "Available Skills:\n"
            + "\n".join(skill_lines)
            + "\n\nData tools:\n"
            + "\n".join(tool_lines)
            + forced
            + "\n\nRules:\n"
            "- First call load_skill when a Skill is relevant. Do not run data tools before loading the relevant Skill.\n"
            "- When calling load_skill, extract brand, marketplace, category, time_range, and other required inputs from the user task into extracted_params.\n"
            "- Category is an open product/category phrase. Copy it from the user's wording or explicit UI params; do not copy examples from Skill descriptions.\n"
            "- For greetings or small talk, call respond_to_user with a normal chat answer.\n"
            "- For questions about what the agent can do, which tools/MCPs are available, or whether Sif/MCP can be called, first call inspect_agent_capabilities, then call respond_to_user using that observation.\n"
            "- load_skill may return missing_required_inputs. If that happens, call ask_user before any data tool.\n"
            "- After a Skill is loaded, the harness enforces its Tool Policy; use only available data tools.\n"
            "- synthesize_artifact runs an Evidence Contract Final Gate. If it returns blocked, call the missing tools before trying again.\n"
            "- When a Skill's Tool Policy or Evidence Contract requires render_html_report, call that tool before synthesize_artifact; synthesize_artifact only publishes the already-rendered report.\n"
            "- For weekly market insight reports, call build_market_report_data, then render_html_report, then call synthesize_artifact; MarketReportData already contains chart_specs.\n"
            "- For hot-product pain analysis, resolve the SellerSprite product node, use the category-validated concentration candidate pool, collect one successful recent balanced review result per requested product, then require Sif sales-list and keyword-competition evidence before render_html_report.\n"
            "- Do not directly generate a final HTML report in chat; render_html_report owns final HTML composition from the Skill's compiled evidence or tool results.\n"
            "- Do not call ask_user merely to confirm parameters that load_skill already resolved.\n"
            "- Use only tool evidence for conclusions. Do not invent sales volume, search volume, demographics, or market size.\n"
            "- Call data tools one at a time unless the next calls are clearly independent.\n"
            "- When evidence is enough, call synthesize_artifact or stop without tool calls.\n"
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
                                        "suggestions": {"type": "array", "items": {"type": "string"}},
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
                            "message": {"type": "string", "description": "The assistant message to show in the chat."},
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
            {
                "type": "function",
                "function": {
                    "name": "synthesize_artifact",
                    "description": "Finish tool collection and generate the final Artifact from collected evidence.",
                    "parameters": {
                        "type": "object",
                        "properties": {"reason": {"type": "string"}},
                        "required": [],
                    },
                },
            },
        ]
        tool_catalog = self.deps.tool_catalog()
        available_data_tools = allowed_data_tools_for_skill(
            state.get("selected_skill"),
            list(tool_catalog.keys()),
        )
        for name in available_data_tools:
            meta = tool_catalog[name]
            tool_defs.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": meta.get("description") or name,
                        "parameters": meta.get("input_schema") if isinstance(meta.get("input_schema"), dict) else {
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
        raw_args = function.get("arguments") if "arguments" in function else tool_call.get("arguments")
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
        payload = self.deps.payload_with_skill_params(state["payload"], state.get("skill_params") or {})
        payload["skillId"] = state.get("selected_skill_id") or payload.get("skillId")
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
                if str(tool.get("name") or "") not in {"build_market_report_data", "build_market_report_charts", "render_html_report"}
            ]
            payload["prompt"] = state["prompt"]
            payload["agentMode"] = state["mode"]
            payload["mode"] = state["mode"]
            payload["category"] = state["category"]
            payload["generatedAt"] = state["generated_at"]
            payload["evidenceGaps"] = state.get("evidence_gaps") or []
        elif tool_name == "render_html_report":
            report_data_tool = self._latest_successful_tool(state, "build_market_report_data")
            report_data = (
                report_data_tool.get("data")
                if isinstance(report_data_tool.get("data"), dict)
                else {}
            ) if report_data_tool else {}
            payload["marketReportData"] = report_data
            payload["toolResults"] = [] if report_data else [
                tool
                for tool in state.get("tools") or []
                if str(tool.get("name") or "") != "render_html_report"
            ]
            payload["prompt"] = state["prompt"]
            payload["agentMode"] = state["mode"]
            payload["mode"] = state["mode"]
            payload["category"] = state["category"]
            payload["generatedAt"] = state["generated_at"]
            payload["evidenceGaps"] = state.get("evidence_gaps") or []
            payload["useLlm"] = bool(state.get("use_llm"))
            payload["skillId"] = state.get("selected_skill_id")
            payload["skillMarkdown"] = str((state.get("selected_skill") or {}).get("markdown") or "")
            payload["skillHtmlTemplate"] = str((state.get("selected_skill") or {}).get("html_template") or "")
        return payload

    def _clarification_from_tool_args(
        self,
        state: AgentRuntimeState,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        questions = args.get("questions") if isinstance(args.get("questions"), list) else []
        missing = args.get("missing_params") if isinstance(args.get("missing_params"), list) else state.get("missing_params") or []
        normalized_questions: list[dict[str, Any]] = []
        for question in questions:
            if isinstance(question, dict):
                field = str(question.get("field") or question.get("label") or question.get("question") or "")
                normalized_questions.append(
                    {
                        "field": field,
                        "label": str(question.get("label") or field),
                        "question": str(question.get("question") or field),
                        "suggestions": question.get("suggestions") if isinstance(question.get("suggestions"), list) else [],
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
            "message": args.get("reason") or (state.get("clarification") or {}).get("message") or "需要补齐参数后继续执行。",
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
                    "label": str(selected_skill.get("name") or state.get("selected_skill_id") or "Skill"),
                    "name": Path(str(state.get("skill_file_path"))).name,
                    "path": str(state.get("skill_file_path")),
                    "summary": str(selected_skill.get("description") or ""),
                }
            )
        if report_file_path:
            output_files.append(
                {
                    "type": "report",
                    "label": "HTML report",
                    "name": Path(report_file_path).name,
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
        return [
            {
                "type": "report",
                "label": "HTML report",
                "name": Path(report_file_path).name,
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
        event = self.deps.agent_event(
            len(events) + 1,
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
                    {
                        key: value
                        for key, value in tool.items()
                        if key != "data"
                    }
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

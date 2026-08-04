import json
from typing import Any

from insight_agent import server as server_module


def chat_response(content: str) -> dict[str, Any]:
    return {
        "provider": "test",
        "model": "role-model",
        "usage": {"total_tokens": 10},
        "finish_reason": "stop",
        "message": {"role": "assistant", "content": content},
    }


def report_html(version: str) -> str:
    body = (
        f"这是市场洞察报告{version}。报告使用同一份 MarketReportData 说明需求、竞争、风险与下一步验证动作。"
        "每个判断都保留证据来源、统计周期、指标口径、替代解释和结论边界，避免把方向性信号写成确定事实。"
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{version}</title>
<style>body{{font-family:sans-serif;color:#172033}}section{{padding:16px;border-bottom:1px solid #ddd}}</style>
</head><body><main><h1>{version}</h1>
<section><h2>执行摘要</h2><p>{body}</p><p>{body}</p></section>
<section><h2>证据与结论</h2><p>{body}</p><p>{body}</p></section>
</main></body></html>"""


def market_report_data() -> dict[str, Any]:
    return {
        "schema_version": "market_report_data.v1",
        "title": "Hsia 市场洞察报告",
        "category": "minimizer bra",
        "marketplace": "Amazon US",
        "chart_specs": [],
        "summary_chart_ids": [],
        "data_gaps": [],
        "artifact": {"title": "Hsia 市场洞察报告", "executive_summary": "测试摘要"},
    }


def test_weekly_market_renderer_stages_v1_for_langgraph_approval(monkeypatch) -> None:
    roles: list[str] = []

    def fake_chat(
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        assert max_tokens == 100_000
        payload = json.loads(messages[-1]["content"])
        role = str(payload.get("role") or "initial_renderer")
        roles.append(role)
        return chat_response(report_html("V1"))

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)

    html, _artifact, analysis = server_module.compose_html_report_with_llm(
        {
            "marketReportData": market_report_data(),
            "skillId": "weekly_market_insight",
            "useLlm": True,
            "prompt": "生成市场洞察报告",
        }
    )

    assert roles == ["initial_renderer"]
    assert "V1" in html
    assert analysis["approval"]["orchestrator"] == "langgraph_nodes"
    assert analysis["approval"]["status"] == "pending_langgraph_review"
    assert analysis["approval"]["review_count"] == 0
    assert analysis["approval"]["revision_count"] == 0
    assert analysis["approval"]["published_without_approval"] is False
    assert analysis["input_profile"]["max_tokens_requested"] == 100_000


def test_report_review_node_returns_structured_rejection(monkeypatch) -> None:
    roles: list[str] = []
    review_requests: list[dict[str, Any]] = []
    review_system_messages: list[str] = []

    def fake_chat(messages: list[dict[str, Any]]) -> dict[str, Any]:
        payload = json.loads(messages[-1]["content"])
        role = str(payload.get("role") or "")
        roles.append(role)
        review_requests.append(payload)
        review_system_messages.append(str(messages[0].get("content") or ""))
        return chat_response(
            json.dumps(
                {
                    "decision": "revise",
                    "summary": "第1轮未通过",
                    "issues": [
                        {
                            "severity": "major",
                            "category": "numeric",
                            "location": "执行摘要",
                            "claim": "该市场适合立即进入",
                            "decision_enabled": "投入新品开发预算",
                            "steelman": "市场需求信号值得继续验证",
                            "fails_if": ["新品90天存活率低于预设门槛"],
                            "expected": "使用报告数据中的值",
                            "actual": "当前值不一致",
                            "evidence_ids": ["E01"],
                            "missing_evidence": ["新品90天存活率及同类样本基准"],
                            "kill_criterion": "拟议决策规则：新品90天存活率低于20%时停止推进，待验证",
                            "fixable_in_revision": True,
                            "revision_action": "downgrade",
                            "repair_instruction": "按 MarketReportData 修订并将进入建议降级为待验证假设",
                            "next_run_evidence_action": "查询最小同类新品样本的90天存活率",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)

    review = server_module.review_html_report_node(
        {
            "reportData": market_report_data(),
            "html": report_html("V1"),
            "reviewRound": 1,
        }
    )

    assert roles == ["html_report_approval_agent"]
    assert review["status"] == "ok"
    assert review["decision"] == "revise"
    assert review["approved"] is False
    assert review["round"] == 1
    assert (
        review["issues"][0]["repair_instruction"]
        == "按 MarketReportData 修订并将进入建议降级为待验证假设"
    )
    assert review["issues"][0]["fails_if"] == ["新品90天存活率低于预设门槛"]
    assert review["issues"][0]["revision_action"] == "downgrade"
    assert review["issues"][0]["next_run_evidence_action"] == "查询最小同类新品样本的90天存活率"
    assert "section ordering against the Skill Output Rules" in review_requests[0]["instruction"]
    assert "factual-consistency issue" in review_requests[0]["instruction"]
    assert "chart_layout_contract.required_chart_bindings" in review_requests[0]["instruction"]
    assert "figure must appear above insight-explanation" in review_requests[0]["instruction"]
    assert "Every required chart" in review_requests[0]["instruction"]
    assert review_requests[0]["chart_layout_contract"]["chart_insight_contract"][
        "one_per_ready_chart"
    ] is True
    assert "red-team" not in review_requests[0]["instruction"].lower()
    assert "factual-consistency approval agent" in review_system_messages[0]


def test_report_red_team_node_is_independent_and_structured(monkeypatch) -> None:
    requests: list[dict[str, Any]] = []
    system_messages: list[str] = []

    def fake_chat(messages: list[dict[str, Any]]) -> dict[str, Any]:
        requests.append(json.loads(messages[-1]["content"]))
        system_messages.append(str(messages[0].get("content") or ""))
        return chat_response(
            json.dumps(
                {
                    "decision": "revise",
                    "summary": "入场结论仍然过强",
                    "reviewed_claim_count": 1,
                    "findings": [
                        {
                            "severity": "major",
                            "location": "执行摘要",
                            "claim": "该市场适合立即进入",
                            "decision_enabled": "投入新品开发预算",
                            "steelman": "当前证据只支持进入小样验证",
                            "fails_if": ["可比新品90天存活率低于20%"],
                            "evidence_ids": ["E01"],
                            "missing_evidence": ["可比新品90天存活率"],
                            "kill_criterion": {
                                "type": "proposed_rule",
                                "value": "90天存活率低于20%时停止",
                                "basis": "当前为拟议规则",
                            },
                            "fixable_in_revision": True,
                            "revision_action": "narrow",
                            "repair_instruction": "把立即进入收窄为小样验证",
                            "next_run_evidence_action": "补一组同类新品90天样本",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)

    result = server_module.red_team_html_report_node(
        {
            "reportData": {
                **market_report_data(),
                "evidence_map": [{"id": "E01", "tool": "sif_market_get_keyword_history"}],
            },
            "html": report_html("V1"),
            "reviewRound": 1,
        }
    )

    assert result["schema_version"] == "report_red_team_review.v1"
    assert result["decision"] == "revise"
    assert result["approved"] is False
    assert result["findings"][0]["revision_action"] == "narrow"
    assert requests[0]["role"] == "html_report_strategy_red_team_agent"
    assert "no more than five load-bearing claims" in requests[0]["instruction"]
    assert "strategy red-team node" in system_messages[0]


def test_report_red_team_ignores_legacy_tool_payload_and_decides_from_report_data(
    monkeypatch,
) -> None:
    requests: list[dict[str, Any]] = []

    def fake_chat(messages: list[dict[str, Any]]) -> dict[str, Any]:
        requests.append(json.loads(messages[-1]["content"]))
        return chat_response(
            json.dumps(
                {
                    "decision": "revise",
                    "summary": "当前证据只支持收窄结论。",
                    "reviewed_claim_count": 0,
                    "findings": [],
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)
    tool_schema = {
        "type": "function",
        "function": {
            "name": "sif_market_get_keyword_demand",
            "description": "Read-only demand evidence.",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    result = server_module.red_team_html_report_node(
        {
            "reportData": market_report_data(),
            "html": report_html("V1"),
            "reviewRound": 1,
            "availableTools": [tool_schema],
        }
    )

    assert result["status"] == "ok"
    assert result["decision"] == "revise"
    assert result["approved"] is False
    assert "evidence_requests" not in result
    assert "evidence_tooling_allowed" not in requests[0]
    assert "evidence_observations" not in requests[0]
    assert "Do not request or call tools" in requests[0]["instruction"]


def test_insight_synthesis_requires_one_unified_interpretation_per_chart(
    monkeypatch,
) -> None:
    requests: list[dict[str, Any]] = []

    def fake_chat(messages: list[dict[str, Any]]) -> dict[str, Any]:
        requests.append(json.loads(messages[-1]["content"]))
        return chat_response(
            json.dumps(
                {
                    "sections": [
                        {
                            "section_id": "demand",
                            "title": "需求变化",
                            "insights": [
                                {
                                    "conclusion": "需求处于调整期",
                                    "observation": "近期值低于阶段峰值。",
                                    "interpretation": "需求尚未恢复到高峰水平。",
                                    "business_implication": "备货应保持克制。",
                                    "evidence_ids": ["E01"],
                                    "confidence": "medium",
                                }
                            ],
                        }
                    ],
                    "chart_insights": [
                        {
                            "chart_id": "demand_trend",
                            "section_id": "demand",
                            "section_title": "需求变化",
                            "observation": "近期值低于阶段峰值。",
                            "interpretation": "图表反映高峰后的调整期。",
                            "evidence_ids": ["E01"],
                            "interpretation_type": "descriptive",
                            "confidence": "medium",
                        },
                        {
                            "chart_id": "price_band",
                            "section_id": "price",
                            "section_title": "价格结构",
                            "observation": "中位价格带样本最密集。",
                            "interpretation": "该价格段更接近当前竞争中心。",
                            "evidence_ids": ["E02"],
                            "interpretation_type": "scope",
                            "confidence": "medium",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)
    result = server_module.synthesize_report_insights_node(
        {
            "reportData": {
                "schema_version": "market_report_data.v1",
                "evidence_map": [{"id": "E01"}, {"id": "E02"}],
                "chart_specs": [
                    {"id": "demand_trend", "quality_status": "ready"},
                    {"id": "price_band", "quality_status": "ready"},
                ],
            },
            "skill": {"skill_id": "weekly_market_insight"},
            "useLlm": True,
        }
    )

    assert result["section_insight_count"] == 1
    assert result["chart_insight_count"] == 2
    assert result["insight_count"] == 3
    assert result["internal_audit"]["unbound_chart_ids"] == []
    assert "Emit exactly one chart_insight for every ready chart_spec" in requests[0][
        "instruction"
    ]
    assert "fixed section count, insight count, or charts-per-insight limit" in requests[
        0
    ]["instruction"]
    assert "chart_insights" in requests[0]["output_schema"]
    assert "supplementary_chart_insights" not in requests[0]["output_schema"]


def test_html_revision_node_returns_next_html_version(monkeypatch) -> None:
    roles: list[str] = []

    def fake_chat(
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        assert max_tokens == 100_000
        payload = json.loads(messages[-1]["content"])
        role = str(payload.get("role") or "")
        roles.append(role)
        return chat_response(report_html("V2"))

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)

    revised = server_module.revise_html_report_node(
        {
            "reportData": market_report_data(),
            "html": report_html("V1"),
            "review": {
                "decision": "revise",
                "summary": "需要修改",
                "issues": [{"repair_instruction": "修订首稿"}],
            },
            "revisionRound": 1,
        }
    )

    assert roles == ["html_report_rendering_agent"]
    assert "V2" in revised["html"]
    assert revised["revision"]["status"] == "ok"
    assert revised["revision"]["applied"] is True
    assert revised["revision"]["max_tokens_requested"] == 100_000
    assert revised["revision"]["round"] == 1


def test_chart_layout_contract_keeps_validated_insight_binding() -> None:
    data = {
        **market_report_data(),
        "chart_specs": [
            {"id": "demand_trend", "quality_status": "ready"},
            {"id": "price_band", "quality_status": "ready"},
        ],
        "insight_narrative": {
            "chart_insights": [
                {
                    "chart_id": "demand_trend",
                    "section_id": "demand",
                    "section_title": "需求变化",
                    "conclusion": "核心词需求增强",
                    "observation": "核心词的近期需求高于外围词。",
                    "interpretation": "需求表达更集中。",
                    "business_implication": "卖点应优先承接核心任务。",
                    "action": "先验证核心词版本。",
                    "evidence_ids": ["E01"],
                    "interpretation_type": "business",
                },
                {
                    "chart_id": "price_band",
                    "section_id": "price",
                    "section_title": "价格结构",
                    "observation": "中位价格带样本更密集。",
                    "interpretation": "首轮测试应控制价格偏差。",
                    "evidence_ids": ["E02"],
                    "interpretation_type": "scope",
                }
            ],
        },
    }

    contract = server_module.report_chart_layout_contract(
        data,
        ["demand_trend", "price_band"],
    )

    assert contract["required_chart_bindings"][0]["section_id"] == "demand"
    assert contract["required_chart_bindings"][0]["chart_ids"] == ["demand_trend"]
    assert contract["required_chart_bindings"][1]["binding_role"] == "chart_insight"
    assert contract["required_chart_bindings"][1]["business_implication"] == ""
    assert contract["required_chart_bindings"][1]["chart_ids"] == ["price_band"]
    assert contract["unbound_required_chart_ids"] == []
    assert "max_charts_per_insight_block" not in contract
    assert contract["separate_text_and_chart_batches_forbidden"] is True
    assert contract["side_by_side_chart_explanation_forbidden"] is True


def test_renderer_context_does_not_truncate_sections_or_chart_insights() -> None:
    narrative = {
        "sections": [
            {
                "section_id": f"section_{section_index}",
                "title": f"章节 {section_index}",
                "insights": [
                    {
                        "conclusion": f"结论 {section_index}-{insight_index}",
                        "observation": "具体观察",
                        "interpretation": "有限解释",
                    }
                    for insight_index in range(5)
                ],
            }
            for section_index in range(13)
        ],
        "chart_insights": [
            {
                "chart_id": f"chart_{index}",
                "observation": f"图表 {index} 的具体观察",
                "interpretation": f"图表 {index} 的有限解释",
            }
            for index in range(30)
        ],
    }

    context = server_module.html_report_insight_narrative_context(narrative)

    assert len(context["sections"]) == 13
    assert all(len(section["insights"]) == 5 for section in context["sections"])
    assert len(context["chart_insights"]) == 30


def test_graph_report_keeps_every_ready_chart() -> None:
    data = {
        **market_report_data(),
        "chart_specs": [
            {"id": "demand_trend", "quality_status": "ready"},
            {"id": "unexplained_supplement", "quality_status": "ready"},
        ],
        "insight_narrative": {
            "sections": [
                {
                    "section_id": "demand",
                    "title": "需求变化",
                    "insights": [
                        {
                            "conclusion": "需求出现波动",
                            "observation": "近期值低于阶段峰值。",
                            "interpretation": "市场处于高峰后的调整期。",
                            "business_implication": "备货应保持克制。",
                            "evidence_ids": ["E01"],
                            "chart_ids": ["demand_trend"],
                        }
                    ],
                }
            ]
        },
    }

    specs = server_module.report_display_chart_specs(data)

    assert [chart["id"] for chart in specs] == [
        "demand_trend",
        "unexplained_supplement",
    ]


def test_other_html_report_skills_stage_for_generic_approval(monkeypatch) -> None:
    calls: list[list[dict[str, Any]]] = []

    def fake_chat(
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        assert max_tokens == 100_000
        calls.append(messages)
        return chat_response(report_html("OTHER"))

    monkeypatch.setattr(server_module, "call_openai_compatible_chat", fake_chat)

    html, _artifact, analysis = server_module.compose_html_report_with_llm(
        {
            "marketReportData": market_report_data(),
            "skillId": "another_market_skill",
            "useLlm": True,
            "prompt": "生成其他报告",
        }
    )

    assert len(calls) == 1
    assert "OTHER" in html
    assert analysis["approval"]["orchestrator"] == "langgraph_nodes"
    assert analysis["approval"]["status"] == "pending_langgraph_review"
    assert analysis["approval"]["review_count"] == 0
    assert analysis["approval"]["revision_count"] == 0

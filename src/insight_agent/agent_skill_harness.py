from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

SYSTEM_TOOL_POLICIES = {"system"}
ALLOWED_DATA_TOOL_POLICIES = {"required", "allowed", "conditional"}


@dataclass(frozen=True)
class ToolPolicyDecision:
    allowed: bool
    tool: str
    policy: str
    reason: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceGap:
    evidence_id: str
    tool: str
    required_when: str
    min_success: int
    observed_success: int
    severity: str
    if_missing: str
    artifact_requirement: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def markdown_section(markdown_text: str, heading: str) -> str:
    import re

    pattern = rf"^##\s+{re.escape(heading)}\s*$"
    match = re.search(pattern, markdown_text, flags=re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^##\s+", markdown_text[start:], flags=re.MULTILINE)
    end = start + next_match.start() if next_match else len(markdown_text)
    return markdown_text[start:end].strip()


def markdown_table_dicts(section: str) -> list[dict[str, str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or all(not cell for cell in cells):
            continue
        if all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        rows.append(cells)
    if len(rows) < 2:
        return []
    headers = [header.strip() for header in rows[0]]
    output: list[dict[str, str]] = []
    for row in rows[1:]:
        item = {
            headers[index]: row[index].strip()
            for index in range(min(len(headers), len(row)))
            if headers[index]
        }
        if item:
            output.append(item)
    return output


def parse_tool_policy(markdown_text: str) -> list[dict[str, str]]:
    policies: list[dict[str, str]] = []
    for row in markdown_table_dicts(markdown_section(markdown_text, "Tool Policy")):
        tool = str(row.get("tool") or "").strip()
        if not tool:
            continue
        policy = str(row.get("policy") or "allowed").strip().lower()
        policies.append(
            {
                "tool": tool,
                "policy": policy,
                "reason": str(row.get("reason") or "").strip(),
            }
        )
    return policies


def parse_evidence_contract(markdown_text: str) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for row in markdown_table_dicts(markdown_section(markdown_text, "Evidence Contract")):
        evidence_id = str(row.get("evidence_id") or "").strip()
        tool = str(row.get("tool") or "").strip()
        if not evidence_id or not tool:
            continue
        raw_min_success = str(row.get("min_success") or "1").strip()
        if raw_min_success.startswith("param:"):
            min_success: int | str = raw_min_success
        else:
            try:
                min_success = max(0, int(raw_min_success))
            except ValueError:
                min_success = 1
        rules.append(
            {
                "evidence_id": evidence_id,
                "tool": tool,
                "required_when": str(row.get("required_when") or "always").strip(),
                "min_success": min_success,
                "severity": str(row.get("severity") or "warn").strip().lower(),
                "if_missing": str(row.get("if_missing") or "continue_with_gap").strip(),
                "artifact_requirement": str(row.get("artifact_requirement") or "").strip(),
            }
        )
    return rules


def tool_policy_map(skill: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    rows = (skill or {}).get("tool_policy")
    if not isinstance(rows, list):
        return {}
    policy: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        tool = str(row.get("tool") or "").strip()
        if not tool:
            continue
        policy[tool] = {
            "policy": str(row.get("policy") or "allowed").strip().lower(),
            "reason": str(row.get("reason") or "").strip(),
        }
    return policy


def allowed_data_tools_for_skill(
    skill: dict[str, Any] | None,
    all_data_tools: list[str],
) -> list[str]:
    policy = tool_policy_map(skill)
    if not policy:
        return all_data_tools
    allowed = [
        tool
        for tool in all_data_tools
        if policy.get(tool, {}).get("policy") in ALLOWED_DATA_TOOL_POLICIES
    ]
    return allowed


def evaluate_tool_policy(
    skill: dict[str, Any] | None,
    tool_name: str,
    *,
    is_data_tool: bool = True,
) -> ToolPolicyDecision:
    if not is_data_tool:
        return ToolPolicyDecision(True, tool_name, "system", "", f"{tool_name} is a system tool.")
    policy = tool_policy_map(skill)
    if not policy:
        return ToolPolicyDecision(True, tool_name, "unspecified", "", "No Tool Policy is declared.")
    row = policy.get(tool_name)
    if not row:
        return ToolPolicyDecision(
            False,
            tool_name,
            "not_listed",
            "",
            f"{tool_name} is not listed in the selected Skill's Tool Policy.",
        )
    rule_policy = str(row.get("policy") or "").strip().lower()
    if rule_policy == "disallowed":
        return ToolPolicyDecision(
            False,
            tool_name,
            rule_policy,
            row.get("reason") or "",
            f"{tool_name} is disallowed by the selected Skill's Tool Policy.",
        )
    if rule_policy in ALLOWED_DATA_TOOL_POLICIES or rule_policy in SYSTEM_TOOL_POLICIES:
        return ToolPolicyDecision(True, tool_name, rule_policy, row.get("reason") or "", "Tool is allowed.")
    return ToolPolicyDecision(
        False,
        tool_name,
        rule_policy or "unknown",
        row.get("reason") or "",
        f"{tool_name} has an unsupported Tool Policy value: {rule_policy or 'unknown'}.",
    )


def required_when_matches(
    required_when: str,
    *,
    prompt: str,
    params: dict[str, Any],
    tools: list[dict[str, Any]],
) -> bool:
    predicate = str(required_when or "always").strip()
    if not predicate or predicate == "always":
        return True
    if predicate.startswith("prompt_mentions:"):
        terms = [term.strip().lower() for term in predicate.split(":", 1)[1].split(",") if term.strip()]
        prompt_lower = prompt.lower()
        return any(term in prompt_lower for term in terms)
    if predicate.startswith("param_present:"):
        key = predicate.split(":", 1)[1].strip()
        value = params.get(key)
        return value is not None and value != ""
    if predicate.startswith("param_equals:"):
        expression = predicate.split(":", 1)[1]
        if "=" not in expression:
            return False
        key, expected = [part.strip() for part in expression.split("=", 1)]
        return str(params.get(key) or "").strip().lower() == expected.lower()
    if predicate.startswith("tool_called:"):
        tool = predicate.split(":", 1)[1].strip()
        return any(str(item.get("name") or "") == tool for item in tools)
    return False


def resolve_min_success(value: Any, params: dict[str, Any]) -> int:
    if isinstance(value, str) and value.startswith("param:"):
        key = value.split(":", 1)[1].strip()
        try:
            return max(0, int(params.get(key) or 1))
        except (TypeError, ValueError):
            return 1
    try:
        return max(0, int(value or 1))
    except (TypeError, ValueError):
        return 1


def evidence_tool_identity(tool: dict[str, Any]) -> str:
    input_payload = tool.get("input") if isinstance(tool.get("input"), dict) else {}
    request = input_payload.get("request") if isinstance(input_payload.get("request"), dict) else {}
    filters = input_payload.get("filter") if isinstance(input_payload.get("filter"), dict) else {}
    identity_containers = (
        ("", input_payload),
        ("request.", request),
        ("filter.", filters),
    )
    for key in (
        "product_id",
        "seller_id",
        "creator_id",
        "uid",
        "room_id",
        "video_id",
        "asin",
        "keyword",
        "departmentKeyword",
        "nodeIdPath",
    ):
        for prefix, container in identity_containers:
            value = container.get(key)
            if value not in (None, ""):
                return f"{prefix}{key}:{str(value).strip().lower()}"
    return json.dumps(input_payload, ensure_ascii=False, sort_keys=True, default=str)


def evidence_tool_has_usable_review_text(tool: dict[str, Any]) -> bool:
    data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
    containers = [data]
    for key in ("result", "data"):
        if isinstance(data.get(key), dict):
            containers.append(data[key])
    for container in containers:
        for key in ("reviews", "list", "items", "comments"):
            rows = container.get(key)
            if not isinstance(rows, list):
                continue
            return any(
                isinstance(row, dict)
                and bool(
                    str(
                        row.get("review_text")
                        or row.get("content")
                        or row.get("review_content")
                        or row.get("comment")
                        or row.get("text")
                        or row.get("body")
                        or ""
                    ).strip()
                )
                for row in rows
            )
    return False


def validate_evidence_contract(
    skill: dict[str, Any] | None,
    *,
    prompt: str,
    params: dict[str, Any],
    tools: list[dict[str, Any]],
    success_statuses: set[str],
) -> dict[str, Any]:
    rules = (skill or {}).get("evidence_contract")
    if not isinstance(rules, list) or not rules:
        return {"status": "pass", "gaps": [], "block_gaps": [], "warn_gaps": []}
    gaps: list[EvidenceGap] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        required_when = str(rule.get("required_when") or "always")
        if not required_when_matches(required_when, prompt=prompt, params=params, tools=tools):
            continue
        tool_name = str(rule.get("tool") or "").strip()
        if not tool_name:
            continue
        min_success = resolve_min_success(rule.get("min_success"), params)
        successful_tools = [
            tool
            for tool in tools
            if str(tool.get("name") or "") == tool_name and str(tool.get("status") or "") in success_statuses
            and (
                tool_name != "mcp__fastmoss__product_review_list"
                or evidence_tool_has_usable_review_text(tool)
            )
        ]
        observed_success = (
            len({evidence_tool_identity(tool) for tool in successful_tools})
            if min_success > 1
            else len(successful_tools)
        )
        if observed_success >= min_success:
            continue
        gaps.append(
            EvidenceGap(
                evidence_id=str(rule.get("evidence_id") or tool_name),
                tool=tool_name,
                required_when=required_when,
                min_success=min_success,
                observed_success=observed_success,
                severity=str(rule.get("severity") or "warn").strip().lower(),
                if_missing=str(rule.get("if_missing") or "continue_with_gap"),
                artifact_requirement=str(rule.get("artifact_requirement") or ""),
            )
        )
    gap_dicts = [gap.to_dict() for gap in gaps]
    block_gaps = [gap for gap in gap_dicts if gap.get("severity") == "block"]
    warn_gaps = [gap for gap in gap_dicts if gap.get("severity") != "block"]
    return {
        "status": "blocked" if block_gaps else "warn" if warn_gaps else "pass",
        "gaps": gap_dicts,
        "block_gaps": block_gaps,
        "warn_gaps": warn_gaps,
    }

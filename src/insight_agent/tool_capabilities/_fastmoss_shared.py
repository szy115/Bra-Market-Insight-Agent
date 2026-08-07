from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .registry import (
    InvocationScope,
    PreservedToolResult,
    RecoveryTraits,
    ResultContract,
    ToolCapability,
)

FASTMOSS_AGENT_TOOL_PREFIX = "mcp__fastmoss__"
FastMossNormalizer = Callable[
    [str, str, dict[str, Any], dict[str, Any]],
    dict[str, Any],
]
FastMossAdapter = Callable[
    [str, dict[str, Any], bool, dict[str, Any]],
    dict[str, Any],
]


def load_fastmoss_specs(
    spec_path: Path,
    expected_names: Sequence[str],
    *,
    family_label: str,
) -> tuple[dict[str, Any], ...]:
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    specs = tuple(dict(item) for item in payload if isinstance(item, dict))
    names = tuple(str(item.get("name") or "") for item in specs)
    if names != tuple(expected_names):
        raise ValueError(f"FastMoss {family_label} capability specs are incomplete or reordered")
    return specs


def build_fastmoss_catalog(
    spec_path: Path,
    expected_names: Sequence[str],
    *,
    family_label: str,
) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for spec in load_fastmoss_specs(
        spec_path,
        expected_names,
        family_label=family_label,
    ):
        mcp_tool_name = str(spec["name"])
        capability_id = f"{FASTMOSS_AGENT_TOOL_PREFIX}{mcp_tool_name}"
        input_schema = dict(spec.get("input_schema") or {})
        input_schema.setdefault("type", "object")
        input_schema.setdefault("properties", {})
        input_schema.setdefault("required", [])
        catalog[capability_id] = {
            "label": f"FastMoss: {mcp_tool_name}",
            "description": str(spec.get("description") or ""),
            "input_schema": input_schema,
            "source": "fastmoss_mcp",
            "mcp_tool": mcp_tool_name,
            "auth_env_names": [
                "FASTMOSS_MCP_API_KEY",
                "FASTMOSS_MCP_KEY",
                "FASTMOSS_API_KEY",
            ],
            "checkpoint_reuse": True,
        }
    return catalog


def validate_fastmoss_result_data(result: Mapping[str, Any]) -> None:
    if not isinstance(result, Mapping):
        raise ValueError("FastMoss result data must be a mapping")


def build_fastmoss_capabilities(
    catalog: Mapping[str, dict[str, Any]],
    *,
    normalize_input: FastMossNormalizer,
    adapter: FastMossAdapter,
) -> list[ToolCapability]:
    capabilities: list[ToolCapability] = []
    for capability_id, tool_meta in catalog.items():
        mcp_tool_name = str(tool_meta["mcp_tool"])
        capabilities.append(
            ToolCapability(
                capability_id=capability_id,
                label=tool_meta["label"],
                description=tool_meta["description"],
                input_schema=tool_meta["input_schema"],
                invocation_scope=InvocationScope.PLANNER,
                normalize_input=lambda category, payload, capability_id=capability_id, tool_meta=tool_meta: normalize_input(
                    capability_id,
                    category,
                    payload,
                    tool_meta,
                ),
                adapter=lambda invocation, capability_id=capability_id, tool_meta=tool_meta: PreservedToolResult(
                    adapter(
                        capability_id,
                        invocation.tool_input,
                        bool(invocation.request_payload.get("bypassCache")),
                        tool_meta,
                    )
                ),
                shape_result=lambda result: dict(result.get("data") or {}),
                shape_error=lambda _exc: {},
                summarize=lambda result: str(
                    result.get("summary") or "FastMoss MCP returned structured evidence."
                ),
                result_contract=ResultContract(
                    contract_id="fastmoss_result.v1",
                    validate=validate_fastmoss_result_data,
                ),
                recovery=RecoveryTraits(
                    retryable=True,
                    default_timeout_seconds=600,
                    default_retry_attempts=2,
                ),
                output_kind="generic_json",
                catalog_metadata={
                    "source": tool_meta["source"],
                    "mcp_tool": mcp_tool_name,
                    "auth_env_names": tool_meta["auth_env_names"],
                    "checkpoint_reuse": tool_meta["checkpoint_reuse"],
                },
            )
        )
    return capabilities

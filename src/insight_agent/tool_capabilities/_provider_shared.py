from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .registry import (
    InvocationScope,
    PreservedToolResult,
    RecoveryTraits,
    ResultContract,
    ToolCapability,
)

ProviderNormalizer = Callable[
    [str, str, dict[str, Any], dict[str, Any]],
    dict[str, Any],
]
ProviderAdapter = Callable[
    [str, dict[str, Any], bool, dict[str, Any]],
    dict[str, Any],
]


@dataclass(frozen=True)
class ProviderCapabilityFamily:
    agent_tool_prefix: str
    provider_label: str
    source: str
    auth_env_names: tuple[str, ...]
    result_contract_id: str
    default_summary: str
    catalog_metadata: Mapping[str, Any] = field(default_factory=dict)


def load_provider_specs(
    spec_path: Path,
    expected_names: Sequence[str],
    *,
    provider_label: str,
    family_label: str,
) -> tuple[dict[str, Any], ...]:
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    specs = tuple(dict(item) for item in payload if isinstance(item, dict))
    names = tuple(str(item.get("name") or "") for item in specs)
    if names != tuple(expected_names):
        raise ValueError(
            f"{provider_label} {family_label} capability specs are incomplete or reordered"
        )
    return specs


def build_provider_catalog(
    spec_path: Path,
    expected_names: Sequence[str],
    *,
    family: ProviderCapabilityFamily,
    family_label: str,
) -> dict[str, dict[str, Any]]:
    specs = load_provider_specs(
        spec_path,
        expected_names,
        provider_label=family.provider_label,
        family_label=family_label,
    )
    return build_provider_catalog_from_specs(
        specs,
        expected_names,
        family=family,
        family_label=family_label,
    )


def build_provider_catalog_from_specs(
    specs: Sequence[Mapping[str, Any]],
    expected_names: Sequence[str],
    *,
    family: ProviderCapabilityFamily,
    family_label: str,
) -> dict[str, dict[str, Any]]:
    names = tuple(str(item.get("name") or "") for item in specs)
    if names != tuple(expected_names):
        raise ValueError(
            f"{family.provider_label} {family_label} capability specs are incomplete or reordered"
        )
    catalog: dict[str, dict[str, Any]] = {}
    for spec in specs:
        provider_tool_name = str(spec["name"])
        capability_id = f"{family.agent_tool_prefix}{provider_tool_name}"
        input_schema = dict(spec.get("input_schema") or {})
        input_schema.setdefault("type", "object")
        input_schema.setdefault("properties", {})
        input_schema.setdefault("required", [])
        catalog[capability_id] = {
            "label": f"{family.provider_label}: {provider_tool_name}",
            "description": str(spec.get("description") or ""),
            "input_schema": input_schema,
            "source": family.source,
            "mcp_tool": provider_tool_name,
            "auth_env_names": list(family.auth_env_names),
            **dict(family.catalog_metadata),
        }
    return catalog


def validate_provider_result_data(
    result: Mapping[str, Any],
    *,
    provider_label: str,
) -> None:
    if not isinstance(result, Mapping):
        raise ValueError(f"{provider_label} result data must be a mapping")


def build_provider_capabilities(
    catalog: Mapping[str, dict[str, Any]],
    *,
    family: ProviderCapabilityFamily,
    normalize_input: ProviderNormalizer,
    adapter: ProviderAdapter,
) -> list[ToolCapability]:
    capabilities: list[ToolCapability] = []
    for capability_id, tool_meta in catalog.items():
        metadata = {
            "source": tool_meta["source"],
            "mcp_tool": tool_meta["mcp_tool"],
            "auth_env_names": tool_meta["auth_env_names"],
            **{
                key: tool_meta[key]
                for key in family.catalog_metadata
                if key in tool_meta
            },
        }
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
                    result.get("summary") or family.default_summary
                ),
                result_contract=ResultContract(
                    contract_id=family.result_contract_id,
                    validate=lambda result: validate_provider_result_data(
                        result,
                        provider_label=family.provider_label,
                    ),
                ),
                recovery=RecoveryTraits(
                    retryable=True,
                    default_timeout_seconds=600,
                    default_retry_attempts=2,
                ),
                output_kind="generic_json",
                catalog_metadata=metadata,
            )
        )
    return capabilities

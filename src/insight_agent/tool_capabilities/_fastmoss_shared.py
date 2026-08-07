from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ._provider_shared import (
    ProviderAdapter,
    ProviderCapabilityFamily,
    ProviderNormalizer,
    build_provider_capabilities,
    build_provider_catalog,
    load_provider_specs,
    validate_provider_result_data,
)
from .registry import ToolCapability

FASTMOSS_AGENT_TOOL_PREFIX = "mcp__fastmoss__"
FastMossNormalizer = ProviderNormalizer
FastMossAdapter = ProviderAdapter

_FASTMOSS_FAMILY = ProviderCapabilityFamily(
    agent_tool_prefix=FASTMOSS_AGENT_TOOL_PREFIX,
    provider_label="FastMoss",
    source="fastmoss_mcp",
    auth_env_names=(
        "FASTMOSS_MCP_API_KEY",
        "FASTMOSS_MCP_KEY",
        "FASTMOSS_API_KEY",
    ),
    result_contract_id="fastmoss_result.v1",
    default_summary="FastMoss MCP returned structured evidence.",
    catalog_metadata={"checkpoint_reuse": True},
)


def load_fastmoss_specs(
    spec_path: Path,
    expected_names: Sequence[str],
    *,
    family_label: str,
) -> tuple[dict[str, Any], ...]:
    return load_provider_specs(
        spec_path,
        expected_names,
        provider_label=_FASTMOSS_FAMILY.provider_label,
        family_label=family_label,
    )


def build_fastmoss_catalog(
    spec_path: Path,
    expected_names: Sequence[str],
    *,
    family_label: str,
) -> dict[str, dict[str, Any]]:
    return build_provider_catalog(
        spec_path,
        expected_names,
        family=_FASTMOSS_FAMILY,
        family_label=family_label,
    )


def validate_fastmoss_result_data(result: Mapping[str, Any]) -> None:
    validate_provider_result_data(
        result,
        provider_label=_FASTMOSS_FAMILY.provider_label,
    )


def build_fastmoss_capabilities(
    catalog: Mapping[str, dict[str, Any]],
    *,
    normalize_input: FastMossNormalizer,
    adapter: FastMossAdapter,
) -> list[ToolCapability]:
    return build_provider_capabilities(
        catalog,
        family=_FASTMOSS_FAMILY,
        normalize_input=normalize_input,
        adapter=adapter,
    )

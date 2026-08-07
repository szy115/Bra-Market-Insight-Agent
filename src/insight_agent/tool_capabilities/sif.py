from __future__ import annotations

from typing import Any

from ..sif_manifest import SIF_MCP_TOOL_NAMES, SIF_SPEC_PATH
from ._provider_shared import (
    ProviderAdapter,
    ProviderCapabilityFamily,
    ProviderNormalizer,
    build_provider_capabilities,
    build_provider_catalog,
)
from .registry import ToolCapability

SIF_AGENT_TOOL_PREFIX = "sif_"
SIF_CAPABILITY_IDS = frozenset(
    f"{SIF_AGENT_TOOL_PREFIX}{name}" for name in SIF_MCP_TOOL_NAMES
)

_SIF_FAMILY = ProviderCapabilityFamily(
    agent_tool_prefix=SIF_AGENT_TOOL_PREFIX,
    provider_label="Sif",
    source="sif_mcp",
    auth_env_names=("SIF_MCP_TOKEN", "SIF_API_KEY", "SIF_TOKEN"),
    result_contract_id="sif_result.v1",
    default_summary="Sif MCP returned structured evidence.",
)


def sif_capability_catalog() -> dict[str, dict[str, Any]]:
    return build_provider_catalog(
        SIF_SPEC_PATH,
        SIF_MCP_TOOL_NAMES,
        family=_SIF_FAMILY,
        family_label="keyword/sales",
    )


def build_sif_capabilities(
    *,
    normalize_input: ProviderNormalizer,
    adapter: ProviderAdapter,
) -> list[ToolCapability]:
    return build_provider_capabilities(
        sif_capability_catalog(),
        family=_SIF_FAMILY,
        normalize_input=normalize_input,
        adapter=adapter,
    )

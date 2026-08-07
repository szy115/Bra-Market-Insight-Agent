from __future__ import annotations

from typing import Any

from ..sellersprite_manifest import (
    SELLERSPRITE_MARKET_ABA_DISTRIBUTION_BATCH,
    SELLERSPRITE_MARKET_ABA_DISTRIBUTION_MCP_TOOL_NAMES,
    sellersprite_specs_for_batch,
)
from ._provider_shared import (
    ProviderAdapter,
    ProviderNormalizer,
    build_provider_capabilities,
    build_provider_catalog_from_specs,
)
from ._sellersprite_shared import (
    SELLERSPRITE_AGENT_TOOL_PREFIX,
    SELLERSPRITE_CAPABILITY_FAMILY,
)
from .registry import ToolCapability

SELLERSPRITE_MARKET_ABA_DISTRIBUTION_CAPABILITY_IDS = frozenset(
    f"{SELLERSPRITE_AGENT_TOOL_PREFIX}{name}"
    for name in SELLERSPRITE_MARKET_ABA_DISTRIBUTION_MCP_TOOL_NAMES
)


def sellersprite_market_aba_distribution_catalog() -> dict[str, dict[str, Any]]:
    specs = sellersprite_specs_for_batch(SELLERSPRITE_MARKET_ABA_DISTRIBUTION_BATCH)
    return build_provider_catalog_from_specs(
        specs,
        SELLERSPRITE_MARKET_ABA_DISTRIBUTION_MCP_TOOL_NAMES,
        family=SELLERSPRITE_CAPABILITY_FAMILY,
        family_label="market/ABA/distribution/trademark",
    )


def build_sellersprite_market_aba_distribution_capabilities(
    *,
    normalize_input: ProviderNormalizer,
    adapter: ProviderAdapter,
) -> list[ToolCapability]:
    return build_provider_capabilities(
        sellersprite_market_aba_distribution_catalog(),
        family=SELLERSPRITE_CAPABILITY_FAMILY,
        normalize_input=normalize_input,
        adapter=adapter,
    )

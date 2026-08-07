from __future__ import annotations

from typing import Any

from ..sellersprite_manifest import (
    SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_BATCH,
    SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_MCP_TOOL_NAMES,
    sellersprite_specs_for_batch,
)
from ._provider_shared import (
    ProviderAdapter,
    ProviderCapabilityFamily,
    ProviderNormalizer,
    build_provider_capabilities,
    build_provider_catalog_from_specs,
)
from .registry import ToolCapability

SELLERSPRITE_AGENT_TOOL_PREFIX = "sellersprite_"
SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_CAPABILITY_IDS = frozenset(
    f"{SELLERSPRITE_AGENT_TOOL_PREFIX}{name}"
    for name in SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_MCP_TOOL_NAMES
)

_SELLERSPRITE_FAMILY = ProviderCapabilityFamily(
    agent_tool_prefix=SELLERSPRITE_AGENT_TOOL_PREFIX,
    provider_label="SellerSprite",
    source="sellersprite_mcp",
    auth_env_names=(
        "SELLERSPRITE_MCP_SECRET_KEY",
        "SELLERSPRITE_SECRET_KEY",
        "SELLERSPRITE_API_KEY",
    ),
    result_contract_id="sellersprite_result.v1",
    default_summary="SellerSprite MCP returned structured evidence.",
)


def sellersprite_product_keyword_traffic_catalog() -> dict[str, dict[str, Any]]:
    specs = sellersprite_specs_for_batch(SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_BATCH)
    return build_provider_catalog_from_specs(
        specs,
        SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_MCP_TOOL_NAMES,
        family=_SELLERSPRITE_FAMILY,
        family_label="product/keyword/traffic",
    )


def build_sellersprite_product_keyword_traffic_capabilities(
    *,
    normalize_input: ProviderNormalizer,
    adapter: ProviderAdapter,
) -> list[ToolCapability]:
    return build_provider_capabilities(
        sellersprite_product_keyword_traffic_catalog(),
        family=_SELLERSPRITE_FAMILY,
        normalize_input=normalize_input,
        adapter=adapter,
    )

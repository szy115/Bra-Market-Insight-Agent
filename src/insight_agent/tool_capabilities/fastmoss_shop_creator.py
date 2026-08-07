from __future__ import annotations

from pathlib import Path
from typing import Any

from ._fastmoss_shared import (
    FASTMOSS_AGENT_TOOL_PREFIX,
    FastMossAdapter,
    FastMossNormalizer,
    build_fastmoss_capabilities,
    build_fastmoss_catalog,
)
from .registry import ToolCapability

FASTMOSS_SHOP_CREATOR_SPEC_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "fastmoss_shop_creator_tools.json"
)
FASTMOSS_SHOP_CREATOR_MCP_TOOL_NAMES = (
    "shop_search",
    "shop_rank_top_selling",
    "shop_base_info",
    "shop_product_analysis",
    "shop_sale_analysis",
    "shop_creator_analysis",
    "shop_data_trends",
    "creator_rank_top_ecommerce",
    "creator_profile_overview",
    "creator_fans_distribution",
)
FASTMOSS_SHOP_CREATOR_CAPABILITY_IDS = frozenset(
    f"{FASTMOSS_AGENT_TOOL_PREFIX}{name}"
    for name in FASTMOSS_SHOP_CREATOR_MCP_TOOL_NAMES
)


def fastmoss_shop_creator_catalog() -> dict[str, dict[str, Any]]:
    return build_fastmoss_catalog(
        FASTMOSS_SHOP_CREATOR_SPEC_PATH,
        FASTMOSS_SHOP_CREATOR_MCP_TOOL_NAMES,
        family_label="shop/creator",
    )


def build_fastmoss_shop_creator_capabilities(
    *,
    normalize_input: FastMossNormalizer,
    adapter: FastMossAdapter,
) -> list[ToolCapability]:
    return build_fastmoss_capabilities(
        fastmoss_shop_creator_catalog(),
        normalize_input=normalize_input,
        adapter=adapter,
    )

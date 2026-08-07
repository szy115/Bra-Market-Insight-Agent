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

FASTMOSS_MARKET_PRODUCT_SPEC_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "fastmoss_market_product_tools.json"
)
FASTMOSS_MARKET_PRODUCT_MCP_TOOL_NAMES = (
    "search_category_by_words",
    "market_category_ranking",
    "market_category_analysis",
    "market_category_author_sales_matrix",
    "product_search",
    "product_rank_top_selling",
    "product_rank_new_listed",
    "product_overview",
    "product_sales_trend",
    "product_creator_analysis",
    "product_video_list",
    "product_detail_info",
    "product_sku",
    "product_investment",
    "product_review_list",
    "video_script_info",
    "fastmoss_detail_url_examples",
    "search_fastmoss_documents",
)
FASTMOSS_MARKET_PRODUCT_CAPABILITY_IDS = frozenset(
    f"{FASTMOSS_AGENT_TOOL_PREFIX}{name}"
    for name in FASTMOSS_MARKET_PRODUCT_MCP_TOOL_NAMES
)


def fastmoss_market_product_catalog() -> dict[str, dict[str, Any]]:
    return build_fastmoss_catalog(
        FASTMOSS_MARKET_PRODUCT_SPEC_PATH,
        FASTMOSS_MARKET_PRODUCT_MCP_TOOL_NAMES,
        family_label="market/product",
    )


def build_fastmoss_market_product_capabilities(
    *,
    normalize_input: FastMossNormalizer,
    adapter: FastMossAdapter,
) -> list[ToolCapability]:
    return build_fastmoss_capabilities(
        fastmoss_market_product_catalog(),
        normalize_input=normalize_input,
        adapter=adapter,
    )

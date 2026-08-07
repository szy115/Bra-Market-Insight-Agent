from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SELLERSPRITE_SPEC_PATH = Path(__file__).resolve().parent / "data" / "sellersprite_tools.json"
SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_BATCH = "product_keyword_traffic"
SELLERSPRITE_MARKET_ABA_DISTRIBUTION_BATCH = "market_aba_distribution_trademark"
SELLERSPRITE_MIGRATION_BATCHES = frozenset(
    {
        SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_BATCH,
        SELLERSPRITE_MARKET_ABA_DISTRIBUTION_BATCH,
    }
)


def load_sellersprite_manifest() -> tuple[dict[str, Any], ...]:
    payload = json.loads(SELLERSPRITE_SPEC_PATH.read_text(encoding="utf-8"))
    specs = tuple(dict(item) for item in payload if isinstance(item, dict))
    names = tuple(str(item.get("name") or "").strip() for item in specs)
    batches = tuple(str(item.get("migration_batch") or "").strip() for item in specs)
    if not specs or any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("SellerSprite capability manifest must contain unique named tools")
    if any(batch not in SELLERSPRITE_MIGRATION_BATCHES for batch in batches):
        raise ValueError("SellerSprite capability manifest contains an invalid migration batch")
    return specs


def sellersprite_specs_for_batch(batch: str) -> tuple[dict[str, Any], ...]:
    if batch not in SELLERSPRITE_MIGRATION_BATCHES:
        raise ValueError(f"Unknown SellerSprite migration batch: {batch}")
    return tuple(
        item
        for item in load_sellersprite_manifest()
        if str(item.get("migration_batch") or "") == batch
    )


SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_MCP_TOOL_NAMES = tuple(
    str(item["name"])
    for item in sellersprite_specs_for_batch(SELLERSPRITE_PRODUCT_KEYWORD_TRAFFIC_BATCH)
)

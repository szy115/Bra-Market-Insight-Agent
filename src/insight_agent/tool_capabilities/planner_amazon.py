from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ._planner_shared import (
    BoundedInt,
    ResolveParams,
    input_schema,
    planner_capability,
    require_list,
    require_mapping_or_none,
)
from .registry import ToolCapability

AMAZON_SHELF_INPUT_SCHEMA = input_schema(
    {
        "category": {"type": "string"},
        "limit": {"type": "integer", "minimum": 5, "maximum": 80},
        "amazonKeywordLimit": {"type": "integer", "minimum": 1, "maximum": 12},
        "bypassCache": {"type": "boolean"},
    }
)


def normalize_amazon_shelf_input(
    category: str,
    payload: dict[str, Any],
    canonical: Mapping[str, Any],
    bounded_int: BoundedInt,
) -> dict[str, Any]:
    return {
        "category": str(canonical.get("category") or category),
        "limit": bounded_int(canonical.get("listing_sample_size"), 30, 5, 80),
        "amazonKeywordLimit": bounded_int(
            canonical.get("amazon_keyword_limit") or payload.get("amazonKeywordLimit"),
            6,
            1,
            12,
        ),
        "useLlm": False,
        "bypassCache": bool(canonical.get("bypass_cache") or payload.get("bypassCache")),
    }


def shape_amazon_shelf_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": result.get("metrics"),
        "price_bands": result.get("price_bands"),
        "brands": result.get("brands", [])[:10],
        "queries": result.get("queries", [])[:8],
        "products": [
            {
                "asin": product.get("asin"),
                "title": product.get("title"),
                "brand": product.get("brand"),
                "url": product.get("product_url"),
                "image_url": product.get("image_url"),
                "price": product.get("price_text"),
                "rating": product.get("rating_value"),
                "reviews": product.get("review_count"),
                "review_sample_count": len(product.get("review_samples") or []),
                "review_samples": product.get("review_samples")
                if isinstance(product.get("review_samples"), list)
                else [],
                "badges": product.get("badges", [])[:4],
            }
            for product in result.get("products", [])
        ],
    }


def summarize_amazon_shelf_result(result: dict[str, Any]) -> str:
    metrics = result.get("metrics") or {}
    return (
        f"{metrics.get('products', 0)} Amazon products, "
        f"{metrics.get('total_review_count', 0)} review/rating signals."
    )


def validate_amazon_shelf_result(result: Mapping[str, Any]) -> None:
    require_mapping_or_none(result, "metrics")
    require_list(result, "brands")
    require_list(result, "queries")
    require_list(result, "products")


def build_amazon_shelf_capability(
    *,
    resolve_params: ResolveParams,
    bounded_int: BoundedInt,
    adapter: Callable[[dict[str, Any]], dict[str, Any]],
) -> ToolCapability:
    return planner_capability(
        capability_id="amazon_shelf",
        label="Amazon shelf",
        description=(
            "Collect Amazon search/product/review evidence for price, rating, review volume, "
            "claims, and brands."
        ),
        schema=AMAZON_SHELF_INPUT_SCHEMA,
        normalize_input=lambda category, payload: normalize_amazon_shelf_input(
            category, payload, resolve_params(payload), bounded_int
        ),
        adapter=lambda invocation: adapter(invocation.tool_input),
        shape_result=shape_amazon_shelf_result,
        summarize=summarize_amazon_shelf_result,
        validate_result=validate_amazon_shelf_result,
    )

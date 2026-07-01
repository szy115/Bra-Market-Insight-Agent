from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from .agent_reach import (
    coerce_items,
    first_value,
    numeric_or_none,
    parse_structured_output,
    resolve_command,
    run_command,
)


@dataclass(frozen=True)
class AmazonConfig:
    enabled: bool = True
    timeout_seconds: int = 90
    product_limit: int = 20
    keyword_limit: int = 8
    detail_limit: int = 5
    discussion_limit: int = 5
    reviews_per_product: int = 5


@dataclass
class AmazonResult:
    products: list[dict[str, Any]]
    warnings: list[str]
    source_mode: str = "amazon_opencli"
    queries: list[str] = field(default_factory=list)
    per_query_counts: dict[str, int] = field(default_factory=dict)


def int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def amazon_config_from_env() -> AmazonConfig:
    return AmazonConfig(
        enabled=os.getenv("AMAZON_OPENCLI_ENABLED", "1").strip().lower() not in {"0", "false", "no"},
        timeout_seconds=int_env("AMAZON_OPENCLI_TIMEOUT", 90, 10, 600),
        product_limit=int_env("AMAZON_PRODUCT_LIMIT", 20, 1, 100),
        keyword_limit=int_env("AMAZON_KEYWORD_LIMIT", 8, 1, 20),
        detail_limit=int_env("AMAZON_DETAIL_LIMIT", 5, 0, 100),
        discussion_limit=int_env("AMAZON_DISCUSSION_LIMIT", 5, 0, 100),
        reviews_per_product=int_env("AMAZON_REVIEWS_PER_PRODUCT", 5, 0, 100),
    )


def amazon_opencli_health() -> dict[str, Any]:
    opencli = resolve_command("opencli")
    return {
        "opencli_installed": bool(opencli),
        "opencli_path": opencli or "",
        "ready": bool(opencli),
        "recommended_backend": "opencli" if opencli else "",
    }


def fetch_amazon_opencli(
    query: str,
    limit: int | None = None,
    keyword_limit: int | None = None,
    bypass_cache: bool = False,
) -> AmazonResult:
    config = amazon_config_from_env()
    if not config.enabled:
        return AmazonResult([], ["Amazon OpenCLI provider is disabled."])
    if not resolve_command("opencli"):
        return AmazonResult([], ["OpenCLI is not installed; Amazon collection is unavailable."])

    requested_limit = max(1, min(int(limit or config.product_limit), 100))
    query_limit = max(1, min(int(keyword_limit or config.keyword_limit), 20))
    queries = build_amazon_queries(query, query_limit)
    warnings: list[str] = []
    per_query_counts: dict[str, int] = {}
    products_by_key: dict[str, dict[str, Any]] = {}

    for search_query in queries:
        search_result = search_amazon_products(search_query, requested_limit, config.timeout_seconds)
        warnings.extend([f"{search_query}: {warning}" for warning in search_result.warnings])
        products = search_result.products[:requested_limit]
        per_query_counts[search_query] = len(products)
        for product in products:
            key = amazon_product_key(product)
            if not key:
                continue
            product = add_matched_query(product, search_query)
            if key in products_by_key:
                products_by_key[key] = merge_product(products_by_key[key], product)
            else:
                products_by_key[key] = product

    products = list(products_by_key.values())

    if bypass_cache:
        warnings.append("Bypassed local cache for Amazon collection.")
    if len(queries) > 1:
        warnings.append(f"Searched {len(queries)} Amazon keyword variants to expand shelf coverage.")

    detail_limit = max(0, min(config.detail_limit, len(products)))
    for index, product in enumerate(products[:detail_limit]):
        asin = str(product.get("asin") or "")
        if not asin:
            continue
        detail = read_amazon_product(asin, config.timeout_seconds)
        warnings.extend(detail.warnings)
        if detail.products:
            products[index] = merge_product(product, detail.products[0])

    discussion_limit = max(0, min(config.discussion_limit, len(products)))
    for index, product in enumerate(products[:discussion_limit]):
        asin = str(product.get("asin") or "")
        if not asin:
            continue
        discussion = read_amazon_discussion(asin, config.reviews_per_product, config.timeout_seconds)
        warnings.extend(discussion.warnings)
        if discussion.products:
            products[index] = merge_product(products[index], discussion.products[0])

    return AmazonResult(products, warnings, queries=queries, per_query_counts=per_query_counts)


def build_amazon_queries(category: str, keyword_limit: int | None = None) -> list[str]:
    cleaned = re.sub(r"\s+", " ", category).strip()
    if not cleaned:
        return []
    limit = max(1, min(int(keyword_limit or 8), 20))
    lower = cleaned.lower()
    is_minimizer = any(term in lower for term in ("minimizer", "minimize", "minimise")) or any(
        term in cleaned for term in ("显小", "大胸", "大杯", "丰满")
    )
    is_large_bust = any(
        term in lower
        for term in ("large bust", "large breast", "big bust", "big breast", "full bust", "plus size")
    ) or any(term in cleaned for term in ("大胸", "大杯", "大码"))

    candidates = [cleaned]
    if is_minimizer:
        candidates.extend(
            [
                "minimizer bra",
                "minimizer bras for women",
                "minimizer bras for large breasts",
                "full coverage minimizer bra",
                "plus size minimizer bra",
                "wireless minimizer bra",
                "underwire minimizer bra",
                "smoothing minimizer bra",
                "minimizer bra for button down shirts",
                "unlined minimizer bra",
                "seamless minimizer bra",
                "minimizer sports bra",
            ]
        )
    else:
        base = re.sub(r"\bbras?\b", "", lower, flags=re.IGNORECASE).strip() or cleaned
        candidates.extend(
            [
                f"{base} bra",
                f"{base} bras for women",
                f"{base} full coverage bra",
                f"{base} wireless bra",
                f"{base} underwire bra",
            ]
        )
        if is_large_bust:
            candidates.extend(
                [
                    f"{base} bras for large bust",
                    f"{base} plus size bra",
                    f"{base} high support bra",
                    f"{base} full bust bra",
                ]
            )
        else:
            candidates.extend(
                [
                    f"{base} comfortable bra",
                    f"{base} supportive bra",
                    f"{base} seamless bra",
                ]
            )

    return unique_terms(candidates)[:limit]


def unique_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", str(value)).strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        results.append(cleaned)
    return results


def amazon_product_key(product: dict[str, Any]) -> str:
    asin = str(product.get("asin") or "").strip().upper()
    if asin:
        return f"asin:{asin}"
    url = str(product.get("product_url") or product.get("url") or "").strip().lower()
    match = re.search(r"/(?:dp|gp/product)/([a-z0-9]{10})", url, flags=re.IGNORECASE)
    if match:
        return f"asin:{match.group(1).upper()}"
    return f"url:{url.split('?', 1)[0].rstrip('/')}" if url else ""


def add_matched_query(product: dict[str, Any], query: str) -> dict[str, Any]:
    updated = dict(product)
    matched = updated.get("matched_queries")
    if not isinstance(matched, list):
        matched = []
    if query not in matched:
        matched.append(query)
    updated["matched_queries"] = matched
    return updated


def search_amazon_products(query: str, limit: int, timeout_seconds: int) -> AmazonResult:
    args = ["opencli", "amazon", "search", query, "--limit", str(limit), "-f", "json"]
    code, stdout, stderr = run_command(args, timeout_seconds)
    if code != 0 or not stdout.strip():
        args = ["opencli", "amazon", "search", query, "--limit", str(limit), "-f", "yaml"]
        code, stdout, stderr = run_command(args, timeout_seconds)
    if code != 0:
        return AmazonResult([], [f"OpenCLI Amazon search failed: {stderr.strip() or stdout.strip()}"])
    products = [normalize_amazon_product(item) for item in coerce_items(parse_structured_output(stdout))]
    return AmazonResult([product for product in products if product.get("asin") or product.get("product_url")], [])


def read_amazon_product(asin_or_url: str, timeout_seconds: int) -> AmazonResult:
    for args in (
        ["opencli", "amazon", "product", asin_or_url, "-f", "json"],
        ["opencli", "amazon", "product", asin_or_url, "-f", "yaml"],
    ):
        code, stdout, stderr = run_command(args, timeout_seconds)
        if code == 0 and stdout.strip():
            products = [normalize_amazon_product(item) for item in coerce_items(parse_structured_output(stdout))]
            return AmazonResult(products[:1], [])
    return AmazonResult([], [f"OpenCLI Amazon product read failed for {asin_or_url}: {stderr.strip() or stdout.strip()}"])


def read_amazon_discussion(asin_or_url: str, limit: int, timeout_seconds: int) -> AmazonResult:
    for args in (
        ["opencli", "amazon", "discussion", asin_or_url, "--limit", str(limit), "-f", "json"],
        ["opencli", "amazon", "discussion", asin_or_url, "--limit", str(limit), "-f", "yaml"],
    ):
        code, stdout, stderr = run_command(args, timeout_seconds)
        if code == 0 and stdout.strip():
            products = [normalize_amazon_discussion(item) for item in coerce_items(parse_structured_output(stdout))]
            return AmazonResult(products[:1], [])
    return AmazonResult([], [f"OpenCLI Amazon discussion read failed for {asin_or_url}: {stderr.strip() or stdout.strip()}"])


def normalize_amazon_product(item: dict[str, Any]) -> dict[str, Any]:
    asin = str(first_value(item, ("asin", "ASIN"), ""))
    url = str(first_value(item, ("product_url", "url", "link"), ""))
    if not url and asin:
        url = f"https://www.amazon.com/dp/{asin}"
    bullet_points = first_value(item, ("bullet_points", "bullets", "features"), [])
    if isinstance(bullet_points, str):
        bullet_points = [bullet_points] if bullet_points.strip() else []
    if not isinstance(bullet_points, list):
        bullet_points = []
    return {
        "rank": numeric_or_none(first_value(item, ("rank", "position"), None)),
        "asin": asin,
        "title": str(first_value(item, ("title", "name"), "")),
        "brand": clean_brand(str(first_value(item, ("brand", "brand_text"), ""))),
        "product_url": url,
        "image_url": str(first_value(item, ("image_url", "image", "thumbnail"), "")),
        "price_text": str(first_value(item, ("price_text", "price"), "")),
        "price_value": numeric_or_none(first_value(item, ("price_value",), None)),
        "currency": str(first_value(item, ("currency",), "USD") or "USD"),
        "rating_text": str(first_value(item, ("rating_text",), "")),
        "rating_value": numeric_or_none(first_value(item, ("rating_value", "rating"), None)),
        "review_count_text": str(first_value(item, ("review_count_text",), "")),
        "review_count": numeric_or_none(first_value(item, ("review_count", "total_review_count"), None)),
        "badges": first_value(item, ("badges",), []) if isinstance(item.get("badges"), list) else [],
        "is_sponsored": bool(item.get("is_sponsored", False)),
        "breadcrumbs": item.get("breadcrumbs") if isinstance(item.get("breadcrumbs"), list) else [],
        "bullet_points": [str(point).strip() for point in bullet_points if str(point).strip()],
        "availability": str(first_value(item, ("availability", "availability_text"), "")),
        "seller": str(first_value(item, ("seller", "seller_name"), "")),
        "review_samples": normalize_review_samples(first_value(item, ("review_samples", "reviews"), [])),
        "source_url": str(first_value(item, ("source_url",), "")),
        "fetched_at": str(first_value(item, ("fetched_at",), "")),
    }


def normalize_amazon_discussion(item: dict[str, Any]) -> dict[str, Any]:
    base = normalize_amazon_product(item)
    base["average_rating_value"] = numeric_or_none(first_value(item, ("average_rating_value",), None))
    base["total_review_count"] = numeric_or_none(first_value(item, ("total_review_count",), None))
    base["discussion_url"] = str(first_value(item, ("discussion_url",), ""))
    base["review_samples"] = normalize_review_samples(first_value(item, ("review_samples", "reviews"), []))
    if not base["review_count"] and base["total_review_count"]:
        base["review_count"] = base["total_review_count"]
    if not base["rating_value"] and base["average_rating_value"]:
        base["rating_value"] = base["average_rating_value"]
    return base


def normalize_review_samples(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    reviews: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        body = str(first_value(item, ("body", "text", "content"), "")).strip()
        title = str(first_value(item, ("title", "review_title"), "")).strip()
        if not body and not title:
            continue
        review_id = str(first_value(item, ("review_id", "id", "external_id"), "")).strip()
        review_url = str(first_value(item, ("review_url", "url", "link", "permalink"), "")).strip()
        reviews.append(
            {
                "id": review_id,
                "title": title,
                "body": body,
                "url": review_url,
                "rating_value": numeric_or_none(first_value(item, ("rating_value", "rating"), None)),
                "rating_text": str(first_value(item, ("rating_text",), "")),
                "author": str(first_value(item, ("author", "user"), "")),
                "date_text": str(first_value(item, ("date_text", "date"), "")),
                "verified_purchase": bool(item.get("verified_purchase", False)),
            }
        )
    return reviews


def merge_product(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if key == "matched_queries":
            merged_queries = merged.get(key) if isinstance(merged.get(key), list) else []
            extra_queries = value if isinstance(value, list) else []
            merged[key] = unique_terms([*merged_queries, *extra_queries])
            continue
        if key == "review_samples":
            if value:
                merged[key] = value
            continue
        if key == "bullet_points":
            if value:
                merged[key] = value
            continue
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def clean_brand(value: str) -> str:
    value = value.strip()
    if value.lower().startswith("visit the ") and value.lower().endswith(" store"):
        value = value[10:-6]
    return value.strip()

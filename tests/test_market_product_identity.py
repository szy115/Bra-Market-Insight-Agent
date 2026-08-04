from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image

from insight_agent.agent_runtime import LangGraphAgentRuntime
from insight_agent.market_product_identity import (
    _image_dhash,
    _ImageBudget,
    find_product_identity_enrichment_candidates,
    normalized_image_identity,
    product_family_report_rows,
    resolve_market_product_identity,
)
from insight_agent.server import build_market_report_data


def _tool(
    name: str,
    rows: list[dict[str, Any]],
    *,
    month: str = "202606",
    marketplace: str = "US",
) -> dict[str, Any]:
    return {
        "name": name,
        "status": "ok",
        "input": {"request": {"marketplace": marketplace, "month": month}},
        "data": {"data": rows},
    }


def _row(asin: str, **values: Any) -> dict[str, Any]:
    return {
        "asin": asin,
        "brand": "Acme",
        "title": "Acme Everyday Full Coverage Support Bra",
        **values,
    }


def _resolve(*tools: dict[str, Any], image_download_budget: int = 0) -> dict[str, Any]:
    return resolve_market_product_identity(
        list(tools),
        marketplace="US",
        category="minimizer bra",
        image_download_budget=image_download_budget,
    )


def test_same_asin_across_three_pools_preserves_sources_evidence_and_observations() -> None:
    tools = [
        _tool(
            "sellersprite_market_product_concentration",
            [_row("B000000001", totalUnits=100, price="29.99", ranking=1)],
        ),
        _tool(
            "sellersprite_product_research",
            [_row("B000000001", totalUnits=100, price="29.99")],
        ),
        _tool(
            "sellersprite_competitor_lookup",
            [_row("B000000001", totalUnits=100, price="29.99")],
        ),
    ]

    result = _resolve(*tools)
    family = result["families"][0]
    report_row = product_family_report_rows(result)[0]

    assert result["schema_version"] == "market_product_identity.v1"
    assert result["audit"]["raw_row_count"] == 3
    assert result["audit"]["unique_asin_count"] == 1
    assert result["audit"]["family_count"] == 1
    assert family["source_tools"] == [
        "sellersprite_market_product_concentration",
        "sellersprite_product_research",
        "sellersprite_competitor_lookup",
    ]
    assert family["evidence_ids"] == ["E01", "E02", "E03"]
    assert len(family["observations"]) == 3
    assert report_row["totalUnits"] == 100
    assert report_row["observations"] == family["observations"]


def test_explicit_parent_and_variation_list_merge_at_full_confidence() -> None:
    parent_result = _resolve(
        _tool(
            "sellersprite_market_product_concentration",
            [
                _row("B000000001", parentAsin="B000PARENT"),
                _row("B000000002", parentAsin="B000PARENT"),
            ],
        )
    )
    variation_result = _resolve(
        _tool(
            "sellersprite_product_research",
            [
                _row("B000000003", variationList=[{"asin": "B000000004"}]),
                _row("B000000004"),
            ],
        )
    )

    assert parent_result["audit"]["family_count"] == 1
    assert parent_result["families"][0]["confidence"] == 1.0
    assert parent_result["families"][0]["match_rules"] == ["shared_parent_asin"]
    assert variation_result["audit"]["family_count"] == 1
    assert variation_result["families"][0]["confidence"] == 1.0
    assert variation_result["families"][0]["match_rules"] == ["explicit_variation"]


def test_asin_detail_relationship_is_added_to_family_evidence() -> None:
    result = _resolve(
        _tool(
            "sellersprite_product_research",
            [_row("B000000001"), _row("B000000002")],
        ),
        {
            "name": "sellersprite_asin_detail",
            "status": "ok",
            "input": {"request": {"asin": "B000000001"}},
            "data": {
                "data": {
                    "parent": "B000PARENT",
                    "variationList": [{"asin": "B000000002"}],
                }
            },
        },
    )

    assert result["audit"]["family_count"] == 1
    assert result["families"][0]["confidence"] == 1.0
    assert result["families"][0]["match_rules"] == ["explicit_variation"]
    assert result["families"][0]["evidence_ids"] == ["E01", "E02"]


def test_brand_model_and_explicit_pack_merge() -> None:
    result = _resolve(
        _tool(
            "sellersprite_product_research",
            [
                _row(
                    "B000000001",
                    title="Acme Smooth T-Shirt Bra",
                    modelNumber="ACM-100",
                    packCount=2,
                ),
                _row(
                    "B000000002",
                    title="Acme Daily Support Brassiere",
                    modelNumber="ACM-100",
                    packCount=2,
                ),
            ],
        )
    )

    assert result["audit"]["family_count"] == 1
    assert result["audit"]["rule_counts"] == {"brand_model_pack": 1}
    assert result["families"][0]["confidence"] == 0.95


def test_brand_normalized_main_image_and_similar_title_merge() -> None:
    result = _resolve(
        _tool(
            "sellersprite_product_research",
            [
                _row(
                    "B000000001",
                    title="Acme Everyday Full Coverage Support Bra Black",
                    imageUrl="https://m.media-amazon.com/images/I/71ABC._AC_SL1500_.jpg",
                ),
                _row(
                    "B000000002",
                    title="Acme Everyday Full Coverage Support Bra Beige",
                    imageUrl="https://images-na.ssl-images-amazon.com/images/I/71ABC.jpg",
                ),
            ],
        )
    )

    assert normalized_image_identity(
        "https://m.media-amazon.com/images/I/71ABC._AC_SL1500_.jpg"
    ) == "71abc.jpg"
    assert result["audit"]["family_count"] == 1
    assert result["audit"]["rule_counts"] == {"brand_image_title": 1}
    assert result["families"][0]["confidence"] == 0.92


def test_brand_title_same_price_and_sales_merge_only_on_same_scope() -> None:
    result = _resolve(
        _tool(
            "sellersprite_product_research",
            [_row("B000000001", title="Acme Everyday Support Bra Black", price="29.99", totalUnits=321)],
        ),
        _tool(
            "sellersprite_competitor_lookup",
            [_row("B000000002", title="Acme Everyday Support Bra Beige", price="29.99", totalUnits=321)],
        ),
    )

    assert result["audit"]["family_count"] == 1
    assert result["audit"]["rule_counts"] == {"brand_title_price_sales": 1}
    assert result["families"][0]["confidence"] == 0.75


@pytest.mark.parametrize(
    ("right_month", "right_values"),
    [
        ("202605", {"price": "29.99", "totalUnits": 321}),
        ("202606", {"price": "29.99", "monthlySales": 321}),
        ("202606", {"totalUnits": 321}),
        ("202606", {"price": "29.99"}),
        ("202606", {"price": "29.99", "totalUnits": 321, "currency": "CAD"}),
    ],
)
def test_price_sales_rule_requires_same_month_metric_currency_and_complete_values(
    right_month: str,
    right_values: dict[str, Any],
) -> None:
    result = _resolve(
        _tool(
            "sellersprite_product_research",
            [_row("B000000001", title="Acme Everyday Support Bra Black", price="29.99", totalUnits=321)],
        ),
        _tool(
            "sellersprite_competitor_lookup",
            [_row("B000000002", title="Acme Everyday Support Bra Beige", **right_values)],
            month=right_month,
        ),
    )

    assert result["audit"]["family_count"] == 2
    assert "brand_title_price_sales" not in result["audit"]["rule_counts"]


def test_title_similarity_below_threshold_does_not_merge() -> None:
    result = _resolve(
        _tool(
            "sellersprite_product_research",
            [
                _row("B000000001", title="Acme Strapless Plunge Bra", price="29.99", totalUnits=321),
                _row("B000000002", title="Acme Longline Sports Compression Top", price="29.99", totalUnits=321),
            ],
        )
    )

    assert result["audit"]["family_count"] == 2
    assert not result["audit"]["rule_counts"]


@pytest.mark.parametrize(
    "left_values,right_values,expected_field",
    [
        (
            {"modelNumber": "ACM-100", "packCount": 2},
            {"modelNumber": "ACM-200", "packCount": 2},
            "model_number",
        ),
        ({"packCount": 2}, {"packCount": 3}, "pack_count"),
        (
            {
                "title": (
                    "Acme Everyday Full Coverage Underwire Support Comfort Seamless Adjustable "
                    "Back Smoothing Daily Lightweight Soft Bra"
                )
            },
            {
                "title": (
                    "Acme Everyday Full Coverage Wireless Support Comfort Seamless Adjustable "
                    "Back Smoothing Daily Lightweight Soft Bra"
                )
            },
            "core_attribute:wire",
        ),
    ],
)
def test_hard_conflicts_block_heuristic_merges(
    left_values: dict[str, Any],
    right_values: dict[str, Any],
    expected_field: str,
) -> None:
    shared_image = "https://m.media-amazon.com/images/I/71SAME.jpg"
    base = {
        "title": "Acme Everyday Full Coverage Support Comfort Bra",
        "imageUrl": shared_image,
        "price": "29.99",
        "totalUnits": 100,
    }
    result = _resolve(
        _tool(
            "sellersprite_product_research",
            [
                _row("B000000001", **{**base, **left_values}),
                _row("B000000002", **{**base, **right_values}),
            ],
        )
    )

    assert result["audit"]["family_count"] == 2
    assert any(
        expected_field in conflict["fields"]
        for edge in result["audit"]["conflicts"]
        for conflict in edge.get("conflicts") or []
    )


def test_explicit_parent_still_merges_and_records_conflicts() -> None:
    result = _resolve(
        _tool(
            "sellersprite_product_research",
            [
                _row("B000000001", parentAsin="B000PARENT", modelNumber="ACM-100", packCount=1),
                _row("B000000002", parentAsin="B000PARENT", modelNumber="ACM-200", packCount=2),
            ],
        )
    )

    assert result["audit"]["family_count"] == 1
    assert result["families"][0]["field_conflicts"]
    assert set(result["families"][0]["field_conflicts"][0]["fields"]) >= {
        "model_number",
        "pack_count",
    }


def test_transitive_merge_does_not_bypass_cluster_hard_conflict() -> None:
    result = _resolve(
        _tool(
            "sellersprite_product_research",
            [
                _row(
                    "B000000001",
                    modelNumber="ACM-100",
                    imageUrl="https://m.media-amazon.com/images/I/71SAME.jpg",
                ),
                _row(
                    "B000000002",
                    imageUrl="https://m.media-amazon.com/images/I/71SAME.jpg",
                ),
                _row(
                    "B000000003",
                    modelNumber="ACM-300",
                    imageUrl="https://m.media-amazon.com/images/I/71SAME.jpg",
                ),
            ],
        )
    )

    assert result["audit"]["family_count"] == 2
    assert result["asin_to_family"]["B000000001"] == result["asin_to_family"]["B000000002"]
    assert result["asin_to_family"]["B000000003"] != result["asin_to_family"]["B000000001"]
    assert result["audit"]["conflicts"]


class _ImageResponse:
    def __init__(self, content: bytes, url: str) -> None:
        self.content = content
        self.url = url
        self.headers = {"Content-Length": str(len(content))}

    def __enter__(self) -> _ImageResponse:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, limit: int) -> bytes:
        return self.content[:limit]


def _png_bytes() -> bytes:
    image = Image.new("L", (16, 16))
    for x in range(16):
        for y in range(16):
            image.putpixel((x, y), (x * 13 + y * 7) % 256)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_dhash_download_cache_failure_and_budget_audit(monkeypatch, tmp_path) -> None:
    import insight_agent.market_product_identity as identity_module

    content = _png_bytes()
    calls: list[str] = []

    def fake_open_image(request):
        calls.append(request.full_url)
        return _ImageResponse(content, request.full_url)

    monkeypatch.setattr(identity_module, "IMAGE_FINGERPRINT_CACHE", tmp_path)
    monkeypatch.setattr(identity_module, "_open_amazon_image", fake_open_image)
    url = "https://m.media-amazon.com/images/I/cache-test.png"

    first_budget = _ImageBudget(limit=20)
    first_hash = _image_dhash(url, first_budget)
    cached_budget = _ImageBudget(limit=20)
    cached_hash = _image_dhash(url, cached_budget)
    invalid_budget = _ImageBudget(limit=20)
    assert _image_dhash("https://example.com/not-amazon.png", invalid_budget) is None

    capped_budget = _ImageBudget(limit=20)
    for index in range(21):
        _image_dhash(f"https://m.media-amazon.com/images/I/budget-{index}.png", capped_budget)

    assert first_hash and first_hash == cached_hash
    assert first_budget.downloads == 1
    assert cached_budget.cache_hits == 1
    assert cached_budget.downloads == 0
    assert invalid_budget.failures == 1
    assert capped_budget.downloads == 20
    assert capped_budget.budget_exhausted is True
    assert len(calls) == 21


def test_dhash_distance_match_merges_images_with_different_asset_urls(monkeypatch, tmp_path) -> None:
    import insight_agent.market_product_identity as identity_module

    content = _png_bytes()
    monkeypatch.setattr(identity_module, "IMAGE_FINGERPRINT_CACHE", tmp_path)
    monkeypatch.setattr(
        identity_module,
        "_open_amazon_image",
        lambda request: _ImageResponse(content, request.full_url),
    )
    result = _resolve(
        _tool(
            "sellersprite_product_research",
            [
                _row("B000000001", imageUrl="https://m.media-amazon.com/images/I/asset-a.png"),
                _row("B000000002", imageUrl="https://m.media-amazon.com/images/I/asset-b.png"),
            ],
        ),
        image_download_budget=20,
    )

    assert result["audit"]["family_count"] == 1
    assert result["audit"]["rule_counts"] == {"brand_image_title": 1}
    assert result["audit"]["image_downloads"] == 2


def test_image_budget_exhaustion_keeps_candidate_unresolved() -> None:
    result = _resolve(
        _tool(
            "sellersprite_product_research",
            [
                _row("B000000001", imageUrl="https://m.media-amazon.com/images/I/asset-a.png"),
                _row("B000000002", imageUrl="https://m.media-amazon.com/images/I/asset-b.png"),
            ],
        ),
        image_download_budget=0,
    )

    assert result["audit"]["family_count"] == 2
    assert result["audit"]["image_budget_exhausted"] is True
    assert result["unresolved"][0]["reason"] == "image_budget_exhausted"


def test_asin_detail_enrichment_candidates_and_runtime_budget_are_deduplicated() -> None:
    suspicious = [
        _row(f"B{i:09d}", title="Acme Everyday Full Coverage Support Bra")
        for i in range(1, 13)
    ]
    distinct = _row("B999999999", title="Acme Heavy Duty Travel Backpack")
    existing_asin = suspicious[0]["asin"]
    state: dict[str, Any] = {
        "selected_skill_id": "weekly_market_insight",
        "skill_params": {"marketplace": "US"},
        "payload": {"marketplace": "US"},
        "tools": [
            _tool("sellersprite_product_research", [*suspicious, distinct]),
            {
                "name": "sellersprite_asin_detail",
                "status": "error",
                "input": {"request": {"asin": existing_asin}},
                "data": {},
            },
        ],
    }
    candidates = find_product_identity_enrichment_candidates(state["tools"], marketplace="US")
    runtime = object.__new__(LangGraphAgentRuntime)
    calls: list[str] = []
    runtime._run_data_tool = lambda _state, _name, args: calls.append(args["asin"])  # type: ignore[method-assign]

    runtime._enrich_weekly_market_product_identity(state)  # type: ignore[arg-type]
    runtime._enrich_weekly_market_product_identity(state)  # type: ignore[arg-type]

    assert len(candidates) == 12
    assert distinct["asin"] not in {item["asin"] for item in candidates}
    assert existing_asin not in calls
    assert len(calls) == 10
    assert len(set(calls)) == 10
    assert len(state["product_identity_detail_lookup_asins"]) == 10


def test_detail_lookup_budget_exhaustion_is_audited_as_unresolved() -> None:
    result = resolve_market_product_identity(
        [
            _tool(
                "sellersprite_product_research",
                [
                    _row("B000000001", title="Acme Everyday Support Bra Black"),
                    _row("B000000002", title="Acme Everyday Support Bra Beige"),
                ],
            )
        ],
        marketplace="US",
        detail_lookup_asins=[f"B{i:09d}" for i in range(1, 11)],
    )

    assert result["audit"]["detail_lookup_count"] == 10
    assert result["audit"]["detail_lookup_budget_exhausted"] is True
    assert result["unresolved"][0]["reason"] == "detail_lookup_budget_exhausted"


def test_report_uses_one_identity_for_m09_m17_and_bra_attributes_without_summing() -> None:
    report = build_market_report_data(
        {
            "brand": "Hsia",
            "marketplace": "US",
            "category": "minimizer bra",
            "timeRange": "90d",
            "toolResults": [
                _tool(
                    "sellersprite_market_product_concentration",
                    [
                        _row(
                            "B000000001",
                            title="Acme Full Coverage Underwire Bra 2 Pack",
                            modelNumber="ACM-100",
                            packCount=2,
                            totalUnits=100,
                            price="29.99",
                            ranking=1,
                        ),
                        _row(
                            "B000000002",
                            title="Acme Full Coverage Underwire Bra 2 Pack Black",
                            modelNumber="ACM-100",
                            packCount=2,
                            totalUnits=60,
                            price="29.99",
                            ranking=2,
                        ),
                    ],
                ),
                _tool(
                    "sellersprite_product_research",
                    [
                        _row(
                            "B000000002",
                            title="Acme Full Coverage Underwire Bra 2 Pack",
                            modelNumber="ACM-100",
                            packCount=2,
                            totalUnits=100,
                            price="29.99",
                        )
                    ],
                ),
                _tool(
                    "sellersprite_competitor_lookup",
                    [
                        _row(
                            "B000000003",
                            title="Acme Strapless Plunge Bra",
                            modelNumber="ACM-300",
                            packCount=1,
                            totalUnits=40,
                            price="24.99",
                        )
                    ],
                ),
            ],
        }
    )

    shared_family_id = report["top_products"][0]["family_id"]
    universe_family = next(
        row for row in report["product_universe"] if "B000000001" in row["member_asins"]
    )
    m17 = next(
        item
        for item in report["non_chart_presentations"]
        if item["dimension_id"] == "M17"
    )
    m17_sources = {
        row["source"]: row["sample_count"] for row in m17["content"]["sources"]
    }

    assert report["deduplication"] | {
        "applied": True,
        "status": "partial",
        "scope": "product_identity_only",
    } == report["deduplication"]
    assert report["product_identity"]["audit"]["unique_asin_count"] == 3
    assert report["product_identity"]["audit"]["family_count"] == 2
    assert len(report["top_products"]) == 1
    assert len(report["product_universe"]) == 2
    assert universe_family["family_id"] == shared_family_id
    assert report["top_products"][0]["totalUnits"] == 100
    assert len(report["top_products"][0]["observations"]) == 3
    assert len({row["asin"] for row in report["top_products"]}) == len(report["top_products"])
    assert report["bra_attribute_distribution"]["sample_scope"] == "unified_product_identity_family"
    assert report["bra_attribute_distribution"]["product_family_count"] == 2
    assert shared_family_id in report["bra_attribute_distribution"]["family_ids"]
    assert m17_sources == {
        "sellersprite_competitor_lookup": 1,
        "sellersprite_market_product_concentration": 1,
        "sellersprite_product_research": 1,
    }
    assert m17["content"]["cross_source_check_applicable"] is True
    assert m17["content"]["cross_source_overlap_count"] == 1
    assert m17["content"]["representativeness_claim_allowed"] is False


def test_identity_failure_keeps_raw_product_rows_and_forbids_unique_claim() -> None:
    report = build_market_report_data(
        {
            "brand": "Hsia",
            "marketplace": "US",
            "category": "yoga pants",
            "toolResults": [
                _tool(
                    "sellersprite_product_research",
                    [{"asin": "invalid", "brand": "Acme", "title": "Acme Yoga Pants"}],
                )
            ],
        }
    )

    assert report["product_identity"]["status"] == "not_applied"
    assert report["deduplication"]["applied"] is False
    assert report["deduplication"]["status"] == "deferred"
    assert report["product_universe"]
    assert any("不得声明唯一商品数" in gap for gap in report["data_gaps"])

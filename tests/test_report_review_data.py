from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import insight_agent.server as server
from insight_agent.server import build_review_report_data

STALE_SENTINEL = "STALE_SENTINEL"
LONG_FACT = "long-factual-title-" + ("商品事实保持原样-" * 300)


def _report_data_fixture() -> dict:
    head_product = {
        f"fact_field_{index:02d}": f"fact-{index}"
        for index in range(1, 30)
    }
    # Regression guard: the legacy generic compactor kept only the first 24
    # dictionary fields, so this fact was previously omitted from review.
    head_product["trend"] = {
        "complete_day_count": 28,
        "l7_units": 754,
        "p7_units": 137,
        "change_percent": 450.4,
        "daily": [
            {
                "date": f"2026-07-{index:02d}",
                "units": index * 3,
                "gmv": index * 99.5,
            }
            for index in range(1, 29)
        ],
    }
    head_product["product_id"] = "head-product-1"

    candidate_products = [
        {
            "product_id": f"product-{index:02d}",
            "units_sold": index * 10,
            "model": f"affiliate-model-{index:02d}",
            "image_url": f"https://images.example/product-{index:02d}.jpg",
            "product_title": LONG_FACT if index == 1 else f"Product {index:02d}",
        }
        for index in range(1, 21)
    ]
    return {
        "schema_version": "review-regression-fixture.v1",
        "candidate_products": candidate_products,
        "candidate_products_duplicate": deepcopy(candidate_products),
        "candidate_shops": [
            {
                "seller_id": f"shop-{index:02d}",
                "day28_gmv": index * 1000,
                "avatar": f"https://images.example/shop-{index:02d}.jpg",
            }
            for index in range(1, 51)
        ],
        "head_products": [head_product],
        "price_distribution": [
            {
                "price_band": f"${index * 10}-${(index + 1) * 10}",
                "gmv": index * 100,
                "product_count": index,
            }
            for index in range(1, 31)
        ],
        "metric_facts": [
            {
                "fact_id": f"MF{index:03d}",
                "concept": "units_sold",
                "value": index,
                "unit": "units",
                "period_key": "L7",
                "entity_id": f"product-{index:03d}",
                "source_path": f"candidate_products[{index - 1}].units_sold",
            }
            for index in range(1, 241)
        ],
        "summary": {
            "candidate_product_count": 20,
            "candidate_shop_count": 50,
        },
        "insight_narrative": {
            "headline": f"{STALE_SENTINEL}: stale generated headline",
            "sections": [{"text": f"{STALE_SENTINEL}: stale generated conclusion"}],
        },
        "analysis_sections": [
            {"title": f"{STALE_SENTINEL}: stale analysis", "body": "old prose"}
        ],
        "swot": {"strengths": [f"{STALE_SENTINEL}: stale generated prose"]},
        "decision_matrix": [
            {"decision": f"{STALE_SENTINEL}: stale generated decision"}
        ],
        "artifact": {"html": f"<html>{STALE_SENTINEL}: stale artifact</html>"},
    }


def test_build_review_report_data_does_not_truncate_fact_collections() -> None:
    source = _report_data_fixture()

    review_data, _manifest = build_review_report_data(source)

    assert [item["product_id"] for item in review_data["candidate_products"]] == [
        f"product-{index:02d}" for index in range(1, 21)
    ]
    assert [item["seller_id"] for item in review_data["candidate_shops"]] == [
        f"shop-{index:02d}" for index in range(1, 51)
    ]
    assert len(review_data["price_distribution"]) == 30
    assert review_data["price_distribution"][-1]["price_band"] == "$300-$310"
    assert len(review_data["metric_facts"]) == 240
    assert review_data["metric_facts"][-1]["fact_id"] == "MF240"


def test_build_review_report_data_preserves_facts_after_legacy_field_limit() -> None:
    source = _report_data_fixture()
    source_head_product = source["head_products"][0]
    assert list(source_head_product).index("trend") == 29

    review_data, _manifest = build_review_report_data(source)

    trend = review_data["head_products"][0]["trend"]
    assert trend["complete_day_count"] == 28
    assert trend["l7_units"] == 754
    assert trend["p7_units"] == 137
    assert trend["change_percent"] == 450.4
    assert len(trend["daily"]) == 28
    assert trend["daily"][-1] == {
        "date": "2026-07-28",
        "units": 84,
        "gmv": 2786.0,
    }


def test_build_review_report_data_removes_old_generated_prose() -> None:
    source = _report_data_fixture()

    review_data, manifest = build_review_report_data(source)

    removed_top_level_fields = {
        "insight_narrative",
        "analysis_sections",
        "swot",
        "decision_matrix",
        "artifact",
    }
    assert removed_top_level_fields.isdisjoint(review_data)
    removed_paths = {
        item["path"]
        for item in manifest["removed_paths"]
        if isinstance(item, dict) and "path" in item
    }
    assert removed_top_level_fields <= removed_paths


def test_build_review_report_data_manifest_proves_collection_counts_unchanged() -> None:
    source = _report_data_fixture()

    _review_data, manifest = build_review_report_data(source)

    assert manifest["facts_sampled"] is False
    assert manifest["strings_truncated"] is False
    expected_counts = {
        "candidate_products": 20,
        "candidate_shops": 50,
        "head_products": 1,
        "price_distribution": 30,
        "metric_facts": 240,
    }
    for path, expected_count in expected_counts.items():
        assert manifest["collection_counts"][path] == {
            "before": expected_count,
            "after": expected_count,
        }


def test_build_review_report_data_does_not_mutate_source() -> None:
    source = _report_data_fixture()
    original = deepcopy(source)

    build_review_report_data(source)

    assert source == original


def test_manifest_detects_unexpected_sampling_and_string_mutation(monkeypatch) -> None:
    source = _report_data_fixture()
    original_deduplicator = server._deduplicate_review_report_data

    def corrupt_wire_view(pruned_data):
        review_data, aliases = original_deduplicator(pruned_data)
        review_data["candidate_products"] = deepcopy(
            review_data["candidate_products"][:-1]
        )
        review_data["candidate_shops"][0]["seller_id"] = "truncated"
        return review_data, aliases

    monkeypatch.setattr(
        server,
        "_deduplicate_review_report_data",
        corrupt_wire_view,
    )

    _review_data, manifest = build_review_report_data(source)

    assert manifest["facts_sampled"] is True
    assert manifest["strings_truncated"] is True
    assert manifest["retained_subtrees_equal"] is False
    assert "candidate_products" in manifest["unexpected_collection_mutations"]
    assert (
        "candidate_shops[].seller_id"
        in manifest["unexpected_string_mutations"]
    )


def test_approval_layout_contract_keeps_structure_without_old_narrative_values() -> None:
    source = _report_data_fixture()
    source["chart_specs"] = [
        {
            "id": "demand_trend",
            "quality_status": "ready",
            "insight": STALE_SENTINEL,
            "data": [{"date": "2026-07-01", "value": 100}],
        }
    ]
    source["insight_narrative"] = {
        "chart_insights": [
            {
                "chart_id": "demand_trend",
                "section_id": STALE_SENTINEL,
                "section_title": STALE_SENTINEL,
                "conclusion": STALE_SENTINEL,
                "observation": STALE_SENTINEL,
                "interpretation": STALE_SENTINEL,
                "interpretation_type": STALE_SENTINEL,
                "business_implication": STALE_SENTINEL,
                "action": STALE_SENTINEL,
            }
        ]
    }

    request = server.report_approval_request_payload({}, source)

    assert STALE_SENTINEL not in json.dumps(request, ensure_ascii=False)
    assert "insight" not in request["report_data"]["chart_specs"][0]
    assert request["report_data"]["chart_specs"][0]["data"] == [
        {"date": "2026-07-01", "value": 100}
    ]
    assert request["chart_layout_contract"]["required_chart_bindings"] == [
        {
            "chart_ids": ["demand_trend"],
            "binding_role": "required_chart",
        }
    ]


def _complete_revision_html() -> str:
    paragraphs = "".join(
        f"<p>Verified report paragraph {index}: retained factual content for regression.</p>"
        for index in range(1, 15)
    )
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Reviewed report</title><style>"
        "body{font-family:Arial,sans-serif;margin:2rem;color:#222}"
        "main{max-width:960px;margin:auto}p{line-height:1.5}"
        "</style></head><body><main><h1>Reviewed report</h1>"
        f"{paragraphs}</main></body></html>"
    )


def test_all_approval_nodes_send_identical_complete_pruned_report_data(
    monkeypatch,
) -> None:
    source = _report_data_fixture()
    captured_messages: list[list[dict]] = []
    revised_html = _complete_revision_html()

    def fake_chat(messages, *args, **kwargs):
        del args, kwargs
        captured_messages.append(deepcopy(messages))
        system_content = str(messages[0].get("content") or "")
        if "HTML rendering agent revising" in system_content:
            content = revised_html
        elif "strategy red-team node" in system_content:
            content = json.dumps(
                {
                    "decision": "approve",
                    "summary": "red-team pass",
                    "reviewed_claim_count": 1,
                    "findings": [],
                }
            )
        else:
            content = json.dumps(
                {
                    "decision": "approve",
                    "summary": "factual pass",
                    "issues": [],
                }
            )
        return {
            "message": {"content": content},
            "provider": "test-provider",
            "model": "test-model",
            "usage": {},
        }

    monkeypatch.setattr(server, "call_openai_compatible_chat", fake_chat)
    payload = {
        "html": revised_html,
        "reportData": source,
        "skillMarkdown": "",
        "reviewRound": 1,
        "revisionRound": 1,
        "review": {
            "decision": "revise",
            "summary": "apply factual corrections",
            "issues": [],
        },
    }

    factual_result = server.review_html_report_node(payload)
    red_team_result = server.red_team_html_report_node(payload)
    revision_result = server.revise_html_report_node(payload)

    assert factual_result["approved"] is True
    assert red_team_result["approved"] is True
    assert revision_result["revision"]["status"] == "ok"
    assert revision_result["revision"]["applied"] is True
    assert len(captured_messages) == 3
    assert all(
        STALE_SENTINEL not in json.dumps(messages, ensure_ascii=False)
        for messages in captured_messages
    )

    requests = [
        json.loads(messages[-1]["content"])
        for messages in captured_messages
    ]
    report_views = [request["report_data"] for request in requests]
    manifests = [
        request["report_data_pruning_manifest"]
        for request in requests
    ]
    assert report_views[1:] == [report_views[0], report_views[0]]
    assert manifests[1:] == [manifests[0], manifests[0]]

    report_view = report_views[0]
    manifest = manifests[0]
    canonical_json = json.dumps(
        report_view,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    assert manifest["review_data_sha256"] == hashlib.sha256(
        canonical_json.encode("utf-8")
    ).hexdigest()
    assert manifest["facts_sampled"] is False
    assert manifest["strings_truncated"] is False

    assert report_view["candidate_products"] == source["candidate_products"]
    assert [
        product["product_id"] for product in report_view["candidate_products"]
    ] == [f"product-{index:02d}" for index in range(1, 21)]
    assert len(report_view["candidate_shops"]) == 50
    assert report_view["candidate_shops"] == source["candidate_shops"]
    assert (
        report_view["head_products"][0]["trend"]["daily"]
        == source["head_products"][0]["trend"]["daily"]
    )
    assert len(report_view["head_products"][0]["trend"]["daily"]) == 28
    assert report_view["metric_facts"] == source["metric_facts"]
    assert len(report_view["metric_facts"]) == 240
    assert report_view["candidate_products"][0]["product_title"] == LONG_FACT
    assert report_view["candidate_products"][0]["model"] == "affiliate-model-01"
    assert (
        report_view["candidate_products"][0]["image_url"]
        == "https://images.example/product-01.jpg"
    )

    duplicate_ref = report_view["candidate_products_duplicate"]
    assert duplicate_ref == {
        "$ref": "#/candidate_products",
        "$deduplicated": True,
        "logical_type": "list",
        "logical_item_count": 20,
    }
    alias = next(
        item
        for item in manifest["aliases"]
        if item["path"] == "candidate_products_duplicate"
    )
    assert alias["canonical_path"] == "candidate_products"
    assert alias["item_count"] == 20
    assert manifest["collection_counts"]["candidate_products_duplicate"] == {
        "before": 20,
        "after": 20,
    }

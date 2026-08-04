from insight_agent.market_data_dedup import (
    MarketDataDedupRequest,
    MarketDataDedupResult,
    run_market_data_dedup,
)


def test_default_market_data_dedup_is_an_audited_passthrough() -> None:
    records = [
        {"keyword": "minimizer bra", "searches": 100},
        {"keyword": "minimizer bra", "searches": 100},
    ]

    result = run_market_data_dedup(
        "keyword_trends",
        records,
        source_tools=("sellersprite_keyword_research",),
        context={"marketplace": "US"},
    )

    assert list(result.records) == records
    assert result.audit["status"] == "deferred"
    assert result.audit["strategy"] == "passthrough_v0"
    assert result.audit["applied"] is False
    assert result.audit["scope"] == "compiled_dataset_only"
    assert result.audit["upstream_normalization_audited"] is False
    assert result.audit["input_count"] == 2
    assert result.audit["output_count"] == 2
    assert result.audit["removed_count"] == 0
    assert result.audit["decisions"] == []


def test_market_data_dedup_accepts_a_future_injected_strategy() -> None:
    class FirstRecordOnly:
        def deduplicate(self, request: MarketDataDedupRequest) -> MarketDataDedupResult:
            return MarketDataDedupResult(
                records=request.records[:1],
                audit={"dataset": request.dataset, "applied": True, "strategy": "test_only"},
            )

    result = run_market_data_dedup(
        "products",
        [{"asin": "A"}, {"asin": "A"}],
        deduplicator=FirstRecordOnly(),
    )

    assert list(result.records) == [{"asin": "A"}]
    assert result.audit == {"dataset": "products", "applied": True, "strategy": "test_only"}

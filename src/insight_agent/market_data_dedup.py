from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class MarketDataDedupRequest:
    dataset: str
    records: tuple[dict[str, Any], ...]
    candidate_keys: tuple[str, ...] = ()
    source_tools: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketDataDedupResult:
    records: tuple[dict[str, Any], ...]
    audit: dict[str, Any]


class MarketDataDeduplicator(Protocol):
    def deduplicate(self, request: MarketDataDedupRequest) -> MarketDataDedupResult: ...


class PassthroughMarketDataDeduplicator:
    """Reserved implementation: preserve records until dataset-specific rules are approved."""

    def deduplicate(self, request: MarketDataDedupRequest) -> MarketDataDedupResult:
        records = tuple(dict(item) for item in request.records)
        return MarketDataDedupResult(
            records=records,
            audit={
                "schema_version": "market_data_dedup.v1",
                "dataset": request.dataset,
                "status": "deferred",
                "strategy": "passthrough_v0",
                "applied": False,
                "scope": "compiled_dataset_only",
                "upstream_normalization_audited": False,
                "input_count": len(request.records),
                "output_count": len(records),
                "removed_count": 0,
                "candidate_keys": list(request.candidate_keys),
                "source_tools": list(request.source_tools),
                "decisions": [],
            },
        )


DEFAULT_MARKET_DATA_DEDUPLICATOR: MarketDataDeduplicator = PassthroughMarketDataDeduplicator()


def run_market_data_dedup(
    dataset: str,
    records: list[dict[str, Any]],
    *,
    candidate_keys: tuple[str, ...] = (),
    source_tools: tuple[str, ...] = (),
    context: dict[str, Any] | None = None,
    deduplicator: MarketDataDeduplicator | None = None,
) -> MarketDataDedupResult:
    request = MarketDataDedupRequest(
        dataset=dataset,
        records=tuple(dict(item) for item in records if isinstance(item, dict)),
        candidate_keys=candidate_keys,
        source_tools=source_tools,
        context=dict(context or {}),
    )
    return (deduplicator or DEFAULT_MARKET_DATA_DEDUPLICATOR).deduplicate(request)

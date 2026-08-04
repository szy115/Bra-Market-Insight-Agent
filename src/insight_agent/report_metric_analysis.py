from __future__ import annotations

import copy
import math
import re
from collections import defaultdict
from typing import Any

METRIC_FACTS_SCHEMA_VERSION = "metric_facts.v1"
DERIVED_METRICS_SCHEMA_VERSION = "derived_metric_data.v1"
MAX_METRIC_FACTS = 240
MAX_METRIC_PROPOSALS = 24


def _snake_case(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


_FIELD_SPECS: dict[str, tuple[str, str]] = {
    "gmv": ("gmv", "USD"),
    "usd_gmv": ("gmv", "USD"),
    "period_gmv": ("gmv", "USD"),
    "day28_gmv": ("gmv", "USD"),
    "lifetime_gmv": ("gmv", "USD"),
    "first_3d_gmv": ("gmv", "USD"),
    "l7_gmv": ("gmv", "USD"),
    "p7_gmv": ("gmv", "USD"),
    "sales_amount": ("gmv", "USD"),
    "revenue": ("gmv", "USD"),
    "units_sold": ("units_sold", "count"),
    "period_units_sold": ("units_sold", "count"),
    "day28_units_sold": ("units_sold", "count"),
    "total_units_sold": ("units_sold", "count"),
    "first_3d_units_sold": ("units_sold", "count"),
    "l7_units_sold": ("units_sold", "count"),
    "p7_units_sold": ("units_sold", "count"),
    "sold_count": ("units_sold", "count"),
    "linked_video_count": ("video_count", "count"),
    "video_count": ("video_count", "count"),
    "videos": ("video_count", "count"),
    "linked_creator_count": ("creator_count", "count"),
    "creator_count": ("creator_count", "count"),
    "observed_creator_count": ("creator_count", "count"),
    "products_with_sales_count": ("products_with_sales_count", "count"),
    "active_product_count_total": ("active_product_count", "count"),
    "active_product_count": ("active_product_count", "count"),
    "observed_product_count": ("product_count", "count"),
    "product_count": ("product_count", "count"),
    "search_volume": ("demand", "count"),
    "purchase_volume": ("demand", "count"),
    "searches": ("demand", "count"),
    "demand": ("demand", "count"),
    "current_price": ("price", "USD"),
    "average_price": ("price", "USD"),
    "avg_price": ("price", "USD"),
    "sale_price": ("price", "USD"),
    "price": ("price", "USD"),
    "sales_share": ("share", "percent"),
    "gmv_share": ("share", "percent"),
    "gmv_share_percent": ("share", "percent"),
    "product_share": ("product_share", "percent"),
    "product_share_percent": ("product_share", "percent"),
    "click_share": ("share", "percent"),
    "click_share_percent": ("share", "percent"),
    "channel_share": ("share", "percent"),
    "market_share": ("share", "percent"),
    "market_share_percent": ("share", "percent"),
    "top3_click_share": ("share", "percent"),
    "ad_gmv_share_percent": ("share", "percent"),
    "affiliate_gmv_share_percent": ("share", "percent"),
    "video_gmv_share_percent": ("share", "percent"),
    "estimated_sales_share": ("share", "percent"),
}

_SKIP_BRANCHES = {
    "artifact",
    "chart_specs",
    "chart_manifest",
    "html",
    "html_analysis",
    "metric_facts",
    "metric_fact_summary",
    "derived_metrics",
    "metric_gaps",
    "metric_analysis",
    "report_quality",
    "tool_methodology",
}

_ENTITY_FIELDS: tuple[tuple[str, str], ...] = (
    ("product_id", "product"),
    ("asin", "product"),
    ("shop_id", "shop"),
    ("seller_id", "shop"),
    ("creator_id", "creator"),
    ("keyword", "keyword"),
    ("query", "keyword"),
    ("price_range", "price_band"),
    ("price_band", "price_band"),
    ("brand", "brand"),
)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        stripped = value.strip().replace(",", "").replace("$", "").replace("%", "")
        if not stripped:
            return None
        try:
            number = float(stripped)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _period_from_field(field: str, current: str) -> str:
    if field.startswith("l7_"):
        return "l7"
    if field.startswith("p7_"):
        return "p7"
    if field.startswith("day28_"):
        return "day28"
    if field.startswith("first_3d_"):
        return "first_3d"
    if field.startswith("lifetime_") or field.startswith("total_"):
        return "lifetime"
    if field.startswith("period_"):
        return "report_period"
    return current or "unspecified"


def _scope_key(context: dict[str, Any]) -> str:
    return "|".join(
        [
            str(context.get("marketplace") or ""),
            str(context.get("category") or ""),
            f"{context.get('entity_type') or 'market'}:{context.get('entity_id') or 'all'}",
        ]
    )


def _fact_semantics(
    field: str,
    path: tuple[str, ...],
) -> tuple[str, str] | None:
    spec = _FIELD_SPECS.get(field)
    if spec:
        return spec
    if field.endswith("_gmv_share_percent"):
        return ("share", "percent")
    if field.endswith("_share_percent"):
        if "product" in field:
            return ("product_share", "percent")
        return ("share", "percent")
    if field.endswith("_growth_rate") or field.endswith("_growth_percent"):
        joined = ".".join(path)
        if "price" in joined:
            return ("price_growth", "percent")
        if any(term in joined for term in ("search", "demand", "purchase")):
            return ("demand_growth", "percent")
        if any(term in joined for term in ("video", "creator", "content")):
            return ("content_growth", "percent")
        if any(term in joined for term in ("product", "supply")):
            return ("supply_growth", "percent")
        if any(term in joined for term in ("gmv", "sales", "revenue")):
            return ("gmv_growth", "percent")
    return None


def build_metric_facts(
    report_data: dict[str, Any],
    *,
    limit: int = MAX_METRIC_FACTS,
) -> list[dict[str, Any]]:
    """Extract a bounded, typed fact layer from versioned ReportData.

    Only fields with registered semantics are emitted. Unknown numeric leaves are
    intentionally ignored so a later LLM cannot assign them a convenient meaning.
    """

    facts: list[dict[str, Any]] = []
    root_context = {
        "marketplace": report_data.get("marketplace") or report_data.get("market"),
        "category": report_data.get("category"),
        "entity_type": "market",
        "entity_id": report_data.get("category_node_id") or report_data.get("category") or "all",
        "period_key": "report_period",
        "denominator_scope": "",
        "sample_complete": None,
        "evidence_ids": [],
    }

    def walk(value: Any, path: tuple[str, ...], context: dict[str, Any]) -> None:
        if len(facts) >= limit:
            return
        if isinstance(value, dict):
            next_context = dict(context)
            for field, entity_type in _ENTITY_FIELDS:
                raw = value.get(field)
                if raw not in (None, ""):
                    next_context["entity_type"] = entity_type
                    next_context["entity_id"] = str(raw)
                    break
            if value.get("marketplace") not in (None, ""):
                next_context["marketplace"] = value.get("marketplace")
            if value.get("category") not in (None, ""):
                next_context["category"] = value.get("category")
            for period_field in ("period_key", "period", "time_range", "date"):
                if value.get(period_field) not in (None, ""):
                    next_context["period_key"] = str(value.get(period_field))
                    break
            if value.get("denominator_scope") not in (None, ""):
                next_context["denominator_scope"] = str(value.get("denominator_scope"))
            for completeness_field in ("sample_complete", "is_complete", "full_sample"):
                if isinstance(value.get(completeness_field), bool):
                    next_context["sample_complete"] = value.get(completeness_field)
                    break
            evidence_ids = [
                *_string_list(next_context.get("evidence_ids")),
                *_string_list(value.get("evidence_id")),
                *_string_list(value.get("evidence_ids")),
                *_string_list(value.get("source_evidence_ids")),
            ]
            next_context["evidence_ids"] = list(dict.fromkeys(evidence_ids))[:12]
            for raw_key, child in value.items():
                key = _snake_case(str(raw_key))
                if key in _SKIP_BRANCHES:
                    continue
                child_path = (*path, key)
                number = _as_number(child)
                semantics = _fact_semantics(key, child_path)
                if number is not None and semantics is not None:
                    concept, unit = semantics
                    period_key = _period_from_field(
                        key, str(next_context.get("period_key") or "")
                    )
                    denominator_scope = str(next_context.get("denominator_scope") or "")
                    sample_complete = next_context.get("sample_complete")
                    if key.startswith("observed_"):
                        denominator_scope = denominator_scope or "observed_sample"
                        if sample_complete is None:
                            sample_complete = False
                    facts.append(
                        {
                            "fact_id": f"MF{len(facts) + 1:03d}",
                            "concept": concept,
                            "value": number,
                            "unit": unit,
                            "semantic_role": "observed_primary_metric",
                            "time_semantics": period_key,
                            "period_key": period_key,
                            "marketplace": next_context.get("marketplace"),
                            "category": next_context.get("category"),
                            "entity_type": next_context.get("entity_type") or "market",
                            "entity_id": next_context.get("entity_id") or "all",
                            "scope_key": _scope_key(next_context),
                            "observation_key": ".".join(path) or "report",
                            "source_field": key,
                            "source_path": ".".join(child_path),
                            "evidence_ids": next_context.get("evidence_ids") or [],
                            "denominator_scope": denominator_scope or "not_applicable",
                            "sample_complete": sample_complete,
                            "status": "observed",
                        }
                    )
                    if len(facts) >= limit:
                        return
                elif isinstance(child, dict | list):
                    walk(child, child_path, next_context)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                if len(facts) >= limit:
                    return
                walk(child, (*path, str(index)), context)

    walk(report_data, (), root_context)
    return facts


def attach_metric_facts(report_data: dict[str, Any]) -> dict[str, Any]:
    next_report_data = copy.deepcopy(report_data)
    facts = build_metric_facts(next_report_data)
    next_report_data["metric_facts_schema_version"] = METRIC_FACTS_SCHEMA_VERSION
    next_report_data["metric_facts"] = facts
    next_report_data["metric_fact_summary"] = {
        "fact_count": len(facts),
        "fact_limit": MAX_METRIC_FACTS,
        "truncated": len(facts) >= MAX_METRIC_FACTS,
        "concepts": sorted({str(fact.get("concept") or "") for fact in facts}),
        "contract": (
            "Only registered primary-metric semantics are exposed. Unknown numeric fields "
            "are excluded from secondary-metric selection."
        ),
    }
    return next_report_data


METRIC_CONTRACTS: dict[str, dict[str, Any]] = {
    "period_growth_rate": {
        "label": "周期增长率",
        "formula": "(current - previous) / abs(previous) × 100",
        "unit": "percent",
        "bindings": {
            "current": ["gmv", "units_sold", "demand", "video_count", "creator_count"],
            "previous": ["gmv", "units_sold", "demand", "video_count", "creator_count"],
        },
        "meaning": "同一对象、同一口径指标在相邻可比周期内的变化。",
    },
    "l7_p7_growth_rate": {
        "label": "近7日环比增长率",
        "formula": "(L7 - P7) / abs(P7) × 100",
        "unit": "percent",
        "bindings": {
            "current": ["gmv", "units_sold", "video_count", "creator_count"],
            "previous": ["gmv", "units_sold", "video_count", "creator_count"],
        },
        "meaning": "近7日相对前7日的同口径变化。",
    },
    "average_order_value": {
        "label": "平均成交单价",
        "formula": "GMV / units_sold",
        "unit": "USD/unit",
        "bindings": {"gmv": ["gmv"], "units": ["units_sold"]},
        "meaning": "每件成交商品对应的销售额，用于观察客单价结构。",
    },
    "gmv_per_video": {
        "label": "单视频产出",
        "formula": "GMV / linked_video_count",
        "unit": "USD/video",
        "bindings": {"gmv": ["gmv"], "videos": ["video_count"]},
        "meaning": "同一周期内每条关联视频对应的销售额。",
    },
    "gmv_per_creator": {
        "label": "单达人产出",
        "formula": "GMV / linked_creator_count",
        "unit": "USD/creator",
        "bindings": {"gmv": ["gmv"], "creators": ["creator_count"]},
        "meaning": "同一周期内每位关联达人对应的销售额。",
    },
    "product_activation_rate": {
        "label": "商品动销率",
        "formula": "products_with_sales / active_products × 100",
        "unit": "percent",
        "bindings": {
            "selling_products": ["products_with_sales_count"],
            "active_products": ["active_product_count"],
        },
        "meaning": "活跃商品中实际产生销售的比例。",
    },
    "demand_per_product": {
        "label": "单商品需求强度",
        "formula": "demand / product_count",
        "unit": "demand/product",
        "bindings": {"demand": ["demand"], "products": ["product_count"]},
        "meaning": "相同市场与周期内，每个供给商品对应的需求量。",
    },
    "price_band_productivity": {
        "label": "价格带产出指数",
        "formula": "GMV share / product share",
        "unit": "index",
        "bindings": {"gmv_share": ["share"], "product_share": ["product_share"]},
        "meaning": "某价格带销售份额相对商品供给份额的效率指数，1 为市场平均。",
    },
    "share_shift_pp": {
        "label": "份额变化",
        "formula": "current share - previous share",
        "unit": "percentage_point",
        "bindings": {"current": ["share"], "previous": ["share"]},
        "meaning": "同一对象的市场份额在两个可比周期间变化的百分点。",
    },
    "demand_supply_growth_gap": {
        "label": "需求—供给增速差",
        "formula": "demand_growth - supply_growth",
        "unit": "percentage_point",
        "bindings": {
            "demand_current": ["demand"],
            "demand_previous": ["demand"],
            "supply_current": ["product_count", "active_product_count"],
            "supply_previous": ["product_count", "active_product_count"],
        },
        "meaning": "需求增速相对供给增速的领先或落后程度。",
    },
    "content_lead_gap": {
        "label": "内容增速领先差",
        "formula": "content_growth - GMV_growth",
        "unit": "percentage_point",
        "bindings": {
            "content_current": ["video_count", "creator_count"],
            "content_previous": ["video_count", "creator_count"],
            "gmv_current": ["gmv"],
            "gmv_previous": ["gmv"],
        },
        "meaning": "内容供给增速相对销售增速的领先幅度，仅作为先行信号。",
    },
    "price_elasticity_proxy": {
        "label": "价格弹性代理值",
        "formula": "demand_growth% / price_growth%",
        "unit": "ratio",
        "bindings": {
            "demand_current": ["demand", "units_sold"],
            "demand_previous": ["demand", "units_sold"],
            "price_current": ["price"],
            "price_previous": ["price"],
        },
        "meaning": "价格变化与需求变化的观察性比率，不代表因果弹性。",
    },
    "cr3_concentration": {
        "label": "CR3 集中度",
        "formula": "top1_share + top2_share + top3_share",
        "unit": "percent",
        "bindings": {"share_fact_ids": ["share"]},
        "meaning": "完整市场分母下前三个不同实体的份额之和。",
    },
}


_DEFAULT_PROFILE = (
    "period_growth_rate",
    "l7_p7_growth_rate",
    "average_order_value",
)

SKILL_METRIC_PROFILES: dict[str, tuple[str, ...]] = {
    "weekly_market_insight": (
        "period_growth_rate",
        "demand_per_product",
        "price_band_productivity",
        "share_shift_pp",
        "demand_supply_growth_gap",
        "price_elasticity_proxy",
        "cr3_concentration",
    ),
    "tiktok_us_market_insight": (
        "period_growth_rate",
        "l7_p7_growth_rate",
        "average_order_value",
        "gmv_per_video",
        "gmv_per_creator",
        "product_activation_rate",
        "content_lead_gap",
        "share_shift_pp",
        "cr3_concentration",
    ),
    "tiktok_us_hot_product_insight": (
        "period_growth_rate",
        "l7_p7_growth_rate",
        "average_order_value",
        "gmv_per_video",
        "gmv_per_creator",
        "product_activation_rate",
        "content_lead_gap",
        "share_shift_pp",
        "cr3_concentration",
    ),
    "tiktok_us_lingerie_new_product_insight": (
        "l7_p7_growth_rate",
        "average_order_value",
        "gmv_per_video",
        "gmv_per_creator",
        "content_lead_gap",
        "price_elasticity_proxy",
    ),
    "tiktok_us_bra_competitor_shop_analysis": (
        "period_growth_rate",
        "l7_p7_growth_rate",
        "average_order_value",
        "gmv_per_video",
        "gmv_per_creator",
        "product_activation_rate",
        "content_lead_gap",
        "share_shift_pp",
        "cr3_concentration",
    ),
    "fashion_trend_report": ("period_growth_rate", "share_shift_pp"),
    "competitor_product_deep_dive": (
        "period_growth_rate",
        "average_order_value",
        "price_elasticity_proxy",
    ),
    "hot_product_pain_analysis": (
        "period_growth_rate",
        "average_order_value",
        "price_elasticity_proxy",
    ),
}


def available_metric_catalog_for_skill(skill_id: str) -> list[dict[str, Any]]:
    metric_ids = SKILL_METRIC_PROFILES.get(skill_id, _DEFAULT_PROFILE)
    return [
        {"metric_id": metric_id, **copy.deepcopy(METRIC_CONTRACTS[metric_id])}
        for metric_id in metric_ids
        if metric_id in METRIC_CONTRACTS
    ]


def _period_role(fact: dict[str, Any]) -> str:
    period = str(fact.get("period_key") or fact.get("time_semantics") or "").lower()
    field = str(fact.get("source_field") or "").lower()
    if period in {"l7", "current", "current_period", "report_period"} or field.startswith("l7_"):
        return "current"
    if period in {"p7", "previous", "previous_period", "prior_period"} or field.startswith("p7_"):
        return "previous"
    return ""


def default_metric_proposals(
    facts: list[dict[str, Any]],
    available_metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Select conservative calculable candidates when the planner LLM is unavailable."""

    allowed = {str(item.get("metric_id") or "") for item in available_metrics}
    by_observation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        if not isinstance(fact, dict) or not fact.get("fact_id"):
            continue
        by_observation[str(fact.get("observation_key") or "")].append(fact)
        by_scope[str(fact.get("scope_key") or "")].append(fact)

    proposals: list[dict[str, Any]] = []

    def add(metric_id: str, bindings: dict[str, Any], rationale: str) -> None:
        if metric_id in allowed and len(proposals) < MAX_METRIC_PROPOSALS:
            proposals.append(
                {"metric_id": metric_id, "bindings": bindings, "rationale": rationale}
            )

    for rows in by_observation.values():
        concepts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fact in rows:
            concepts[str(fact.get("concept") or "")].append(fact)

        def same_period(left: dict[str, Any], right: dict[str, Any]) -> bool:
            return str(left.get("period_key") or "") == str(right.get("period_key") or "")

        for gmv in concepts.get("gmv", []):
            for units in concepts.get("units_sold", []):
                if same_period(gmv, units):
                    add(
                        "average_order_value",
                        {"gmv": gmv["fact_id"], "units": units["fact_id"]},
                        "GMV 与销量来自同一对象和周期。",
                    )
                    break
            for videos in concepts.get("video_count", []):
                if same_period(gmv, videos):
                    add(
                        "gmv_per_video",
                        {"gmv": gmv["fact_id"], "videos": videos["fact_id"]},
                        "GMV 与视频数来自同一对象和周期。",
                    )
                    break
            for creators in concepts.get("creator_count", []):
                if same_period(gmv, creators):
                    add(
                        "gmv_per_creator",
                        {"gmv": gmv["fact_id"], "creators": creators["fact_id"]},
                        "GMV 与达人数量来自同一对象和周期。",
                    )
                    break
        for selling in concepts.get("products_with_sales_count", []):
            for active in concepts.get("active_product_count", []):
                if same_period(selling, active):
                    add(
                        "product_activation_rate",
                        {
                            "selling_products": selling["fact_id"],
                            "active_products": active["fact_id"],
                        },
                        "动销商品数与活跃商品数来自同一对象和周期。",
                    )
                    break
        for demand in concepts.get("demand", []):
            for products in concepts.get("product_count", []):
                if same_period(demand, products):
                    add(
                        "demand_per_product",
                        {"demand": demand["fact_id"], "products": products["fact_id"]},
                        "需求与商品数来自同一市场和周期。",
                    )
                    break
        for share in concepts.get("share", []):
            for product_share in concepts.get("product_share", []):
                if same_period(share, product_share):
                    add(
                        "price_band_productivity",
                        {
                            "gmv_share": share["fact_id"],
                            "product_share": product_share["fact_id"],
                        },
                        "销售份额与商品份额来自同一价格带和周期。",
                    )
                    break

    for rows in by_scope.values():
        by_concept: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fact in rows:
            by_concept[str(fact.get("concept") or "")].append(fact)
        for concept, concept_facts in by_concept.items():
            current = next(
                (fact for fact in concept_facts if _period_role(fact) == "current"), None
            )
            previous = next(
                (fact for fact in concept_facts if _period_role(fact) == "previous"), None
            )
            if current and previous:
                metric_id = (
                    "l7_p7_growth_rate"
                    if {
                        str(current.get("period_key") or "").lower(),
                        str(previous.get("period_key") or "").lower(),
                    }
                    == {"l7", "p7"}
                    else "period_growth_rate"
                )
                add(
                    metric_id,
                    {"current": current["fact_id"], "previous": previous["fact_id"]},
                    f"{concept} 具备相邻可比周期。",
                )
    return proposals[:MAX_METRIC_PROPOSALS]


class MetricValidationError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _normalize_share(fact: dict[str, Any]) -> float:
    value = float(fact["value"])
    unit = str(fact.get("unit") or "").lower()
    if unit in {"ratio", "fraction"}:
        value *= 100
    if value < 0 or value > 100:
        raise MetricValidationError(
            "invalid_share_range", f"{fact.get('fact_id')} 的份额不在 0–100% 范围内。"
        )
    return value


def _validate_same_scope(facts: list[dict[str, Any]]) -> None:
    scopes = {str(fact.get("scope_key") or "") for fact in facts}
    if len(scopes) > 1:
        raise MetricValidationError("scope_mismatch", "绑定事实不属于同一市场或实体范围。")


def _validate_same_observation(facts: list[dict[str, Any]]) -> None:
    observations = {str(fact.get("observation_key") or "") for fact in facts}
    if len(observations) > 1:
        raise MetricValidationError(
            "denominator_scope_mismatch", "分子和分母不是同一统计对象。"
        )


def _validate_same_period(facts: list[dict[str, Any]]) -> None:
    periods = {str(fact.get("period_key") or "") for fact in facts}
    if len(periods) > 1:
        raise MetricValidationError("period_mismatch", "分子和分母的统计周期不一致。")


def _validate_comparable_period_pair(current: dict[str, Any], previous: dict[str, Any]) -> None:
    _validate_same_scope([current, previous])
    current_role = _period_role(current)
    previous_role = _period_role(previous)
    if current_role != "current" or previous_role != "previous":
        raise MetricValidationError(
            "period_mismatch", "增长计算必须绑定当前周期与上一可比周期。"
        )
    if str(current.get("concept") or "") != str(previous.get("concept") or ""):
        raise MetricValidationError("metric_mismatch", "增长计算的前后指标口径不同。")
    period_pair = (
        str(current.get("period_key") or "").lower(),
        str(previous.get("period_key") or "").lower(),
    )
    if period_pair not in {
        ("l7", "p7"),
        ("current", "previous"),
        ("current_period", "previous_period"),
        ("report_period", "prior_period"),
    }:
        raise MetricValidationError(
            "period_mismatch",
            f"周期 {period_pair[0]} 与 {period_pair[1]} 未声明为等长可比周期。",
        )


def _growth(current: dict[str, Any], previous: dict[str, Any]) -> float:
    _validate_comparable_period_pair(current, previous)
    previous_value = float(previous["value"])
    if previous_value == 0:
        raise MetricValidationError("zero_denominator", "上一周期数值为 0，不能计算增长率。")
    return (float(current["value"]) - previous_value) / abs(previous_value) * 100


def _resolve_bindings(
    proposal: dict[str, Any],
    contract: dict[str, Any],
    fact_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    raw_bindings = proposal.get("bindings")
    if not isinstance(raw_bindings, dict):
        raise MetricValidationError("missing_binding", "缺少事实绑定。")
    resolved: dict[str, Any] = {}
    expected_bindings = contract.get("bindings") if isinstance(contract.get("bindings"), dict) else {}
    for binding_name, allowed_concepts in expected_bindings.items():
        raw_fact_ids = raw_bindings.get(binding_name)
        fact_ids = (
            [str(item) for item in raw_fact_ids]
            if isinstance(raw_fact_ids, list)
            else [str(raw_fact_ids)] if raw_fact_ids not in (None, "") else []
        )
        if not fact_ids:
            raise MetricValidationError(
                "missing_binding", f"缺少参数 {binding_name} 的事实绑定。"
            )
        facts: list[dict[str, Any]] = []
        for fact_id in fact_ids:
            fact = fact_index.get(fact_id)
            if not fact:
                raise MetricValidationError(
                    "unknown_fact", f"事实 {fact_id} 不在 Builder 的 metric_facts 中。"
                )
            if str(fact.get("concept") or "") not in set(allowed_concepts):
                raise MetricValidationError(
                    "metric_mismatch",
                    f"事实 {fact_id} 的语义不适用于参数 {binding_name}。",
                )
            facts.append(fact)
        resolved[binding_name] = facts if isinstance(raw_fact_ids, list) else facts[0]
    return resolved


def _round_metric(value: float) -> float:
    return round(value, 4 if abs(value) < 10 else 2)


def _calculate_one(
    metric_id: str,
    bindings: dict[str, Any],
) -> tuple[float, list[dict[str, Any]], list[str]]:
    limitations: list[str] = []
    if metric_id in {"period_growth_rate", "l7_p7_growth_rate"}:
        current, previous = bindings["current"], bindings["previous"]
        if metric_id == "l7_p7_growth_rate" and {
            str(current.get("period_key") or "").lower(),
            str(previous.get("period_key") or "").lower(),
        } != {"l7", "p7"}:
            raise MetricValidationError("period_mismatch", "该指标只允许 L7 对 P7。")
        return _growth(current, previous), [current, previous], limitations

    if metric_id in {
        "average_order_value",
        "gmv_per_video",
        "gmv_per_creator",
        "product_activation_rate",
        "demand_per_product",
        "price_band_productivity",
    }:
        binding_names = list(bindings)
        numerator, denominator = bindings[binding_names[0]], bindings[binding_names[1]]
        _validate_same_scope([numerator, denominator])
        _validate_same_observation([numerator, denominator])
        _validate_same_period([numerator, denominator])
        if denominator.get("sample_complete") is False:
            raise MetricValidationError(
                "incomplete_denominator", "分母来自明确标记为不完整的样本。"
            )
        denominator_value = float(denominator["value"])
        if denominator_value <= 0:
            raise MetricValidationError("zero_denominator", "分母必须大于 0。")
        if metric_id == "price_band_productivity":
            numerator_value = _normalize_share(numerator)
            denominator_value = _normalize_share(denominator)
            if denominator_value == 0:
                raise MetricValidationError("zero_denominator", "商品份额为 0。")
        else:
            numerator_value = float(numerator["value"])
        value = numerator_value / denominator_value
        if metric_id == "product_activation_rate":
            value *= 100
        return value, [numerator, denominator], limitations

    if metric_id == "share_shift_pp":
        current, previous = bindings["current"], bindings["previous"]
        _validate_comparable_period_pair(current, previous)
        return _normalize_share(current) - _normalize_share(previous), [current, previous], limitations

    if metric_id in {"demand_supply_growth_gap", "content_lead_gap"}:
        if metric_id == "demand_supply_growth_gap":
            first_current, first_previous = (
                bindings["demand_current"],
                bindings["demand_previous"],
            )
            second_current, second_previous = (
                bindings["supply_current"],
                bindings["supply_previous"],
            )
        else:
            first_current, first_previous = (
                bindings["content_current"],
                bindings["content_previous"],
            )
            second_current, second_previous = (
                bindings["gmv_current"],
                bindings["gmv_previous"],
            )
            limitations.append("内容增速是先行信号，不证明其导致 GMV 变化。")
        _validate_same_scope([first_current, first_previous, second_current, second_previous])
        value = _growth(first_current, first_previous) - _growth(
            second_current, second_previous
        )
        return (
            value,
            [first_current, first_previous, second_current, second_previous],
            limitations,
        )

    if metric_id == "price_elasticity_proxy":
        demand_current, demand_previous = (
            bindings["demand_current"],
            bindings["demand_previous"],
        )
        price_current, price_previous = (
            bindings["price_current"],
            bindings["price_previous"],
        )
        _validate_same_scope([demand_current, demand_previous, price_current, price_previous])
        demand_growth = _growth(demand_current, demand_previous)
        price_growth = _growth(price_current, price_previous)
        if abs(price_growth) < 2:
            raise MetricValidationError(
                "insufficient_price_change",
                "价格变化小于 2%，弹性代理值会被噪声放大，拒绝计算。",
            )
        limitations.append("这是观察性代理值，未控制促销、内容、季节等混杂因素。")
        return (
            demand_growth / price_growth,
            [demand_current, demand_previous, price_current, price_previous],
            limitations,
        )

    if metric_id == "cr3_concentration":
        shares = bindings["share_fact_ids"]
        if not isinstance(shares, list) or len(shares) != 3:
            raise MetricValidationError("incomplete_sample", "CR3 必须绑定恰好 3 个份额事实。")
        periods = {str(fact.get("period_key") or "") for fact in shares}
        marketplaces = {str(fact.get("marketplace") or "") for fact in shares}
        categories = {str(fact.get("category") or "") for fact in shares}
        entities = {
            (str(fact.get("entity_type") or ""), str(fact.get("entity_id") or ""))
            for fact in shares
        }
        if len(periods) != 1 or len(marketplaces) != 1 or len(categories) != 1:
            raise MetricValidationError(
                "period_or_scope_mismatch", "CR3 的三个实体必须来自同一市场和周期。"
            )
        if len(entities) != 3:
            raise MetricValidationError("duplicate_entity", "CR3 必须是三个不同实体。")
        if any(
            str(fact.get("denominator_scope") or "") != "full_market"
            or fact.get("sample_complete") is not True
            for fact in shares
        ):
            raise MetricValidationError(
                "incomplete_denominator",
                "CR3 只允许使用完整市场分母，不能对 TopN/观察样本再做集中度。",
            )
        return sum(_normalize_share(fact) for fact in shares), shares, limitations

    raise MetricValidationError("unsupported_metric", f"未实现指标 {metric_id}。")


def calculate_metric_analysis(
    report_data: dict[str, Any],
    proposals: list[dict[str, Any]],
    *,
    skill_id: str,
    planner: dict[str, Any] | None = None,
) -> dict[str, Any]:
    facts = (
        report_data.get("metric_facts")
        if isinstance(report_data.get("metric_facts"), list)
        else []
    )
    facts = [fact for fact in facts if isinstance(fact, dict) and fact.get("fact_id")]
    fact_index = {str(fact["fact_id"]): fact for fact in facts}
    available_metrics = available_metric_catalog_for_skill(skill_id)
    allowed_ids = {str(item.get("metric_id") or "") for item in available_metrics}
    derived_metrics: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, proposal in enumerate(proposals[:MAX_METRIC_PROPOSALS], start=1):
        if not isinstance(proposal, dict):
            rejected.append(
                {
                    "proposal_index": index,
                    "status": "not_calculable",
                    "reason_code": "invalid_proposal",
                    "reason": "提案不是对象。",
                }
            )
            continue
        metric_id = str(proposal.get("metric_id") or "")
        if metric_id not in allowed_ids:
            rejected.append(
                {
                    "proposal_index": index,
                    "metric_id": metric_id,
                    "status": "not_calculable",
                    "reason_code": "metric_not_available_for_skill",
                    "reason": "当前 Skill 未开放该固定指标。",
                }
            )
            continue
        contract = METRIC_CONTRACTS[metric_id]
        try:
            bindings = _resolve_bindings(proposal, contract, fact_index)
            value, used_facts, limitations = _calculate_one(metric_id, bindings)
            binding_signature = "|".join(
                sorted(
                    str(fact.get("fact_id") or "")
                    for fact in used_facts
                    if isinstance(fact, dict)
                )
            )
            dedup_key = f"{metric_id}:{binding_signature}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            evidence_ids = list(
                dict.fromkeys(
                    evidence_id
                    for fact in used_facts
                    for evidence_id in _string_list(fact.get("evidence_ids"))
                )
            )[:16]
            anchor = used_facts[0]
            derived_metrics.append(
                {
                    "metric_id": metric_id,
                    "label": contract["label"],
                    "value": _round_metric(value),
                    "unit": contract["unit"],
                    "formula": contract["formula"],
                    "formula_version": "v1",
                    "bindings": {
                        name: (
                            [str(fact.get("fact_id")) for fact in bound]
                            if isinstance(bound, list)
                            else str(bound.get("fact_id"))
                        )
                        for name, bound in bindings.items()
                    },
                    "scope": {
                        "marketplace": anchor.get("marketplace"),
                        "category": anchor.get("category"),
                        "entity_type": anchor.get("entity_type"),
                        "entity_id": anchor.get("entity_id"),
                        "period_key": anchor.get("period_key"),
                    },
                    "evidence_ids": evidence_ids,
                    "meaning": contract["meaning"],
                    "interpretation_hint": str(proposal.get("rationale") or ""),
                    "limitations": limitations,
                    "status": "calculated",
                }
            )
        except MetricValidationError as exc:
            rejected.append(
                {
                    "proposal_index": index,
                    "metric_id": metric_id,
                    "bindings": proposal.get("bindings") or {},
                    "status": "not_calculable",
                    "reason_code": exc.reason_code,
                    "reason": str(exc),
                }
            )
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            rejected.append(
                {
                    "proposal_index": index,
                    "metric_id": metric_id,
                    "bindings": proposal.get("bindings") or {},
                    "status": "not_calculable",
                    "reason_code": "invalid_numeric_input",
                    "reason": str(exc),
                }
            )

    metric_gaps = [
        {
            "metric_id": item.get("metric_id"),
            "reason_code": item.get("reason_code"),
            "message": item.get("reason"),
        }
        for item in rejected
    ][:24]
    return {
        "schema_version": DERIVED_METRICS_SCHEMA_VERSION,
        "source_report_data_version": report_data.get("schema_version"),
        "metric_facts_schema_version": report_data.get("metric_facts_schema_version"),
        "skill_id": skill_id,
        "available_metrics": available_metrics,
        "proposed_metrics": proposals[:MAX_METRIC_PROPOSALS],
        "derived_metrics": derived_metrics,
        "rejected_metric_proposals": rejected,
        "metric_gaps": metric_gaps,
        "calculation_audit": {
            "calculator": "deterministic_metric_contracts",
            "calculator_version": "v1",
            "llm_can_calculate_values": False,
            "registered_metric_count": len(METRIC_CONTRACTS),
            "available_metric_count": len(available_metrics),
            "fact_count": len(facts),
            "proposed_metric_count": min(len(proposals), MAX_METRIC_PROPOSALS),
            "calculated_metric_count": len(derived_metrics),
            "rejected_metric_count": len(rejected),
            "planner": planner or {},
        },
    }

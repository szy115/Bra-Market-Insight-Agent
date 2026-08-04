from __future__ import annotations

import re
from collections import Counter
from typing import Any

BRA_ATTRIBUTE_AXES: tuple[dict[str, Any], ...] = (
    {
        "id": "wire_structure",
        "label": "钢圈结构",
        "values": (
            ("underwire", "有钢圈", (r"\bunderwire\b", r"\bwired\b")),
            (
                "wirefree",
                "无钢圈",
                (r"\bwire[- ]?free\b", r"\bwireless\b", r"\bno wire\b", r"\bnon[- ]?wired\b"),
            ),
        ),
    },
    {
        "id": "strap_presence",
        "label": "肩带形态",
        "values": (
            (
                "convertible",
                "可拆/多穿",
                (r"\bconvertible\b", r"\bmulti[- ]?way\b", r"\bremovable straps?\b", r"\bdetachable straps?\b"),
            ),
            ("strapless", "无肩带", (r"\bstrapless\b", r"\bno straps?\b")),
            (
                "strapped",
                "有肩带",
                (
                    r"\badjustable straps?\b",
                    r"\bwide straps?\b",
                    r"\bshoulder straps?\b",
                    r"\bstrappy\b",
                    r"\bracerback\b",
                    r"\bcross[- ]?back\b",
                    r"\bcriss[- ]?cross\b",
                    r"\bhalter\b",
                ),
            ),
        ),
    },
    {
        "id": "closure_type",
        "label": "穿脱/扣合方式",
        "values": (
            (
                "front_closure",
                "前扣",
                (r"\bfront[- ]?(?:closure|close|clasp|hook)\b", r"\bzip[- ]?front\b"),
            ),
            ("back_closure", "后扣", (r"\bback[- ]?(?:closure|close|clasp|hook)\b", r"\bhook[- ]?and[- ]?eye\b")),
            ("side_closure", "侧扣", (r"\bside[- ]?(?:closure|close|clasp|hook)\b",)),
            (
                "pullover",
                "套头/无扣",
                (r"\bpull[- ]?over\b", r"\bpull[- ]?on\b", r"\boverhead\b", r"\bno closure\b", r"\bclosure[- ]?free\b"),
            ),
        ),
    },
    {
        "id": "cup_construction",
        "label": "罩杯衬垫结构",
        "values": (
            ("removable_pad", "可拆杯垫", (r"\bremovable (?:pads?|cups?)\b", r"\bremovable padding\b")),
            (
                "padded_molded",
                "固定衬垫/模杯",
                (r"(?<!non-)(?<!non )\bpadded\b", r"\bmolded\b", r"\bcontour cups?\b", r"\bfoam cups?\b"),
            ),
            ("unlined", "无衬/薄杯", (r"\bunlined\b", r"\bnon[- ]?padded\b", r"\bno padding\b")),
        ),
    },
    {
        "id": "cup_coverage",
        "label": "罩杯覆盖度",
        "values": (
            ("full_coverage", "全罩杯", (r"\bfull[- ]?coverage\b", r"\bfull cup\b")),
            ("demi_balconette", "半罩/阳台杯", (r"\bdemi\b", r"\bbalconette\b", r"\bbalcony bra\b")),
            ("plunge_low_cut", "低胸/深V", (r"\bplunge\b", r"\blow[- ]?cut\b", r"\bdeep[- ]?v\b")),
        ),
    },
    {
        "id": "back_style",
        "label": "背部结构",
        "values": (
            ("racerback", "工字背", (r"\bracer[- ]?back\b",)),
            ("crossback", "交叉背", (r"\bcross[- ]?back\b", r"\bcriss[- ]?cross back\b")),
            ("u_back", "U背/背心背", (r"\bu[- ]?back\b", r"\bleotard back\b", r"\bscoop back\b")),
            ("open_back", "露背", (r"\bopen[- ]?back\b", r"\blow[- ]?back\b")),
        ),
    },
    {
        "id": "band_length",
        "label": "下围长度",
        "values": (
            ("longline", "长下围", (r"\blong[- ]?line\b", r"\blongline\b")),
            ("standard_band", "常规下围", (r"\bstandard band\b", r"\bregular[- ]?length band\b")),
        ),
    },
    {
        "id": "pack_size",
        "label": "包装数量",
        "values": (
            (
                "multi_pack",
                "多件装",
                (r"\b(?:[2-9]|[1-9][0-9])[- ]?(?:pack|pk)\b", r"\bmulti[- ]?pack\b", r"\bset of (?:[2-9]|[1-9][0-9])\b"),
            ),
            ("single", "单件", (r"\bsingle[- ]?(?:pack|piece)\b", r"\b1[- ]?(?:pack|pk)\b", r"\bpacksize\s*[:=]?\s*1\b")),
        ),
    },
)


ATTRIBUTE_TEXT_KEYS = {
    "title",
    "feature",
    "features",
    "bullet",
    "bullets",
    "bulletpoints",
    "description",
    "attributes",
    "productattributes",
    "productdetails",
    "details",
    "style",
    "closure",
    "wire",
    "padding",
    "straps",
    "backstyle",
    "packsize",
}


def is_bra_category(value: Any) -> bool:
    text = f" {str(value or '').casefold()} "
    return any(
        token in text
        for token in (
            " bra ",
            " bras ",
            "brassiere",
            "bralette",
            "minimizer",
            "文胸",
            "胸罩",
            "内衣",
        )
    )


def _flatten_attribute_text(value: Any, *, key: str = "", depth: int = 0) -> list[str]:
    if depth > 4 or value is None or value is False:
        return []
    if isinstance(value, str | int | float):
        prefix = f"{key} " if key else ""
        return [f"{prefix}{value}"]
    if isinstance(value, list | tuple):
        text: list[str] = []
        for item in value[:40]:
            text.extend(_flatten_attribute_text(item, key=key, depth=depth + 1))
        return text
    if isinstance(value, dict):
        text = []
        for child_key, child_value in list(value.items())[:60]:
            normalized_key = re.sub(r"[^a-z0-9]", "", str(child_key).casefold())
            if depth == 0 and normalized_key not in ATTRIBUTE_TEXT_KEYS:
                continue
            text.extend(_flatten_attribute_text(child_value, key=str(child_key), depth=depth + 1))
        return text
    return []


def classify_bra_attributes(product: dict[str, Any]) -> dict[str, str]:
    text = " ".join(_flatten_attribute_text(product)).casefold()
    classifications: dict[str, str] = {}
    for axis in BRA_ATTRIBUTE_AXES:
        matches: list[str] = []
        for value_id, _label, patterns in axis["values"]:
            if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
                matches.append(value_id)
        classifications[axis["id"]] = matches[0] if len(matches) == 1 else "conflict" if matches else "unknown"
    return classifications


def _numeric_value(product: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        raw = product.get(key)
        if raw in (None, ""):
            continue
        try:
            value = float(str(raw).replace(",", "").replace("$", "").strip())
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return None


def _product_rows(tool_results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    for tool in reversed(tool_results):
        if str(tool.get("name") or "") != "sellersprite_market_product_concentration":
            continue
        if str(tool.get("status") or "") not in {"ok", "partial_ok", "success", "completed"}:
            continue
        data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
        selection = data.get("product_selection") if isinstance(data.get("product_selection"), dict) else {}
        eligible = [item for item in selection.get("eligible_candidates") or [] if isinstance(item, dict)]
        eligible_asins = {str(item.get("asin") or "").strip().upper() for item in eligible}
        payload = data.get("data")
        raw_rows = [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
        if eligible_asins and raw_rows:
            filtered = [row for row in raw_rows if str(row.get("asin") or "").strip().upper() in eligible_asins]
            if filtered:
                return filtered, str(tool.get("label") or tool.get("name") or "SellerSprite")
        if eligible:
            return eligible, str(tool.get("label") or tool.get("name") or "SellerSprite")
        if raw_rows:
            return raw_rows, str(tool.get("label") or tool.get("name") or "SellerSprite")
    return [], ""


def build_bra_attribute_distribution(
    tool_results: list[dict[str, Any]],
    *,
    sample_limit: int = 100,
    product_families: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if product_families is not None:
        rows = []
        source_tools: list[str] = []
        raw_product_count = 0
        for family in product_families:
            if not isinstance(family, dict):
                continue
            observations = [
                item for item in family.get("observations") or [] if isinstance(item, dict)
            ]
            raw_product_count += len(observations)
            source_tools.extend(
                str(item) for item in family.get("source_tools") or [] if str(item).strip()
            )
            representative = (
                dict(family.get("representative"))
                if isinstance(family.get("representative"), dict)
                else {}
            )
            representative.update(
                {
                    "family_id": family.get("family_id"),
                    "family_asin": family.get("family_asin"),
                    "representative_asin": family.get("representative_asin"),
                    "member_asins": family.get("member_asins") or [],
                }
            )
            rows.append(representative)
        unique_rows = rows[: max(1, sample_limit)]
        source = ", ".join(dict.fromkeys(source_tools)) or "market_product_identity.v1"
        sample_scope = "unified_product_identity_family"
    else:
        rows, source = _product_rows(tool_results)
        raw_product_count = len(rows)
        unique_rows = []
        seen_families: set[str] = set()
        for row in rows:
            asin = str(row.get("asin") or "").strip().upper()
            family = str(
                row.get("family_asin")
                or row.get("parentAsin")
                or row.get("parent_asin")
                or row.get("parent")
                or asin
            ).strip().upper()
            if not family or family in seen_families:
                continue
            seen_families.add(family)
            unique_rows.append(row)
            if len(unique_rows) >= max(1, sample_limit):
                break
        sample_scope = "deduplicated_product_family"

    classified_rows = [
        {
            "attributes": classify_bra_attributes(row),
            "sales": _numeric_value(row, ("totalUnits", "total_units", "monthlySales", "monthly_sales", "units")),
        }
        for row in unique_rows
    ]
    sales_rows = [row for row in classified_rows if row["sales"] is not None]
    sales_total = sum(float(row["sales"] or 0) for row in sales_rows)
    axes: list[dict[str, Any]] = []
    for axis in BRA_ATTRIBUTE_AXES:
        value_labels = {value_id: label for value_id, label, _patterns in axis["values"]}
        value_labels.update({"unknown": "未知", "conflict": "冲突"})
        counts = Counter(row["attributes"][axis["id"]] for row in classified_rows)
        sales = Counter()
        for row in sales_rows:
            sales[row["attributes"][axis["id"]]] += float(row["sales"] or 0)
        ordered_value_ids = [value_id for value_id, _label, _patterns in axis["values"]] + ["unknown", "conflict"]
        values = []
        for value_id in ordered_value_ids:
            count = counts.get(value_id, 0)
            weighted_sales = sales.get(value_id, 0.0)
            if not count and weighted_sales <= 0:
                continue
            values.append(
                {
                    "id": value_id,
                    "label": value_labels[value_id],
                    "product_family_count": count,
                    "product_family_share": round((count / len(classified_rows) * 100), 1) if classified_rows else None,
                    "estimated_sales": round(weighted_sales, 2) if sales_rows else None,
                    "estimated_sales_share": round((weighted_sales / sales_total * 100), 1) if sales_total > 0 else None,
                }
            )
        known_count = len(classified_rows) - counts.get("unknown", 0) - counts.get("conflict", 0)
        axes.append(
            {
                "id": axis["id"],
                "label": axis["label"],
                "classified_product_count": known_count,
                "classified_product_share": round((known_count / len(classified_rows) * 100), 1) if classified_rows else 0.0,
                "values": values,
                "source": source,
            }
        )

    return {
        "sample_scope": sample_scope,
        "raw_product_count": raw_product_count,
        "product_family_count": len(unique_rows),
        "family_ids": [
            str(row.get("family_id") or row.get("family_asin") or row.get("asin") or "")
            for row in unique_rows
            if row.get("family_id") or row.get("family_asin") or row.get("asin")
        ],
        "sales_metric_product_count": len(sales_rows),
        "sales_metric_coverage": round((len(sales_rows) / len(unique_rows) * 100), 1) if unique_rows else 0.0,
        "source": source,
        "classification_method": "explicit_title_or_structured_attribute_text_only",
        "absence_is_not_negative": True,
        "axes": axes,
    }

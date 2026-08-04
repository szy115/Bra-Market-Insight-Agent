from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pymysql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from insight_agent.bra_attributes import classify_bra_attributes, is_bra_category  # noqa: E402
from insight_agent.mcp_fastmoss import execute_fastmoss_agent_tool  # noqa: E402
from insight_agent.mcp_sellersprite import execute_sellersprite_agent_tool  # noqa: E402
from insight_agent.mcp_sif import execute_sif_agent_tool  # noqa: E402

FASTMOSS_CATEGORY_PARAMS = {
    "query": ["women bra", "womens bras", "bras", "女士文胸"],
    "top_k": 5,
    "max_total_results": 12,
}
BRA_KEYWORDS = [
    "bra",
    "wireless bra",
    "sports bra",
    "strapless bra",
    "push up bra",
    "bralette",
    "minimizer bra",
    "front closure bra",
    "plus size bra",
    "nursing bra",
    "seamless bra",
    "full coverage bra",
    "backless bra",
    "underwire bra",
    "t shirt bra",
    "padded bra",
    "racerback bra",
    "longline bra",
    "convertible bra",
    "everyday bra",
]


def load_dotenv() -> None:
    path = PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def digest(value: Any) -> bytes:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).digest()


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None else None


def parse_date(value: Any) -> dt.date | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y.%m", "%Y-%m", "%Y%m"):
        try:
            parsed = dt.datetime.strptime(text, fmt)
            return parsed.date().replace(day=1) if fmt != "%Y-%m-%d" else parsed.date()
        except ValueError:
            continue
    return None


def previous_complete_month(today: dt.date) -> str:
    return (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y%m")


def pack_count(title: str) -> int | None:
    match = re.search(r"\b([1-9][0-9]?)\s*[- ]?(?:pack|pk)\b", title, flags=re.I)
    return int(match.group(1)) if match else None


def list_at(value: Any, *path: str) -> list[dict[str, Any]]:
    current = value
    for key in path:
        current = current.get(key) if isinstance(current, dict) else None
    return [item for item in current if isinstance(item, dict)] if isinstance(current, list) else []


def record_call(
    cur: pymysql.cursors.Cursor,
    provider: str,
    tool_name: str,
    params: dict[str, Any],
    result: dict[str, Any],
    *,
    initial_import: bool,
) -> int:
    now = utc_now()
    raw = canonical_json(result).encode("utf-8")
    compressed = gzip.compress(raw, compresslevel=6)
    cache = result.get("cache") if isinstance(result.get("cache"), dict) else {}
    cur.execute(
        """
        INSERT INTO source_call (
            provider, tool_name, request_hash, request_params, status, summary,
            remote_row_count, duration_ms, is_cache_hit, called_at, completed_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            provider,
            tool_name,
            digest(params),
            json_value(params),
            str(result.get("status") or "unknown"),
            str(result.get("summary") or "")[:1000],
            count_rows(result.get("data")),
            integer(result.get("duration_ms")),
            False if initial_import else bool(cache.get("hit")),
            now,
            now,
        ),
    )
    call_id = int(cur.lastrowid)
    cur.execute(
        """
        INSERT INTO source_raw_response (
            call_id, response_sha256, schema_version, compression,
            payload, payload_bytes, created_at
        ) VALUES (%s,%s,%s,'gzip',%s,%s,%s)
        """,
        (call_id, hashlib.sha256(raw).digest(), "bra_mcp_ingest.v1", compressed, len(raw), now),
    )
    return call_id


def count_rows(value: Any) -> int:
    best = 0
    if isinstance(value, list):
        best = len(value)
        for item in value[:50]:
            best = max(best, count_rows(item))
    elif isinstance(value, dict):
        for item in value.values():
            best = max(best, count_rows(item))
    return best


def upsert_category(
    cur: pymysql.cursors.Cursor,
    row: dict[str, Any],
    call_id: int,
) -> int:
    category_id = str(row.get("category_id_level3") or "").strip()
    name = str(row.get("cn_name") or "").strip()
    path = str(row.get("cn_full_name") or name).strip()
    is_bra = bool(category_id and "文胸" in name and "配件" not in name)
    now = utc_now()
    cur.execute(
        """
        INSERT INTO bra_category_scope (
            platform, market, provider, external_category_id, category_level,
            category_name, category_path, is_bra_leaf, enabled,
            source_call_id, first_seen_at, last_seen_at
        ) VALUES ('tiktok','US','fastmoss',%s,3,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            category_name=VALUES(category_name), category_path=VALUES(category_path),
            is_bra_leaf=VALUES(is_bra_leaf), enabled=VALUES(enabled),
            source_call_id=VALUES(source_call_id), last_seen_at=VALUES(last_seen_at)
        """,
        (category_id, name, path, is_bra, is_bra, call_id, now, now),
    )
    cur.execute(
        "SELECT id FROM bra_category_scope WHERE platform='tiktok' AND market='US' AND provider='fastmoss' AND external_category_id=%s",
        (category_id,),
    )
    return int(cur.fetchone()[0])


def upsert_shop(cur: pymysql.cursors.Cursor, shop: dict[str, Any]) -> int | None:
    external_id = str(shop.get("shop_id") or "").strip()
    if not external_id:
        return None
    now = utc_now()
    cur.execute(
        """
        INSERT INTO bra_shop (
            platform, market, provider, external_shop_id, shop_name,
            extra_attributes, first_seen_at, last_seen_at
        ) VALUES ('tiktok','US','fastmoss',%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            shop_name=VALUES(shop_name), extra_attributes=VALUES(extra_attributes),
            last_seen_at=VALUES(last_seen_at)
        """,
        (external_id, shop.get("shop_name"), json_value(shop), now, now),
    )
    cur.execute(
        "SELECT id FROM bra_shop WHERE platform='tiktok' AND market='US' AND provider='fastmoss' AND external_shop_id=%s",
        (external_id,),
    )
    return int(cur.fetchone()[0])


def upsert_family(
    cur: pymysql.cursors.Cursor,
    *,
    platform: str,
    provider: str,
    external_id: str,
    title: str,
    brand: str | None = None,
    shop_id: int | None = None,
    category_scope_id: int | None = None,
    image_url: str | None = None,
    listed_at: Any = None,
    extra: dict[str, Any] | None = None,
) -> tuple[int, bool]:
    cur.execute(
        "SELECT id FROM bra_product_family WHERE platform=%s AND market='US' AND provider=%s AND external_family_id=%s",
        (platform, provider, external_id),
    )
    existing = cur.fetchone()
    attrs = classify_bra_attributes({"title": title, "attributes": extra or {}})
    now = utc_now()
    parsed_listed_at = None
    parsed_date = parse_date(listed_at)
    if parsed_date:
        parsed_listed_at = dt.datetime.combine(parsed_date, dt.time.min)
    cur.execute(
        """
        INSERT INTO bra_product_family (
            platform, market, provider, external_family_id, shop_id,
            category_scope_id, brand, title, image_url, listed_at,
            wire_structure, strap_presence, closure_type, cup_construction,
            cup_coverage, back_style, band_length, pack_size,
            extra_attributes, first_seen_at, last_seen_at
        ) VALUES (%s,'US',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            shop_id=COALESCE(VALUES(shop_id),shop_id),
            category_scope_id=COALESCE(VALUES(category_scope_id),category_scope_id),
            brand=COALESCE(VALUES(brand),brand), title=COALESCE(VALUES(title),title),
            image_url=COALESCE(VALUES(image_url),image_url),
            listed_at=COALESCE(VALUES(listed_at),listed_at),
            wire_structure=VALUES(wire_structure), strap_presence=VALUES(strap_presence),
            closure_type=VALUES(closure_type), cup_construction=VALUES(cup_construction),
            cup_coverage=VALUES(cup_coverage), back_style=VALUES(back_style),
            band_length=VALUES(band_length), pack_size=COALESCE(VALUES(pack_size),pack_size),
            extra_attributes=VALUES(extra_attributes), last_seen_at=VALUES(last_seen_at)
        """,
        (
            platform, provider, external_id, shop_id, category_scope_id, brand, title,
            image_url, parsed_listed_at, attrs.get("wire_structure"), attrs.get("strap_presence"),
            attrs.get("closure_type"), attrs.get("cup_construction"), attrs.get("cup_coverage"),
            attrs.get("back_style"), attrs.get("band_length"), pack_count(title),
            json_value(extra or {}), now, now,
        ),
    )
    cur.execute(
        "SELECT id FROM bra_product_family WHERE platform=%s AND market='US' AND provider=%s AND external_family_id=%s",
        (platform, provider, external_id),
    )
    return int(cur.fetchone()[0]), existing is None


def upsert_variant(cur: pymysql.cursors.Cursor, family_id: int, provider: str, external_id: str, currency: str | None) -> int:
    now = utc_now()
    cur.execute(
        """
        INSERT INTO bra_product_variant (
            family_id, provider, external_product_id, currency, first_seen_at, last_seen_at
        ) VALUES (%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            family_id=VALUES(family_id), currency=COALESCE(VALUES(currency),currency),
            last_seen_at=VALUES(last_seen_at)
        """,
        (family_id, provider, external_id, currency, now, now),
    )
    cur.execute(
        "SELECT id FROM bra_product_variant WHERE provider=%s AND external_product_id=%s",
        (provider, external_id),
    )
    return int(cur.fetchone()[0])


def upsert_keyword(cur: pymysql.cursors.Cursor, keyword: str) -> tuple[int, bool]:
    normalized = " ".join(keyword.casefold().split())
    keyword_hash = hashlib.sha256(normalized.encode("utf-8")).digest()
    cur.execute("SELECT id FROM bra_keyword WHERE market='US' AND keyword_hash=%s", (keyword_hash,))
    existing = cur.fetchone()
    now = utc_now()
    cur.execute(
        """
        INSERT INTO bra_keyword (
            market, keyword, normalized_keyword, keyword_hash, first_seen_at, last_seen_at
        ) VALUES ('US',%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE keyword=VALUES(keyword), last_seen_at=VALUES(last_seen_at)
        """,
        (keyword, normalized, keyword_hash, now, now),
    )
    cur.execute("SELECT id FROM bra_keyword WHERE market='US' AND keyword_hash=%s", (keyword_hash,))
    return int(cur.fetchone()[0]), existing is None


def ingest_fastmoss_categories(cur: pymysql.cursors.Cursor, result: dict[str, Any], call_id: int) -> tuple[int, int | None]:
    rows = list_at(result.get("data"), "result", "categories")
    exact_scope_id = None
    inserted = 0
    for row in rows:
        name = str(row.get("cn_name") or "")
        if "文胸" not in name or "配件" in name:
            continue
        category_scope_id = upsert_category(cur, row, call_id)
        inserted += 1
        if str(row.get("category_id_level3")) == "601262" or name == "女士文胸":
            exact_scope_id = category_scope_id
    return inserted, exact_scope_id


def ingest_fastmoss_products(
    cur: pymysql.cursors.Cursor,
    result: dict[str, Any],
    call_id: int,
    category_scope_id: int,
    metric_date: dt.date,
) -> tuple[int, int]:
    rows = list_at(result.get("data"), "list")
    entities = 0
    facts = 0
    for row in rows:
        product_id = str(row.get("product_id") or "").strip()
        title = str(row.get("title") or "").strip()
        l3 = (((row.get("category") or {}).get("l3") or {}) if isinstance(row.get("category"), dict) else {})
        if not product_id or str(l3.get("id") or "") != "601262" or not is_bra_category(l3.get("name") or title):
            continue
        shop = row.get("shop") if isinstance(row.get("shop"), dict) else {}
        shop_id = upsert_shop(cur, shop)
        family_id, created = upsert_family(
            cur,
            platform="tiktok",
            provider="fastmoss",
            external_id=product_id,
            title=title,
            shop_id=shop_id,
            category_scope_id=category_scope_id,
            image_url=str(row.get("cover_url") or "") or None,
            listed_at=row.get("launch_date"),
            extra=row,
        )
        entities += int(created)
        variant_id = upsert_variant(cur, family_id, "fastmoss", product_id, row.get("currency_code"))
        cur.execute(
            """
            INSERT INTO bra_offer (
                variant_id, shop_id, provider, observed_at, currency, price,
                list_price, commission_rate, is_available, source_call_id
            ) VALUES (%s,%s,'fastmoss',%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                variant_id, shop_id, utc_now(), row.get("currency_code"), number(row.get("floor_price")),
                number(row.get("ceiling_price")),
                (number(row.get("commission_rate_percent")) or 0) / 100 if row.get("commission_rate_percent") is not None else None,
                not bool(row.get("is_off_shelf")), call_id,
            ),
        )
        cur.execute(
            """
            INSERT INTO bra_product_daily (
                metric_date, provider, platform, market, family_id, period_days,
                currency, price, units_daily, units_total, gmv_daily, gmv_total,
                is_estimated, source_call_id, observed_at, version, extra_metrics
            )
            SELECT %s,'fastmoss','tiktok','US',%s,1,%s,%s,%s,%s,%s,%s,TRUE,%s,%s,
                   COALESCE(MAX(version),0)+1,%s
            FROM bra_product_daily
            WHERE metric_date=%s AND provider='fastmoss' AND family_id=%s AND period_days=1
            """,
            (
                metric_date, family_id, row.get("currency_code"), number(row.get("floor_price")),
                integer(row.get("period_units_sold")), integer(row.get("total_units_sold")),
                number(row.get("period_gmv")), number(row.get("total_gmv")), call_id, utc_now(),
                json_value(row), metric_date, family_id,
            ),
        )
        facts += 1
    return entities, facts


def ingest_sellersprite_keywords(
    cur: pymysql.cursors.Cursor,
    result: dict[str, Any],
    call_id: int,
    *,
    expand_related_asins: bool = False,
) -> tuple[int, int]:
    rows = list_at(result.get("data"), "data", "items")
    entities = 0
    facts = 0
    for row in rows:
        keyword = str(row.get("keywords") or row.get("keyword") or "").strip()
        if not keyword or not is_bra_category(keyword):
            continue
        keyword_id, created = upsert_keyword(cur, keyword)
        entities += int(created)
        period_start = parse_date(row.get("month")) or dt.date.today().replace(day=1)
        cur.execute(
            """
            INSERT INTO bra_keyword_period (
                provider, market, keyword_id, period_type, period_start,
                search_volume, purchase_volume, purchase_rate, search_growth,
                product_count, supply_demand_ratio, click_concentration,
                title_density, ppc_bid_low, ppc_bid_high, avg_price,
                source_call_id, observed_at, version, extra_metrics
            )
            SELECT 'sellersprite','US',%s,'month',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   COALESCE(MAX(version),0)+1,%s
            FROM bra_keyword_period
            WHERE provider='sellersprite' AND market='US' AND keyword_id=%s
              AND period_type='month' AND period_start=%s
            """,
            (
                keyword_id, period_start, integer(row.get("searches")), integer(row.get("purchases")),
                number(row.get("purchaseRate")), number(row.get("searchMonthlyCr") or row.get("growth")),
                integer(row.get("products")), number(row.get("supplyDemandRatio")),
                number(row.get("araClickRate")), integer(row.get("titleDensityExact")),
                number(row.get("bidMin")), number(row.get("bidMax")), number(row.get("avgPrice")),
                call_id, utc_now(), json_value(row), keyword_id, period_start,
            ),
        )
        facts += 1
        if not expand_related_asins:
            continue
        for relation_index, product in enumerate(row.get("relationAsinList") or [], start=1):
            if not isinstance(product, dict):
                continue
            asin = str(product.get("asin") or "").strip().upper()
            title = str(product.get("title") or "").strip()
            if not asin or (title and not is_bra_category(title)):
                continue
            family_id, family_created = upsert_family(
                cur,
                platform="amazon",
                provider="sellersprite",
                external_id=asin,
                title=title,
                image_url=str(product.get("imageUrl") or "") or None,
                extra=product,
            )
            entities += int(family_created)
            variant_id = upsert_variant(cur, family_id, "sellersprite", asin, "USD")
            cur.execute(
                """
                INSERT INTO bra_offer (
                    variant_id, provider, observed_at, currency, price, source_call_id
                ) VALUES (%s,'sellersprite',%s,'USD',%s,%s)
                """,
                (variant_id, utc_now(), number(product.get("price")), call_id),
            )
            cur.execute(
                """
                INSERT INTO bra_product_keyword_period (
                    provider, family_id, keyword_id, period_start, traffic_type,
                    source_call_id, observed_at, version, extra_metrics
                )
                SELECT 'sellersprite',%s,%s,%s,'related',%s,%s,
                       COALESCE(MAX(version),0)+1,%s
                FROM bra_product_keyword_period
                WHERE provider='sellersprite' AND family_id=%s AND keyword_id=%s
                  AND period_start=%s AND traffic_type='related'
                """,
                (
                    family_id, keyword_id, period_start, call_id, utc_now(),
                    json_value({"rank": relation_index, **product}),
                    family_id, keyword_id, period_start,
                ),
            )
            facts += 1
    return entities, facts


def update_call_counts(cur: pymysql.cursors.Cursor, call_id: int, entities: int, facts: int) -> None:
    cur.execute(
        "UPDATE source_call SET new_entity_count=%s, new_fact_count=%s WHERE id=%s",
        (entities, facts, call_id),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a low-cost recent US bra MCP sample into MySQL.")
    parser.add_argument("--initial-import", action="store_true", help="Mark current cached results as their originating calls.")
    parser.add_argument("--include-sif", action="store_true", help="Call SIF keyword demand; omit while quota is unavailable.")
    parser.add_argument("--record-known-sif-quota", action="store_true", help="Record the quota failure already observed without another remote call.")
    parser.add_argument(
        "--expand-related-asins",
        action="store_true",
        help="Normalize SellerSprite relationAsinList rows; raw responses always retain them.",
    )
    args = parser.parse_args()
    load_dotenv()

    today = dt.datetime.now(dt.UTC).date()
    latest_day = today - dt.timedelta(days=1)
    ranking_params = {
        "filter": {
            "category_id": 601262,
            "date_type": "day",
            "date_value": latest_day.isoformat(),
            "region": "US",
        },
        "orderby": [{"field": "period_units_sold", "order": "desc"}],
        "page": 1,
        "pagesize": 10,
    }
    seller_params = {
        "request": {
            "marketplace": "US",
            "keywords": "bra",
            "month": previous_complete_month(today),
            "page": 1,
            "size": 10,
            "order": {"field": "searches", "desc": True},
        }
    }

    results: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = [
        (
            "fastmoss",
            "mcp__fastmoss__search_category_by_words",
            FASTMOSS_CATEGORY_PARAMS,
            execute_fastmoss_agent_tool("mcp__fastmoss__search_category_by_words", FASTMOSS_CATEGORY_PARAMS),
        ),
        (
            "fastmoss",
            "mcp__fastmoss__product_rank_top_selling",
            ranking_params,
            execute_fastmoss_agent_tool("mcp__fastmoss__product_rank_top_selling", ranking_params),
        ),
        (
            "sellersprite",
            "sellersprite_keyword_research",
            seller_params,
            execute_sellersprite_agent_tool("sellersprite_keyword_research", seller_params),
        ),
    ]
    if args.include_sif:
        sif_params = {"keywords": BRA_KEYWORDS, "country": "US"}
        results.append(
            (
                "sif",
                "sif_market_get_keyword_demand",
                sif_params,
                execute_sif_agent_tool("sif_market_get_keyword_demand", sif_params),
            )
        )
    elif args.record_known_sif_quota:
        results.append(
            (
                "sif",
                "sif_market_get_keyword_demand",
                {"keywords": BRA_KEYWORDS, "country": "US"},
                {
                    "name": "sif_market_get_keyword_demand",
                    "status": "error",
                    "summary": "SIF quota is not allocated for the configured MCP key.",
                    "duration_ms": 0,
                    "data": {"error": "QUOTA_EXCEEDED"},
                },
            )
        )

    conn = pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
        autocommit=False,
    )
    summary: dict[str, Any] = {"calls": [], "latest_day": latest_day.isoformat()}
    try:
        with conn.cursor() as cur:
            call_ids: dict[str, int] = {}
            for provider, tool_name, params, result in results:
                call_id = record_call(cur, provider, tool_name, params, result, initial_import=args.initial_import)
                call_ids[tool_name] = call_id
                summary["calls"].append({"provider": provider, "tool": tool_name, "status": result.get("status"), "call_id": call_id})

            category_result = next(item[3] for item in results if item[1] == "mcp__fastmoss__search_category_by_words")
            categories, exact_scope_id = ingest_fastmoss_categories(
                cur, category_result, call_ids["mcp__fastmoss__search_category_by_words"]
            )
            if exact_scope_id is None:
                raise RuntimeError("FastMoss exact US Bras L3 category 601262 was not resolved.")

            ranking_result = next(item[3] for item in results if item[1] == "mcp__fastmoss__product_rank_top_selling")
            fm_entities, fm_facts = ingest_fastmoss_products(
                cur,
                ranking_result,
                call_ids["mcp__fastmoss__product_rank_top_selling"],
                exact_scope_id,
                latest_day,
            )
            update_call_counts(cur, call_ids["mcp__fastmoss__search_category_by_words"], categories, 0)
            update_call_counts(cur, call_ids["mcp__fastmoss__product_rank_top_selling"], fm_entities, fm_facts)

            seller_result = next(item[3] for item in results if item[1] == "sellersprite_keyword_research")
            ss_entities, ss_facts = ingest_sellersprite_keywords(
                cur,
                seller_result,
                call_ids["sellersprite_keyword_research"],
                expand_related_asins=args.expand_related_asins,
            )
            update_call_counts(cur, call_ids["sellersprite_keyword_research"], ss_entities, ss_facts)

            conn.commit()
            for table in (
                "source_call", "source_raw_response", "bra_category_scope", "bra_shop",
                "bra_product_family", "bra_product_variant", "bra_offer", "bra_product_daily",
                "bra_keyword", "bra_keyword_period", "bra_product_keyword_period",
            ):
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                summary[table] = int(cur.fetchone()[0])
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

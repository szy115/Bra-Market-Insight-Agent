from __future__ import annotations

import hashlib
import io
import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

PRODUCT_POOL_TOOLS = {
    "sellersprite_market_product_concentration",
    "sellersprite_product_research",
    "sellersprite_competitor_lookup",
}
SUCCESS_STATUSES = {"ok", "partial_ok", "success", "completed"}
PRODUCT_IDENTITY_SCHEMA_VERSION = "market_product_identity.v1"
DEFAULT_IMAGE_DOWNLOAD_BUDGET = 20
DEFAULT_ASIN_DETAIL_BUDGET = 10

PROJECT_ROOT = Path(os.getenv("INSIGHT_AGENT_HOME", Path(__file__).resolve().parents[2])).resolve()
IMAGE_FINGERPRINT_CACHE = PROJECT_ROOT / ".cache" / "product-image-fingerprints"

_SOURCE_PRIORITY = {
    "sellersprite_market_product_concentration": 0,
    "sellersprite_product_research": 1,
    "sellersprite_competitor_lookup": 2,
}
_COLOR_TOKENS = {
    "beige",
    "black",
    "blue",
    "blush",
    "brown",
    "burgundy",
    "charcoal",
    "cream",
    "gray",
    "green",
    "grey",
    "ivory",
    "khaki",
    "navy",
    "nude",
    "pink",
    "purple",
    "red",
    "rose",
    "tan",
    "taupe",
    "white",
    "wine",
    "yellow",
}
_TITLE_NOISE_TOKENS = {
    "amazon",
    "best",
    "classic",
    "collection",
    "comfortable",
    "fashion",
    "for",
    "ladies",
    "latest",
    "new",
    "premium",
    "style",
    "women",
    "woman",
    "womens",
}
_IMAGE_HOST_SUFFIXES = (
    ".media-amazon.com",
    ".ssl-images-amazon.com",
)
_IMAGE_HOSTS = {
    "m.media-amazon.com",
    "images.amazon.com",
    "images-na.ssl-images-amazon.com",
}


@dataclass
class _ImageBudget:
    limit: int
    downloads: int = 0
    cache_hits: int = 0
    failures: int = 0
    budget_exhausted: bool = False
    hashes: dict[str, str | None] = field(default_factory=dict)


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {item: item for item in items}
        self.members = {item: {item} for item in items}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def component(self, item: str) -> set[str]:
        return set(self.members[self.find(item)])

    def union(self, left: str, right: str) -> str:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return left_root
        if len(self.members[left_root]) < len(self.members[right_root]):
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        self.members[left_root].update(self.members.pop(right_root))
        return left_root


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    normalized = {re.sub(r"[^a-z0-9]", "", str(key).casefold()): value for key, value in row.items()}
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
        value = normalized.get(re.sub(r"[^a-z0-9]", "", key.casefold()))
        if value not in (None, ""):
            return value
    return None


def _asin(value: Any) -> str:
    normalized = re.sub(r"[^A-Z0-9]", "", str(value or "").strip().upper())
    return normalized if re.fullmatch(r"[A-Z0-9]{10}", normalized) else ""


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalized_name(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", normalized))


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _number(value: Any) -> float | int | None:
    parsed = _decimal(value)
    if parsed is None:
        return None
    if parsed == parsed.to_integral_value():
        return int(parsed)
    return float(parsed)


def _month_from_tool(tool: dict[str, Any], row: dict[str, Any]) -> str:
    direct = _first(row, ("month", "dataMonth", "snapshotMonth"))
    if direct not in (None, ""):
        return re.sub(r"[^0-9]", "", str(direct))[:6]
    tool_input = tool.get("input") if isinstance(tool.get("input"), dict) else {}
    request = tool_input.get("request") if isinstance(tool_input.get("request"), dict) else tool_input
    value = request.get("month") if isinstance(request, dict) else None
    return re.sub(r"[^0-9]", "", str(value or ""))[:6]


def _marketplace_from_tool(tool: dict[str, Any], fallback: str) -> str:
    tool_input = tool.get("input") if isinstance(tool.get("input"), dict) else {}
    request = tool_input.get("request") if isinstance(tool_input.get("request"), dict) else tool_input
    value = request.get("marketplace") if isinstance(request, dict) else None
    normalized = str(value or fallback or "US").strip().upper()
    return "US" if "US" in normalized or "美国" in normalized else normalized


def _query_from_tool(tool: dict[str, Any]) -> str:
    tool_input = tool.get("input") if isinstance(tool.get("input"), dict) else {}
    request = tool_input.get("request") if isinstance(tool_input.get("request"), dict) else tool_input
    if not isinstance(request, dict):
        return ""
    return _text(request.get("keyword") or request.get("departmentKeyword") or tool_input.get("category"))


def _payload_candidates(data: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[Any] = [data.get("data")]
    parsed = data.get("parsed_content") if isinstance(data.get("parsed_content"), dict) else {}
    values.append(parsed.get("data"))
    rows: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            for key in ("items", "products", "list"):
                nested = value.get(key)
                if isinstance(nested, list):
                    rows.extend(item for item in nested if isinstance(item, dict))
    return rows


def _product_rows(tool: dict[str, Any]) -> list[dict[str, Any]]:
    data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
    rows = _payload_candidates(data)
    if str(tool.get("name") or "") != "sellersprite_market_product_concentration":
        return rows
    selection = data.get("product_selection") if isinstance(data.get("product_selection"), dict) else {}
    if not selection:
        return rows
    allowed_asins = {
        _asin(item.get("asin"))
        for item in selection.get("eligible_candidates") or []
        if isinstance(item, dict)
    }
    duplicate_rows = [
        item
        for item in selection.get("excluded") or []
        if isinstance(item, dict)
        and str(item.get("exclusion_reason") or "").startswith("Duplicate parent/variation family:")
    ]
    allowed_asins.update(_asin(item.get("asin")) for item in duplicate_rows)
    allowed_asins.discard("")
    if rows and allowed_asins:
        return [row for row in rows if _asin(row.get("asin")) in allowed_asins]
    fallback = [
        item
        for item in selection.get("eligible_candidates") or []
        if isinstance(item, dict)
    ]
    return [*fallback, *duplicate_rows]


def _model_number(row: dict[str, Any], title: str) -> str:
    direct = _first(
        row,
        (
            "model",
            "modelNumber",
            "model_number",
            "styleNumber",
            "style_number",
            "itemModelNumber",
        ),
    )
    if direct not in (None, ""):
        return re.sub(r"[^A-Z0-9-]", "", str(direct).strip().upper())
    labeled = re.search(
        r"\b(?:model|style|item)\s*(?:number|no\.?|#)?\s*[:#-]?\s*([A-Za-z0-9-]{4,20})\b",
        title,
        flags=re.IGNORECASE,
    )
    if labeled:
        candidate = re.sub(r"[^A-Z0-9-]", "", labeled.group(1).upper())
        if re.search(r"[A-Z]", candidate) and re.search(r"\d", candidate) and not _asin(candidate):
            return candidate
    return ""


def _pack_count(row: dict[str, Any], title: str) -> int | None:
    direct = _first(
        row,
        ("packCount", "pack_count", "itemPackageQuantity", "packageQuantity", "unitCount"),
    )
    parsed = _number(direct)
    if isinstance(parsed, int) and parsed > 0:
        return parsed
    patterns = (
        r"\b(\d{1,2})\s*[- ]?(?:pack|pk|count|ct|pcs|pieces)\b",
        r"\bset\s+of\s+(\d{1,2})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, title, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    if re.search(r"\b(?:single|single-piece|single piece)\b", title, flags=re.IGNORECASE):
        return 1
    return None


def _pack_form(row: dict[str, Any], title: str) -> str:
    direct = _normalized_name(_first(row, ("packForm", "pack_form", "bundleType", "bundle_type")))
    text = f"{direct} {title.casefold()}"
    count = _pack_count(row, title)
    if count is not None:
        return "multi_pack" if count > 1 else "single"
    if re.search(r"\b(?:multipack|multi-pack|bundle|set)\b", text):
        return "multi_pack"
    if re.search(r"\b(?:single|individual)\b", text):
        return "single"
    return ""


def _core_title(title: str, brand: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).casefold().replace("'s", "")
    tokens = re.findall(r"[a-z0-9]+", normalized)
    brand_tokens = set(re.findall(r"[a-z0-9]+", brand.casefold()))
    core: list[str] = []
    for token in tokens:
        if token in brand_tokens or token in _COLOR_TOKENS or token in _TITLE_NOISE_TOKENS:
            continue
        if re.fullmatch(r"(?:xxs|xs|s|m|l|xl|xxl|xxxl|[2-6]xl)", token):
            continue
        if re.fullmatch(r"\d{2,3}[a-z]{1,3}", token):
            continue
        core.append(token)
    return " ".join(core)


def title_similarity(left: str, right: str) -> float:
    left = " ".join(left.split())
    right = " ".join(right.split())
    if not left or not right:
        return 0.0
    sequence = SequenceMatcher(None, left, right).ratio()
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    dice = 2 * len(left_tokens & right_tokens) / (len(left_tokens) + len(right_tokens))
    return round(max(sequence, dice), 4)


def _core_attributes(title: str) -> dict[str, str]:
    text = title.casefold()
    attributes: dict[str, str] = {}
    if re.search(r"\b(?:wireless|wirefree|wire-free|wire free|no wire)\b", text):
        attributes["wire"] = "wireless"
    elif re.search(r"\bunderwire\b", text):
        attributes["wire"] = "underwire"
    if re.search(r"\b(?:strapless|no straps?)\b", text):
        attributes["strap"] = "strapless"
    elif re.search(r"\b(?:straps|strapped|adjustable strap|shoulder strap)\b", text):
        attributes["strap"] = "strapped"
    if re.search(r"\bfront[- ]?(?:closure|close|hook)\b", text):
        attributes["closure"] = "front"
    elif re.search(r"\bback[- ]?(?:closure|close|hook)\b", text):
        attributes["closure"] = "back"
    elif re.search(r"\b(?:pullover|pull on|pull-on|overhead)\b", text):
        attributes["closure"] = "pullover"
    return attributes


def _image_url(row: dict[str, Any]) -> str:
    value = _first(row, ("imageUrl", "image_url", "mainImage", "main_image", "image"))
    if isinstance(value, dict):
        value = value.get("url") or value.get("large") or value.get("src")
    elif isinstance(value, list):
        value = next((item for item in value if isinstance(item, str)), "")
    url = str(value or "").strip()
    return url if url.startswith(("https://", "http://")) else ""


def normalized_image_identity(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    host = parsed.hostname.casefold() if parsed.hostname else ""
    if parsed.scheme != "https" or not _allowed_image_host(host):
        return ""
    path = urllib.parse.unquote(parsed.path)
    path = re.sub(r"\._[^/]*_\.(jpg|jpeg|png|webp)$", r".\1", path, flags=re.IGNORECASE)
    filename = path.rsplit("/", 1)[-1].casefold()
    return filename or f"{host}{path.casefold()}"


def _allowed_image_host(host: str) -> bool:
    normalized = host.casefold()
    return normalized in _IMAGE_HOSTS or any(normalized.endswith(suffix) for suffix in _IMAGE_HOST_SUFFIXES)


class _AmazonImageRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        parsed = urllib.parse.urlsplit(new_url)
        if parsed.scheme != "https" or not parsed.hostname or not _allowed_image_host(parsed.hostname):
            raise urllib.error.HTTPError(
                new_url,
                code,
                "Image redirect left the Amazon HTTPS allowlist.",
                headers,
                file_pointer,
            )
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def _open_amazon_image(request: urllib.request.Request) -> Any:
    opener = urllib.request.build_opener(_AmazonImageRedirectHandler())
    return opener.open(request, timeout=8)


def _image_dhash(url: str, budget: _ImageBudget) -> str | None:
    normalized_url = urllib.parse.urlunsplit((*urllib.parse.urlsplit(url)[:3], "", ""))
    if normalized_url in budget.hashes:
        budget.cache_hits += 1
        return budget.hashes[normalized_url]
    cache_key = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
    cache_path = IMAGE_FINGERPRINT_CACHE / f"{cache_key}.json"
    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            value = str(payload.get("dhash") or "")
            if re.fullmatch(r"[0-9a-f]{16}", value):
                budget.cache_hits += 1
                budget.hashes[normalized_url] = value
                return value
        except (json.JSONDecodeError, OSError):
            pass
    if budget.downloads >= budget.limit:
        budget.budget_exhausted = True
        budget.hashes[normalized_url] = None
        return None
    parsed = urllib.parse.urlsplit(normalized_url)
    if parsed.scheme != "https" or not parsed.hostname or not _allowed_image_host(parsed.hostname):
        budget.failures += 1
        budget.hashes[normalized_url] = None
        return None
    budget.downloads += 1
    try:
        request = urllib.request.Request(
            normalized_url,
            headers={"User-Agent": "InsightAgent/0.1"},
            method="GET",
        )
        with _open_amazon_image(request) as response:
            final_url = urllib.parse.urlsplit(response.geturl())
            if final_url.scheme != "https" or not final_url.hostname or not _allowed_image_host(final_url.hostname):
                raise ValueError("Image redirect left the Amazon image allowlist.")
            content_length = int(response.headers.get("Content-Length") or 0)
            if content_length > 10 * 1024 * 1024:
                raise ValueError("Image exceeds 10 MB.")
            raw = response.read(10 * 1024 * 1024 + 1)
            if len(raw) > 10 * 1024 * 1024:
                raise ValueError("Image exceeds 10 MB.")
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as image:
            grayscale = image.convert("L").resize((9, 8))
            pixels = list(
                grayscale.get_flattened_data()
                if hasattr(grayscale, "get_flattened_data")
                else grayscale.getdata()
            )
        bits = 0
        for row_index in range(8):
            offset = row_index * 9
            for column in range(8):
                bits = (bits << 1) | int(pixels[offset + column] > pixels[offset + column + 1])
        value = f"{bits:016x}"
        IMAGE_FINGERPRINT_CACHE.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"url": normalized_url, "dhash": value}, ensure_ascii=False),
            encoding="utf-8",
        )
        budget.hashes[normalized_url] = value
        return value
    except Exception:  # noqa: BLE001 - image evidence is optional and audited
        budget.failures += 1
        budget.hashes[normalized_url] = None
        return None


def _hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _sales_metric(row: dict[str, Any]) -> tuple[str, float | int | None]:
    aliases = (
        ("total_units", ("totalUnits", "total_units")),
        ("monthly_sales", ("monthlySales", "monthly_sales")),
        ("units", ("units",)),
        ("sales", ("sales",)),
    )
    for canonical, keys in aliases:
        value = _first(row, keys)
        parsed = _number(value)
        if parsed is not None:
            return canonical, parsed
    return "", None


def normalize_product_observations(
    tool_results: list[dict[str, Any]],
    *,
    marketplace: str,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, tool in enumerate(tool_results, start=1):
        if not isinstance(tool, dict):
            continue
        source_tool = str(tool.get("name") or "")
        if source_tool not in PRODUCT_POOL_TOOLS or str(tool.get("status") or "") not in SUCCESS_STATUSES:
            continue
        for source_index, row in enumerate(_product_rows(tool), start=1):
            asin = _asin(_first(row, ("asin", "childAsin", "productAsin")))
            if not asin:
                continue
            title = _text(_first(row, ("title", "productTitle", "name")))
            brand = _text(_first(row, ("brand", "brandName")))
            sales_metric, sales_value = _sales_metric(row)
            price_decimal = _decimal(_first(row, ("price", "currentPrice", "salePrice")))
            parent_asin = _asin(_first(row, ("family_asin", "parentAsin", "parent_asin", "parent")))
            variation_asins = [
                _asin(item.get("asin") if isinstance(item, dict) else item)
                for item in row.get("variationList") or row.get("variations") or []
            ]
            scalar_fields = {
                str(key): value
                for key, value in row.items()
                if isinstance(value, (str, int, float, bool)) or value is None
            }
            observation = {
                **scalar_fields,
                "observation_id": f"E{index:02d}:{source_tool}:{source_index}",
                "evidence_id": f"E{index:02d}",
                "source_tool": source_tool,
                "source_rank": source_index,
                "marketplace": _marketplace_from_tool(tool, marketplace),
                "snapshot_month": _month_from_tool(tool, row),
                "source_query": _query_from_tool(tool),
                "asin": asin,
                "parent_asin": parent_asin,
                "variation_asins": [item for item in variation_asins if item],
                "title": title,
                "brand": brand,
                "brand_norm": _normalized_name(brand),
                "model_number": _model_number(row, title),
                "pack_count": _pack_count(row, title),
                "pack_form": _pack_form(row, title),
                "core_title": _core_title(title, brand),
                "core_attributes": _core_attributes(title),
                "image_url": _image_url(row),
                "image_identity": normalized_image_identity(_image_url(row)),
                "price_normalized": float(price_decimal.quantize(Decimal("0.01"))) if price_decimal is not None else None,
                "price_currency": str(
                    _first(row, ("currency", "currencyCode", "priceCurrency"))
                    or ("USD" if _marketplace_from_tool(tool, marketplace) == "US" else "")
                ).strip().upper(),
                "sales_metric": sales_metric,
                "sales_value": sales_value,
            }
            identity = json.dumps(
                {
                    key: observation.get(key)
                    for key in (
                        "source_tool",
                        "marketplace",
                        "snapshot_month",
                        "source_query",
                        "asin",
                        "parent_asin",
                        "variation_asins",
                        "title",
                        "brand_norm",
                        "model_number",
                        "pack_count",
                        "pack_form",
                        "image_identity",
                        "price_normalized",
                        "price_currency",
                        "sales_metric",
                        "sales_value",
                    )
                },
                sort_keys=True,
                default=str,
            )
            if identity in seen:
                continue
            seen.add(identity)
            observations.append(observation)
    return observations


def _detail_records(tool_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}
    for index, tool in enumerate(tool_results, start=1):
        if not isinstance(tool, dict) or str(tool.get("name") or "") != "sellersprite_asin_detail":
            continue
        if str(tool.get("status") or "") not in SUCCESS_STATUSES:
            continue
        tool_input = tool.get("input") if isinstance(tool.get("input"), dict) else {}
        request = tool_input.get("request") if isinstance(tool_input.get("request"), dict) else tool_input
        asin = _asin(request.get("asin") or tool_input.get("asin"))
        data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
        detail = data.get("data") if isinstance(data.get("data"), dict) else data
        if not asin or not detail:
            continue
        variations = [
            _asin(item.get("asin"))
            for item in detail.get("variationList") or []
            if isinstance(item, dict)
        ]
        details[asin] = {
            "asin": asin,
            "evidence_id": f"E{index:02d}",
            "parent_asin": _asin(_first(detail, ("parentAsin", "parent_asin", "parent"))),
            "variations": [item for item in variations if item],
            "brand": _text(_first(detail, ("brand", "brandName"))),
            "title": _text(_first(detail, ("title", "productTitle", "name"))),
            "model_number": _model_number(detail, _text(detail.get("title"))),
            "pack_count": _pack_count(detail, _text(detail.get("title"))),
            "pack_form": _pack_form(detail, _text(detail.get("title"))),
            "image_url": _image_url(detail),
        }
    return details


def _profile_sort_key(observation: dict[str, Any]) -> tuple[Any, ...]:
    completeness = sum(
        observation.get(key) not in (None, "", [], {})
        for key in (
            "parent_asin",
            "title",
            "brand",
            "model_number",
            "pack_count",
            "pack_form",
            "image_url",
            "price_normalized",
            "sales_value",
        )
    )
    ranking = _number(_first(observation, ("ranking", "rank", "candidate_order")))
    return (
        _SOURCE_PRIORITY.get(str(observation.get("source_tool") or ""), 99),
        float(ranking) if ranking is not None else float("inf"),
        -completeness,
        str(observation.get("asin") or ""),
    )


def _first_profile_value(items: list[dict[str, Any]], key: str) -> Any:
    return next((item.get(key) for item in items if item.get(key) not in (None, "")), None)


def _build_profiles(
    observations: list[dict[str, Any]],
    details: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        grouped[str(observation["asin"])].append(observation)
    profiles: dict[str, dict[str, Any]] = {}
    for asin, items in grouped.items():
        items.sort(key=_profile_sort_key)
        representative = items[0]
        detail = details.get(asin) or {}
        title = str(_first_profile_value(items, "title") or detail.get("title") or "")
        brand = str(_first_profile_value(items, "brand") or detail.get("brand") or "")
        image_url = str(_first_profile_value(items, "image_url") or detail.get("image_url") or "")
        variations = {
            variation
            for item in items
            for variation in item.get("variation_asins") or []
            if variation
        }
        variations.update(detail.get("variations") or [])
        profiles[asin] = {
            "asin": asin,
            "observations": items,
            "representative": representative,
            "parent_asin": str(detail.get("parent_asin") or _first_profile_value(items, "parent_asin") or ""),
            "variations": sorted(variations),
            "title": title,
            "brand": brand,
            "brand_norm": _normalized_name(brand),
            "model_number": str(detail.get("model_number") or _first_profile_value(items, "model_number") or ""),
            "pack_count": detail.get("pack_count") or _first_profile_value(items, "pack_count"),
            "pack_form": detail.get("pack_form") or _first_profile_value(items, "pack_form") or "",
            "core_title": _core_title(title, brand),
            "core_attributes": _core_attributes(title),
            "image_url": image_url,
            "image_identity": normalized_image_identity(image_url),
            "relationship_evidence_ids": [detail["evidence_id"]] if detail.get("evidence_id") else [],
        }
    return profiles


def _hard_conflicts(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    conflicts: list[str] = []
    if left.get("model_number") and right.get("model_number") and left["model_number"] != right["model_number"]:
        conflicts.append("model_number")
    if left.get("pack_count") and right.get("pack_count") and left["pack_count"] != right["pack_count"]:
        conflicts.append("pack_count")
    if left.get("pack_form") and right.get("pack_form") and left["pack_form"] != right["pack_form"]:
        conflicts.append("pack_form")
    left_attributes = left.get("core_attributes") or {}
    right_attributes = right.get("core_attributes") or {}
    for key in sorted(set(left_attributes) & set(right_attributes)):
        if left_attributes[key] != right_attributes[key]:
            conflicts.append(f"core_attribute:{key}")
    return conflicts


def _profile_observation_conflicts(profile: dict[str, Any]) -> list[str]:
    observations = [
        item for item in profile.get("observations") or [] if isinstance(item, dict)
    ]
    conflicts: list[str] = []
    for key in ("model_number", "pack_count", "pack_form"):
        values = {str(item.get(key)) for item in observations if item.get(key) not in (None, "")}
        if len(values) > 1:
            conflicts.append(key)
    for attribute in ("wire", "strap", "closure"):
        values = {
            str((item.get("core_attributes") or {}).get(attribute))
            for item in observations
            if (item.get("core_attributes") or {}).get(attribute)
        }
        if len(values) > 1:
            conflicts.append(f"core_attribute:{attribute}")
    return conflicts


def _same_price_sales(left: dict[str, Any], right: dict[str, Any]) -> bool:
    for left_observation in left.get("observations") or []:
        for right_observation in right.get("observations") or []:
            if not left_observation.get("snapshot_month") or not right_observation.get("snapshot_month"):
                continue
            if left_observation["snapshot_month"] != right_observation["snapshot_month"]:
                continue
            if left_observation.get("marketplace") != right_observation.get("marketplace"):
                continue
            if left_observation.get("price_currency") != right_observation.get("price_currency"):
                continue
            if not left_observation.get("sales_metric") or left_observation.get("sales_value") is None:
                continue
            if left_observation.get("sales_metric") != right_observation.get("sales_metric"):
                continue
            if left_observation.get("price_normalized") is None or right_observation.get("price_normalized") is None:
                continue
            if (
                left_observation["price_normalized"] == right_observation["price_normalized"]
                and left_observation["sales_value"] == right_observation["sales_value"]
            ):
                return True
    return False


def _images_same(left: dict[str, Any], right: dict[str, Any], budget: _ImageBudget) -> tuple[bool, str]:
    left_identity = str(left.get("image_identity") or "")
    right_identity = str(right.get("image_identity") or "")
    if left_identity and left_identity == right_identity:
        return True, "normalized_url"
    left_url = str(left.get("image_url") or "")
    right_url = str(right.get("image_url") or "")
    if not left_url or not right_url:
        return False, "missing_image"
    left_hash = _image_dhash(left_url, budget)
    right_hash = _image_dhash(right_url, budget)
    if left_hash and right_hash and _hamming_distance(left_hash, right_hash) <= 4:
        return True, "dhash"
    return False, "image_mismatch_or_unavailable"


def _candidate_pairs(profiles: dict[str, dict[str, Any]]) -> list[tuple[str, str, float]]:
    asins = sorted(profiles)
    pairs: list[tuple[str, str, float]] = []
    for index, left_asin in enumerate(asins):
        left = profiles[left_asin]
        for right_asin in asins[index + 1 :]:
            right = profiles[right_asin]
            if not left.get("brand_norm") or left.get("brand_norm") != right.get("brand_norm"):
                continue
            similarity = title_similarity(str(left.get("core_title") or ""), str(right.get("core_title") or ""))
            if similarity >= 0.90 or (
                left.get("model_number")
                and left.get("model_number") == right.get("model_number")
            ) or (
                left.get("image_identity")
                and left.get("image_identity") == right.get("image_identity")
            ):
                pairs.append((left_asin, right_asin, similarity))
    pairs.sort(
        key=lambda item: (
            min(
                _SOURCE_PRIORITY.get(str(profiles[item[0]]["representative"].get("source_tool") or ""), 99),
                _SOURCE_PRIORITY.get(str(profiles[item[1]]["representative"].get("source_tool") or ""), 99),
            ),
            -item[2],
            item[0],
            item[1],
        )
    )
    return pairs


def find_product_identity_enrichment_candidates(
    tool_results: list[dict[str, Any]],
    *,
    marketplace: str,
) -> list[dict[str, Any]]:
    observations = normalize_product_observations(tool_results, marketplace=marketplace)
    details = _detail_records(tool_results)
    profiles = _build_profiles(observations, details)
    scores: dict[str, tuple[float, set[str]]] = {}
    for left_asin, right_asin, similarity in _candidate_pairs(profiles):
        left = profiles[left_asin]
        right = profiles[right_asin]
        reasons: list[str] = []
        score = similarity
        if left.get("model_number") and left.get("model_number") == right.get("model_number"):
            reasons.append("same_model")
            score = max(score, 0.95)
        if left.get("image_identity") and left.get("image_identity") == right.get("image_identity"):
            reasons.append("same_image_url")
            score = max(score, 0.92)
        if similarity >= 0.90 and _same_price_sales(left, right):
            reasons.append("same_title_price_sales")
            score = max(score, 0.75)
        if similarity >= 0.90:
            reasons.append("similar_title_needs_image_or_relation")
        for asin, profile in ((left_asin, left), (right_asin, right)):
            if profile.get("parent_asin") or profile.get("variations") or asin in details:
                continue
            previous_score, previous_reasons = scores.get(asin, (0.0, set()))
            scores[asin] = (max(previous_score, score), previous_reasons | set(reasons))
    concentration_asins = {
        str(observation.get("asin") or "")
        for observation in observations
        if observation.get("source_tool") == "sellersprite_market_product_concentration"
    }
    return [
        {
            "asin": asin,
            "priority": round(score + (0.05 if asin in concentration_asins else 0.0), 4),
            "reasons": sorted(reasons),
        }
        for asin, (score, reasons) in sorted(
            scores.items(),
            key=lambda item: (-(item[1][0] + (0.05 if item[0] in concentration_asins else 0.0)), item[0]),
        )
    ]


def resolve_market_product_identity(
    tool_results: list[dict[str, Any]],
    *,
    marketplace: str,
    category: str = "",
    image_download_budget: int = DEFAULT_IMAGE_DOWNLOAD_BUDGET,
    detail_lookup_asins: list[str] | None = None,
) -> dict[str, Any]:
    observations = normalize_product_observations(tool_results, marketplace=marketplace)
    details = _detail_records(tool_results)
    profiles = _build_profiles(observations, details)
    budget = _ImageBudget(limit=max(0, image_download_budget))
    automatic_detail_lookups = {_asin(item) for item in detail_lookup_asins or [] if _asin(item)}
    detail_budget_exhausted = len(automatic_detail_lookups) >= DEFAULT_ASIN_DETAIL_BUDGET
    if not profiles:
        return {
            "schema_version": PRODUCT_IDENTITY_SCHEMA_VERSION,
            "status": "not_applied",
            "families": [],
            "asin_to_family": {},
            "observations": [],
            "unresolved": [],
            "audit": {
                "applied": False,
                "strategy": "product_identity_v1",
                "raw_row_count": 0,
                "unique_asin_count": 0,
                "family_count": 0,
                "merged_asin_count": 0,
                "rule_counts": {},
                "conflicts": [],
                "image_downloads": 0,
                "image_cache_hits": 0,
                "image_failures": 0,
                "image_budget": budget.limit,
                "image_budget_exhausted": False,
                "detail_lookup_count": len(automatic_detail_lookups),
                "detail_evidence_count": len(details),
                "detail_lookup_budget": DEFAULT_ASIN_DETAIL_BUDGET,
                "detail_lookup_budget_exhausted": detail_budget_exhausted,
            },
        }

    edges: list[dict[str, Any]] = []
    parent_groups: dict[str, set[str]] = defaultdict(set)
    for asin, profile in profiles.items():
        parent = str(profile.get("parent_asin") or "")
        if parent:
            parent_groups[parent].add(asin)
        for variation in profile.get("variations") or []:
            if variation in profiles and variation != asin:
                edges.append(
                    {
                        "left": asin,
                        "right": variation,
                        "rule": "explicit_variation",
                        "confidence": 1.0,
                        "explicit": True,
                        "evidence_ids": profile.get("relationship_evidence_ids") or [],
                    }
                )
    for parent, members in parent_groups.items():
        ordered = sorted(members)
        for member in ordered[1:]:
            edges.append(
                {
                    "left": ordered[0],
                    "right": member,
                    "rule": "shared_parent_asin",
                    "confidence": 1.0,
                    "explicit": True,
                    "parent_asin": parent,
                    "evidence_ids": list(
                        dict.fromkeys(
                            [
                                *profiles[ordered[0]].get("relationship_evidence_ids", []),
                                *profiles[member].get("relationship_evidence_ids", []),
                            ]
                        )
                    ),
                }
            )

    unresolved: list[dict[str, Any]] = []
    for left_asin, right_asin, similarity in _candidate_pairs(profiles):
        left = profiles[left_asin]
        right = profiles[right_asin]
        conflicts = _hard_conflicts(left, right)
        rule = ""
        confidence = 0.0
        evidence: dict[str, Any] = {"title_similarity": similarity}
        if (
            left.get("model_number")
            and left.get("model_number") == right.get("model_number")
            and left.get("pack_count") is not None
            and left.get("pack_count") == right.get("pack_count")
        ):
            rule = "brand_model_pack"
            confidence = 0.95
        elif similarity >= 0.90:
            image_same, image_method = _images_same(left, right, budget)
            evidence["image_method"] = image_method
            if image_same:
                rule = "brand_image_title"
                confidence = 0.92
            elif _same_price_sales(left, right):
                rule = "brand_title_price_sales"
                confidence = 0.75
        if rule:
            edges.append(
                {
                    "left": left_asin,
                    "right": right_asin,
                    "rule": rule,
                    "confidence": confidence,
                    "explicit": False,
                    "pair_conflicts": conflicts,
                    "evidence": evidence,
                }
            )
        elif similarity >= 0.90:
            unresolved_reason = "insufficient_identity_evidence"
            if detail_budget_exhausted and any(
                asin not in details for asin in (left_asin, right_asin)
            ):
                unresolved_reason = "detail_lookup_budget_exhausted"
            if budget.budget_exhausted:
                unresolved_reason = "image_budget_exhausted"
            if conflicts:
                unresolved_reason = "hard_conflict"
            unresolved.append(
                {
                    "asins": [left_asin, right_asin],
                    "reason": unresolved_reason,
                    "conflicts": conflicts,
                    "title_similarity": similarity,
                }
            )

    edges.sort(key=lambda item: (-float(item["confidence"]), item["left"], item["right"]))
    union_find = _UnionFind(sorted(profiles))
    accepted_edges: list[dict[str, Any]] = []
    rejected_edges: list[dict[str, Any]] = []
    for edge in edges:
        left = str(edge["left"])
        right = str(edge["right"])
        if union_find.find(left) == union_find.find(right):
            continue
        if edge.get("explicit"):
            direct_conflicts = _hard_conflicts(profiles[left], profiles[right])
            if direct_conflicts:
                edge = {**edge, "recorded_conflicts": direct_conflicts}
            union_find.union(left, right)
            accepted_edges.append(edge)
            continue
        cluster_conflicts: list[dict[str, Any]] = []
        for left_member in union_find.component(left):
            for right_member in union_find.component(right):
                conflicts = _hard_conflicts(profiles[left_member], profiles[right_member])
                if conflicts:
                    cluster_conflicts.append(
                        {"left": left_member, "right": right_member, "fields": conflicts}
                    )
        if cluster_conflicts:
            rejected_edges.append({**edge, "reason": "cluster_hard_conflict", "conflicts": cluster_conflicts})
            continue
        union_find.union(left, right)
        accepted_edges.append(edge)

    components: dict[str, list[str]] = defaultdict(list)
    for asin in sorted(profiles):
        components[union_find.find(asin)].append(asin)
    unresolved = [
        item
        for item in unresolved
        if len({union_find.find(asin) for asin in item.get("asins") or []}) > 1
    ]

    families: list[dict[str, Any]] = []
    asin_to_family: dict[str, str] = {}
    for members in sorted(components.values(), key=lambda items: min(items)):
        member_set = set(members)
        family_observations = [
            observation
            for member in members
            for observation in profiles[member].get("observations") or []
        ]
        family_observations.sort(key=_profile_sort_key)
        representative = family_observations[0]
        representative_profile = profiles[str(representative["asin"])]
        representative_record = dict(representative)
        representative_record.update(
            {
                "title": representative.get("title") or representative_profile.get("title") or "",
                "brand": representative.get("brand") or representative_profile.get("brand") or "",
                "brand_norm": representative_profile.get("brand_norm") or "",
                "model_number": representative_profile.get("model_number") or "",
                "pack_count": representative_profile.get("pack_count"),
                "pack_form": representative_profile.get("pack_form") or "",
                "core_title": representative_profile.get("core_title") or "",
                "core_attributes": representative_profile.get("core_attributes") or {},
                "image_url": representative.get("image_url") or representative_profile.get("image_url") or "",
                "image_identity": representative_profile.get("image_identity") or "",
            }
        )
        explicit_parents = sorted(
            {
                str(profiles[member].get("parent_asin") or "")
                for member in members
                if profiles[member].get("parent_asin")
            }
        )
        family_id = f"{representative.get('marketplace') or marketplace}:{explicit_parents[0] if len(explicit_parents) == 1 else min(members)}"
        family_edges = [
            edge
            for edge in accepted_edges
            if edge["left"] in member_set and edge["right"] in member_set
        ]
        conflicts = [
            {"left": left, "right": right, "fields": _hard_conflicts(profiles[left], profiles[right])}
            for index, left in enumerate(members)
            for right in members[index + 1 :]
            if _hard_conflicts(profiles[left], profiles[right])
        ]
        conflicts.extend(
            {
                "left": member,
                "right": member,
                "scope": "cross_observation",
                "fields": observation_conflicts,
            }
            for member in members
            if (observation_conflicts := _profile_observation_conflicts(profiles[member]))
        )
        source_tools = list(
            dict.fromkeys(str(item.get("source_tool") or "") for item in family_observations if item.get("source_tool"))
        )
        evidence_ids = list(
            dict.fromkeys(
                [
                    *(str(item.get("evidence_id") or "") for item in family_observations if item.get("evidence_id")),
                    *(
                        str(evidence_id)
                        for edge in family_edges
                        for evidence_id in edge.get("evidence_ids") or []
                        if evidence_id
                    ),
                ]
            )
        )
        confidence = min((float(edge["confidence"]) for edge in family_edges), default=1.0)
        family = {
            "family_id": family_id,
            "family_asin": explicit_parents[0] if len(explicit_parents) == 1 else min(members),
            "parent_asin": explicit_parents[0] if len(explicit_parents) == 1 else None,
            "representative_asin": str(representative["asin"]),
            "member_asins": members,
            "source_tools": source_tools,
            "evidence_ids": evidence_ids,
            "matched_queries": list(
                dict.fromkeys(str(item.get("source_query") or "") for item in family_observations if item.get("source_query"))
            ),
            "match_rules": list(dict.fromkeys(str(edge["rule"]) for edge in family_edges)) or ["exact_asin"],
            "confidence": round(confidence, 2),
            "field_conflicts": conflicts,
            "representative": representative_record,
            "observations": family_observations,
        }
        families.append(family)
        for member in members:
            asin_to_family[member] = family_id

    rule_counts = Counter(str(edge["rule"]) for edge in accepted_edges)
    family_conflict_audits = [
        {
            "family_id": family.get("family_id"),
            "reason": "family_field_conflict",
            "conflicts": family.get("field_conflicts") or [],
        }
        for family in families
        if family.get("field_conflicts")
    ]
    audit = {
        "applied": True,
        "strategy": "product_identity_v1",
        "category": category,
        "raw_row_count": len(observations),
        "unique_asin_count": len(profiles),
        "family_count": len(families),
        "merged_asin_count": len(profiles) - len(families),
        "rule_counts": dict(rule_counts),
        "conflicts": [
            *rejected_edges,
            *(
                {**edge, "reason": "explicit_relationship_conflict"}
                for edge in accepted_edges
                if edge.get("recorded_conflicts")
            ),
            *family_conflict_audits,
        ],
        "detail_lookup_count": len(automatic_detail_lookups),
        "detail_evidence_count": len(details),
        "detail_lookup_budget": DEFAULT_ASIN_DETAIL_BUDGET,
        "detail_lookup_budget_exhausted": detail_budget_exhausted,
        "image_downloads": budget.downloads,
        "image_cache_hits": budget.cache_hits,
        "image_failures": budget.failures,
        "image_budget": budget.limit,
        "image_budget_exhausted": budget.budget_exhausted,
        "unresolved_count": len(unresolved),
    }
    return {
        "schema_version": PRODUCT_IDENTITY_SCHEMA_VERSION,
        "status": "ok",
        "families": families,
        "asin_to_family": asin_to_family,
        "observations": observations,
        "unresolved": unresolved,
        "audit": audit,
    }


def product_family_report_rows(
    resolution: dict[str, Any],
    *,
    require_source_tool: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for family in resolution.get("families") or []:
        if not isinstance(family, dict):
            continue
        observations = [
            item
            for item in family.get("observations") or []
            if isinstance(item, dict)
            and (not require_source_tool or item.get("source_tool") == require_source_tool)
        ]
        if not observations:
            continue
        observations.sort(key=_profile_sort_key)
        family_representative = (
            family.get("representative")
            if isinstance(family.get("representative"), dict)
            else {}
        )
        representative = dict(family_representative if not require_source_tool else observations[0])
        if require_source_tool and representative.get("asin") == family_representative.get("asin"):
            for key in (
                "title",
                "brand",
                "brand_norm",
                "model_number",
                "pack_count",
                "pack_form",
                "core_title",
                "core_attributes",
                "image_url",
                "image_identity",
            ):
                if representative.get(key) in (None, "", [], {}):
                    representative[key] = family_representative.get(key)
        representative.update(
            {
                "asin": family.get("representative_asin")
                if not require_source_tool
                else observations[0].get("asin"),
                "family_id": family.get("family_id"),
                "family_asin": family.get("family_asin"),
                "parent_asin": family.get("parent_asin"),
                "representative_asin": family.get("representative_asin"),
                "member_asins": family.get("member_asins") or [],
                "source_tools": family.get("source_tools") or [],
                "evidence_ids": family.get("evidence_ids") or [],
                "identity_confidence": family.get("confidence"),
                "identity_rules": family.get("match_rules") or [],
                "observations": family.get("observations") or [],
            }
        )
        rows.append(representative)
    rows.sort(key=_profile_sort_key)
    return rows

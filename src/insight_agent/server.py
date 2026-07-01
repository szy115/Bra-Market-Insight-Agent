from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .ingestion.agent_reach import (
    agent_reach_health,
    fetch_reddit_agent_reach,
    reconnect_opencli_extension,
)
from .ingestion.amazon_opencli import amazon_config_from_env, fetch_amazon_opencli
from .llm import (
    LLMUnavailable,
    enhance_amazon_report_with_llm,
    enhance_combined_insight_with_llm,
    enhance_report_with_llm,
)
from .settings import (
    DEFAULT_AMAZON_LLM_PRODUCT_LIMIT,
    DEFAULT_AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT,
    DEFAULT_LLM_COMMENT_SAMPLES_PER_POST,
    DEFAULT_LLM_EVIDENCE_POSTS,
    DEFAULT_REDDIT_USER_AGENT,
    MAX_RESEARCH_POST_LIMIT,
    build_agent_reach_settings_response,
    build_llm_settings_response,
    build_reddit_settings_response,
    build_research_settings_response,
    int_setting,
    read_settings_values,
    sync_runtime_env,
    update_agent_reach_settings,
    update_llm_settings,
    update_reddit_settings,
    update_research_settings,
)

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(os.getenv("INSIGHT_AGENT_HOME", Path.cwd())).resolve()
STATIC_DIR = PACKAGE_DIR / "static"
CACHE_DIR = PROJECT_ROOT / ".cache"
HISTORY_PATH = CACHE_DIR / "research-history.json"
DATA_DIR = PACKAGE_DIR / "data"

CACHE_VERSION = "v4"
ANALYSIS_CACHE_TTL_SECONDS = 60 * 60 * 24

FOCUS_SUBREDDITS = [
    "ABraThatFits",
    "bigboobproblems",
    "PlusSizeFashion",
    "LingerieAddiction",
    "femalefashionadvice",
]

PAIN_TOPICS = {
    "Fit and sizing": [
        "fit",
        "fits",
        "fitting",
        "size",
        "sizing",
        "band",
        "cup",
        "gap",
        "gaping",
        "tight",
        "loose",
        "measurement",
        "measurements",
    ],
    "Support and lift": [
        "support",
        "supportive",
        "lift",
        "lifting",
        "hold",
        "holds",
        "bounce",
        "sag",
        "separate",
        "separation",
        "side support",
    ],
    "Comfort": [
        "comfort",
        "comfortable",
        "uncomfortable",
        "pain",
        "hurt",
        "hurts",
        "dig",
        "digging",
        "itch",
        "rubbing",
        "scratchy",
        "strap",
        "straps",
    ],
    "Wireless tradeoffs": [
        "wireless",
        "underwire",
        "wire",
        "no wire",
        "bralette",
        "uniboob",
        "shape",
        "structured",
    ],
    "Large bust and plus size": [
        "large chest",
        "large bust",
        "big boob",
        "big boobs",
        "full bust",
        "plus size",
        "dd",
        "ddd",
        "g cup",
        "h cup",
        "i cup",
    ],
    "Price and availability": [
        "affordable",
        "cheap",
        "expensive",
        "under $",
        "under 60",
        "budget",
        "find",
        "exist",
        "available",
        "recommend",
        "recommendations",
        "recs",
    ],
    "Material and padding": [
        "foam",
        "padding",
        "padded",
        "removable",
        "lace",
        "cotton",
        "fabric",
        "satin",
        "silk",
        "unlined",
    ],
}

POSITIVE_WORDS = {
    "best",
    "good",
    "great",
    "love",
    "loved",
    "comfortable",
    "supportive",
    "cute",
    "holy grail",
    "works",
    "recommend",
    "helpful",
}

NEGATIVE_WORDS = {
    "crying",
    "failed",
    "cant",
    "can't",
    "frustrated",
    "pain",
    "hurt",
    "hurts",
    "digging",
    "uncomfortable",
    "problem",
    "problems",
    "doesn't exist",
    "not made",
    "struggle",
}

BRANDS = [
    "Aerie",
    "Bali",
    "Bravissimo",
    "Chantelle",
    "Cosabella",
    "Elomi",
    "Evelyn & Bobbie",
    "Freya",
    "Harper Wilde",
    "Honeylove",
    "Knix",
    "Lane Bryant",
    "Maidenform",
    "Natori",
    "Panache",
    "Shapermint",
    "Skims",
    "Soma",
    "ThirdLove",
    "Torrid",
    "True & Co",
    "Uniqlo",
    "Victoria's Secret",
    "Wacoal",
    "Warner's",
]


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "query"


def request_json() -> dict[str, Any]:
    length = int(os.environ.get("CONTENT_LENGTH", "0") or "0")
    if length <= 0:
        return {}
    raw = os.sys.stdin.buffer.read(length)
    return json.loads(raw.decode("utf-8"))


def reddit_user_agent() -> str:
    return os.getenv("REDDIT_USER_AGENT", DEFAULT_REDDIT_USER_AGENT)


def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> bytes:
    final_headers = {"User-Agent": reddit_user_agent()}
    if headers:
        final_headers.update(headers)
    request = urllib.request.Request(url, headers=final_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def cache_key(parts: list[str]) -> Path:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / f"{digest}.json"


def read_cache(path: Path, ttl_seconds: int = 60 * 60 * 6) -> Any | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    created = payload.get("created", 0)
    if time.time() - created > ttl_seconds:
        return None
    return payload.get("data")


def write_cache(path: Path, data: Any) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    path.write_text(
        json.dumps({"created": time.time(), "data": data}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_history_items() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    try:
        payload = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def write_history_items(items: list[dict[str, Any]]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def history_storage_path() -> str:
    try:
        return str(HISTORY_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(HISTORY_PATH)


def history_summary(item: dict[str, Any]) -> dict[str, Any]:
    reddit_report = item.get("reddit_report") if isinstance(item.get("reddit_report"), dict) else None
    amazon_report = item.get("amazon_report") if isinstance(item.get("amazon_report"), dict) else None
    combined_report = item.get("combined_report") if isinstance(item.get("combined_report"), dict) else None
    return {
        "id": item.get("id", ""),
        "category": item.get("category", ""),
        "saved_at": item.get("saved_at", ""),
        "summary": item.get("summary", ""),
        "has_reddit": bool(reddit_report),
        "has_amazon": bool(amazon_report),
        "has_combined": bool(combined_report),
        "reddit_posts": int(((reddit_report or {}).get("coverage") or {}).get("posts") or 0),
        "amazon_products": int(((amazon_report or {}).get("metrics") or {}).get("products") or 0),
        "evidence_items": int(((combined_report or {}).get("data_summary") or {}).get("evidence_items") or 0),
    }


def list_research_history() -> dict[str, Any]:
    items = sorted(read_history_items(), key=lambda item: str(item.get("saved_at", "")), reverse=True)
    return {"items": [history_summary(item) for item in items], "storage_path": history_storage_path()}


def save_research_history(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    reddit_report = payload.get("reddit_report") if isinstance(payload.get("reddit_report"), dict) else None
    amazon_report = payload.get("amazon_report") if isinstance(payload.get("amazon_report"), dict) else None
    combined_report = payload.get("combined_report") if isinstance(payload.get("combined_report"), dict) else None
    if not category:
        category = str(((combined_report or reddit_report or amazon_report or {}).get("category")) or "").strip()
    if not category:
        raise ValueError("category is required")
    if not any((reddit_report, amazon_report, combined_report)):
        raise ValueError("At least one report is required to save history")

    saved_at = now_iso()
    digest = hashlib.sha256(
        json.dumps(
            {
                "category": category,
                "saved_at": saved_at,
                "reddit": bool(reddit_report),
                "amazon": bool(amazon_report),
                "combined": bool(combined_report),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:10]
    summary = ""
    if combined_report:
        summary = str(((combined_report.get("verdict") or {}).get("text")) or "")
    if not summary and reddit_report:
        summary = str(((reddit_report.get("market_signal") or {}).get("summary")) or "")
    if not summary and amazon_report:
        metrics = amazon_report.get("metrics") or {}
        summary = f"{metrics.get('products', 0)} Amazon products collected."

    entry = {
        "id": f"{dt.datetime.now(dt.UTC).strftime('%Y%m%d%H%M%S')}-{digest}",
        "category": category,
        "saved_at": saved_at,
        "summary": compact_text(summary, 280),
        "reddit_report": reddit_report,
        "amazon_report": amazon_report,
        "combined_report": combined_report,
    }
    items = [entry, *read_history_items()]
    write_history_items(items[:100])
    return {"item": history_summary(entry), "storage_path": history_storage_path()}


def get_research_history_item(item_id: str) -> dict[str, Any]:
    for item in read_history_items():
        if item.get("id") == item_id:
            return {"item": item, "storage_path": history_storage_path()}
    raise ValueError("History item not found")


def delete_research_history_item(item_id: str) -> dict[str, Any]:
    items = read_history_items()
    next_items = [item for item in items if item.get("id") != item_id]
    if len(next_items) == len(items):
        raise ValueError("History item not found")
    write_history_items(next_items)
    result = list_research_history()
    result["deleted_id"] = item_id
    return result


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def extract_subreddit(link: str, fallback: str = "") -> str:
    match = re.search(r"/r/([^/]+)/", link, flags=re.I)
    if match:
        return match.group(1)
    return fallback


def parse_reddit_rss(xml_bytes: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_bytes)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    posts: list[dict[str, Any]] = []
    for entry in root.findall("a:entry", ns):
        links = [node.attrib.get("href", "") for node in entry.findall("a:link", ns)]
        link = next((item for item in links if "/comments/" in item), "")
        if not link:
            continue
        title = clean_text(entry.findtext("a:title", namespaces=ns))
        excerpt = clean_text(entry.findtext("a:content", namespaces=ns))
        updated = entry.findtext("a:updated", namespaces=ns) or ""
        subreddit = extract_subreddit(link)
        post_id = link.rstrip("/").split("/")[-2] if "/comments/" in link else link
        posts.append(
            {
                "id": post_id,
                "title": title,
                "excerpt": excerpt[:700],
                "subreddit": subreddit,
                "url": link,
                "created_utc": updated,
                "score": None,
                "comments": None,
                "source": "reddit_rss",
            }
        )
    return posts


def get_reddit_oauth_token() -> tuple[str | None, str | None]:
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None, "REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET are not set."

    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
    request = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=body,
        headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": reddit_user_agent(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - report upstream auth errors to UI.
        return None, f"Reddit OAuth failed: {exc}"
    return payload.get("access_token"), None


def fetch_reddit_oauth(query: str, limit: int, time_range: str) -> tuple[list[dict[str, Any]], list[str]]:
    token, error = get_reddit_oauth_token()
    if not token:
        return [], [error or "Reddit OAuth token was unavailable."]
    params = urllib.parse.urlencode(
        {
            "q": query,
            "limit": min(limit, 50),
            "sort": "relevance",
            "t": time_range,
            "type": "link",
        }
    )
    url = f"https://oauth.reddit.com/search?{params}"
    try:
        body = http_get(url, headers={"Authorization": f"bearer {token}"})
    except Exception as exc:  # noqa: BLE001
        return [], [f"Reddit OAuth search failed: {exc}"]
    payload = json.loads(body.decode("utf-8"))
    posts = []
    for child in payload.get("data", {}).get("children", []):
        data = child.get("data", {})
        permalink = data.get("permalink") or ""
        url = "https://www.reddit.com" + permalink if permalink.startswith("/") else permalink
        created = data.get("created_utc")
        created_iso = ""
        if created:
            created_iso = dt.datetime.fromtimestamp(float(created), dt.UTC).isoformat()
        posts.append(
            {
                "id": data.get("id"),
                "title": data.get("title") or "",
                "excerpt": clean_text(data.get("selftext") or "")[:700],
                "subreddit": data.get("subreddit") or extract_subreddit(url),
                "url": url,
                "created_utc": created_iso,
                "score": data.get("score"),
                "comments": data.get("num_comments"),
                "source": "reddit_oauth",
            }
        )
    return posts, []


def build_reddit_query(category: str) -> str:
    value = category.strip().lower()
    if not re.search(r"\bbra|bras|bralette|lingerie\b", value, flags=re.I):
        value = f"{value} bra"

    terms = [f'"{value}"']
    if "wireless" in value:
        terms.extend(['"wireless bra"', '"wireless bras"', '"wireless bralette"'])
    if "front" in value and ("closure" in value or "close" in value):
        terms.extend(['"front closure bra"', '"front close bra"', '"front clasp bra"'])
    if "senior" in value or "elder" in value or "adaptive" in value:
        terms.extend(['"senior bra"', '"adaptive bra"', '"easy on bra"'])
    if "sports" in value or "sport" in value:
        terms.extend(['"sports bra"', '"sport bra"', '"high support bra"'])
    if "nursing" in value or "maternity" in value or "postpartum" in value:
        terms.extend(['"nursing bra"', '"maternity bra"', '"postpartum bra"'])
    if "large bust" in value or "large chest" in value or "big" in value or "plus" in value:
        terms.extend(
            [
                '"large bust bra"',
                '"large chest bra"',
                '"full bust bra"',
                '"big boob bra"',
                '"plus size bra"',
            ]
        )
    if "strapless" in value:
        terms.extend(['"strapless bra"', '"strapless bras"'])
    if "minimizer" in value:
        terms.extend(['"minimizer bra"', '"minimizer bras"'])

    return " OR ".join(dict.fromkeys(terms[:10]))


def fetch_reddit_rss(
    query: str,
    limit: int,
    time_range: str,
    bypass_cache: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "sort": "relevance",
            "t": time_range,
            "type": "link",
        }
    )
    url = f"https://www.reddit.com/search.rss?{params}"
    cache_path = cache_key([CACHE_VERSION, "rss", query, time_range])
    cached = None if bypass_cache else read_cache(cache_path)
    if cached:
        return cached[:limit], ["Loaded Reddit RSS results from local cache."]

    try:
        body = http_get(url)
        posts = parse_reddit_rss(body)
        write_cache(cache_path, posts)
        return posts[:limit], []
    except urllib.error.HTTPError as exc:
        return [], [f"Reddit RSS returned HTTP {exc.code}: {exc.reason}."]
    except Exception as exc:  # noqa: BLE001
        return [], [f"Reddit RSS failed: {exc}"]


def load_sample_posts() -> list[dict[str, Any]]:
    sample_path = DATA_DIR / "sample_reddit_posts.json"
    return json.loads(sample_path.read_text(encoding="utf-8"))


def dedupe_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for post in posts:
        key = post.get("url") or post.get("id") or post.get("title")
        if key in seen:
            continue
        seen.add(key)
        result.append(post)
    return result


def collect_reddit(
    category: str,
    limit: int,
    time_range: str,
    mode: str,
    bypass_cache: bool = False,
) -> tuple[list[dict[str, Any]], list[str], str]:
    query = build_reddit_query(category)
    cache_path = cache_key(
        [
            CACHE_VERSION,
            "analysis",
            query,
            str(limit),
            time_range,
            mode,
            os.getenv("AGENT_REACH_DETAIL_LIMIT", ""),
            os.getenv("AGENT_REACH_COMMENTS_PER_POST", ""),
        ]
    )
    warnings: list[str] = []
    cached = None if bypass_cache else read_cache(cache_path, ttl_seconds=ANALYSIS_CACHE_TTL_SECONDS)
    if bypass_cache:
        warnings.append("Bypassed local cache for this run.")
    if cached:
        cached_posts = cached["posts"]
        cached_mode = cached["mode"]
        wants_comment_bodies = (
            int_setting(read_settings_values(), "AGENT_REACH_DETAIL_LIMIT", 8, 0, 100) > 0
            and int_setting(read_settings_values(), "AGENT_REACH_COMMENTS_PER_POST", 20, 0, 200) > 0
        )
        cached_missing_comment_bodies = (
            cached_mode == "agent_reach"
            and bool(cached_posts)
            and sum(len(post_comment_items(post)) for post in cached_posts) == 0
        )
        if cached_missing_comment_bodies and wants_comment_bodies and agent_reach_health().get("ready"):
            warnings.append(
                "Skipped cached Agent Reach results because they had posts but no comment bodies."
            )
        else:
            return cached_posts, ["Loaded analyzed input from local cache."], cached_mode

    posts: list[dict[str, Any]] = []
    source_mode = mode if mode in {"agent_reach", "oauth", "rss"} else "sample"

    if mode == "sample":
        posts = load_sample_posts()
        warnings.append("Using built-in sample data by request.")
        write_cache(cache_path, {"posts": posts[:limit], "mode": source_mode})
        return posts[:limit], warnings, source_mode

    if mode in {"auto", "agent_reach"}:
        agent_reach_result = fetch_reddit_agent_reach(query, limit, time_range)
        warnings.extend(agent_reach_result.warnings)
        if agent_reach_result.items:
            posts = [item.to_legacy_post() for item in agent_reach_result.items]
            source_mode = "agent_reach"

    if not posts and mode in {"auto", "oauth"}:
        oauth_posts, oauth_warnings = fetch_reddit_oauth(query, limit, time_range)
        warnings.extend(oauth_warnings)
        if oauth_posts:
            posts = oauth_posts
            source_mode = "oauth"

    if not posts and mode in {"auto", "rss"}:
        rss_posts, rss_warnings = fetch_reddit_rss(query, limit, time_range, bypass_cache=bypass_cache)
        warnings.extend(rss_warnings)
        if rss_posts:
            posts = rss_posts
            source_mode = "rss"

    if not posts and mode == "auto":
        posts = load_sample_posts()
        source_mode = "sample"
        warnings.append("Using built-in sample data because live Reddit access was unavailable.")

    if not posts:
        warnings.append(
            f"No Reddit posts were collected with {mode}. Not falling back because the source mode is explicit."
        )
        return [], warnings, source_mode

    posts = dedupe_posts(posts)[:limit]
    write_cache(cache_path, {"posts": posts, "mode": source_mode})
    return posts, warnings, source_mode


def parse_date(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def add_months(value: dt.date, offset: int) -> dt.date:
    month_index = value.year * 12 + value.month - 1 + offset
    return dt.date(month_index // 12, month_index % 12 + 1, 1)


def parse_month(value: str) -> dt.date | None:
    try:
        year, month = value.split("-", 1)
        return dt.date(int(year), int(month), 1)
    except (ValueError, TypeError):
        return None


def build_trend_series(month_counts: Counter[str], minimum_months: int = 6) -> list[dict[str, int | str]]:
    valid_months = [month for month in (parse_month(item) for item in month_counts) if month]
    if not valid_months:
        return []
    start = min(valid_months)
    end = max(valid_months)
    while (end.year - start.year) * 12 + (end.month - start.month) + 1 < minimum_months:
        start = add_months(start, -1)
    trend = []
    current = start
    while current <= end:
        label = current.strftime("%Y-%m")
        trend.append({"month": label, "count": month_counts.get(label, 0)})
        current = add_months(current, 1)
    return trend


def score_sentiment(text: str) -> str:
    lowered = text.lower()
    positive = sum(1 for word in POSITIVE_WORDS if word in lowered)
    negative = sum(1 for word in NEGATIVE_WORDS if word in lowered)
    if negative > positive:
        return "negative"
    if positive > negative:
        return "positive"
    return "neutral"


def matching_topics(text: str) -> list[str]:
    lowered = text.lower()
    matched = []
    for topic, keywords in PAIN_TOPICS.items():
        if any(keyword in lowered for keyword in keywords):
            matched.append(topic)
    return matched


def extract_brands(text: str) -> list[str]:
    found = []
    for brand in BRANDS:
        if re.search(rf"\b{re.escape(brand)}\b", text, flags=re.I):
            found.append(brand)
    return found


def extract_sizes(text: str) -> list[str]:
    patterns = [
        r"\b(?:2[8-9]|3[0-9]|4[0-9]|5[0-6])\s?[A-K]{1,3}\b",
        r"\b[A-K]{1,3}\s?cup\b",
        r"\bplus size\b",
        r"\blarge bust\b",
        r"\bfull bust\b",
    ]
    sizes: list[str] = []
    for pattern in patterns:
        sizes.extend(re.findall(pattern, text, flags=re.I))
    return [item.upper().replace(" CUP", " cup") for item in sizes]


def make_snippet(post: dict[str, Any], max_length: int = 180) -> str:
    text = clean_text(f"{post.get('title', '')}. {post.get('excerpt', '')}")
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "..."


def post_comment_items(post: dict[str, Any]) -> list[dict[str, Any]]:
    comments = post.get("comment_items", [])
    if not isinstance(comments, list):
        return []
    return [
        comment
        for comment in comments
        if isinstance(comment, dict) and str(comment.get("text", "")).strip()
    ]


def build_data_volume_stats(
    requested_posts: int,
    posts: list[dict[str, Any]],
    source_mode: str,
    llm_requested: bool,
) -> dict[str, Any]:
    values = read_settings_values()
    detail_limit = int_setting(values, "AGENT_REACH_DETAIL_LIMIT", 8, 0, 100)
    comments_per_post_limit = int_setting(values, "AGENT_REACH_COMMENTS_PER_POST", 20, 0, 200)
    ai_evidence_post_limit = int_setting(
        values,
        "INSIGHT_LLM_EVIDENCE_POSTS",
        DEFAULT_LLM_EVIDENCE_POSTS,
        1,
        100,
    )
    ai_comment_sample_limit = int_setting(
        values,
        "INSIGHT_LLM_COMMENT_SAMPLES_PER_POST",
        DEFAULT_LLM_COMMENT_SAMPLES_PER_POST,
        0,
        50,
    )
    collected_comments = sum(len(post_comment_items(post)) for post in posts)
    posts_with_comments = sum(1 for post in posts if post_comment_items(post))
    ai_posts = posts[:ai_evidence_post_limit] if llm_requested else []
    ai_comment_samples = sum(
        len(post_comment_items(post)[:ai_comment_sample_limit])
        for post in ai_posts
    )
    return {
        "requested_posts": requested_posts,
        "collected_posts": len(posts),
        "source_mode": source_mode,
        "comment_enrichment_post_limit": detail_limit,
        "comments_per_enriched_post_limit": comments_per_post_limit,
        "posts_with_collected_comments": posts_with_comments,
        "collected_comments": collected_comments,
        "llm_requested": llm_requested,
        "ai_evidence_post_limit": ai_evidence_post_limit,
        "ai_evidence_posts": len(ai_posts),
        "ai_comment_samples_per_post_limit": ai_comment_sample_limit,
        "ai_comment_samples": ai_comment_samples,
    }


def summarize_posts(category: str, posts: list[dict[str, Any]], source_mode: str, warnings: list[str]) -> dict[str, Any]:
    subreddit_counts = Counter(post.get("subreddit") or "unknown" for post in posts)
    sentiment_counts = Counter()
    topic_counts = Counter()
    topic_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    brand_counts = Counter()
    size_counts = Counter()
    month_counts = Counter()

    for post in posts:
        text = f"{post.get('title', '')} {post.get('excerpt', '')}"
        sentiment_counts[score_sentiment(text)] += 1
        for topic in matching_topics(text):
            topic_counts[topic] += 1
            if len(topic_examples[topic]) < 3:
                topic_examples[topic].append(
                    {
                        "title": post.get("title"),
                        "subreddit": post.get("subreddit"),
                        "url": post.get("url"),
                        "snippet": make_snippet(post),
                    }
                )
        brand_counts.update(extract_brands(text))
        size_counts.update(extract_sizes(text))
        created = parse_date(post.get("created_utc"))
        if created:
            month_counts[created.strftime("%Y-%m")] += 1

    total = max(len(posts), 1)
    negative_share = round(sentiment_counts["negative"] / total, 2)
    positive_share = round(sentiment_counts["positive"] / total, 2)
    top_topics = []
    for topic, count in topic_counts.most_common(7):
        top_topics.append(
            {
                "topic": topic,
                "count": count,
                "share": round(count / total, 2),
                "examples": topic_examples[topic],
            }
        )

    market_signal_score = min(
        100,
        round(
            20
            + min(len(posts), 40) * 1.2
            + min(len(subreddit_counts), 8) * 3
            + min(sum(1 for item in topic_counts.values() if item > 0), 8) * 2
        ),
    )
    confidence = "Medium" if source_mode in {"agent_reach", "oauth", "rss"} and len(posts) >= 15 else "Low"
    if source_mode == "sample":
        confidence = "Demo only"

    opportunities = generate_opportunities(top_topics, brand_counts, size_counts)

    return {
        "category": category,
        "generated_at": now_iso(),
        "source_mode": source_mode,
        "warnings": warnings,
        "coverage": {
            "posts": len(posts),
            "subreddits": len(subreddit_counts),
            "top_subreddits": [
                {"name": name, "count": count} for name, count in subreddit_counts.most_common(8)
            ],
            "confidence": confidence,
        },
        "market_signal": {
            "score": market_signal_score,
            "summary": make_market_summary(category, posts, subreddit_counts, topic_counts, confidence),
        },
        "sentiment": {
            "positive": sentiment_counts["positive"],
            "neutral": sentiment_counts["neutral"],
            "negative": sentiment_counts["negative"],
            "positive_share": positive_share,
            "negative_share": negative_share,
        },
        "pain_points": top_topics,
        "brands": [{"name": name, "count": count} for name, count in brand_counts.most_common(10)],
        "sizes": [{"name": name, "count": count} for name, count in size_counts.most_common(10)],
        "trend": build_trend_series(month_counts),
        "opportunities": opportunities,
        "posts": posts,
        "method": {
            "query": build_reddit_query(category),
            "notes": [
                "This MVP analyzes Reddit post titles, snippets/selftext, and comments when Agent Reach detail enrichment is available.",
                "Agent Reach collection depends on local OpenCLI/rdt login state and should be used conservatively with caching and rate limits.",
                "Use OAuth credentials for more stable live access and richer metadata.",
                "Treat all scores as directional signals, not market-size measurements.",
            ],
        },
    }


def make_market_summary(
    category: str,
    posts: list[dict[str, Any]],
    subreddit_counts: Counter,
    topic_counts: Counter,
    confidence: str,
) -> str:
    if not posts:
        return f"No Reddit signal was found for {category}."
    top_subreddit = subreddit_counts.most_common(1)[0][0]
    top_topic = topic_counts.most_common(1)[0][0] if topic_counts else "general recommendations"
    return (
        f"Reddit has directional discussion around '{category}', concentrated in r/{top_subreddit}. "
        f"The strongest repeated theme is {top_topic.lower()}. Confidence is {confidence.lower()} "
        "because this demo only uses Reddit-visible posts/snippets."
    )


def generate_opportunities(
    top_topics: list[dict[str, Any]],
    brand_counts: Counter,
    size_counts: Counter,
) -> list[dict[str, str]]:
    topic_names = [item["topic"] for item in top_topics[:4]]
    opportunities: list[dict[str, str]] = []
    if "Support and lift" in topic_names and "Wireless tradeoffs" in topic_names:
        opportunities.append(
            {
                "title": "Position wireless support as a proof point",
                "detail": "Users repeatedly ask whether wireless styles can lift, separate, and avoid uniboob. A demo should compare support, side coverage, and shape directly.",
            }
        )
    if "Fit and sizing" in topic_names:
        opportunities.append(
            {
                "title": "Make fit guidance part of the product, not just the size chart",
                "detail": "Fit uncertainty appears as a decision blocker. Add calculator copy, exchange guidance, and fit photos by cup/band range.",
            }
        )
    if "Comfort" in topic_names:
        opportunities.append(
            {
                "title": "Treat comfort claims as testable details",
                "detail": "Strap digging, rubbing, and pressure language suggest buyers need material, strap width, and all-day wear evidence.",
            }
        )
    if "Price and availability" in topic_names:
        opportunities.append(
            {
                "title": "Own a clear price-performance lane",
                "detail": "Recommendation posts often include budget constraints, so price anchors and comparison tables may reduce purchase friction.",
            }
        )
    if size_counts:
        top_size = size_counts.most_common(1)[0][0]
        opportunities.append(
            {
                "title": f"Audit coverage for {top_size}",
                "detail": "Detected size language can guide which fit models, reviews, and variants should be visible first.",
            }
        )
    if brand_counts:
        top_brand = brand_counts.most_common(1)[0][0]
        opportunities.append(
            {
                "title": f"Benchmark against {top_brand}",
                "detail": "Mentioned brands are useful anchors for feature, price, review-count, and messaging comparisons in the next MVP phase.",
            }
        )
    if not opportunities:
        opportunities.append(
            {
                "title": "Use Reddit language to shape the next research query",
                "detail": "The current sample is thin. Expand with adjacent phrases, size ranges, and use cases before making a product decision.",
            }
        )
    return opportunities[:5]


def collect_amazon(
    category: str,
    limit: int,
    keyword_limit: int,
    bypass_cache: bool = False,
) -> tuple[list[dict[str, Any]], list[str], str, list[str], dict[str, int]]:
    cache_path = cache_key(
        [
            CACHE_VERSION,
            "amazon",
            category,
            str(limit),
            str(keyword_limit),
            os.getenv("AMAZON_DETAIL_LIMIT", ""),
            os.getenv("AMAZON_DISCUSSION_LIMIT", ""),
            os.getenv("AMAZON_REVIEWS_PER_PRODUCT", ""),
        ]
    )
    cached = read_cache(cache_path, ttl_seconds=ANALYSIS_CACHE_TTL_SECONDS)
    if cached and not bypass_cache:
        return (
            cached["products"],
            ["Loaded Amazon input from local cache."],
            cached["mode"],
            cached.get("queries") or [category],
            cached.get("per_query_counts") or {},
        )

    result = fetch_amazon_opencli(category, limit, keyword_limit=keyword_limit, bypass_cache=bypass_cache)
    products = result.products
    queries = result.queries or [category]
    per_query_counts = result.per_query_counts or {queries[0]: len(products)}
    warnings = list(result.warnings)
    if bypass_cache:
        warnings.append("Bypassed local cache for Amazon analysis.")
    write_cache(
        cache_path,
        {
            "products": products,
            "mode": result.source_mode,
            "queries": queries,
            "per_query_counts": per_query_counts,
        },
    )
    return products, warnings, result.source_mode, queries, per_query_counts


def summarize_amazon(
    category: str,
    products: list[dict[str, Any]],
    source_mode: str,
    warnings: list[str],
    queries: list[str],
) -> dict[str, Any]:
    brand_counts = Counter(product.get("brand") or brand_from_title(str(product.get("title") or "")) for product in products)
    brand_counts.pop("", None)
    prices = [float(product["price_value"]) for product in products if isinstance(product.get("price_value"), int | float)]
    ratings = [
        float(product["rating_value"]) for product in products if isinstance(product.get("rating_value"), int | float)
    ]
    review_counts = [
        int(product["review_count"]) for product in products if isinstance(product.get("review_count"), int | float)
    ]
    sponsored_count = sum(1 for product in products if product.get("is_sponsored"))
    review_sample_count = sum(len(product.get("review_samples") or []) for product in products)
    products_with_reviews = sum(1 for product in products if product.get("review_samples"))
    price_bands = build_price_bands(prices)
    confidence = "Medium" if len(products) >= 10 else "Low"
    if not products:
        confidence = "Low"
    metrics = {
        "products": len(products),
        "products_with_price": len(prices),
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
        "price_avg": round(sum(prices) / len(prices), 2) if prices else None,
        "products_with_rating": len(ratings),
        "rating_avg": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "total_review_count": sum(review_counts),
        "products_with_review_count": len(review_counts),
        "sponsored_count": sponsored_count,
        "review_samples": review_sample_count,
        "products_with_review_samples": products_with_reviews,
    }
    return {
        "category": category,
        "query": category,
        "queries": queries,
        "generated_at": now_iso(),
        "source_mode": source_mode,
        "warnings": warnings,
        "confidence": confidence,
        "metrics": metrics,
        "brands": [{"name": name, "count": count} for name, count in brand_counts.most_common(12)],
        "price_bands": price_bands,
        "products": products,
        "method": {
            "query": category,
            "notes": [
                "This MVP uses OpenCLI Amazon search/product/discussion surfaces through a browser-backed provider.",
                f"Amazon search expanded across {len(queries)} keyword variants; products are deduplicated by ASIN or product URL.",
                "Amazon true unit sales are not public; review count, search rank, badges, and discussion samples are directional signals only.",
                "Use third-party Amazon data providers or seller-owned reports for stable sales estimates and historical BSR.",
            ],
        },
    }


def build_amazon_data_volume(
    requested_products_per_query: int,
    products: list[dict[str, Any]],
    source_mode: str,
    llm_requested: bool,
    queries: list[str],
    per_query_counts: dict[str, int],
) -> dict[str, Any]:
    config = amazon_config_from_env()
    values = read_settings_values()
    ai_product_limit = int_setting(
        values,
        "AMAZON_LLM_PRODUCT_LIMIT",
        DEFAULT_AMAZON_LLM_PRODUCT_LIMIT,
        1,
        100,
    )
    ai_review_samples_per_product = int_setting(
        values,
        "AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT",
        DEFAULT_AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT,
        0,
        50,
    )
    collected_review_samples = sum(len(product.get("review_samples") or []) for product in products)
    products_with_review_samples = sum(1 for product in products if product.get("review_samples"))
    ai_products = products[:ai_product_limit] if llm_requested else []
    ai_review_samples = sum(
        len((product.get("review_samples") or [])[:ai_review_samples_per_product]) for product in ai_products
    )
    per_query = [{"query": query, "count": per_query_counts.get(query, 0)} for query in queries]
    raw_collected_products = sum(item["count"] for item in per_query)
    return {
        "requested_products": requested_products_per_query * max(1, len(queries)),
        "requested_products_per_query": requested_products_per_query,
        "query_count": len(queries),
        "queries": queries,
        "per_query_counts": per_query,
        "raw_collected_products": raw_collected_products,
        "collected_products": len(products),
        "unique_products": len(products),
        "source_mode": source_mode,
        "detail_product_limit": max(0, min(config.detail_limit, len(products))),
        "discussion_product_limit": max(0, min(config.discussion_limit, len(products))),
        "products_with_review_samples": products_with_review_samples,
        "collected_review_samples": collected_review_samples,
        "llm_requested": llm_requested,
        "ai_product_limit": ai_product_limit,
        "ai_products": len(ai_products),
        "ai_review_samples_per_product_limit": ai_review_samples_per_product,
        "ai_review_samples": ai_review_samples,
    }


def build_price_bands(prices: list[float]) -> list[dict[str, Any]]:
    bands = [
        ("<$20", lambda price: price < 20),
        ("$20-$29", lambda price: 20 <= price < 30),
        ("$30-$49", lambda price: 30 <= price < 50),
        ("$50+", lambda price: price >= 50),
    ]
    return [{"name": name, "count": sum(1 for price in prices if predicate(price))} for name, predicate in bands]


def brand_from_title(title: str) -> str:
    words = title.split()
    return words[0] if words else ""


def analyze_amazon_category(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    if not category:
        raise ValueError("category is required")
    limit = int(payload.get("limit") or os.getenv("AMAZON_PRODUCT_LIMIT", "20") or 20)
    limit = max(1, min(limit, 100))
    keyword_limit = int(payload.get("amazonKeywordLimit") or os.getenv("AMAZON_KEYWORD_LIMIT", "8") or 8)
    keyword_limit = max(1, min(keyword_limit, 20))
    bypass_cache = bool(payload.get("bypassCache"))
    use_llm = payload.get("useLlm", True) is not False
    products, warnings, source_mode, queries, per_query_counts = collect_amazon(
        category,
        limit,
        keyword_limit,
        bypass_cache=bypass_cache,
    )
    result = summarize_amazon(category, products, source_mode, warnings, queries)
    result["data_volume"] = build_amazon_data_volume(
        limit,
        products,
        source_mode,
        use_llm,
        queries,
        per_query_counts,
    )
    result["llm_analysis"] = {
        "enabled": False,
        "status": "not_requested",
        "message": "Enable AI synthesis to call the configured LLM provider.",
    }
    if use_llm:
        try:
            enhanced = enhance_amazon_report_with_llm(result)
            result["llm_analysis"] = {
                "enabled": True,
                "status": "ok",
                **enhanced,
            }
        except LLMUnavailable as exc:
            result["llm_analysis"] = {
                "enabled": True,
                "status": "unavailable",
                "message": str(exc),
            }
            result["warnings"].append(str(exc))
    return result


def analyze_combined_insight(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    reddit_report = payload.get("reddit_report") or payload.get("redditReport") or None
    amazon_report = payload.get("amazon_report") or payload.get("amazonReport") or None
    if not category:
        category = str((reddit_report or amazon_report or {}).get("category") or "").strip()
    if not category:
        raise ValueError("category is required")
    if not reddit_report and not amazon_report:
        raise ValueError("At least one Reddit or Amazon report is required")

    evidence_pool = build_combined_evidence_pool(reddit_report, amazon_report)
    if not evidence_pool:
        raise ValueError("No citable Reddit or Amazon evidence is available")

    context = build_combined_context(category, reddit_report, amazon_report, evidence_pool)
    use_llm = payload.get("useLlm", True) is not False
    locale = str(payload.get("locale") or "zh")
    warnings: list[str] = []
    llm_analysis = {
        "enabled": False,
        "status": "not_requested",
        "message": "AI synthesis was not requested; generated a rule-based integrated view.",
    }
    raw: dict[str, Any] | None = None
    if use_llm:
        try:
            enhanced = enhance_combined_insight_with_llm(context, locale=locale)
            raw = enhanced.get("result") if isinstance(enhanced.get("result"), dict) else {}
            llm_analysis = {
                "enabled": True,
                "status": "ok",
                "provider": enhanced.get("provider"),
                "model": enhanced.get("model"),
                "usage": enhanced.get("usage") or {},
            }
        except LLMUnavailable as exc:
            warnings.append(str(exc))
            llm_analysis = {
                "enabled": True,
                "status": "unavailable",
                "message": str(exc),
            }

    if not raw:
        raw = build_fallback_combined_raw(category, reddit_report, amazon_report, evidence_pool)

    result = normalize_combined_insight(category, raw, evidence_pool)
    result.update(
        {
            "category": category,
            "generated_at": now_iso(),
            "warnings": warnings,
            "data_summary": {
                "reddit_posts": int(((reddit_report or {}).get("coverage") or {}).get("posts") or 0),
                "reddit_comments": int(((reddit_report or {}).get("data_volume") or {}).get("collected_comments") or 0),
                "amazon_products": int(((amazon_report or {}).get("metrics") or {}).get("products") or 0),
                "amazon_review_samples": int(((amazon_report or {}).get("metrics") or {}).get("review_samples") or 0),
                "evidence_items": len(evidence_pool),
            },
            "llm_analysis": llm_analysis,
        }
    )
    return result


def build_combined_context(
    category: str,
    reddit_report: dict[str, Any] | None,
    amazon_report: dict[str, Any] | None,
    evidence_pool: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "category": category,
        "reddit": {
            "coverage": (reddit_report or {}).get("coverage"),
            "data_volume": (reddit_report or {}).get("data_volume"),
            "market_signal": (reddit_report or {}).get("market_signal"),
            "sentiment": (reddit_report or {}).get("sentiment"),
            "pain_points": (reddit_report or {}).get("pain_points", [])[:8],
            "brands": (reddit_report or {}).get("brands", [])[:8],
            "sizes": (reddit_report or {}).get("sizes", [])[:8],
            "trend": (reddit_report or {}).get("trend", [])[-12:],
        },
        "amazon": {
            "metrics": (amazon_report or {}).get("metrics"),
            "data_volume": (amazon_report or {}).get("data_volume"),
            "brands": (amazon_report or {}).get("brands", [])[:12],
            "price_bands": (amazon_report or {}).get("price_bands", []),
            "queries": (amazon_report or {}).get("queries", []),
        },
        "evidence_pool": [
            {
                "id": item["id"],
                "source": item["source"],
                "kind": item["kind"],
                "title": item["title"],
                "url": item["url"],
                "excerpt": item["excerpt"],
                "reference": item["reference"],
            }
            for item in evidence_pool
        ],
    }


def build_combined_evidence_pool(
    reddit_report: dict[str, Any] | None,
    amazon_report: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for index, post in enumerate((reddit_report or {}).get("posts", [])[:30], start=1):
        url = str(post.get("url") or "")
        if not url:
            continue
        title = str(post.get("title") or f"Reddit post {index}")
        subreddit = str(post.get("subreddit") or "unknown")
        evidence.append(
            {
                "id": f"R{index}",
                "source": "reddit",
                "kind": "post",
                "title": title,
                "url": url,
                "excerpt": compact_text(str(post.get("excerpt") or ""), 520),
                "reference": f"Reddit r/{subreddit}",
            }
        )
        comments = post.get("comment_items") if isinstance(post.get("comment_items"), list) else []
        for comment_index, comment in enumerate(comments[:2], start=1):
            text = compact_text(str(comment.get("text") or ""), 420)
            if not text:
                continue
            evidence.append(
                {
                    "id": f"R{index}C{comment_index}",
                    "source": "reddit",
                    "kind": "comment",
                    "title": f"Comment on {title}",
                    "url": str(comment.get("url") or url),
                    "excerpt": text,
                    "reference": f"Reddit comment r/{subreddit}",
                }
            )

    for index, product in enumerate((amazon_report or {}).get("products", [])[:35], start=1):
        url = str(product.get("product_url") or "")
        if not url:
            continue
        title = str(product.get("title") or product.get("asin") or f"Amazon product {index}")
        reference_bits = [
            str(product.get("brand") or "").strip(),
            str(product.get("price_text") or "").strip(),
            f"{product.get('rating_value')} stars" if product.get("rating_value") else "",
            f"{product.get('review_count')} reviews" if product.get("review_count") else "",
        ]
        reference = " · ".join(bit for bit in reference_bits if bit) or "Amazon product"
        bullets = product.get("bullet_points") if isinstance(product.get("bullet_points"), list) else []
        excerpt = " ".join(str(point) for point in bullets[:3]) or reference
        evidence.append(
            {
                "id": f"A{index}",
                "source": "amazon",
                "kind": "product",
                "title": title,
                "url": url,
                "excerpt": compact_text(excerpt, 520),
                "reference": reference,
            }
        )
        reviews = product.get("review_samples") if isinstance(product.get("review_samples"), list) else []
        for review_index, review in enumerate(reviews[:2], start=1):
            body = compact_text(
                f"{review.get('title') or ''}: {review.get('body') or ''}".strip(": "),
                420,
            )
            if not body:
                continue
            evidence.append(
                {
                    "id": f"A{index}R{review_index}",
                    "source": "amazon",
                    "kind": "review",
                    "title": f"Review for {title}",
                    "url": amazon_review_url(review, url),
                    "excerpt": body,
                    "reference": f"Amazon review · {review.get('rating_value') or '-'} stars",
                }
            )
    return evidence


def amazon_review_url(review: dict[str, Any], product_url: str) -> str:
    review_url = str(review.get("url") or review.get("review_url") or "").strip()
    if review_url:
        return absolutize_amazon_url(review_url)
    review_id = str(review.get("id") or review.get("review_id") or "").strip()
    if review_id:
        return f"https://www.amazon.com/gp/customer-reviews/{urllib.parse.quote(review_id)}"
    base = product_url.split("#", 1)[0]
    return f"{base}#customerReviews" if base else product_url


def absolutize_amazon_url(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return f"https://www.amazon.com{url}"
    return url


def compact_text(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def build_fallback_combined_raw(
    category: str,
    reddit_report: dict[str, Any] | None,
    amazon_report: dict[str, Any] | None,
    evidence_pool: list[dict[str, Any]],
) -> dict[str, Any]:
    top_pain = ((reddit_report or {}).get("pain_points") or [{}])[0].get("topic") or "fit and comfort signals"
    amazon_metrics = (amazon_report or {}).get("metrics") or {}
    price_avg = amazon_metrics.get("price_avg")
    review_total = amazon_metrics.get("total_review_count") or 0
    default_ids = [item["id"] for item in evidence_pool[:3]]
    reddit_ids = [item["id"] for item in evidence_pool if item["source"] == "reddit"][:2] or default_ids[:1]
    amazon_ids = [item["id"] for item in evidence_pool if item["source"] == "amazon"][:2] or default_ids[:1]
    mixed_ids = unique_ids([*(reddit_ids[:1]), *(amazon_ids[:1])]) or default_ids[:1]
    return {
        "verdict": {
            "text": f"{category} has usable demand signals, but the current decision should be treated as evidence-led and directional rather than a market-size estimate.",
            "citation_ids": mixed_ids,
        },
        "opportunities": [
            {
                "title": "把 Reddit 高频痛点转成商品 claim",
                "detail": f"Reddit discussion clusters around {top_pain}; use that language to shape feature claims and test-copy.",
                "citation_ids": reddit_ids or mixed_ids,
            },
            {
                "title": "用 Amazon 货架验证价格与卖点表达",
                "detail": f"Collected Amazon shelf signals include average price {price_avg or 'unknown'} and {review_total} review/rating signals.",
                "citation_ids": amazon_ids or mixed_ids,
            },
            {
                "title": "用评论样本寻找可被研发解决的小缺口",
                "detail": "Amazon review samples and Reddit comments can be paired to identify claim gaps that competitors have not explained clearly.",
                "citation_ids": mixed_ids,
            },
        ],
        "risks": [
            {
                "title": "不能把 review count 等同销量",
                "detail": "Amazon review/rating signals are historical validation proxies, not true sales volume.",
                "citation_ids": amazon_ids or mixed_ids,
            },
            {
                "title": "社媒样本可能放大痛点人群",
                "detail": "Reddit evidence is useful for language and pain points, but it is not representative of the whole US market.",
                "citation_ids": reddit_ids or mixed_ids,
            },
            {
                "title": "跨平台证据仍缺少时间序列",
                "detail": "Current MVP compares one collection run, so it cannot yet prove week-over-week demand movement.",
                "citation_ids": mixed_ids,
            },
        ],
        "rd_recommendations": [
            {
                "title": "先做痛点-结构映射",
                "detail": "Translate fit, support, smoothing, and comfort language into measurable construction requirements.",
                "citation_ids": mixed_ids,
            },
            {
                "title": "建立竞品 claim checklist",
                "detail": "For each top Amazon product, compare bullet claims, review complaints, and visible construction choices.",
                "citation_ids": amazon_ids or mixed_ids,
            },
            {
                "title": "用真实评论补充试穿假设",
                "detail": "Prioritize prototypes around complaints that appear in both Reddit discussion and Amazon reviews.",
                "citation_ids": mixed_ids,
            },
        ],
        "brand_communication": [
            {
                "title": "用用户原话表达利益点",
                "detail": "Copy should mirror the shopper's own discomfort and outcome language before introducing technical features.",
                "citation_ids": reddit_ids or mixed_ids,
            },
            {
                "title": "公开解释差异化证据",
                "detail": "Position against Amazon shelf claims with visible proof points such as construction, fit range, and review-backed use cases.",
                "citation_ids": amazon_ids or mixed_ids,
            },
            {
                "title": "避免没有证据的规模化表述",
                "detail": "Until sales and longitudinal data are added, market communication should avoid claiming category growth or market size.",
                "citation_ids": mixed_ids,
            },
        ],
        "evidence_chain": [
            {"claim": item["title"], "detail": item["excerpt"], "citation_ids": [item["id"]]}
            for item in evidence_pool[:6]
        ],
        "data_gaps": [
            {
                "title": "真实销量与 BSR 历史",
                "detail": "Need third-party Amazon estimates, seller data, or BSR history to size the shelf and detect weekly change.",
                "citation_ids": amazon_ids or mixed_ids,
            },
            {
                "title": "用户画像缺口",
                "detail": "Need survey, panel, or owned customer data to move beyond platform-specific discussion language.",
                "citation_ids": reddit_ids or mixed_ids,
            },
            {
                "title": "跨周趋势缺口",
                "detail": "Need repeated snapshots before using this tool for week-over-week market movement.",
                "citation_ids": mixed_ids,
            },
        ],
    }


def normalize_combined_insight(
    category: str,
    raw: dict[str, Any],
    evidence_pool: list[dict[str, Any]],
) -> dict[str, Any]:
    fallback_ids = [item["id"] for item in evidence_pool[:2]]
    verdict_raw = raw.get("verdict") if isinstance(raw.get("verdict"), dict) else {}
    verdict = {
        "text": str(verdict_raw.get("text") or f"{category} has directional evidence, but needs stronger sales and trend data."),
        "citations": resolve_citations(verdict_raw.get("citation_ids"), evidence_pool, fallback_ids),
    }
    return {
        "verdict": verdict,
        "opportunities": normalize_insight_items(raw.get("opportunities"), 3, evidence_pool, fallback_ids, "机会"),
        "risks": normalize_insight_items(raw.get("risks"), 3, evidence_pool, fallback_ids, "风险"),
        "rd_recommendations": normalize_insight_items(
            raw.get("rd_recommendations"),
            3,
            evidence_pool,
            fallback_ids,
            "研发建议",
        ),
        "brand_communication": normalize_insight_items(
            raw.get("brand_communication"),
            3,
            evidence_pool,
            fallback_ids,
            "品牌沟通建议",
        ),
        "evidence_chain": normalize_chain_items(raw.get("evidence_chain"), evidence_pool, fallback_ids),
        "data_gaps": normalize_insight_items(raw.get("data_gaps"), 3, evidence_pool, fallback_ids, "数据缺口"),
    }


def normalize_insight_items(
    items: Any,
    target_count: int,
    evidence_pool: list[dict[str, Any]],
    fallback_ids: list[str],
    fallback_title: str,
) -> list[dict[str, Any]]:
    raw_items = items if isinstance(items, list) else []
    normalized: list[dict[str, Any]] = []
    for index in range(target_count):
        item = raw_items[index] if index < len(raw_items) and isinstance(raw_items[index], dict) else {}
        normalized.append(
            {
                "title": str(item.get("title") or f"{fallback_title} {index + 1}"),
                "detail": str(item.get("detail") or "Needs review against the cited evidence before action."),
                "citations": resolve_citations(item.get("citation_ids"), evidence_pool, rotate_ids(fallback_ids, index)),
            }
        )
    return normalized


def normalize_chain_items(items: Any, evidence_pool: list[dict[str, Any]], fallback_ids: list[str]) -> list[dict[str, Any]]:
    raw_items = items if isinstance(items, list) else []
    if not raw_items:
        raw_items = [
            {"claim": item["title"], "detail": item["excerpt"], "citation_ids": [item["id"]]}
            for item in evidence_pool[:6]
        ]
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items[:8]):
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "claim": str(item.get("claim") or item.get("title") or f"Evidence {index + 1}"),
                "detail": str(item.get("detail") or "Cited source evidence."),
                "citations": resolve_citations(item.get("citation_ids"), evidence_pool, rotate_ids(fallback_ids, index)),
            }
        )
    return normalized


def resolve_citations(ids: Any, evidence_pool: list[dict[str, Any]], fallback_ids: list[str]) -> list[dict[str, Any]]:
    evidence_by_id = {item["id"]: item for item in evidence_pool}
    requested_ids = ids if isinstance(ids, list) else []
    resolved = [evidence_by_id[item_id] for item_id in requested_ids if isinstance(item_id, str) and item_id in evidence_by_id]
    if not resolved:
        resolved = [evidence_by_id[item_id] for item_id in fallback_ids if item_id in evidence_by_id]
    return [
        {
            "id": item["id"],
            "source": item["source"],
            "kind": item["kind"],
            "title": item["title"],
            "url": item["url"],
            "excerpt": item["excerpt"],
            "reference": item["reference"],
        }
        for item in resolved[:3]
    ]


def unique_ids(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in ids:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def rotate_ids(ids: list[str], index: int) -> list[str]:
    if not ids:
        return []
    return [ids[index % len(ids)]]


def analyze_category(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    if not category:
        raise ValueError("category is required")
    limit = int(payload.get("limit") or 25)
    limit = max(5, min(limit, MAX_RESEARCH_POST_LIMIT))
    time_range = str(payload.get("timeRange") or "year")
    if time_range not in {"day", "week", "month", "year", "all"}:
        time_range = "year"
    mode = str(payload.get("mode") or "auto")
    if mode not in {"auto", "agent_reach", "oauth", "rss", "sample"}:
        mode = "auto"
    bypass_cache = bool(payload.get("bypassCache"))
    use_llm = payload.get("useLlm", True) is not False
    posts, warnings, source_mode = collect_reddit(category, limit, time_range, mode, bypass_cache=bypass_cache)
    result = summarize_posts(category, posts, source_mode, warnings)
    result["data_volume"] = build_data_volume_stats(limit, posts, source_mode, use_llm)
    data_volume = result["data_volume"]
    if (
        source_mode == "agent_reach"
        and data_volume["comment_enrichment_post_limit"] > 0
        and data_volume["comments_per_enriched_post_limit"] > 0
        and data_volume["collected_posts"] > 0
        and data_volume["collected_comments"] == 0
    ):
        result["warnings"].append(
            "Agent Reach returned Reddit posts and comment counts, but no comment bodies. "
            "Reconnect the OpenCLI Chrome extension or rdt-cli login, then rerun without using the cached result."
        )
    result["llm_analysis"] = {
        "enabled": False,
        "status": "not_requested",
        "message": "Enable AI synthesis to call the configured LLM provider.",
    }
    if use_llm:
        try:
            enhanced = enhance_report_with_llm(result)
            result["llm_analysis"] = {
                "enabled": True,
                "status": "ok",
                **enhanced,
            }
        except LLMUnavailable as exc:
            result["llm_analysis"] = {
                "enabled": True,
                "status": "unavailable",
                "message": str(exc),
            }
            result["warnings"].append(str(exc))
    return result


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        print(f"{self.address_string()} - {format % args}")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "time": now_iso()})
            return
        if parsed.path == "/api/history":
            self.send_json(list_research_history())
            return
        if parsed.path.startswith("/api/history/"):
            item_id = urllib.parse.unquote(parsed.path.removeprefix("/api/history/"))
            self.send_json(get_research_history_item(item_id))
            return
        if parsed.path == "/api/settings/llm":
            self.send_json(build_llm_settings_response())
            return
        if parsed.path == "/api/settings/reddit":
            self.send_json(build_reddit_settings_response())
            return
        if parsed.path == "/api/settings/research":
            self.send_json(build_research_settings_response())
            return
        if parsed.path == "/api/settings/agent-reach":
            self.send_json(build_agent_reach_settings_response())
            return
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in {
            "/api/analyze",
            "/api/analyze/amazon",
            "/api/analyze/combined",
            "/api/history",
            "/api/settings/llm",
            "/api/settings/reddit",
            "/api/settings/research",
            "/api/settings/agent-reach",
            "/api/settings/agent-reach/reconnect",
        }:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if parsed.path == "/api/settings/agent-reach/reconnect":
                result = reconnect_opencli_extension()
            elif parsed.path == "/api/history":
                result = save_research_history(payload)
            elif parsed.path == "/api/settings/llm":
                result = update_llm_settings(payload)
            elif parsed.path == "/api/settings/reddit":
                result = update_reddit_settings(payload)
            elif parsed.path == "/api/settings/research":
                result = update_research_settings(payload)
            elif parsed.path == "/api/settings/agent-reach":
                result = update_agent_reach_settings(payload)
            elif parsed.path == "/api/analyze/amazon":
                result = analyze_amazon_category(payload)
            elif parsed.path == "/api/analyze/combined":
                result = analyze_combined_insight(payload)
            else:
                result = analyze_category(payload)
            self.send_json(result)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": f"Analysis failed: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/history/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            item_id = urllib.parse.unquote(parsed.path.removeprefix("/api/history/"))
            self.send_json(delete_research_history_item(item_id))
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": f"Delete failed: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    sync_runtime_env()
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Insight Agent Reddit demo running at http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    selected_port = int(os.getenv("PORT", "8000"))
    run(port=selected_port)


if __name__ == "__main__":
    main()

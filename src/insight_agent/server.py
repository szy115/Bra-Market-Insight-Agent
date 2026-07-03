from __future__ import annotations

import base64
import concurrent.futures
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
    clear_run_cancel,
    fetch_reddit_agent_reach,
    is_run_cancelled,
    reconnect_opencli_extension,
    request_run_cancel,
    reset_current_run_id,
    resolve_command,
    run_command,
    set_current_run_id,
)
from .ingestion.amazon_opencli import (
    amazon_config_from_env,
    fetch_amazon_opencli,
    merge_product,
    read_amazon_discussion,
    read_amazon_product,
)
from .ingestion.tiktok_browser import fetch_tiktok_playwright, open_tiktok_login_browser
from .ingestion.youtube_ytdlp import fetch_youtube_ytdlp
from .llm import (
    LLMUnavailable,
    call_openai_compatible,
    enhance_amazon_report_with_llm,
    enhance_combined_insight_with_llm,
    enhance_competitor_deep_dive_with_llm,
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
    build_web_search_settings_response,
    configured_secret,
    int_setting,
    read_settings_values,
    selected_web_search_provider,
    sync_runtime_env,
    update_agent_reach_settings,
    update_llm_settings,
    update_reddit_settings,
    update_research_settings,
    update_web_search_settings,
)

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(os.getenv("INSIGHT_AGENT_HOME", Path.cwd())).resolve()
STATIC_DIR = PACKAGE_DIR / "static"
CACHE_DIR = PROJECT_ROOT / ".cache"
HISTORY_PATH = CACHE_DIR / "research-history.json"
DATA_DIR = PACKAGE_DIR / "data"

CACHE_VERSION = "v4"
ANALYSIS_CACHE_TTL_SECONDS = 60 * 60 * 24


class OperationCancelled(RuntimeError):
    """Raised when a long-running analysis is cancelled by the user."""

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

DEFAULT_COMPETITOR_DISCOVERY_QUERY = "minimizer bra"
DEFAULT_COMPETITOR_DISCOVERY_BRIEF = {
    "brand": "Hsia / 遐",
    "market": "美国",
    "category": "大胸显小 / Minimizer Bra",
    "coreKeywords": "minimizer bra, full coverage bra, large bust bra, supportive bra",
    "targetPriceBand": "$49-$69",
    "upgradePriceBand": "$59-$79",
    "coreSizes": "D-G",
    "coreUsers": "大胸、通勤、显小、支撑、舒适、外穿平滑",
    "brandDirection": "好看、支撑、显小的大胸文胸",
}
DEFAULT_COMPETITOR_SCORE_WEIGHTS = {
    "briefMatch": 1.0,
    "priceFit": 1.35,
    "sizeMatch": 1.0,
    "marketProof": 1.0,
    "reviewEvidence": 1.0,
    "queryCoverage": 1.0,
    "tiktokProof": 1.0,
}
COMPETITOR_STRONG_REVIEW_COUNT = 1000
COMPETITOR_PROMISING_REVIEW_COUNT = 300
COMPETITOR_MIN_REVIEW_COUNT = 100
COMPETITOR_MIN_RATING = 4.0
HSIA_TARGET_PRICE_MIN = 49
HSIA_TARGET_PRICE_MAX = 69
HSIA_UPGRADE_PRICE_MIN = 59
HSIA_UPGRADE_PRICE_MAX = 79

CHINESE_COMPETITOR_BRIEF_TERMS = {
    "大胸": ["large bust", "large breasts", "full bust"],
    "大杯": ["large bust", "full bust", "dd", "ddd", "g cup"],
    "显小": ["minimizer", "minimize", "minimizes"],
    "支撑": ["support", "supportive", "lift"],
    "舒适": ["comfort", "comfortable", "soft"],
    "通勤": ["everyday", "work", "under shirts", "t-shirt"],
    "外穿平滑": ["smoothing", "smooth", "under shirts", "t-shirt"],
    "平滑": ["smoothing", "smooth"],
    "好看": ["pretty", "beautiful", "lace", "cute"],
}

COMPETITOR_RELEVANCE_TERMS = {
    "minimizer": 18,
    "minimize": 12,
    "minimizes": 12,
    "full coverage": 12,
    "large bust": 10,
    "large breasts": 10,
    "full bust": 10,
    "support": 8,
    "supportive": 8,
    "smoothing": 8,
    "smooth": 6,
    "back smoothing": 10,
    "side support": 8,
    "wireless": 4,
    "underwire": 4,
    "unlined": 4,
    "ddd": 5,
    "g cup": 5,
    "plus size": 5,
}

ARTICLE_REVIEW_DOMAINS = {
    "byrdie.com",
    "cosmopolitan.com",
    "elle.com",
    "forbes.com",
    "glamour.com",
    "goodhousekeeping.com",
    "harpersbazaar.com",
    "health.com",
    "instyle.com",
    "nymag.com",
    "oprahdaily.com",
    "people.com",
    "reviewed.usatoday.com",
    "thecut.com",
    "usatoday.com",
    "verywellhealth.com",
    "vogue.com",
    "whowhatwear.com",
    "womenshealthmag.com",
    "wirecutter.com",
    "nytimes.com",
}

ARTICLE_INDUSTRY_REPORT_DOMAINS = {
    "circana.com",
    "fortunebusinessinsights.com",
    "grandviewresearch.com",
    "ibisworld.com",
    "marketresearch.com",
    "mintel.com",
    "mordorintelligence.com",
    "nielseniq.com",
    "researchandmarkets.com",
    "statista.com",
    "technavio.com",
}

ARTICLE_SEARCH_SITE_DOMAINS = [
    "goodhousekeeping.com",
    "instyle.com",
    "people.com",
    "womenshealthmag.com",
    "byrdie.com",
    "glamour.com",
    "nymag.com",
    "wirecutter.com",
]

ARTICLE_EXCLUDED_DOMAINS = {
    "amazon.com",
    "ebay.com",
    "etsy.com",
    "facebook.com",
    "instagram.com",
    "pinterest.com",
    "reddit.com",
    "tiktok.com",
    "temu.com",
    "twitter.com",
    "walmart.com",
    "x.com",
    "youtube.com",
}

ARTICLE_SIGNAL_TERMS = {
    "minimizer": "minimizer / visually smaller bust",
    "minimize": "minimizer / visually smaller bust",
    "full coverage": "full coverage",
    "large bust": "large bust",
    "full bust": "full bust",
    "supportive": "support",
    "support": "support",
    "smoothing": "smoothing",
    "smooth": "smoothing",
    "underwire": "underwire structure",
    "wireless": "wireless comfort",
    "unlined": "unlined construction",
    "side support": "side support",
    "back smoothing": "back smoothing",
    "plus size": "plus size",
}


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


def http_post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> bytes:
    final_headers = {
        "User-Agent": reddit_user_agent(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if headers:
        final_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=final_headers,
        method="POST",
    )
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
    youtube_report = item.get("youtube_report") if isinstance(item.get("youtube_report"), dict) else None
    tiktok_report = item.get("tiktok_report") if isinstance(item.get("tiktok_report"), dict) else None
    combined_report = item.get("combined_report") if isinstance(item.get("combined_report"), dict) else None
    article_report = item.get("article_report") if isinstance(item.get("article_report"), dict) else None
    return {
        "id": item.get("id", ""),
        "category": item.get("category", ""),
        "saved_at": item.get("saved_at", ""),
        "summary": item.get("summary", ""),
        "has_reddit": bool(reddit_report),
        "has_amazon": bool(amazon_report),
        "has_youtube": bool(youtube_report),
        "has_tiktok": bool(tiktok_report),
        "has_combined": bool(combined_report),
        "has_articles": bool(article_report),
        "reddit_posts": int(((reddit_report or {}).get("coverage") or {}).get("posts") or 0),
        "amazon_products": int(((amazon_report or {}).get("metrics") or {}).get("products") or 0),
        "youtube_videos": int(((youtube_report or {}).get("metrics") or {}).get("videos") or 0),
        "tiktok_videos": int(((tiktok_report or {}).get("metrics") or {}).get("videos") or 0),
        "article_count": int(((article_report or {}).get("data_volume") or {}).get("collected_articles") or 0),
        "evidence_items": int(((combined_report or {}).get("data_summary") or {}).get("evidence_items") or 0),
    }


def list_research_history() -> dict[str, Any]:
    items = sorted(read_history_items(), key=lambda item: str(item.get("saved_at", "")), reverse=True)
    return {"items": [history_summary(item) for item in items], "storage_path": history_storage_path()}


def save_research_history(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    reddit_report = payload.get("reddit_report") if isinstance(payload.get("reddit_report"), dict) else None
    amazon_report = payload.get("amazon_report") if isinstance(payload.get("amazon_report"), dict) else None
    youtube_report = payload.get("youtube_report") if isinstance(payload.get("youtube_report"), dict) else None
    tiktok_report = payload.get("tiktok_report") if isinstance(payload.get("tiktok_report"), dict) else None
    combined_report = payload.get("combined_report") if isinstance(payload.get("combined_report"), dict) else None
    article_report = payload.get("article_report") if isinstance(payload.get("article_report"), dict) else None
    if not category:
        category = str(((combined_report or reddit_report or amazon_report or youtube_report or tiktok_report or article_report or {}).get("category")) or "").strip()
    if not category:
        raise ValueError("category is required")
    if not any((reddit_report, amazon_report, youtube_report, tiktok_report, combined_report, article_report)):
        raise ValueError("At least one report is required to save history")

    saved_at = now_iso()
    digest = hashlib.sha256(
        json.dumps(
            {
                "category": category,
                "saved_at": saved_at,
                "reddit": bool(reddit_report),
                "amazon": bool(amazon_report),
                "youtube": bool(youtube_report),
                "tiktok": bool(tiktok_report),
                "combined": bool(combined_report),
                "articles": bool(article_report),
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
    if not summary and youtube_report:
        metrics = youtube_report.get("metrics") or {}
        summary = f"{metrics.get('videos', 0)} YouTube videos collected."
    if not summary and tiktok_report:
        metrics = tiktok_report.get("metrics") or {}
        summary = f"{metrics.get('videos', 0)} TikTok videos collected."
    if not summary and article_report:
        data_volume = article_report.get("data_volume") or {}
        summary = f"{data_volume.get('collected_articles', 0)} media/ranking articles collected."

    entry = {
        "id": f"{dt.datetime.now(dt.UTC).strftime('%Y%m%d%H%M%S')}-{digest}",
        "category": category,
        "saved_at": saved_at,
        "summary": compact_text(summary, 280),
        "reddit_report": reddit_report,
        "amazon_report": amazon_report,
        "youtube_report": youtube_report,
        "tiktok_report": tiktok_report,
        "combined_report": combined_report,
        "article_report": article_report,
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


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


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
    detail_limit: int | None = None,
    comments_per_post: int | None = None,
) -> tuple[list[dict[str, Any]], list[str], str]:
    query = build_reddit_query(category)
    settings_values = read_settings_values()
    effective_detail_limit = int_setting(settings_values, "AGENT_REACH_DETAIL_LIMIT", 8, 0, 100)
    effective_comments_per_post = int_setting(settings_values, "AGENT_REACH_COMMENTS_PER_POST", 20, 0, 200)
    if detail_limit is not None:
        effective_detail_limit = max(0, min(int(detail_limit), 100))
    if comments_per_post is not None:
        effective_comments_per_post = max(0, min(int(comments_per_post), 200))
    detail_cache_part = (
        str(effective_detail_limit)
        if detail_limit is not None
        else os.getenv("AGENT_REACH_DETAIL_LIMIT", "")
    )
    comments_cache_part = (
        str(effective_comments_per_post)
        if comments_per_post is not None
        else os.getenv("AGENT_REACH_COMMENTS_PER_POST", "")
    )
    cache_path = cache_key(
        [
            CACHE_VERSION,
            "analysis",
            query,
            str(limit),
            time_range,
            mode,
            detail_cache_part,
            comments_cache_part,
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
            effective_detail_limit > 0
            and effective_comments_per_post > 0
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
        agent_reach_kwargs: dict[str, int] = {}
        if detail_limit is not None or comments_per_post is not None:
            agent_reach_kwargs = {
                "detail_limit": effective_detail_limit,
                "comments_per_post": effective_comments_per_post,
            }
        agent_reach_result = fetch_reddit_agent_reach(query, limit, time_range, **agent_reach_kwargs)
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
    detail_limit_override: int | None = None,
    comments_per_post_override: int | None = None,
) -> dict[str, Any]:
    values = read_settings_values()
    detail_limit = int_setting(values, "AGENT_REACH_DETAIL_LIMIT", 8, 0, 100)
    comments_per_post_limit = int_setting(values, "AGENT_REACH_COMMENTS_PER_POST", 20, 0, 200)
    if detail_limit_override is not None:
        detail_limit = max(0, min(int(detail_limit_override), 100))
    if comments_per_post_override is not None:
        comments_per_post_limit = max(0, min(int(comments_per_post_override), 200))
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


def normalize_competitor_brief(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("brief") if isinstance(payload.get("brief"), dict) else payload
    brief: dict[str, str] = {}
    for key, fallback in DEFAULT_COMPETITOR_DISCOVERY_BRIEF.items():
        value = raw.get(key) if isinstance(raw, dict) else None
        brief[key] = str(value if value is not None else fallback).strip() or fallback
    query = str(payload.get("query") or "").strip()
    if query and brief["coreKeywords"] == DEFAULT_COMPETITOR_DISCOVERY_BRIEF["coreKeywords"]:
        brief["coreKeywords"] = query
    return brief


def normalize_competitor_score_weights(payload: dict[str, Any]) -> dict[str, float]:
    raw = payload.get("scoreWeights") if isinstance(payload.get("scoreWeights"), dict) else {}
    weights: dict[str, float] = {}
    for key, fallback in DEFAULT_COMPETITOR_SCORE_WEIGHTS.items():
        value = raw.get(key) if isinstance(raw, dict) else fallback
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = fallback
        weights[key] = round(max(0.0, min(3.0, numeric)), 2)
    return weights


def split_brief_terms(value: str) -> list[str]:
    parts = re.split(r"[,，、;\n]+", value)
    terms = [clean_text(part) for part in parts if clean_text(part)]
    return terms


def parse_price_band(value: str, fallback: tuple[int, int]) -> tuple[int, int]:
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", value)]
    if len(numbers) >= 2:
        low, high = sorted((numbers[0], numbers[1]))
        return int(low), int(high)
    return fallback


def competitor_size_terms(value: str) -> list[str]:
    lowered = value.lower()
    terms: list[str] = []
    if re.search(r"\bd\s*[-–]\s*g\b", lowered) or "d-g" in lowered:
        terms.extend(["d cup", "dd", "ddd", "f cup", "g cup", "large bust", "full bust"])
    terms.extend(re.findall(r"\b(?:dd|ddd|d|f|g)\s?(?:cup)?\b", lowered, flags=re.I))
    return unique_strings(terms)


def competitor_brief_terms(brief: dict[str, str]) -> dict[str, int]:
    weighted = dict(COMPETITOR_RELEVANCE_TERMS)
    for keyword in split_brief_terms(brief["coreKeywords"]):
        lowered = keyword.lower()
        if lowered and lowered not in {"bra", "bras"}:
            weighted[lowered] = max(weighted.get(lowered, 0), 12)
    combined = " ".join([brief["category"], brief["coreUsers"], brief["brandDirection"]])
    for chinese, mapped_terms in CHINESE_COMPETITOR_BRIEF_TERMS.items():
        if chinese in combined:
            for term in mapped_terms:
                weighted[term] = max(weighted.get(term, 0), 8)
    for term in competitor_size_terms(brief["coreSizes"]):
        weighted[term.lower()] = max(weighted.get(term.lower(), 0), 5)
    return weighted


def build_competitor_discovery_query(brief: dict[str, str]) -> str:
    parts = [
        brief["category"],
        brief["coreKeywords"],
        brief["coreSizes"],
        "large bust support smoothing comfortable under shirts",
    ]
    query = " ".join(part for part in parts if part).strip()
    return query or DEFAULT_COMPETITOR_DISCOVERY_QUERY


def competitor_own_brand_terms(brand: str) -> list[str]:
    terms = []
    for part in re.split(r"[/,，、\s]+", brand):
        cleaned = clean_text(part).lower()
        if cleaned and len(cleaned) >= 3:
            terms.append(cleaned)
    if "遐" in brand:
        terms.append("遐")
    if "hsia" in terms:
        terms.append("hisa")
    if "hisa" in terms:
        terms.append("hsia")
    return unique_strings(terms)


def competitor_brand_term_in_text(term: str, text: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", term):
        return term in text
    return bool(re.search(rf"\b{re.escape(term)}\b", text, flags=re.I))


def should_exclude_competitor_product(product: dict[str, Any], brief: dict[str, str]) -> tuple[bool, str]:
    text = competitor_product_text(product)
    if "bra" not in text and "brassiere" not in text:
        return True, "Excluded because the collected item does not look like a bra product."
    for term in competitor_own_brand_terms(brief["brand"]):
        if term and competitor_brand_term_in_text(term, text):
            return True, "Excluded Hsia's own brand from competitor candidates."
    return False, ""


def competitor_number(value: Any) -> float | None:
    if isinstance(value, bool) or value in {None, ""}:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def competitor_breakout_evidence(product: dict[str, Any]) -> dict[str, Any]:
    review_count_value = competitor_number(product.get("review_count"))
    rating_value = competitor_number(product.get("rating_value"))
    review_count = int(review_count_value or 0)
    rating = float(rating_value or 0)
    review_evidence = competitor_review_evidence(product)
    if not review_evidence and isinstance(product.get("review_evidence"), list):
        review_evidence_count = len(product["review_evidence"])
    else:
        review_evidence_count = len(review_evidence)
    badges = product.get("badges") if isinstance(product.get("badges"), list) else []
    reasons: list[str] = []
    risks: list[str] = []

    if review_count >= COMPETITOR_STRONG_REVIEW_COUNT:
        reasons.append(f"Amazon review count {review_count:,} is a strong public demand proxy.")
    elif review_count >= COMPETITOR_PROMISING_REVIEW_COUNT:
        reasons.append(f"Amazon review count {review_count:,} is enough for a promising breakout read.")
    elif review_count >= COMPETITOR_MIN_REVIEW_COUNT:
        risks.append(f"Amazon review count {review_count:,} is directional but still thin for breakout status.")
    else:
        risks.append(f"Amazon review count {review_count:,} is too low to call this a breakout competitor.")

    if rating >= 4.3:
        reasons.append(f"Rating {rating:.1f} suggests broad buyer satisfaction.")
    elif rating >= COMPETITOR_MIN_RATING:
        reasons.append(f"Rating {rating:.1f} clears the minimum satisfaction gate.")
    elif rating > 0:
        risks.append(f"Rating {rating:.1f} is below the breakout satisfaction gate.")
    else:
        risks.append("No rating was collected.")

    if review_evidence_count:
        reasons.append(f"{review_evidence_count} review samples are available for qualitative teardown.")
    else:
        risks.append("No readable review samples were collected; teardown confidence is limited.")
    if badges:
        reasons.append(f"Amazon badge signal: {', '.join(str(badge) for badge in badges[:2])}.")

    if review_count >= COMPETITOR_STRONG_REVIEW_COUNT and rating >= 4.2 and review_evidence_count:
        tier = "strong_breakout"
        label = "Strong breakout candidate"
    elif review_count >= COMPETITOR_PROMISING_REVIEW_COUNT and rating >= COMPETITOR_MIN_RATING:
        tier = "needs_tiktok_validation"
        label = "Promising, validate on TikTok"
    elif review_count >= COMPETITOR_MIN_REVIEW_COUNT and rating >= 3.8:
        tier = "watchlist"
        label = "Watchlist, evidence still thin"
    else:
        tier = "low_evidence"
        label = "Low-evidence Amazon result"

    return {
        "tier": tier,
        "label": label,
        "review_count": review_count,
        "rating": rating_value,
        "review_evidence_count": review_evidence_count,
        "reasons": reasons[:5],
        "risks": risks[:5],
    }


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


def discover_competitors(payload: dict[str, Any]) -> dict[str, Any]:
    brief = normalize_competitor_brief(payload)
    score_weights = normalize_competitor_score_weights(payload)
    query = str(payload.get("query") or build_competitor_discovery_query(brief) or DEFAULT_COMPETITOR_DISCOVERY_QUERY).strip()
    if not query:
        raise ValueError("query is required")
    limit = int(payload.get("limit") or os.getenv("AMAZON_PRODUCT_LIMIT", "20") or 20)
    limit = max(1, min(limit, 100))
    keyword_limit = int(payload.get("amazonKeywordLimit") or os.getenv("AMAZON_KEYWORD_LIMIT", "8") or 8)
    keyword_limit = max(1, min(keyword_limit, 20))
    bypass_cache = bool(payload.get("bypassCache"))

    products, warnings, source_mode, queries, per_query_counts = collect_amazon(
        query,
        limit,
        keyword_limit,
        bypass_cache=bypass_cache,
    )
    excluded: list[str] = []
    candidates = []
    for product in products:
        should_exclude, reason = should_exclude_competitor_product(product, brief)
        if should_exclude:
            excluded.append(reason)
            continue
        candidates.append(build_competitor_candidate(product, brief, score_weights))
    candidates.sort(
        key=lambda item: (
            item["score"],
            {"strong_breakout": 4, "needs_tiktok_validation": 3, "watchlist": 2, "low_evidence": 1}.get(item.get("breakout_tier"), 0),
            item["review_count"] or 0,
            item["rating_value"] or 0,
        ),
        reverse=True,
    )
    brand_counts = Counter(candidate["brand"] or "Unknown" for candidate in candidates)
    brand_counts.pop("Unknown", None)
    return {
        "query": query,
        "brief": brief,
        "score_weights": score_weights,
        "generated_at": now_iso(),
        "source_mode": source_mode,
        "source": {
            "source_name": "Amazon",
            "source_type": "marketplace",
            "status": "ready" if products else "partial",
            "collected_items_count": len(products),
            "evidence_items_count": sum(1 + len(candidate["review_evidence"]) for candidate in candidates),
            "last_run_at": now_iso(),
            "failure_reason": "" if products else "Amazon provider returned no products for this query.",
            "next_action": "Review breakout tiers, run TikTok validation on promising candidates, then confirm items for teardown."
            if products
            else "Check OpenCLI Amazon access, broaden keywords, or rerun with bypass cache.",
        },
        "data_volume": {
            "requested_products": limit * max(1, len(queries)),
            "requested_products_per_query": limit,
            "query_count": len(queries),
            "queries": queries,
            "per_query_counts": [{"query": query, "count": per_query_counts.get(query, 0)} for query in queries],
            "raw_collected_products": sum(per_query_counts.get(query, 0) for query in queries),
            "unique_products": len(products),
            "excluded_products": len(excluded),
            "candidate_count": len(candidates),
            "strong_breakout_candidates": sum(1 for candidate in candidates if candidate.get("breakout_tier") == "strong_breakout"),
            "needs_tiktok_validation_candidates": sum(1 for candidate in candidates if candidate.get("breakout_tier") == "needs_tiktok_validation"),
            "low_evidence_candidates": sum(1 for candidate in candidates if candidate.get("breakout_tier") == "low_evidence"),
        },
        "summary": {
            "candidate_count": len(candidates),
            "high_priority": sum(1 for candidate in candidates if candidate["priority"] == "High"),
            "medium_priority": sum(1 for candidate in candidates if candidate["priority"] == "Medium"),
            "strong_breakout": sum(1 for candidate in candidates if candidate.get("breakout_tier") == "strong_breakout"),
            "needs_tiktok_validation": sum(1 for candidate in candidates if candidate.get("breakout_tier") == "needs_tiktok_validation"),
            "low_evidence": sum(1 for candidate in candidates if candidate.get("breakout_tier") == "low_evidence"),
            "brands": [{"name": name, "count": count} for name, count in brand_counts.most_common(12)],
        },
        "candidates": candidates,
        "warnings": warnings,
        "method": {
            "notes": [
                "Amazon is the first competitor-discovery source because it returns structured product, price, rating, review, badge, and rank signals.",
                "High-priority breakout competitors must clear review-count and rating gates; low-review products stay visible but are downgraded to low-evidence or TikTok-validation buckets.",
                "Scores are deterministic Hsia relevance heuristics from the editable competitor brief and scoring weights, not sales estimates.",
                "The price-fit weight affects both in-band price rewards and out-of-band price penalties.",
                "TikTok validation should be run on strong and promising candidates to confirm social visibility, creator language, and comment-level pain points.",
                "LLM-as-judge should be used as a secondary qualitative review layer after public evidence gates, not as the primary filter.",
            ],
        },
    }


def build_competitor_candidate(
    product: dict[str, Any],
    brief: dict[str, str],
    score_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    title = str(product.get("title") or product.get("asin") or "Amazon product")
    brand = str(product.get("brand") or brand_from_title(title) or "")
    score, reasons, risks, score_breakdown = score_competitor_product(product, brief, score_weights)
    breakout = competitor_breakout_evidence(product)
    combined_reasons = unique_strings([*breakout["reasons"], *reasons])[:6]
    combined_risks = unique_strings([*breakout["risks"], *risks])[:6]
    return {
        "id": str(product.get("asin") or product.get("product_url") or title),
        "platform": "Amazon",
        "brand": brand,
        "title": title,
        "price_text": str(product.get("price_text") or ""),
        "price_value": product.get("price_value"),
        "rating_value": product.get("rating_value"),
        "review_count": product.get("review_count"),
        "badges": product.get("badges") if isinstance(product.get("badges"), list) else [],
        "is_sponsored": bool(product.get("is_sponsored")),
        "product_url": absolutize_amazon_url(str(product.get("product_url") or "")),
        "image_url": str(product.get("image_url") or ""),
        "asin": str(product.get("asin") or ""),
        "matched_queries": product.get("matched_queries") if isinstance(product.get("matched_queries"), list) else [],
        "score": score,
        "score_breakdown": score_breakdown,
        "priority": competitor_priority(score, product),
        "breakout_tier": breakout["tier"],
        "breakout_label": breakout["label"],
        "breakout_reasons": breakout["reasons"],
        "why_worth_tracking": combined_reasons,
        "risks": combined_risks,
        "claim_evidence": competitor_claim_evidence(product),
        "review_evidence": competitor_review_evidence(product),
        "tiktok_validation": None,
        "suggested_status": "candidate",
    }


def score_competitor_product(
    product: dict[str, Any],
    brief: dict[str, str],
    score_weights: dict[str, float] | None = None,
) -> tuple[int, list[str], list[str], list[dict[str, Any]]]:
    text = competitor_product_text(product)
    weights = score_weights or DEFAULT_COMPETITOR_SCORE_WEIGHTS
    reasons: list[str] = []
    risks: list[str] = []
    score = 20.0
    score_breakdown: list[dict[str, Any]] = [
        {"key": "base", "raw_points": 20, "weight": 1.0, "points": 20}
    ]

    def add_weighted_component(key: str, raw_points: float) -> None:
        nonlocal score
        weight = float(weights.get(key, DEFAULT_COMPETITOR_SCORE_WEIGHTS.get(key, 1.0)))
        weighted_points = raw_points * weight
        score += weighted_points
        score_breakdown.append(
            {
                "key": key,
                "raw_points": round(raw_points, 1),
                "weight": round(weight, 2),
                "points": round(weighted_points, 1),
            }
        )

    term_score = 0
    matched_terms: list[str] = []
    for term, points in competitor_brief_terms(brief).items():
        if term in text:
            term_score += points
            matched_terms.append(term)
    term_score = min(term_score, 34)
    add_weighted_component("briefMatch", term_score)
    if matched_terms:
        reasons.append(f"Matches the brief's category/user language: {', '.join(matched_terms[:5])}.")
    else:
        risks.append("Weak explicit match to the brief's category, user, or brand-direction language.")

    price = product.get("price_value")
    target_min, target_max = parse_price_band(
        brief["targetPriceBand"],
        (HSIA_TARGET_PRICE_MIN, HSIA_TARGET_PRICE_MAX),
    )
    upgrade_min, upgrade_max = parse_price_band(
        brief["upgradePriceBand"],
        (HSIA_UPGRADE_PRICE_MIN, HSIA_UPGRADE_PRICE_MAX),
    )
    if isinstance(price, int | float):
        if target_min <= float(price) <= target_max:
            price_score = 12
            reasons.append(f"Price sits in the brief's target {brief['targetPriceBand']} band.")
        elif upgrade_min <= float(price) <= upgrade_max:
            price_score = 9
            reasons.append(f"Price sits in the brief's upgrade-test {brief['upgradePriceBand']} band.")
        elif max(0, target_min - 20) <= float(price) <= upgrade_max + 20:
            price_score = 4
            reasons.append("Price is close enough to benchmark against the brief's price lane.")
        else:
            price_score = -10
            risks.append("Price is outside the brief's target and upgrade-test bands.")
    else:
        price_score = -6
        risks.append("No parseable price was collected.")
    add_weighted_component("priceFit", price_score)

    size_terms = competitor_size_terms(brief["coreSizes"])
    size_matches = [term for term in size_terms if term.lower() in text]
    if size_matches:
        size_score = min(10, len(size_matches) * 3)
        reasons.append(f"Size language overlaps the brief's {brief['coreSizes']} target: {', '.join(size_matches[:3])}.")
    else:
        size_score = 0
        risks.append(f"No explicit evidence for the brief's {brief['coreSizes']} size lane was collected.")
    add_weighted_component("sizeMatch", size_score)

    market_score = 0
    rating = product.get("rating_value")
    if isinstance(rating, int | float):
        if float(rating) >= 4.4:
            market_score += 8
            reasons.append("High rating suggests strong buyer satisfaction.")
        elif float(rating) >= 4.0:
            market_score += 5
            reasons.append("Rating is high enough to treat as a credible benchmark.")
        else:
            market_score -= 8
            risks.append("Rating is below the usual benchmark threshold.")
    else:
        risks.append("No rating was collected.")

    review_count = product.get("review_count")
    if isinstance(review_count, int | float):
        count = int(review_count)
        if count >= 5000:
            market_score += 14
            reasons.append("Large review base is a strong public validation proxy.")
        elif count >= 1000:
            market_score += 11
            reasons.append("Review count is large enough to justify teardown.")
        elif count >= 300:
            market_score += 7
            reasons.append("Review count clears the minimum breakout-candidate gate.")
        elif count >= 100:
            market_score += 2
            risks.append("Review count is only a thin public feedback signal.")
        else:
            market_score -= 18
            risks.append("Review count is thin, so confidence should stay low.")
    else:
        market_score -= 10
        risks.append("No review count was collected.")

    badges = product.get("badges") if isinstance(product.get("badges"), list) else []
    if badges:
        market_score += 4
        reasons.append(f"Amazon badge signal: {', '.join(str(badge) for badge in badges[:2])}.")
    if product.get("is_sponsored"):
        risks.append("Sponsored placement may inflate visibility versus organic demand.")
    add_weighted_component("marketProof", market_score)

    review_evidence = competitor_review_evidence(product)
    if review_evidence:
        review_evidence_score = min(8, len(review_evidence) * 2)
        reasons.append("Collected review samples can support praise/complaint extraction.")
    else:
        review_evidence_score = 0
        risks.append("No review samples were collected for qualitative teardown.")
    add_weighted_component("reviewEvidence", review_evidence_score)

    matched_queries = product.get("matched_queries") if isinstance(product.get("matched_queries"), list) else []
    if len(matched_queries) > 1:
        query_score = min(8, (len(matched_queries) - 1) * 3)
        reasons.append("Product appears across multiple expanded Amazon queries.")
    else:
        query_score = 0
    add_weighted_component("queryCoverage", query_score)

    final_score = int(round(max(0, min(100, score))))
    return final_score, reasons[:5], risks[:5], score_breakdown


def competitor_product_text(product: dict[str, Any]) -> str:
    parts = [
        str(product.get("title") or ""),
        str(product.get("brand") or ""),
        " ".join(str(point) for point in product.get("bullet_points") or []),
    ]
    for review in product.get("review_samples") or []:
        if isinstance(review, dict):
            parts.append(str(review.get("title") or ""))
            parts.append(str(review.get("body") or ""))
    return " ".join(parts).lower()


def competitor_claim_evidence(product: dict[str, Any]) -> list[str]:
    bullets = product.get("bullet_points") if isinstance(product.get("bullet_points"), list) else []
    if bullets:
        return [compact_text(str(point), 220) for point in bullets[:5] if str(point).strip()]
    title = str(product.get("title") or "").strip()
    return [title] if title else []


def competitor_review_evidence(product: dict[str, Any]) -> list[dict[str, Any]]:
    reviews = product.get("review_samples") if isinstance(product.get("review_samples"), list) else []
    evidence = []
    for review in reviews[:5]:
        if not isinstance(review, dict):
            continue
        body = compact_text(f"{review.get('title') or ''}: {review.get('body') or ''}".strip(": "), 320)
        if not body:
            continue
        evidence.append(
            {
                "text": body,
                "rating_value": review.get("rating_value"),
                "verified_purchase": bool(review.get("verified_purchase")),
            }
        )
    return evidence


def competitor_priority(score: int, product: dict[str, Any] | None = None) -> str:
    if not product:
        if score >= 70:
            return "High"
        if score >= 50:
            return "Medium"
        return "Low"
    breakout = competitor_breakout_evidence(product)
    review_count = int(breakout.get("review_count") or 0)
    rating = float(breakout.get("rating") or 0)
    review_evidence_count = int(breakout.get("review_evidence_count") or 0)
    tiktok_status = (((product.get("tiktok_validation") or {}) if isinstance(product.get("tiktok_validation"), dict) else {}).get("status") or "")
    has_quality_evidence = review_evidence_count > 0 or review_count >= COMPETITOR_STRONG_REVIEW_COUNT or tiktok_status == "verified"
    if score >= 72 and review_count >= COMPETITOR_PROMISING_REVIEW_COUNT and rating >= COMPETITOR_MIN_RATING and has_quality_evidence:
        return "High"
    if score >= 52 and review_count >= COMPETITOR_MIN_REVIEW_COUNT and rating >= 3.8:
        return "Medium"
    return "Low"


def competitor_tiktok_query(candidate: dict[str, Any], brief: dict[str, str] | None = None) -> str:
    brand = clean_text(str(candidate.get("brand") or ""))
    title = clean_text(str(candidate.get("title") or ""))
    category_terms = "minimizer bra large bust review"
    if brief and brief.get("coreKeywords"):
        first_keyword = split_brief_terms(brief["coreKeywords"])[0] if split_brief_terms(brief["coreKeywords"]) else ""
        if first_keyword:
            category_terms = f"{first_keyword} review"
    title_without_brand = title
    if brand:
        title_without_brand = re.sub(rf"\b{re.escape(brand)}\b", "", title_without_brand, flags=re.I)
    title_words = [
        word
        for word in re.split(r"[^A-Za-z0-9]+", title_without_brand)
        if len(word) >= 3 and word.lower() not in {"women", "womens", "woman", "plus", "size", "with", "for", "and", "the"}
    ][:6]
    if brand:
        return clean_text(f"{brand} {' '.join(title_words[:3])} {category_terms}")
    return clean_text(f"{' '.join(title_words)} {category_terms}") or category_terms


def score_tiktok_competitor_validation(candidate: dict[str, Any], videos: list[dict[str, Any]]) -> dict[str, Any]:
    brand = str(candidate.get("brand") or "").lower().strip()
    title_terms = [
        word
        for word in re.split(r"[^a-z0-9]+", str(candidate.get("title") or "").lower())
        if len(word) >= 4 and word not in {"women", "womens", "with", "support", "coverage", "minimizer", "brassiere"}
    ][:8]
    category_terms = ["minimizer", "large bust", "full coverage", "support", "smoothing", "bra", "review", "try on", "try-on"]
    matched_terms: set[str] = set()
    video_evidence: list[dict[str, Any]] = []
    relevant_videos = 0
    total_views = 0
    total_likes = 0
    comment_samples = 0
    for video in videos:
        text = tiktok_video_text(video).lower()
        video_matched_terms: set[str] = set()
        if isinstance(video.get("view_count"), int):
            total_views += int(video["view_count"])
        if isinstance(video.get("like_count"), int):
            total_likes += int(video["like_count"])
        comment_samples += len(video.get("comment_samples") or [])
        video_matched = False
        if brand and competitor_brand_term_in_text(brand, text):
            matched_terms.add(brand)
            video_matched_terms.add(brand)
            video_matched = True
        for term in title_terms:
            if term in text:
                matched_terms.add(term)
                video_matched_terms.add(term)
                video_matched = True
        for term in category_terms:
            if term in text:
                matched_terms.add(term)
                video_matched_terms.add(term)
                video_matched = True
        if video_matched:
            relevant_videos += 1
        video_comments = [
            {
                "author": str(comment.get("author") or ""),
                "text": compact_text(comment.get("text"), 220),
                "like_count": comment.get("like_count"),
            }
            for comment in (video.get("comment_samples") or [])[:3]
            if isinstance(comment, dict) and str(comment.get("text") or "").strip()
        ]
        video_evidence.append(
            {
                "title": compact_text(video.get("title") or video.get("caption") or "TikTok video", 180),
                "url": str(video.get("url") or ""),
                "author": str(video.get("author") or ""),
                "view_count": video.get("view_count"),
                "like_count": video.get("like_count"),
                "comment_count": video.get("comment_count"),
                "matched_terms": sorted(video_matched_terms)[:10],
                "snippet": compact_text(tiktok_video_text(video), 260),
                "comment_samples": video_comments,
            }
        )

    score = 0
    reasons: list[str] = []
    risks: list[str] = []
    if videos:
        score += min(25, len(videos) * 4)
        reasons.append(f"TikTok returned {len(videos)} videos for the competitor-validation query.")
    else:
        risks.append("TikTok returned no readable videos for this competitor.")
    if relevant_videos:
        score += min(30, relevant_videos * 8)
        reasons.append(f"{relevant_videos} videos matched brand, product, or category language.")
    else:
        risks.append("Collected TikTok videos did not clearly match the candidate.")
    if total_views:
        score += min(25, total_views.bit_length() * 3)
        reasons.append(f"Collected TikTok videos show {total_views:,} total public views.")
    if comment_samples:
        score += min(20, comment_samples * 2)
        reasons.append(f"{comment_samples} detail-page comment samples were collected.")
    else:
        risks.append("No TikTok detail-page comment samples were collected.")

    final_score = max(0, min(100, score))
    if final_score >= 65 and relevant_videos:
        status = "verified"
        label = "TikTok verified"
    elif final_score >= 35 and videos:
        status = "directional"
        label = "Directional TikTok signal"
    elif videos:
        status = "weak"
        label = "Weak TikTok signal"
    else:
        status = "no_signal"
        label = "No TikTok signal"
    return {
        "status": status,
        "label": label,
        "score": final_score,
        "video_count": len(videos),
        "relevant_video_count": relevant_videos,
        "total_views": total_views,
        "total_likes": total_likes,
        "comment_samples": comment_samples,
        "matched_terms": sorted(matched_terms)[:16],
        "video_evidence": video_evidence[:5],
        "reasons": reasons[:5],
        "risks": risks[:5],
    }


def apply_tiktok_validation_to_competitor(
    candidate: dict[str, Any],
    validation: dict[str, Any],
    score_weights: dict[str, float],
) -> dict[str, Any]:
    updated = {**candidate, "tiktok_validation": validation}
    raw_points_by_status = {
        "verified": 14,
        "directional": 8,
        "weak": 2,
        "no_signal": -6,
    }
    raw_points = raw_points_by_status.get(str(validation.get("status") or ""), 0)
    weight = float(score_weights.get("tiktokProof", DEFAULT_COMPETITOR_SCORE_WEIGHTS["tiktokProof"]))
    weighted_points = round(raw_points * weight, 1)
    updated["score"] = int(round(max(0, min(100, int(candidate.get("score") or 0) + weighted_points))))
    breakdown = list(candidate.get("score_breakdown") if isinstance(candidate.get("score_breakdown"), list) else [])
    breakdown = [item for item in breakdown if not (isinstance(item, dict) and item.get("key") == "tiktokProof")]
    breakdown.append(
        {
            "key": "tiktokProof",
            "raw_points": raw_points,
            "weight": round(weight, 2),
            "points": weighted_points,
        }
    )
    updated["score_breakdown"] = breakdown
    updated["priority"] = competitor_priority(updated["score"], updated)
    if validation.get("reasons"):
        updated["why_worth_tracking"] = unique_strings(
            [*validation["reasons"], *(candidate.get("why_worth_tracking") or [])]
        )[:6]
    if validation.get("risks"):
        updated["risks"] = unique_strings([*validation["risks"], *(candidate.get("risks") or [])])[:6]
    return updated


def verify_competitor_tiktok(payload: dict[str, Any]) -> dict[str, Any]:
    raw_candidate = payload.get("candidate")
    if not isinstance(raw_candidate, dict):
        raise ValueError("candidate is required")
    brief = normalize_competitor_brief(payload)
    score_weights = normalize_competitor_score_weights(payload)
    limit = max(1, min(int(payload.get("limit") or 8), 20))
    bypass_cache = bool(payload.get("bypassCache"))
    comments_per_video = max(1, min(int(payload.get("tiktokCommentsPerVideo") or 8), 30))
    query = clean_text(str(payload.get("query") or competitor_tiktok_query(raw_candidate, brief)))
    videos, warnings, source_mode, settings = collect_tiktok(
        query,
        limit,
        bypass_cache=bypass_cache,
        settings_override={"comments_per_video": comments_per_video},
    )
    validation = score_tiktok_competitor_validation(raw_candidate, videos)
    validation.update(
        {
            "query": query,
            "source_mode": source_mode,
            "warnings": warnings,
            "generated_at": now_iso(),
            "requested_videos": limit,
            "comments_per_video_limit": settings["comments_per_video"],
        }
    )
    updated_candidate = apply_tiktok_validation_to_competitor(raw_candidate, validation, score_weights)
    return {
        "candidate": updated_candidate,
        "validation": validation,
        "videos": videos,
        "warnings": warnings,
        "method": {
            "query": query,
            "notes": [
                "TikTok validation searches the candidate brand/product/category phrase, then opens each returned video detail page for comments.",
                "This is cross-platform directional proof; it validates social visibility and user language, not true sales volume.",
                "A no-signal result should downgrade confidence but does not prove the Amazon product is not selling.",
            ],
        },
    }


def extract_asin_from_url(url: str) -> str:
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url, flags=re.I)
    return match.group(1).upper() if match else ""


def normalize_competitor_product_seed(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("candidate") or payload.get("product") or payload
    if not isinstance(raw, dict):
        raise ValueError("candidate is required")

    title = clean_text(str(raw.get("title") or raw.get("name") or raw.get("asin") or ""))
    product_url = absolutize_amazon_url(str(raw.get("product_url") or raw.get("url") or ""))
    asin = str(raw.get("asin") or extract_asin_from_url(product_url)).strip().upper()
    if not product_url and asin:
        product_url = f"https://www.amazon.com/dp/{asin}"
    if not title and not asin and not product_url:
        raise ValueError("candidate must include at least title, ASIN, or product URL")

    review_samples = raw.get("review_samples") if isinstance(raw.get("review_samples"), list) else []
    if not review_samples and isinstance(raw.get("review_evidence"), list):
        review_samples = [
            {
                "title": "",
                "body": str(item.get("text") or ""),
                "rating_value": item.get("rating_value"),
                "verified_purchase": bool(item.get("verified_purchase")),
            }
            for item in raw["review_evidence"]
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]

    bullet_points = raw.get("bullet_points") if isinstance(raw.get("bullet_points"), list) else []
    if not bullet_points and isinstance(raw.get("claim_evidence"), list):
        bullet_points = [str(item) for item in raw["claim_evidence"] if str(item).strip()]

    return {
        "rank": raw.get("rank"),
        "asin": asin,
        "title": title or asin or product_url,
        "brand": str(raw.get("brand") or brand_from_title(title) or "").strip(),
        "product_url": product_url,
        "image_url": str(raw.get("image_url") or ""),
        "price_text": str(raw.get("price_text") or ""),
        "price_value": raw.get("price_value"),
        "currency": str(raw.get("currency") or "USD"),
        "rating_text": str(raw.get("rating_text") or ""),
        "rating_value": raw.get("rating_value"),
        "review_count_text": str(raw.get("review_count_text") or ""),
        "review_count": raw.get("review_count"),
        "badges": raw.get("badges") if isinstance(raw.get("badges"), list) else [],
        "is_sponsored": bool(raw.get("is_sponsored")),
        "breadcrumbs": raw.get("breadcrumbs") if isinstance(raw.get("breadcrumbs"), list) else [],
        "bullet_points": bullet_points,
        "availability": str(raw.get("availability") or ""),
        "seller": str(raw.get("seller") or ""),
        "review_samples": review_samples,
        "source_url": str(raw.get("source_url") or ""),
        "fetched_at": str(raw.get("fetched_at") or ""),
        "matched_queries": raw.get("matched_queries") if isinstance(raw.get("matched_queries"), list) else [],
        "score": raw.get("score"),
        "priority": raw.get("priority"),
    }


def competitor_product_search_phrase(product: dict[str, Any], max_words: int = 12) -> str:
    brand = clean_text(str(product.get("brand") or ""))
    title = clean_text(str(product.get("title") or ""))
    title = re.sub(r"\b(?:women'?s|for women|amazon|prime|store|visit the)\b", " ", title, flags=re.I)
    title = re.sub(r"[|:()\[\]{}]", " ", title)
    words = [word for word in re.split(r"\s+", title) if word]
    if brand:
        words = [word for word in words if word.casefold() != brand.casefold()]
    core_title = " ".join(words[:max_words])
    phrase = clean_text(f"{brand} {core_title}".strip())
    return phrase or title or str(product.get("asin") or "").strip() or str(product.get("product_url") or "").strip()


def competitor_category_context(product: dict[str, Any], payload: dict[str, Any]) -> str:
    category = str(payload.get("category") or "").strip()
    if category:
        return category
    brief = normalize_competitor_brief(payload) if isinstance(payload.get("brief"), dict) else DEFAULT_COMPETITOR_DISCOVERY_BRIEF
    product_phrase = competitor_product_search_phrase(product, max_words=8)
    return clean_text(f"{product_phrase} {brief.get('category') or ''} {brief.get('coreKeywords') or ''}")


def collect_competitor_amazon_product(
    product: dict[str, Any],
    review_limit: int,
    bypass_cache: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    target = str(product.get("asin") or product.get("product_url") or "").strip()
    cache_path = cache_key([CACHE_VERSION, "competitor-amazon-product", target, str(review_limit)])
    cached = None if bypass_cache else read_cache(cache_path, ttl_seconds=ANALYSIS_CACHE_TTL_SECONDS)
    if isinstance(cached, dict) and isinstance(cached.get("product"), dict):
        return cached["product"], ["Loaded competitor Amazon product/reviews from local cache."]

    warnings: list[str] = []
    enriched = dict(product)
    if not target:
        warnings.append("No ASIN or Amazon product URL is available, so Amazon detail/review reads were skipped.")
        return enriched, warnings

    config = amazon_config_from_env()
    detail = read_amazon_product(target, config.timeout_seconds)
    warnings.extend(detail.warnings)
    if detail.products:
        enriched = merge_product(enriched, detail.products[0])

    discussion = read_amazon_discussion(target, review_limit, config.timeout_seconds)
    warnings.extend(discussion.warnings)
    if discussion.products:
        enriched = merge_product(enriched, discussion.products[0])

    if review_limit >= 0 and isinstance(enriched.get("review_samples"), list):
        enriched["review_samples"] = enriched["review_samples"][:review_limit]

    if bypass_cache:
        warnings.append("Bypassed local cache for competitor Amazon detail/reviews.")
    write_cache(cache_path, {"product": enriched})
    return enriched, warnings


def parse_amazon_review_date(value: str) -> dt.date | None:
    cleaned = re.sub(r"^Reviewed\b.*?\bon\s+", "", str(value or "").strip(), flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def build_competitor_sales_proxy(product: dict[str, Any]) -> dict[str, Any]:
    reviews = product.get("review_samples") if isinstance(product.get("review_samples"), list) else []
    signals: list[dict[str, str]] = []
    review_count = product.get("review_count")
    if isinstance(review_count, int | float):
        count = int(review_count)
        if count >= 5000:
            strength = "strong public validation proxy"
        elif count >= 1000:
            strength = "meaningful public validation proxy"
        elif count >= 100:
            strength = "some public validation proxy"
        else:
            strength = "thin public validation proxy"
        signals.append(
            {
                "name": "Amazon review count",
                "value": f"{count:,}",
                "interpretation": f"{strength}; it reflects accumulated buyer feedback, not true unit sales.",
            }
        )
    rating = product.get("rating_value")
    if isinstance(rating, int | float):
        signals.append(
            {
                "name": "Amazon rating",
                "value": f"{float(rating):.1f}",
                "interpretation": "Directional satisfaction signal; compare against complaint themes before treating it as product-market proof.",
            }
        )
    badges = product.get("badges") if isinstance(product.get("badges"), list) else []
    if badges:
        signals.append(
            {
                "name": "Amazon badges",
                "value": ", ".join(str(item) for item in badges[:4]),
                "interpretation": "Visibility/merchandising signal that may correlate with demand or ad/retail treatment.",
            }
        )
    if product.get("is_sponsored"):
        signals.append(
            {
                "name": "Sponsored placement",
                "value": "Detected",
                "interpretation": "The product may be buying visibility; separate paid exposure from organic demand.",
            }
        )
    if reviews:
        dates = [date for date in (parse_amazon_review_date(str(review.get("date_text") or "")) for review in reviews) if date]
        if dates:
            newest = max(dates)
            oldest = min(dates)
            signals.append(
                {
                    "name": "Review sample date span",
                    "value": f"{oldest.isoformat()} to {newest.isoformat()}",
                    "interpretation": "Only a sample-based freshness check; it is not enough for weekly sales velocity.",
                }
            )
        signals.append(
            {
                "name": "Collected review bodies",
                "value": f"{len(reviews):,}",
                "interpretation": "Useful for qualitative teardown of love points, complaints, and claim gaps.",
            }
        )

    return {
        "signals": signals,
        "confidence": "Medium" if isinstance(review_count, int | float) and int(review_count) >= 1000 and reviews else "Low",
        "caveats": [
            "Amazon true unit sales are not public in this MVP.",
            "Review count, rating, badges, rank, and sponsorship are proxy signals, not revenue or market share.",
            "Reliable sales sizing needs paid third-party Amazon estimates, seller-owned data, or repeated BSR/rank snapshots.",
        ],
    }


def competitor_web_search_queries(product: dict[str, Any], category: str, limit: int = 4) -> list[str]:
    brand = clean_text(str(product.get("brand") or ""))
    phrase = competitor_product_search_phrase(product, max_words=8)
    queries = [
        f"{phrase} official site",
        f"{phrase} review",
        f"{brand} bra official site" if brand else "",
        f"{phrase} {category} brand",
    ]
    return unique_strings([query for query in queries if query])[:limit]


def score_competitor_web_candidate(
    product: dict[str, Any],
    category: str,
    title: str,
    snippet: str,
    domain: str,
    url: str,
) -> tuple[int, str, list[str]]:
    if domain_matches(domain, ARTICLE_EXCLUDED_DOMAINS):
        return 0, "excluded", ["Excluded marketplace/social/video domain."]
    brand = clean_text(str(product.get("brand") or "")).lower()
    brand_tokens = [token for token in re.split(r"[^a-z0-9]+", brand) if len(token) >= 3]
    text = f"{title} {snippet} {url}".lower()
    category_terms = [
        term.lower()
        for term in re.split(r"[^A-Za-z0-9]+", " ".join(article_search_terms(category)))
        if len(term) >= 3
    ]
    score = 20
    reasons: list[str] = []
    source_type = classify_article_source(domain, title, snippet)
    if brand_tokens and any(token in domain for token in brand_tokens):
        score += 36
        reasons.append("Domain appears to match the product brand.")
        source_type = "brand_site"
    if brand_tokens and any(token in text for token in brand_tokens):
        score += 12
        reasons.append("Search result mentions the product brand.")
    if any(phrase in text for phrase in ["official", "product", "shop", "store", "size guide"]):
        score += 12
        reasons.append("Result looks like an official/product page.")
    if source_type in {"public_ranking", "media_review"}:
        score += 12
        reasons.append("Result looks like a review or ranking.")
    matched_terms = sorted({term for term in category_terms if term in text})
    if matched_terms:
        score += min(16, len(matched_terms) * 3)
        reasons.append(f"Matches category terms: {', '.join(matched_terms[:5])}.")
    return max(0, min(100, score)), source_type, reasons[:5]


def discover_competitor_web_sources(
    product: dict[str, Any],
    category: str,
    candidate_limit: int,
    bypass_cache: bool = False,
    run_id: str = "",
) -> dict[str, Any]:
    queries = competitor_web_search_queries(product, category)
    candidates_by_url: dict[str, dict[str, Any]] = {}
    per_query_counts: list[dict[str, Any]] = []
    warnings: list[str] = []
    raw_results = 0
    provider_name = selected_web_search_provider(read_settings_values()).name

    for query in queries:
        ensure_competitor_run_active(run_id)
        try:
            provider_name, results, query_warnings = web_search_query(query, 5, bypass_cache=bypass_cache)
            warnings.extend(query_warnings)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            warnings.append(f"Search failed for {query}: {exc}")
            results = []
        raw_results += len(results)
        per_query_counts.append({"query": query, "count": len(results)})
        for rank, item in enumerate(results, start=1):
            url = normalize_discovery_url(str(item.get("url") or ""))
            if not url:
                continue
            domain = article_domain(url)
            title = clean_text(str(item.get("title") or ""))
            snippet = clean_text(str(item.get("snippet") or ""))
            score, source_type, reasons = score_competitor_web_candidate(product, category, title, snippet, domain, url)
            if score <= 0:
                continue
            candidate = {
                "title": compact_text(title or domain or url, 180),
                "url": url,
                "domain": domain,
                "snippet": compact_text(snippet, 320),
                "provider": provider_name,
                "query": query,
                "rank": rank,
                "score": score,
                "source_type": source_type,
                "reasons": reasons,
                "published": str(item.get("published") or ""),
            }
            existing = candidates_by_url.get(url)
            if not existing or candidate["score"] > existing["score"]:
                candidates_by_url[url] = candidate

    candidates = sorted(
        candidates_by_url.values(),
        key=lambda item: (int(item.get("score") or 0), -int(item.get("rank") or 99)),
        reverse=True,
    )[:candidate_limit]
    articles: list[dict[str, Any]] = []
    failed_urls = 0
    for candidate in candidates:
        ensure_competitor_run_active(run_id)
        try:
            markdown = fetch_article_markdown(str(candidate["url"]), bypass_cache=bypass_cache)
            article = build_article_item(str(candidate["url"]), markdown)
            article["source_type"] = candidate.get("source_type") or article["source_type"]
            article["search_score"] = candidate.get("score")
            article["search_reasons"] = candidate.get("reasons") or []
            articles.append(article)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            failed_urls += 1
            warnings.append(f"Failed to read {candidate['url']}: {exc}")

    return {
        "source_mode": f"web_search_{provider_name}",
        "queries": queries,
        "candidates": candidates,
        "articles": articles,
        "warnings": warnings,
        "data_volume": {
            "query_count": len(queries),
            "raw_results": raw_results,
            "candidate_count": len(candidates),
            "readable_sources": len(articles),
            "failed_sources": failed_urls,
            "per_query_counts": per_query_counts,
        },
    }


def competitor_review_text(review: dict[str, Any], limit: int = 900) -> str:
    return compact_text(f"{review.get('title') or ''}: {review.get('body') or ''}".strip(": "), limit)


def build_competitor_evidence_pool(
    product: dict[str, Any],
    reddit_report: dict[str, Any],
    web_sources: dict[str, Any],
    ai_review_limit: int,
    ai_reddit_post_limit: int,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    product_url = str(product.get("product_url") or "")
    if product_url:
        evidence.append(
            {
                "id": "A1",
                "source": "amazon",
                "kind": "product",
                "title": str(product.get("title") or product.get("asin") or "Amazon product"),
                "url": product_url,
                "excerpt": compact_text(
                    " ".join(str(point) for point in (product.get("bullet_points") or [])[:5])
                    or str(product.get("title") or ""),
                    700,
                ),
                "reference": "Amazon product page",
            }
        )

    reviews = product.get("review_samples") if isinstance(product.get("review_samples"), list) else []
    for index, review in enumerate(reviews[:ai_review_limit], start=1):
        body = competitor_review_text(review, 900)
        if not body:
            continue
        evidence.append(
            {
                "id": f"A1R{index}",
                "source": "amazon",
                "kind": "review",
                "title": f"Amazon review {index}",
                "url": amazon_review_url(review, product_url),
                "excerpt": body,
                "reference": f"Amazon review · {review.get('rating_value') or '-'} stars",
            }
        )

    for post_index, post in enumerate((reddit_report or {}).get("posts", [])[:ai_reddit_post_limit], start=1):
        url = str(post.get("url") or "")
        if not url:
            continue
        title = str(post.get("title") or f"Reddit post {post_index}")
        subreddit = str(post.get("subreddit") or "unknown")
        evidence.append(
            {
                "id": f"R{post_index}",
                "source": "reddit",
                "kind": "post",
                "title": title,
                "url": url,
                "excerpt": compact_text(str(post.get("excerpt") or ""), 700),
                "reference": f"Reddit r/{subreddit}",
            }
        )
        for comment_index, comment in enumerate(post_comment_items(post)[:3], start=1):
            text = compact_text(str(comment.get("text") or ""), 650)
            if not text:
                continue
            evidence.append(
                {
                    "id": f"R{post_index}C{comment_index}",
                    "source": "reddit",
                    "kind": "comment",
                    "title": f"Reddit comment {comment_index}",
                    "url": str(comment.get("url") or url),
                    "excerpt": text,
                    "reference": f"Reddit comment r/{subreddit}",
                }
            )

    for article_index, article in enumerate((web_sources or {}).get("articles", [])[:8], start=1):
        snippets = article.get("evidence_snippets") if isinstance(article.get("evidence_snippets"), list) else []
        excerpt = " ".join(str(snippet) for snippet in snippets[:2]) or str(article.get("title") or "")
        evidence.append(
            {
                "id": f"W{article_index}",
                "source": "web",
                "kind": str(article.get("source_type") or "web_page"),
                "title": str(article.get("title") or f"Web source {article_index}"),
                "url": str(article.get("url") or ""),
                "excerpt": compact_text(excerpt, 700),
                "reference": f"{article.get('domain') or 'web'} · {article.get('authority_level') or 'source'}",
            }
        )
    return [item for item in evidence if item.get("url") and item.get("excerpt")]


def build_competitor_deep_dive_context(
    product: dict[str, Any],
    category: str,
    reddit_report: dict[str, Any],
    web_sources: dict[str, Any],
    sales_proxy: dict[str, Any],
    evidence_pool: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "category": category,
        "product": {
            "asin": product.get("asin"),
            "title": product.get("title"),
            "brand": product.get("brand"),
            "price_text": product.get("price_text"),
            "price_value": product.get("price_value"),
            "rating_value": product.get("rating_value"),
            "review_count": product.get("review_count"),
            "badges": product.get("badges"),
            "is_sponsored": product.get("is_sponsored"),
            "product_url": product.get("product_url"),
            "bullet_points": (product.get("bullet_points") or [])[:8],
            "availability": product.get("availability"),
            "seller": product.get("seller"),
        },
        "amazon": {
            "review_samples_collected": len(product.get("review_samples") or []),
            "review_samples": [
                {
                    "title": review.get("title"),
                    "body": competitor_review_text(review, 700),
                    "rating_value": review.get("rating_value"),
                    "verified_purchase": review.get("verified_purchase"),
                    "date_text": review.get("date_text"),
                }
                for review in (product.get("review_samples") or [])[:40]
                if isinstance(review, dict)
            ],
        },
        "reddit": {
            "coverage": reddit_report.get("coverage"),
            "data_volume": reddit_report.get("data_volume"),
            "sentiment": reddit_report.get("sentiment"),
            "pain_points": reddit_report.get("pain_points", [])[:8],
            "brands": reddit_report.get("brands", [])[:8],
        },
        "web": {
            "data_volume": web_sources.get("data_volume"),
            "articles": [
                {
                    "title": article.get("title"),
                    "domain": article.get("domain"),
                    "source_type": article.get("source_type"),
                    "authority_level": article.get("authority_level"),
                    "evidence_snippets": article.get("evidence_snippets", [])[:3],
                    "url": article.get("url"),
                }
                for article in web_sources.get("articles", [])[:8]
            ],
        },
        "sales_proxy": sales_proxy,
        "evidence_pool": evidence_pool,
    }


def build_fallback_competitor_deep_dive_raw(
    category: str,
    product: dict[str, Any],
    reddit_report: dict[str, Any],
    sales_proxy: dict[str, Any],
    evidence_pool: list[dict[str, Any]],
) -> dict[str, Any]:
    product_title = str(product.get("title") or "this product")
    review_count = product.get("review_count")
    top_pain = ((reddit_report or {}).get("pain_points") or [{}])[0].get("topic") or "fit/support language"
    default_ids = [item["id"] for item in evidence_pool[:3]]
    amazon_ids = [item["id"] for item in evidence_pool if item["source"] == "amazon"][:3] or default_ids[:1]
    reddit_ids = [item["id"] for item in evidence_pool if item["source"] == "reddit"][:3] or default_ids[:1]
    web_ids = [item["id"] for item in evidence_pool if item["source"] == "web"][:2] or default_ids[:1]
    mixed_ids = unique_ids([*(amazon_ids[:1]), *(reddit_ids[:1]), *(web_ids[:1])]) or default_ids[:1]
    proxy_summary = "; ".join(f"{item['name']}: {item['value']}" for item in sales_proxy.get("signals", [])[:3]) or "limited public proxy signals"
    return {
        "verdict": {
            "text": f"{product_title} is worth a competitor teardown for {category}, but current sales confidence is proxy-based rather than true-sales based.",
            "citation_ids": mixed_ids,
        },
        "breakout_assessment": [
            {
                "title": "公开验证强度",
                "detail": f"Amazon public signals include {review_count or 'unknown'} reviews/ratings and {proxy_summary}.",
                "citation_ids": amazon_ids,
            },
            {
                "title": "社媒可见度",
                "detail": f"Reddit evidence should be read as discussion-language validation; current top theme is {top_pain}.",
                "citation_ids": reddit_ids or mixed_ids,
            },
            {
                "title": "独立网页证据",
                "detail": "Brand or media pages help verify official claims, positioning, and off-Amazon messaging.",
                "citation_ids": web_ids or mixed_ids,
            },
        ],
        "why_it_sells": [
            {
                "title": "高可见 public proof",
                "detail": "Review count, rating, badges, and review bodies create enough public proof to benchmark the product.",
                "citation_ids": amazon_ids,
            },
            {
                "title": "卖点可被拆解",
                "detail": "Title, bullets, and reviews expose the product's claimed benefits and actual user language.",
                "citation_ids": amazon_ids,
            },
        ],
        "user_love": [
            {
                "title": "从正面 review 提取可复用表达",
                "detail": "Use collected review bodies to identify concrete praised outcomes before copying competitor claim language.",
                "citation_ids": amazon_ids,
            }
        ],
        "user_complaints": [
            {
                "title": "优先看跨平台重复痛点",
                "detail": "Complaints that appear in both Amazon reviews and Reddit discussion deserve R&D validation first.",
                "citation_ids": mixed_ids,
            }
        ],
        "rd_teardown": [
            {
                "title": "拆解结构-痛点映射",
                "detail": "Map support, smoothing, coverage, strap, wire, side support, and comfort claims to physical construction choices.",
                "citation_ids": amazon_ids,
            },
            {
                "title": "建立反向试穿清单",
                "detail": "Turn complaints into prototype test cases, especially fit drift, digging, shape, and under-shirt visibility.",
                "citation_ids": mixed_ids,
            },
        ],
        "brand_communication": [
            {
                "title": "用证据说话",
                "detail": "Brand copy should contrast against competitor claims only where review or Reddit evidence supports a real gap.",
                "citation_ids": mixed_ids,
            }
        ],
        "sales_proxy_interpretation": [
            {
                "title": "不能当真实销量",
                "detail": "The current MVP can read public proxies, but true sales needs seller data, BSR history, or paid Amazon estimates.",
                "citation_ids": amazon_ids,
            }
        ],
        "risks": [
            {
                "title": "销量误判",
                "detail": "Review count is cumulative and can lag current demand; it should not be interpreted as current weekly sales.",
                "citation_ids": amazon_ids,
            },
            {
                "title": "社媒样本偏差",
                "detail": "Reddit overrepresents vocal users and problem-solving contexts.",
                "citation_ids": reddit_ids or mixed_ids,
            },
            {
                "title": "网页证据可能偏营销",
                "detail": "Brand-owned pages validate claims but are not neutral proof.",
                "citation_ids": web_ids or mixed_ids,
            },
        ],
        "evidence_chain": [
            {"claim": item["title"], "detail": item["excerpt"], "citation_ids": [item["id"]]}
            for item in evidence_pool[:8]
        ],
        "data_gaps": [
            {
                "title": "真实销量",
                "detail": "Need paid estimates, seller-owned data, or repeated BSR snapshots to estimate sales volume.",
                "citation_ids": amazon_ids,
            },
            {
                "title": "近期趋势",
                "detail": "Need repeated weekly snapshots before judging whether the product is accelerating or fading.",
                "citation_ids": mixed_ids,
            },
            {
                "title": "用户画像",
                "detail": "Need owned survey/review tagging or panel data to move beyond platform-specific language.",
                "citation_ids": reddit_ids or mixed_ids,
            },
        ],
    }


def normalize_competitor_deep_dive_report(
    category: str,
    raw: dict[str, Any],
    evidence_pool: list[dict[str, Any]],
) -> dict[str, Any]:
    fallback_ids = [item["id"] for item in evidence_pool[:2]]
    verdict_raw = raw.get("verdict") if isinstance(raw.get("verdict"), dict) else {}
    return {
        "verdict": {
            "text": str(verdict_raw.get("text") or f"{category} has directional competitor evidence, but sales confidence remains limited."),
            "citations": resolve_citations(verdict_raw.get("citation_ids"), evidence_pool, fallback_ids),
        },
        "breakout_assessment": normalize_insight_items(raw.get("breakout_assessment"), 3, evidence_pool, fallback_ids, "爆款判断"),
        "why_it_sells": normalize_insight_items(raw.get("why_it_sells"), 3, evidence_pool, fallback_ids, "可能热卖原因"),
        "user_love": normalize_insight_items(raw.get("user_love"), 3, evidence_pool, fallback_ids, "用户喜欢"),
        "user_complaints": normalize_insight_items(raw.get("user_complaints"), 3, evidence_pool, fallback_ids, "用户抱怨"),
        "rd_teardown": normalize_insight_items(raw.get("rd_teardown"), 3, evidence_pool, fallback_ids, "研发拆解"),
        "brand_communication": normalize_insight_items(raw.get("brand_communication"), 3, evidence_pool, fallback_ids, "品牌沟通"),
        "sales_proxy_interpretation": normalize_insight_items(
            raw.get("sales_proxy_interpretation"),
            2,
            evidence_pool,
            fallback_ids,
            "销量代理解读",
        ),
        "risks": normalize_insight_items(raw.get("risks"), 3, evidence_pool, fallback_ids, "风险"),
        "evidence_chain": normalize_chain_items(raw.get("evidence_chain"), evidence_pool, fallback_ids),
        "data_gaps": normalize_insight_items(raw.get("data_gaps"), 3, evidence_pool, fallback_ids, "数据缺口"),
    }


def ensure_competitor_run_active(run_id: str) -> None:
    if run_id and is_run_cancelled(run_id):
        raise OperationCancelled("Competitor analysis stopped by user.")


def cancel_competitor_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(payload.get("runId") or payload.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("runId is required")
    result = request_run_cancel(run_id)
    return {
        "ok": bool(result.get("ok")),
        "run_id": result.get("run_id") or run_id,
        "terminated_processes": result.get("terminated_processes", 0),
        "message": "Competitor analysis cancellation requested.",
    }


def analyze_competitor_deep_dive(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(payload.get("runId") or payload.get("run_id") or "").strip()
    token = set_current_run_id(run_id)
    try:
        return _analyze_competitor_deep_dive(payload, run_id)
    finally:
        reset_current_run_id(token)
        clear_run_cancel(run_id)


def _analyze_competitor_deep_dive(payload: dict[str, Any], run_id: str = "") -> dict[str, Any]:
    ensure_competitor_run_active(run_id)
    seed_product = normalize_competitor_product_seed(payload)
    category = competitor_category_context(seed_product, payload)
    bypass_cache = bool(payload.get("bypassCache"))
    use_llm = payload.get("useLlm", True) is not False
    locale = str(payload.get("locale") or "zh")
    values = read_settings_values()
    amazon_review_limit = max(
        0,
        min(int(payload.get("amazonReviewLimit") or values.get("COMPETITOR_AMAZON_REVIEW_LIMIT", "80") or 80), 300),
    )
    reddit_limit = max(
        5,
        min(int(payload.get("redditLimit") or values.get("INSIGHT_RESEARCH_POST_LIMIT", "50") or 50), MAX_RESEARCH_POST_LIMIT),
    )
    reddit_detail_limit_raw = payload.get("redditDetailLimit")
    if reddit_detail_limit_raw is None:
        reddit_detail_limit_raw = values.get("AGENT_REACH_DETAIL_LIMIT", "8") or 8
    reddit_comments_per_post_raw = payload.get("redditCommentsPerPost")
    if reddit_comments_per_post_raw is None:
        reddit_comments_per_post_raw = values.get("AGENT_REACH_COMMENTS_PER_POST", "20") or 20
    try:
        reddit_detail_limit = int(reddit_detail_limit_raw)
    except (TypeError, ValueError):
        reddit_detail_limit = 8
    try:
        reddit_comments_per_post = int(reddit_comments_per_post_raw)
    except (TypeError, ValueError):
        reddit_comments_per_post = 20
    reddit_detail_limit = max(0, min(reddit_detail_limit, 100))
    reddit_comments_per_post = max(0, min(reddit_comments_per_post, 200))
    web_candidate_limit = max(0, min(int(payload.get("webCandidateLimit") or 6), 12))
    ai_review_limit = max(1, min(int(payload.get("aiReviewLimit") or 40), 100))
    ai_reddit_post_limit = max(1, min(int(payload.get("aiRedditPostLimit") or 20), 100))
    time_range = str(payload.get("timeRange") or "all")
    if time_range not in {"day", "week", "month", "year", "all"}:
        time_range = "all"
    mode = str(payload.get("mode") or values.get("INSIGHT_RESEARCH_MODE", "auto") or "auto")
    if mode not in {"auto", "agent_reach", "oauth", "rss", "sample"}:
        mode = "auto"

    product, amazon_warnings = collect_competitor_amazon_product(
        seed_product,
        amazon_review_limit,
        bypass_cache=bypass_cache,
    )
    ensure_competitor_run_active(run_id)
    reddit_query = competitor_product_search_phrase(product, max_words=10)
    reddit_posts, reddit_warnings, reddit_source_mode = collect_reddit(
        reddit_query,
        reddit_limit,
        time_range,
        mode,
        bypass_cache=bypass_cache,
        detail_limit=reddit_detail_limit,
        comments_per_post=reddit_comments_per_post,
    )
    ensure_competitor_run_active(run_id)
    reddit_report = summarize_posts(reddit_query, reddit_posts, reddit_source_mode, reddit_warnings)
    reddit_report["data_volume"] = build_data_volume_stats(
        reddit_limit,
        reddit_posts,
        reddit_source_mode,
        use_llm,
        detail_limit_override=reddit_detail_limit,
        comments_per_post_override=reddit_comments_per_post,
    )
    ensure_competitor_run_active(run_id)

    web_sources = discover_competitor_web_sources(
        product,
        category,
        web_candidate_limit,
        bypass_cache=bypass_cache,
        run_id=run_id,
    ) if web_candidate_limit else {
        "source_mode": "web_search_skipped",
        "queries": [],
        "candidates": [],
        "articles": [],
        "warnings": ["Brand/web source discovery was skipped because webCandidateLimit is 0."],
        "data_volume": {"query_count": 0, "raw_results": 0, "candidate_count": 0, "readable_sources": 0, "failed_sources": 0, "per_query_counts": []},
    }
    ensure_competitor_run_active(run_id)

    sales_proxy = build_competitor_sales_proxy(product)
    evidence_pool = build_competitor_evidence_pool(
        product,
        reddit_report,
        web_sources,
        ai_review_limit,
        ai_reddit_post_limit,
    )
    context = build_competitor_deep_dive_context(
        product,
        category,
        reddit_report,
        web_sources,
        sales_proxy,
        evidence_pool,
    )
    warnings = [*amazon_warnings, *(web_sources.get("warnings") or [])]
    raw: dict[str, Any] | None = None
    llm_analysis = {
        "enabled": False,
        "status": "not_requested",
        "message": "AI synthesis was not requested; generated a rule-based competitor deep dive.",
    }
    ensure_competitor_run_active(run_id)
    if use_llm:
        try:
            enhanced = enhance_competitor_deep_dive_with_llm(context, locale=locale)
            ensure_competitor_run_active(run_id)
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
        raw = build_fallback_competitor_deep_dive_raw(category, product, reddit_report, sales_proxy, evidence_pool)

    narrative = normalize_competitor_deep_dive_report(category, raw, evidence_pool)
    reviews = product.get("review_samples") if isinstance(product.get("review_samples"), list) else []
    source_status = {
        "amazon": "ready" if product.get("product_url") or reviews else "partial",
        "reddit": "ready" if reddit_posts else "partial",
        "web": "ready" if web_sources.get("articles") else "partial",
    }
    return {
        "category": category,
        "generated_at": now_iso(),
        "source_mode": "competitor_deep_dive",
        "source_status": source_status,
        "warnings": warnings,
        "product": product,
        "data_volume": {
            "amazon_reviews_requested": amazon_review_limit,
            "amazon_reviews_collected": len(reviews),
            "reddit_posts_requested": reddit_limit,
            "reddit_posts_collected": int(reddit_report["data_volume"]["collected_posts"]),
            "reddit_detail_posts_requested": reddit_detail_limit,
            "reddit_comments_per_post_requested": reddit_comments_per_post,
            "reddit_comments_collected": int(reddit_report["data_volume"]["collected_comments"]),
            "web_candidates": int((web_sources.get("data_volume") or {}).get("candidate_count") or 0),
            "web_sources_read": int((web_sources.get("data_volume") or {}).get("readable_sources") or 0),
            "ai_review_limit": ai_review_limit,
            "ai_reviews": min(len(reviews), ai_review_limit),
            "ai_reddit_post_limit": ai_reddit_post_limit,
            "ai_reddit_posts": min(int(reddit_report["data_volume"]["collected_posts"]), ai_reddit_post_limit),
            "ai_evidence_items": len(evidence_pool),
        },
        "sales_proxy": sales_proxy,
        "amazon": {
            "product": product,
            "review_samples": reviews,
            "warnings": amazon_warnings,
        },
        "reddit": reddit_report,
        "web": web_sources,
        "evidence_pool": evidence_pool,
        "llm_analysis": llm_analysis,
        "method": {
            "query": reddit_query,
            "notes": [
                "This deep dive starts from a monitored Amazon product and enriches it with product details and review/discussion samples.",
                "Reddit is queried with the product brand/title phrase to find product-specific or brand-adjacent user discussion.",
                "Brand-site and media pages are discovered through the Agent Reach web-search route, then read through Jina Reader when accessible.",
                "Sales volume is not directly observable here; the report separates true-sales gaps from proxy signals such as review count, rating, badges, and sponsorship.",
                "LLM context is capped to keep reports stable; the data-volume block shows collected items versus items included in the AI evidence pool.",
            ],
        },
        **narrative,
    }


def article_search_terms(category: str) -> list[str]:
    lowered = category.lower()
    terms = [category.strip()]
    alias_phrases = {
        "大胸显小": "minimizer bra large bust",
        "显小": "minimizer bra",
        "大胸": "large bust bra",
        "无钢圈": "wireless bra",
        "钢圈": "underwire bra",
        "运动": "sports bra",
        "哺乳": "nursing bra",
        "睡眠": "sleep bra",
        "文胸": "bra",
        "内衣": "bra",
    }
    for needle, replacement in alias_phrases.items():
        if needle in category:
            terms.append(replacement)
    if "large bust" in lowered or "full bust" in lowered or "minimizer" in lowered:
        terms.append("minimizer bra large bust")
    if "wireless" in lowered:
        terms.append("wireless bra large bust")
    if "bra" not in lowered and not any("bra" in term.lower() for term in terms):
        terms.append(f"{category.strip()} bra")
    return unique_strings(terms)


def build_article_search_queries(category: str, limit: int = 12, include_industry_reports: bool = True) -> list[str]:
    base_terms = article_search_terms(category)
    primary = base_terms[0]
    queries: list[str] = [
        f"best {primary} tested",
        f"{primary} expert review",
        f"{primary} best bras 2026",
        f"{primary} ranking review",
    ]
    queries.extend([f"site:{domain} {primary}" for domain in ARTICLE_SEARCH_SITE_DOMAINS])
    for term in base_terms[1:3]:
        queries.extend([f"best {term} tested", f"{term} expert review"])
    if include_industry_reports:
        queries.extend(
            [
                f"{primary} market size United States 2026",
                "bra market size United States 2026",
                "women lingerie market United States 2026",
            ]
        )
    return unique_strings(queries)[:limit]


def normalize_discovery_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urllib.parse.urlunparse(parsed._replace(query="", fragment=""))


def search_provider_credentials() -> tuple[str, dict[str, str]]:
    values = read_settings_values()
    provider = selected_web_search_provider(values)
    if provider.name == "agent_reach":
        return provider.name, {}
    api_key = values.get(provider.api_key_env, "")
    if not configured_secret(api_key):
        raise ValueError(f"{provider.label} API key is not configured. Add it in Settings > Web Search.")
    credentials = {"api_key": api_key}
    if provider.requires_search_engine_id and provider.search_engine_id_env:
        search_engine_id = values.get(provider.search_engine_id_env, "")
        if not configured_secret(search_engine_id):
            raise ValueError(f"{provider.label} search engine id is not configured. Add it in Settings > Web Search.")
        credentials["search_engine_id"] = search_engine_id
    return provider.name, credentials


def parse_json_loose(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    match = re.search(r"(\{.*\}|\[.*\])", stripped, flags=re.S)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    return None


def extract_search_results_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        if all(isinstance(item, dict) and (item.get("url") or item.get("link") or item.get("href")) for item in payload):
            return [item for item in payload if isinstance(item, dict)]
        results: list[dict[str, Any]] = []
        for item in payload:
            results.extend(extract_search_results_from_payload(item))
        return results
    if not isinstance(payload, dict):
        return []

    for key in ("results", "items", "web", "data"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested = extract_search_results_from_payload(value)
            if nested:
                return nested
        if isinstance(value, list):
            nested = extract_search_results_from_payload(value)
            if nested:
                return nested

    content = payload.get("content")
    if isinstance(content, list):
        nested_results: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                nested_payload = parse_json_loose(item["text"])
                nested_results.extend(extract_search_results_from_payload(nested_payload))
                if not nested_results:
                    nested_results.extend(parse_mcporter_text_search_results(item["text"]))
        if nested_results:
            return nested_results

    if payload.get("url") or payload.get("link") or payload.get("href"):
        return [payload]
    return []


def parse_mcporter_text_search_results(text: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    blocks = re.split(r"\n\s*---\s*\n", text.strip())
    for block in blocks:
        title = ""
        url = ""
        published = ""
        highlights: list[str] = []
        in_highlights = False
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("Title:"):
                title = line.split(":", 1)[1].strip()
                in_highlights = False
            elif line.startswith("URL:"):
                url = line.split(":", 1)[1].strip()
                in_highlights = False
            elif line.startswith("Published:"):
                published = line.split(":", 1)[1].strip()
                in_highlights = False
            elif line.startswith("Highlights:"):
                in_highlights = True
            elif in_highlights:
                highlights.append(line)
        if url:
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": clean_text(" ".join(highlights)),
                    "published": published,
                }
            )
    return results


def search_agent_reach_exa(query: str, count: int) -> list[dict[str, Any]]:
    if not resolve_command("mcporter"):
        raise ValueError(
            "Agent Reach web search route is unavailable because mcporter is not installed or not on PATH. "
            "Install/enable Agent Reach search tooling, or set AGENT_REACH_BIN_DIR in Settings."
        )
    mcporter_config = Path.home() / ".agent-reach" / "mcporter.json"
    if not mcporter_config.exists():
        raise ValueError(
            f"Agent Reach search config is missing at {mcporter_config}. "
            "Run scripts\\install-agent-reach.ps1 or configure mcporter exa manually."
        )
    escaped_query = query.replace("\\", "\\\\").replace('"', '\\"')
    call_expr = f'exa.web_search_exa(query: "{escaped_query}", numResults: {max(1, min(count, 10))})'
    code, stdout, stderr = run_command(
        ["mcporter", "--config", str(mcporter_config), "call", call_expr, "--output", "json"],
        45,
    )
    if code != 0:
        raise ValueError(stderr.strip() or stdout.strip() or f"mcporter exited with code {code}")
    payload = parse_json_loose(stdout)
    raw_results = extract_search_results_from_payload(payload)
    if not raw_results:
        raw_results = parse_mcporter_text_search_results(stdout)
    return [
        {
            "title": item.get("title") or item.get("name") or "",
            "url": item.get("url") or item.get("link") or item.get("href") or "",
            "snippet": item.get("snippet") or item.get("description") or item.get("text") or item.get("content") or "",
            "published": item.get("publishedDate") or item.get("published_date") or item.get("date") or "",
        }
        for item in raw_results
        if isinstance(item, dict)
    ]


def web_search_query(
    query: str,
    count: int,
    bypass_cache: bool = False,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    provider, credentials = search_provider_credentials()
    cache_path = cache_key([CACHE_VERSION, "web-search", provider, query, str(count)])
    if not bypass_cache:
        cached = read_cache(cache_path, ANALYSIS_CACHE_TTL_SECONDS)
        if isinstance(cached, dict) and isinstance(cached.get("results"), list):
            return provider, cached["results"], []

    warnings: list[str] = []
    if provider == "agent_reach":
        results = search_agent_reach_exa(query, count)
    elif provider == "brave":
        params = urllib.parse.urlencode(
            {
                "q": query,
                "count": max(1, min(count, 10)),
                "country": "us",
                "search_lang": "en",
                "spellcheck": 1,
            }
        )
        body = http_get(
            f"https://api.search.brave.com/res/v1/web/search?{params}",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": credentials["api_key"],
            },
            timeout=25,
        )
        payload = json.loads(body.decode("utf-8"))
        raw_results = ((payload.get("web") or {}).get("results") or []) if isinstance(payload, dict) else []
        results = [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
                "published": item.get("age") or item.get("page_age") or "",
            }
            for item in raw_results
            if isinstance(item, dict)
        ]
    elif provider == "tavily":
        body = http_post_json(
            "https://api.tavily.com/search",
            {
                "api_key": credentials["api_key"],
                "query": query,
                "search_depth": "basic",
                "max_results": max(1, min(count, 10)),
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=30,
        )
        payload = json.loads(body.decode("utf-8"))
        raw_results = payload.get("results") if isinstance(payload, dict) else []
        results = [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
                "published": item.get("published_date") or "",
            }
            for item in (raw_results if isinstance(raw_results, list) else [])
            if isinstance(item, dict)
        ]
    elif provider == "google_cse":
        params = urllib.parse.urlencode(
            {
                "key": credentials["api_key"],
                "cx": credentials["search_engine_id"],
                "q": query,
                "num": max(1, min(count, 10)),
            }
        )
        body = http_get(f"https://www.googleapis.com/customsearch/v1?{params}", timeout=25)
        payload = json.loads(body.decode("utf-8"))
        raw_results = payload.get("items") if isinstance(payload, dict) else []
        results = [
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "published": "",
            }
            for item in (raw_results if isinstance(raw_results, list) else [])
            if isinstance(item, dict)
        ]
    else:
        raise ValueError("Unsupported web search provider")

    write_cache(cache_path, {"results": results})
    if not results:
        warnings.append(f"No search results returned for query: {query}")
    return provider, results, warnings


def score_article_search_candidate(category: str, title: str, snippet: str, domain: str, url: str) -> tuple[int, str, list[str]]:
    if domain_matches(domain, ARTICLE_EXCLUDED_DOMAINS):
        return 0, "excluded", ["Excluded commerce/social/video domain."]

    text = f"{title} {snippet}".lower()
    category_terms = [
        term.lower()
        for term in re.split(r"[^A-Za-z0-9]+", " ".join(article_search_terms(category)))
        if len(term) >= 3
    ]
    source_type = classify_article_source(domain, title, snippet)
    score = 20
    reasons: list[str] = []

    if domain_matches(domain, ARTICLE_REVIEW_DOMAINS):
        score += 26
        reasons.append("Known US editorial/review domain.")
    if domain_matches(domain, ARTICLE_INDUSTRY_REPORT_DOMAINS):
        score += 28
        reasons.append("Known industry research/report domain.")
    if source_type in {"public_ranking", "media_review"}:
        score += 18
        reasons.append("Search result matches ranking/review framing.")
    if source_type == "industry_report":
        score += 15
        reasons.append("Search result matches market-size/report framing.")
    matched_terms = sorted({term for term in category_terms if term in text})
    if matched_terms:
        score += min(20, len(matched_terms) * 4)
        reasons.append(f"Matches category terms: {', '.join(matched_terms[:5])}.")
    if any(phrase in text for phrase in ["tested", "expert", "reviewed", "best", "editor"]):
        score += 10
        reasons.append("Mentions testing, editors, experts, or best-list language.")
    if re.search(r"\b20(?:2[4-9]|3[0-9])\b", text + " " + url):
        score += 6
        reasons.append("Recent year signal detected.")
    if any(phrase in text for phrase in ["affiliate", "commission", "sponsored"]):
        score -= 5
        reasons.append("Affiliate/commerce wording detected; treat directionally.")

    return max(0, min(100, score)), source_type, reasons[:5]


def discover_article_urls(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    if not category:
        raise ValueError("category is required")
    query_limit = max(1, min(int(payload.get("queryLimit") or 12), 25))
    results_per_query = max(1, min(int(payload.get("resultsPerQuery") or 5), 10))
    candidate_limit = max(1, min(int(payload.get("candidateLimit") or 20), 50))
    include_industry_reports = payload.get("includeIndustryReports", True) is not False
    bypass_cache = bool(payload.get("bypassCache"))

    queries = build_article_search_queries(category, query_limit, include_industry_reports=include_industry_reports)
    candidates_by_url: dict[str, dict[str, Any]] = {}
    per_query_counts: list[dict[str, Any]] = []
    warnings: list[str] = []
    raw_results = 0
    provider_name = selected_web_search_provider(read_settings_values()).name

    for query in queries:
        try:
            provider_name, results, query_warnings = web_search_query(query, results_per_query, bypass_cache=bypass_cache)
            warnings.extend(query_warnings)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            warnings.append(f"Search failed for {query}: {exc}")
            results = []
        raw_results += len(results)
        per_query_counts.append({"query": query, "count": len(results)})
        for rank, item in enumerate(results, start=1):
            url = normalize_discovery_url(str(item.get("url") or ""))
            if not url:
                continue
            domain = article_domain(url)
            title = clean_text(str(item.get("title") or ""))
            snippet = clean_text(str(item.get("snippet") or ""))
            score, source_type, reasons = score_article_search_candidate(category, title, snippet, domain, url)
            if score <= 0:
                continue
            existing = candidates_by_url.get(url)
            candidate = {
                "title": compact_text(title or domain or url, 180),
                "url": url,
                "domain": domain,
                "snippet": compact_text(snippet, 320),
                "provider": provider_name,
                "query": query,
                "rank": rank,
                "score": score,
                "source_type": source_type,
                "reasons": reasons,
                "published": str(item.get("published") or ""),
            }
            if not existing or candidate["score"] > existing["score"]:
                candidates_by_url[url] = candidate

    candidates = sorted(
        candidates_by_url.values(),
        key=lambda item: (int(item.get("score") or 0), -int(item.get("rank") or 99), item.get("domain") in ARTICLE_REVIEW_DOMAINS),
        reverse=True,
    )[:candidate_limit]
    status = "ready" if candidates else "failed" if warnings else "unavailable"
    failed_next_action = (
        "Install or enable local Agent Reach search tooling, set AGENT_REACH_BIN_DIR if needed, "
        "broaden the category, or paste known URLs manually."
        if provider_name == "agent_reach"
        else "Configure a web search API key, broaden the category, or paste known URLs manually."
    )
    return {
        "category": category,
        "generated_at": now_iso(),
        "source_mode": f"web_search_{provider_name}",
        "source": {
            "source_name": provider_name,
            "source_type": "web_search",
            "status": status,
            "collected_items_count": len(candidates),
            "evidence_items_count": len(candidates),
            "last_run_at": now_iso(),
            "failure_reason": "" if candidates else "No usable article URLs were discovered.",
            "next_action": "Review candidates, keep the relevant URLs, then run article collection."
            if candidates
            else failed_next_action,
        },
        "data_volume": {
            "query_count": len(queries),
            "results_per_query": results_per_query,
            "raw_results": raw_results,
            "unique_results": len(candidates_by_url),
            "candidate_count": len(candidates),
            "per_query_counts": per_query_counts,
        },
        "queries": queries,
        "candidates": candidates,
        "warnings": warnings,
        "method": {
            "notes": [
                "Article discovery generates deterministic search queries from the category and known media/report source patterns.",
                "The search route only discovers candidate URLs; article bodies are read later by the existing Agent Reach Web / Jina Reader path.",
                "Scores prioritize known editorial/review/report domains, category-term matches, ranking/review language, and recency signals.",
            ],
        },
    }


def domain_matches(domain: str, candidates: set[str]) -> bool:
    return any(domain == candidate or domain.endswith(f".{candidate}") for candidate in candidates)


def article_domain(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()
    return domain.removeprefix("www.")


def extract_article_urls(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    raw_urls = payload.get("urls") or payload.get("articleUrls") or payload.get("url") or ""
    if isinstance(raw_urls, str):
        values = re.split(r"[\s,]+", raw_urls)
    elif isinstance(raw_urls, list):
        values = [str(item) for item in raw_urls]
    else:
        values = []

    urls: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = value.strip()
        if not url:
            continue
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            warnings.append(f"Skipped invalid article URL: {url}")
            continue
        normalized = urllib.parse.urlunparse(parsed._replace(fragment=""))
        if normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)
    return urls, warnings


def fetch_article_markdown(url: str, bypass_cache: bool = False) -> str:
    cache_path = cache_key([CACHE_VERSION, "agent-reach-web-article", url])
    if not bypass_cache:
        cached = read_cache(cache_path, ANALYSIS_CACHE_TTL_SECONDS)
        if isinstance(cached, dict) and isinstance(cached.get("body"), str):
            return cached["body"]

    reader_url = f"https://r.jina.ai/{url}"
    body = http_get(reader_url, headers={"Accept": "text/plain"}, timeout=35).decode("utf-8", errors="replace")
    if not body.strip():
        raise ValueError("Jina Reader returned an empty article body")
    write_cache(cache_path, {"body": body, "reader_url": reader_url})
    return body


def article_title_from_markdown(markdown: str, url: str) -> str:
    for line in markdown.splitlines()[:20]:
        cleaned = line.strip()
        if cleaned.lower().startswith("title:"):
            title = cleaned.split(":", 1)[1].strip()
            if title:
                return compact_text(title, 180)
    for line in markdown.splitlines():
        cleaned = line.strip()
        if cleaned.startswith("#"):
            title = cleaned.lstrip("#").strip()
            if title:
                return compact_text(title, 180)
    return article_domain(url) or url


def article_markdown_to_text(markdown: str) -> str:
    text = re.sub(r"(?im)^(title|url source|markdown content):.*$", " ", markdown)
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"[#*_>`~-]+", " ", text)
    return clean_text(text)


def classify_article_source(domain: str, title: str, text: str) -> str:
    lowered = f"{title} {text[:1200]}".lower()
    if domain_matches(domain, ARTICLE_INDUSTRY_REPORT_DOMAINS) or any(
        phrase in lowered
        for phrase in [
            "market size",
            "market report",
            "industry report",
            "market share",
            "forecast period",
            "compound annual growth",
            "cagr",
        ]
    ):
        return "industry_report"
    if any(phrase in lowered for phrase in ["best bras", "best minimizer", "top bras", "best full coverage"]):
        return "public_ranking"
    if any(phrase in lowered for phrase in ["reviewed", "tested", "editor-tested", "lab-tested", "expert-approved"]):
        return "media_review"
    return "media_article"


def extract_article_signals(text: str) -> list[str]:
    lowered = text.lower()
    signals: list[str] = []
    seen: set[str] = set()
    for term, label in ARTICLE_SIGNAL_TERMS.items():
        if term in lowered and label not in seen:
            seen.add(label)
            signals.append(label)
    return signals


def score_article_authority(domain: str, source_type: str, title: str, text: str) -> tuple[int, str, list[str], list[str]]:
    lowered = f"{title} {text}".lower()
    score = 25
    evidence: list[str] = []
    cautions: list[str] = []

    if domain_matches(domain, ARTICLE_REVIEW_DOMAINS):
        score += 22
        evidence.append("Known US editorial/review domain baseline.")
    if domain_matches(domain, ARTICLE_INDUSTRY_REPORT_DOMAINS):
        score += 28
        evidence.append("Known industry research/report domain baseline.")
    if source_type == "industry_report":
        score += 12
        evidence.append("Article language matches industry report or market-size framing.")
    if source_type in {"media_review", "public_ranking"}:
        score += 8
        evidence.append("Article language matches review/ranking framing.")

    if re.search(r"\bby\s+[A-Z][A-Za-z .'-]{2,80}\b", text[:1600]):
        score += 8
        evidence.append("Byline-like author metadata detected.")
    else:
        cautions.append("No clear byline was detected in the readable text.")
    if re.search(r"\b(?:20[1-3][0-9]|Jan\.?|Feb\.?|Mar\.?|Apr\.?|May|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Oct\.?|Nov\.?|Dec\.?)\b", text[:2200]):
        score += 7
        evidence.append("Date or update metadata detected.")
    else:
        cautions.append("No clear publish/update date was detected.")

    if any(phrase in lowered for phrase in ["tested", "reviewed", "lab", "expert", "editor", "dermatologist", "fit specialist"]):
        score += 12
        evidence.append("Testing, expert, or editorial review language detected.")
    if len(extract_brands(text)) >= 2:
        score += 8
        evidence.append("Multiple known bra/lingerie brands are mentioned.")
    if len(text) >= 1800:
        score += 6
        evidence.append("Readable body is long enough for directional analysis.")
    if any(phrase in lowered for phrase in ["affiliate", "commission", "may earn", "sponsored"]):
        score -= 5
        cautions.append("Commerce/affiliate disclosure detected; treat rankings as directional, not neutral.")
    if len(text) < 700:
        score -= 10
        cautions.append("Readable text is short; article may be paywalled, truncated, or weakly extracted.")

    score = max(0, min(100, score))
    if score >= 70:
        level = "High"
    elif score >= 45:
        level = "Medium"
    else:
        level = "Low"
    return score, level, evidence[:6], cautions[:5]


def article_snippets(text: str, brands: list[str], signals: list[str]) -> list[str]:
    needles = [brand.lower() for brand in brands] + [signal.split(" / ", 1)[0].lower() for signal in signals]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    snippets: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        cleaned = compact_text(clean_text(sentence), 280)
        if len(cleaned) < 45:
            continue
        lowered = cleaned.lower()
        if needles and not any(needle and needle in lowered for needle in needles):
            continue
        if cleaned not in seen:
            seen.add(cleaned)
            snippets.append(cleaned)
        if len(snippets) >= 5:
            break
    if not snippets and text:
        snippets.append(compact_text(text, 280))
    return snippets


def build_article_item(url: str, markdown: str) -> dict[str, Any]:
    title = article_title_from_markdown(markdown, url)
    text = article_markdown_to_text(markdown)
    domain = article_domain(url)
    source_type = classify_article_source(domain, title, text)
    brands = sorted(set(extract_brands(f"{title} {text}")), key=str.lower)
    signals = extract_article_signals(f"{title} {text}")
    authority_score, authority_level, authority_evidence, cautions = score_article_authority(
        domain,
        source_type,
        title,
        text,
    )
    snippets = article_snippets(text, brands, signals)
    return {
        "title": title,
        "url": url,
        "domain": domain,
        "source_type": source_type,
        "authority_score": authority_score,
        "authority_level": authority_level,
        "authority_evidence": authority_evidence,
        "cautions": cautions,
        "brand_mentions": brands,
        "product_signals": signals,
        "evidence_snippets": snippets,
        "readable_chars": len(text),
        "fetched_at": now_iso(),
    }


def analyze_articles(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    if not category:
        raise ValueError("category is required")
    limit = int(payload.get("limit") or 12)
    limit = max(1, min(limit, 30))
    bypass_cache = bool(payload.get("bypassCache"))
    urls, warnings = extract_article_urls(payload)
    urls = urls[:limit]
    if not urls:
        raise ValueError("At least one valid http(s) article URL is required")

    articles: list[dict[str, Any]] = []
    failed_urls = 0
    for url in urls:
        try:
            markdown = fetch_article_markdown(url, bypass_cache=bypass_cache)
            articles.append(build_article_item(url, markdown))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            failed_urls += 1
            warnings.append(f"Failed to read {url}: {exc}")

    domain_counts = Counter(article["domain"] for article in articles)
    brand_counts: Counter[str] = Counter()
    signal_counts: Counter[str] = Counter()
    source_type_counts = Counter(article["source_type"] for article in articles)
    for article in articles:
        brand_counts.update(article.get("brand_mentions") or [])
        signal_counts.update(article.get("product_signals") or [])

    evidence_items = sum(len(article.get("evidence_snippets") or []) for article in articles)
    status = "ready" if articles and not failed_urls else "partial" if articles else "failed"
    return {
        "category": category,
        "generated_at": now_iso(),
        "source_mode": "agent_reach_web",
        "source": {
            "source_name": "Agent Reach Web / Jina Reader",
            "source_type": "web_article_reader",
            "status": status,
            "collected_items_count": len(articles),
            "evidence_items_count": evidence_items,
            "last_run_at": now_iso(),
            "failure_reason": "" if articles else "No readable article bodies were collected.",
            "next_action": "Use high/medium authority articles as evidence; add more URLs for weak domains or thin extractions."
            if articles
            else "Check article URLs, avoid paywalled pages, or paste accessible report/article links.",
        },
        "data_volume": {
            "requested_articles": len(urls),
            "collected_articles": len(articles),
            "failed_articles": failed_urls,
            "high_authority_articles": sum(1 for article in articles if article["authority_level"] == "High"),
            "medium_authority_articles": sum(1 for article in articles if article["authority_level"] == "Medium"),
            "low_authority_articles": sum(1 for article in articles if article["authority_level"] == "Low"),
            "evidence_snippets": evidence_items,
        },
        "summary": {
            "top_domains": [{"name": name, "count": count} for name, count in domain_counts.most_common(10)],
            "top_brands": [{"name": name, "count": count} for name, count in brand_counts.most_common(12)],
            "top_signals": [{"name": name, "count": count} for name, count in signal_counts.most_common(12)],
            "source_types": [{"name": name, "count": count} for name, count in source_type_counts.most_common(6)],
        },
        "articles": articles,
        "warnings": warnings,
        "method": {
            "query": category,
            "notes": [
                "This source reads user-provided public URLs through the Agent Reach web route, using Jina Reader for readable article text.",
                "Authority score is a heuristic based on source domain, byline/date signals, testing language, article length, brand evidence, and affiliate cautions.",
                "Public rankings and media reviews are directional evidence; do not treat a single article as product truth or sales proof.",
                "Professional industry reports can be included when the URL/PDF is publicly accessible or provided with authorization; this tool does not bypass paywalls.",
                "Keyword-based article discovery should be added after a configured search backend such as Exa, Google CSE, or SerpAPI is available.",
            ],
        },
    }


def youtube_collection_settings() -> dict[str, int]:
    values = read_settings_values()
    return {
        "transcript_video_limit": int_setting(values, "YOUTUBE_TRANSCRIPT_VIDEO_LIMIT", 5, 0, 20),
        "comment_video_limit": int_setting(values, "YOUTUBE_COMMENT_VIDEO_LIMIT", 3, 0, 20),
        "comments_per_video": int_setting(values, "YOUTUBE_COMMENTS_PER_VIDEO", 10, 0, 50),
        "timeout_seconds": int_setting(values, "YOUTUBE_TIMEOUT_SECONDS", 120, 20, 600),
    }


def collect_youtube(
    category: str,
    limit: int,
    bypass_cache: bool = False,
    settings_override: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], list[str], str, dict[str, int]]:
    settings = youtube_collection_settings()
    if settings_override:
        settings = {**settings, **settings_override}
    cache_path = cache_key(
        [
            CACHE_VERSION,
            "youtube",
            category,
            str(limit),
            str(settings["transcript_video_limit"]),
            str(settings["comment_video_limit"]),
            str(settings["comments_per_video"]),
        ]
    )
    cached = None if bypass_cache else read_cache(cache_path, ttl_seconds=ANALYSIS_CACHE_TTL_SECONDS)
    if cached:
        return (
            cached.get("videos") or [],
            ["Loaded YouTube input from local cache."],
            str(cached.get("mode") or "youtube_ytdlp"),
            settings,
        )

    result = fetch_youtube_ytdlp(
        category,
        limit,
        transcript_video_limit=settings["transcript_video_limit"],
        comment_video_limit=settings["comment_video_limit"],
        comments_per_video=settings["comments_per_video"],
        timeout_seconds=settings["timeout_seconds"],
    )
    videos = result.videos
    for video in videos:
        video["fetched_at"] = now_iso()
    warnings = list(result.warnings)
    if bypass_cache:
        warnings.append("Bypassed local cache for YouTube analysis.")
    write_cache(cache_path, {"videos": videos, "mode": result.source_mode})
    return videos, warnings, result.source_mode, settings


def youtube_video_text(video: dict[str, Any]) -> str:
    comments = " ".join(
        str(comment.get("text") or "")
        for comment in video.get("comment_samples") or []
        if isinstance(comment, dict)
    )
    return " ".join(
        [
            str(video.get("title") or ""),
            str(video.get("description") or ""),
            str(video.get("transcript") or "")[:2500],
            comments,
        ]
    )


def summarize_youtube(
    category: str,
    videos: list[dict[str, Any]],
    source_mode: str,
    warnings: list[str],
    settings: dict[str, int],
) -> dict[str, Any]:
    channel_counts = Counter(str(video.get("channel") or "Unknown") for video in videos)
    channel_counts.pop("", None)
    view_counts = [int(video["view_count"]) for video in videos if isinstance(video.get("view_count"), int)]
    like_counts = [int(video["like_count"]) for video in videos if isinstance(video.get("like_count"), int)]
    comment_counts = [int(video["comment_count"]) for video in videos if isinstance(video.get("comment_count"), int)]
    transcript_chars = sum(int(video.get("transcript_chars") or 0) for video in videos)
    comment_samples = sum(len(video.get("comment_samples") or []) for video in videos)
    sentiment_counts = Counter()
    topic_counts = Counter()
    topic_examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    brand_counts = Counter()
    signal_counts = Counter()
    for video in videos:
        text = youtube_video_text(video)
        sentiment_counts[score_sentiment(text)] += 1
        for topic in matching_topics(text):
            topic_counts[topic] += 1
            if len(topic_examples[topic]) < 3:
                topic_examples[topic].append(
                    {
                        "title": str(video.get("title") or ""),
                        "channel": str(video.get("channel") or ""),
                        "url": str(video.get("url") or ""),
                        "snippet": compact_text(text, 220),
                    }
                )
        brand_counts.update(extract_brands(text))
        signal_counts.update(extract_article_signals(text))
    total_sentiment = max(1, sum(sentiment_counts.values()))
    confidence = "Medium" if len(videos) >= 8 else "Low"
    if len(videos) >= 15 and (transcript_chars or comment_samples):
        confidence = "High"
    top_topic = topic_counts.most_common(1)[0][0] if topic_counts else "No repeated product pain point detected"
    total_views = sum(view_counts)
    market_score = min(
        100,
        int(20 + len(videos) * 2 + min(35, total_views.bit_length() * 3) + min(20, comment_samples)),
    )
    pain_points = [
        {
            "topic": topic,
            "count": count,
            "share": round(count / max(1, len(videos)), 3),
            "examples": topic_examples.get(topic, []),
        }
        for topic, count in topic_counts.most_common(8)
    ]
    return {
        "category": category,
        "generated_at": now_iso(),
        "source_mode": source_mode,
        "warnings": warnings,
        "confidence": confidence,
        "source": {
            "source_name": "Agent Reach YouTube / yt-dlp",
            "source_type": "youtube_video_search",
            "status": "ready" if videos else "failed",
            "collected_items_count": len(videos),
            "evidence_items_count": len(videos) + comment_samples + sum(1 for video in videos if video.get("transcript")),
            "last_run_at": now_iso(),
            "failure_reason": "" if videos else "No YouTube videos were collected.",
            "next_action": "Use video titles, creator language, transcripts, and comments as directional social evidence."
            if videos
            else "Install yt-dlp or rerun with a narrower English YouTube query.",
        },
        "data_volume": {
            "requested_videos": len(videos),
            "collected_videos": len(videos),
            "transcript_video_limit": settings["transcript_video_limit"],
            "videos_with_transcripts": sum(1 for video in videos if video.get("transcript")),
            "transcript_chars": transcript_chars,
            "comment_video_limit": settings["comment_video_limit"],
            "comments_per_video_limit": settings["comments_per_video"],
            "comment_samples": comment_samples,
        },
        "metrics": {
            "videos": len(videos),
            "channels": len(channel_counts),
            "total_views": total_views,
            "videos_with_view_count": len(view_counts),
            "average_views": round(total_views / len(view_counts), 1) if view_counts else None,
            "total_likes": sum(like_counts),
            "videos_with_like_count": len(like_counts),
            "total_comment_count": sum(comment_counts),
            "videos_with_comment_count": len(comment_counts),
        },
        "market_signal": {
            "score": market_score if videos else 0,
            "summary": f"YouTube returned {len(videos)} videos across {len(channel_counts)} channels. Top repeated theme: {top_topic}.",
        },
        "sentiment": {
            "positive": sentiment_counts["positive"],
            "neutral": sentiment_counts["neutral"],
            "negative": sentiment_counts["negative"],
            "positive_share": round(sentiment_counts["positive"] / total_sentiment, 3),
            "negative_share": round(sentiment_counts["negative"] / total_sentiment, 3),
        },
        "channels": [{"name": name, "count": count} for name, count in channel_counts.most_common(12)],
        "pain_points": pain_points,
        "brands": [{"name": name, "count": count} for name, count in brand_counts.most_common(12)],
        "product_signals": [{"name": name, "count": count} for name, count in signal_counts.most_common(12)],
        "videos": videos,
        "method": {
            "query": category,
            "notes": [
                "This source uses Agent Reach's YouTube route through yt-dlp for search, metadata, subtitles, and best-effort comments.",
                "Manual captions are usually more reliable than auto-generated captions; auto captions may contain repeated lines.",
                "YouTube comments through yt-dlp are best-effort and can be incomplete or unavailable depending on the video and platform rate limits.",
                "YouTube visibility is directional social evidence; it is not a replacement for TikTok Shop, Amazon sales, or panel data.",
            ],
        },
        "llm_analysis": {
            "enabled": False,
            "status": "not_requested",
            "message": "YouTube collection is available; LLM synthesis can be added after the evidence format stabilizes.",
        },
    }


def analyze_youtube_category(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    if not category:
        raise ValueError("category is required")
    limit = int(payload.get("limit") or 12)
    limit = max(1, min(limit, 50))
    bypass_cache = bool(payload.get("bypassCache"))
    settings_override = {
        "transcript_video_limit": max(0, min(int(payload.get("youtubeTranscriptVideoLimit", 5)), 20)),
        "comment_video_limit": max(0, min(int(payload.get("youtubeCommentVideoLimit", 3)), 20)),
        "comments_per_video": max(0, min(int(payload.get("youtubeCommentsPerVideo", 10)), 50)),
    }
    videos, warnings, source_mode, settings = collect_youtube(
        category,
        limit,
        bypass_cache=bypass_cache,
        settings_override=settings_override,
    )
    report = summarize_youtube(category, videos, source_mode, warnings, settings)
    report["data_volume"]["requested_videos"] = limit
    return report


def tiktok_collection_settings() -> dict[str, int]:
    values = read_settings_values()
    return {
        "comments_per_video": int_setting(values, "TIKTOK_COMMENTS_PER_VIDEO", 10, 1, 50),
        "timeout_seconds": int_setting(values, "TIKTOK_TIMEOUT_SECONDS", 180, 30, 600),
    }


def collect_tiktok(
    category: str,
    limit: int,
    bypass_cache: bool = False,
    settings_override: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], list[str], str, dict[str, int]]:
    settings = tiktok_collection_settings()
    if settings_override:
        settings = {**settings, **settings_override}
    cache_path = cache_key(
        [
            CACHE_VERSION,
            "tiktok",
            category,
            str(limit),
            str(settings["comments_per_video"]),
        ]
    )
    cached = None if bypass_cache else read_cache(cache_path, ttl_seconds=ANALYSIS_CACHE_TTL_SECONDS)
    if cached:
        return (
            cached.get("videos") or [],
            ["Loaded TikTok input from local cache."],
            str(cached.get("mode") or "tiktok_playwright"),
            settings,
        )

    result = fetch_tiktok_playwright(
        category,
        limit,
        comments_per_video=settings["comments_per_video"],
        timeout_seconds=settings["timeout_seconds"],
    )
    videos = result.videos
    for video in videos:
        video["fetched_at"] = now_iso()
    warnings = list(result.warnings)
    if bypass_cache:
        warnings.append("Bypassed local cache for TikTok analysis.")
    write_cache(cache_path, {"videos": videos, "mode": result.source_mode})
    return videos, warnings, result.source_mode, settings


def tiktok_video_text(video: dict[str, Any]) -> str:
    comments = " ".join(
        str(comment.get("text") or "")
        for comment in video.get("comment_samples") or []
        if isinstance(comment, dict)
    )
    return " ".join(
        [
            str(video.get("title") or ""),
            str(video.get("caption") or ""),
            " ".join(str(tag) for tag in video.get("hashtags") or []),
            comments,
        ]
    )


def summarize_tiktok(
    category: str,
    videos: list[dict[str, Any]],
    source_mode: str,
    warnings: list[str],
    settings: dict[str, int],
) -> dict[str, Any]:
    author_counts = Counter(str(video.get("author") or "Unknown") for video in videos)
    author_counts.pop("", None)
    view_counts = [int(video["view_count"]) for video in videos if isinstance(video.get("view_count"), int)]
    like_counts = [int(video["like_count"]) for video in videos if isinstance(video.get("like_count"), int)]
    comment_counts = [int(video["comment_count"]) for video in videos if isinstance(video.get("comment_count"), int)]
    share_counts = [int(video["share_count"]) for video in videos if isinstance(video.get("share_count"), int)]
    comment_samples = sum(len(video.get("comment_samples") or []) for video in videos)
    hashtag_counts = Counter()
    sentiment_counts = Counter()
    topic_counts = Counter()
    topic_examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    brand_counts = Counter()
    signal_counts = Counter()
    for video in videos:
        text = tiktok_video_text(video)
        sentiment_counts[score_sentiment(text)] += 1
        hashtag_counts.update(str(tag).lstrip("#") for tag in video.get("hashtags") or [] if str(tag).strip())
        for topic in matching_topics(text):
            topic_counts[topic] += 1
            if len(topic_examples[topic]) < 3:
                topic_examples[topic].append(
                    {
                        "title": str(video.get("title") or video.get("caption") or ""),
                        "subreddit": str(video.get("author") or "TikTok"),
                        "url": str(video.get("url") or ""),
                        "snippet": compact_text(text, 220),
                    }
                )
        brand_counts.update(extract_brands(text))
        signal_counts.update(extract_article_signals(text))
    total_sentiment = max(1, sum(sentiment_counts.values()))
    confidence = "Low"
    if len(videos) >= 10 and comment_samples >= 30:
        confidence = "Medium"
    if len(videos) >= 20 and comment_samples >= 80:
        confidence = "High"
    top_topic = topic_counts.most_common(1)[0][0] if topic_counts else "No repeated product pain point detected"
    total_views = sum(view_counts)
    total_likes = sum(like_counts)
    market_score = min(
        100,
        int(15 + len(videos) * 2 + min(35, total_views.bit_length() * 3) + min(25, comment_samples)),
    )
    pain_points = [
        {
            "topic": topic,
            "count": count,
            "share": round(count / max(1, len(videos)), 3),
            "examples": topic_examples.get(topic, []),
        }
        for topic, count in topic_counts.most_common(8)
    ]
    return {
        "category": category,
        "generated_at": now_iso(),
        "source_mode": source_mode,
        "warnings": warnings,
        "confidence": confidence,
        "source": {
            "source_name": "TikTok Browser / Playwright",
            "source_type": "tiktok_video_search",
            "status": "ready" if videos else "failed",
            "collected_items_count": len(videos),
            "evidence_items_count": len(videos) + comment_samples,
            "last_run_at": now_iso(),
            "failure_reason": "" if videos else "No TikTok videos were collected.",
            "next_action": "Use TikTok captions, hashtags, creator language, and detail-page comments as directional social evidence."
            if videos
            else "Install Playwright Chromium, log in to TikTok in the opened browser, solve any challenge, then rerun with bypass cache.",
        },
        "data_volume": {
            "requested_videos": len(videos),
            "collected_videos": len(videos),
            "detail_pages_visited": len(videos),
            "comments_per_video_limit": settings["comments_per_video"],
            "comment_samples": comment_samples,
            "videos_with_comment_samples": sum(1 for video in videos if video.get("comment_samples")),
        },
        "metrics": {
            "videos": len(videos),
            "authors": len(author_counts),
            "total_views": total_views,
            "videos_with_view_count": len(view_counts),
            "average_views": round(total_views / len(view_counts), 1) if view_counts else None,
            "total_likes": total_likes,
            "videos_with_like_count": len(like_counts),
            "total_comment_count": sum(comment_counts),
            "videos_with_comment_count": len(comment_counts),
            "total_shares": sum(share_counts),
            "videos_with_share_count": len(share_counts),
        },
        "market_signal": {
            "score": market_score if videos else 0,
            "summary": f"TikTok returned {len(videos)} videos across {len(author_counts)} creators. Top repeated theme: {top_topic}.",
        },
        "sentiment": {
            "positive": sentiment_counts["positive"],
            "neutral": sentiment_counts["neutral"],
            "negative": sentiment_counts["negative"],
            "positive_share": round(sentiment_counts["positive"] / total_sentiment, 3),
            "negative_share": round(sentiment_counts["negative"] / total_sentiment, 3),
        },
        "authors": [{"name": name, "count": count} for name, count in author_counts.most_common(12)],
        "hashtags": [{"name": name, "count": count} for name, count in hashtag_counts.most_common(16)],
        "pain_points": pain_points,
        "brands": [{"name": name, "count": count} for name, count in brand_counts.most_common(12)],
        "product_signals": [{"name": name, "count": count} for name, count in signal_counts.most_common(12)],
        "videos": videos,
        "method": {
            "query": category,
            "notes": [
                "This source uses a local Playwright Chromium browser profile to search TikTok and open every collected video detail page.",
                "Comment samples are collected from video detail pages only; videos without readable detail-page comments are kept with warnings.",
                "The collector is read-only and stops at public browser-visible content; it does not bypass login, CAPTCHA, or platform restrictions.",
                "TikTok visibility is directional social evidence for language, creative angles, and pain points; it is not sales evidence.",
            ],
        },
        "llm_analysis": {
            "enabled": False,
            "status": "not_requested",
            "message": "TikTok collection is available; LLM synthesis can be added after the evidence format stabilizes.",
        },
    }


def analyze_tiktok_category(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    if not category:
        raise ValueError("category is required")
    limit = int(payload.get("limit") or 12)
    limit = max(1, min(limit, 30))
    bypass_cache = bool(payload.get("bypassCache"))
    settings_override = {
        "comments_per_video": max(1, min(int(payload.get("tiktokCommentsPerVideo", 10)), 50)),
    }
    videos, warnings, source_mode, settings = collect_tiktok(
        category,
        limit,
        bypass_cache=bypass_cache,
        settings_override=settings_override,
    )
    report = summarize_tiktok(category, videos, source_mode, warnings, settings)
    report["data_volume"]["requested_videos"] = limit
    return report


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
                2000,
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


AGENT_TOOL_CATALOG: dict[str, dict[str, str]] = {
    "reddit_voc": {
        "label": "Reddit VOC",
        "description": "Collect Reddit posts and comment samples for user pain points, language, and brand/size mentions.",
    },
    "amazon_shelf": {
        "label": "Amazon shelf",
        "description": "Collect Amazon search/product/review evidence for price, rating, review volume, claims, and brands.",
    },
    "media_rankings": {
        "label": "Media/ranking articles",
        "description": "Discover and read US media reviews, public rankings, and accessible report pages.",
    },
    "tiktok_social": {
        "label": "TikTok social validation",
        "description": "Collect TikTok videos and detail-page comment samples for social visibility and creator/user language.",
    },
}


def plan_agent_tools(
    prompt: str,
    mode: str,
    use_llm: bool,
) -> tuple[list[str], dict[str, Any]]:
    if not use_llm:
        return [], {
            "enabled": False,
            "status": "not_requested",
            "message": "Tool planning was skipped; no deterministic backend routing was used.",
        }
    try:
        planned = call_openai_compatible(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a tool-routing planner for an ecommerce market insight agent. "
                        "Return strict JSON only. Select the smallest useful set of callable data tools from the catalog. "
                        "Follow the user's prompt; do not use hidden backend defaults."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "ui_mode": mode,
                            "user_prompt": prompt,
                            "tool_catalog": AGENT_TOOL_CATALOG,
                            "rules": [
                                "Select tools only when the user prompt requires the evidence that tool can provide.",
                                "Use only tool names present in tool_catalog.",
                                "Do not select product workflow pages as tools; only data-source tools are callable.",
                                "If the prompt does not imply any concrete data source, return an empty tools array and explain why.",
                                "Return 0-4 tools.",
                            ],
                            "schema": {"tools": ["tool_name"], "reason": "string"},
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
        )
        raw_tools = (planned.get("result") or {}).get("tools") or []
        selected = [tool for tool in raw_tools if tool in AGENT_TOOL_CATALOG]
        return selected[:4], {
            "enabled": True,
            "status": "ok",
            "provider": planned.get("provider"),
            "model": planned.get("model"),
            "usage": planned.get("usage") or {},
            "message": (planned.get("result") or {}).get("reason") or "",
        }
    except LLMUnavailable as exc:
        return [], {"enabled": True, "status": "unavailable", "message": str(exc)}


def agent_category_from_payload(payload: dict[str, Any]) -> str:
    category = str(payload.get("category") or "").strip()
    if category:
        return category
    prompt = str(payload.get("prompt") or "").strip().lower()
    if "minimizer" in prompt:
        return "minimizer bra"
    if "large bust" in prompt:
        return "large bust bra"
    return "minimizer bra"


def agent_brief_for_category(category: str) -> dict[str, str]:
    brief = dict(DEFAULT_COMPETITOR_DISCOVERY_BRIEF)
    if category:
        brief["coreKeywords"] = category
    return brief


def compact_agent_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "reddit_voc":
        return {
            "coverage": result.get("coverage"),
            "market_signal": result.get("market_signal"),
            "sentiment": result.get("sentiment"),
            "pain_points": result.get("pain_points", [])[:5],
            "brands": result.get("brands", [])[:8],
            "sizes": result.get("sizes", [])[:8],
            "evidence": [
                {
                    "title": post.get("title"),
                    "url": post.get("url"),
                    "subreddit": post.get("subreddit"),
                    "excerpt": compact_text(str(post.get("excerpt") or ""), 260),
                }
                for post in result.get("posts", [])[:6]
            ],
        }
    if tool_name == "amazon_shelf":
        return {
            "metrics": result.get("metrics"),
            "price_bands": result.get("price_bands"),
            "brands": result.get("brands", [])[:10],
            "queries": result.get("queries", [])[:8],
            "products": [
                {
                    "asin": product.get("asin"),
                    "title": product.get("title"),
                    "brand": product.get("brand"),
                    "url": product.get("product_url"),
                    "price": product.get("price_text"),
                    "rating": product.get("rating_value"),
                    "reviews": product.get("review_count"),
                    "badges": product.get("badges", [])[:4],
                }
                for product in result.get("products", [])[:8]
            ],
        }
    if tool_name == "media_rankings":
        return {
            "summary": result.get("summary"),
            "articles": [
                {
                    "title": article.get("title"),
                    "domain": article.get("domain"),
                    "url": article.get("url"),
                    "source_type": article.get("source_type"),
                    "authority_level": article.get("authority_level"),
                    "product_signals": article.get("product_signals", [])[:5],
                }
                for article in result.get("articles", [])[:6]
            ],
        }
    if tool_name == "tiktok_social":
        return {
            "metrics": result.get("metrics"),
            "market_signal": result.get("market_signal"),
            "hashtags": result.get("hashtags", [])[:10],
            "pain_points": result.get("pain_points", [])[:5],
            "videos": [
                {
                    "title": video.get("title") or video.get("caption"),
                    "url": video.get("url"),
                    "author": video.get("author"),
                    "views": video.get("view_count"),
                    "comments": len(video.get("comment_samples") or []),
                    "snippet": compact_text(tiktok_video_text(video), 260),
                }
                for video in result.get("videos", [])[:8]
            ],
        }
    return result


def agent_tool_summary(tool_name: str, result: dict[str, Any]) -> str:
    if tool_name == "reddit_voc":
        coverage = result.get("coverage") or {}
        data_volume = result.get("data_volume") or {}
        return f"{coverage.get('posts', 0)} Reddit posts, {data_volume.get('collected_comments', 0)} comments."
    if tool_name == "amazon_shelf":
        metrics = result.get("metrics") or {}
        return f"{metrics.get('products', 0)} Amazon products, {metrics.get('total_review_count', 0)} review/rating signals."
    if tool_name == "media_rankings":
        data_volume = result.get("data_volume") or {}
        return f"{data_volume.get('collected_articles', 0)} readable articles."
    if tool_name == "tiktok_social":
        metrics = result.get("metrics") or {}
        data_volume = result.get("data_volume") or {}
        return f"{metrics.get('videos', 0)} TikTok videos, {data_volume.get('comment_samples', 0)} comment samples."
    return "Tool completed."


def execute_agent_tool(tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    bypass_cache = bool(payload.get("bypassCache"))
    try:
        if tool_name == "reddit_voc":
            raw = analyze_category(
                {
                    "category": category,
                    "timeRange": payload.get("timeRange") or "year",
                    "limit": min(max(int(payload.get("redditLimit") or 30), 5), 120),
                    "mode": payload.get("mode") or "auto",
                    "useLlm": False,
                    "redditDetailLimit": min(max(int(payload.get("redditDetailLimit") or 5), 0), 30),
                    "redditCommentsPerPost": min(max(int(payload.get("redditCommentsPerPost") or 10), 0), 80),
                    "bypassCache": bypass_cache,
                }
            )
        elif tool_name == "amazon_shelf":
            raw = analyze_amazon_category(
                {
                    "category": category,
                    "limit": min(max(int(payload.get("amazonLimit") or 30), 5), 80),
                    "amazonKeywordLimit": min(max(int(payload.get("amazonKeywordLimit") or 6), 1), 12),
                    "useLlm": False,
                    "bypassCache": bypass_cache,
                }
            )
        elif tool_name == "media_rankings":
            discovery = discover_article_urls(
                {
                    "category": category,
                    "queryLimit": min(max(int(payload.get("articleQueryLimit") or 4), 1), 10),
                    "resultsPerQuery": min(max(int(payload.get("articleResultsPerQuery") or 5), 1), 10),
                    "candidateLimit": min(max(int(payload.get("articleCandidateLimit") or 8), 1), 20),
                    "includeIndustryReports": True,
                    "bypassCache": bypass_cache,
                }
            )
            urls = [item.get("url") for item in discovery.get("candidates", [])[:3] if item.get("url")]
            raw = analyze_articles(
                {
                    "category": category,
                    "urls": urls,
                    "limit": len(urls),
                    "bypassCache": bypass_cache,
                }
            ) if urls else {
                "category": category,
                "generated_at": now_iso(),
                "summary": {"collected_articles": 0},
                "data_volume": {"collected_articles": 0},
                "articles": [],
                "warnings": discovery.get("warnings", []) + ["No article URLs were selected for reading."],
            }
            raw["discovery"] = discovery
        elif tool_name == "tiktok_social":
            raw = analyze_tiktok_category(
                {
                    "category": category,
                    "limit": min(max(int(payload.get("tiktokLimit") or 6), 1), 12),
                    "tiktokCommentsPerVideo": min(max(int(payload.get("tiktokCommentsPerVideo") or 4), 1), 20),
                    "bypassCache": bypass_cache,
                }
            )
        else:
            raise ValueError(f"Unknown agent tool: {tool_name}")
        return {
            "name": tool_name,
            "label": AGENT_TOOL_CATALOG[tool_name]["label"],
            "status": "ok",
            "summary": agent_tool_summary(tool_name, raw),
            "duration_ms": int((time.time() - started) * 1000),
            "data": compact_agent_result(tool_name, raw),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": tool_name,
            "label": AGENT_TOOL_CATALOG.get(tool_name, {}).get("label", tool_name),
            "status": "error",
            "summary": str(exc),
            "duration_ms": int((time.time() - started) * 1000),
            "data": {},
        }


def execute_agent_tool_with_timeout(tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
    timeout_seconds = min(max(int(payload.get("agentToolTimeoutSeconds") or 600), 30), 1200)
    started = time.time()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(execute_agent_tool, tool_name, category, payload)
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        return {
            "name": tool_name,
            "label": AGENT_TOOL_CATALOG.get(tool_name, {}).get("label", tool_name),
            "status": "error",
            "summary": f"Tool timed out after {timeout_seconds} seconds.",
            "duration_ms": int((time.time() - started) * 1000),
            "data": {},
        }
    finally:
        if future.done():
            executor.shutdown(wait=False, cancel_futures=True)


def fallback_agent_artifact(prompt: str, mode: str, category: str, tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    ok_tools = [tool for tool in tool_results if tool.get("status") == "ok"]
    findings = [f"{tool.get('label')}: {tool.get('summary')}" for tool in ok_tools]
    return {
        "title": f"{category} {'爆款竞品分析' if mode == 'competitor' else '市场洞察'}",
        "executive_summary": "已完成工具调用；当前 LLM 不可用，因此先返回基于工具结果的保守摘要。",
        "key_findings": findings[:6] or ["暂无成功工具结果。"],
        "opportunities": [
            "优先查看成功工具的证据明细，再决定是否扩大抓取量。",
            "对 Amazon 高 review/high rating 商品做人工复核，避免把低证据商品误判为爆款。",
            "如需要社媒交叉验证，请确保 TikTok 登录状态可用后重新运行。",
        ],
        "risks": [
            "公开数据只能作为方向性证据，不能等同真实销量。",
            "TikTok、文章和 Amazon 抓取可能受登录、反爬和页面结构影响。",
            "需要 SellerSprite/Helium10/JungleScout 类数据补齐搜索量、销量代理和季节性。",
        ],
        "next_steps": [
            "进入研究页查看各数据源原始证据。",
            "进入爆款竞品页确认候选并生成拆解。",
            "保存本轮结果到历史研究。",
        ],
        "prompt": prompt,
    }


def synthesize_agent_artifact(
    prompt: str,
    mode: str,
    category: str,
    tool_results: list[dict[str, Any]],
    locale: str,
    use_llm: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not use_llm:
        return fallback_agent_artifact(prompt, mode, category, tool_results), {
            "enabled": False,
            "status": "not_requested",
            "message": "Generated a rule-based Artifact.",
        }
    try:
        enhanced = call_openai_compatible(
            [
                {
                    "role": "system",
                    "content": (
                        "You are Hsia's R&D insight agent for the US minimizer bra market. "
                        "Use only the supplied tool results. Do not invent sales volume, search volume, or platform-wide market size. "
                        "Return strict JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "language": "Chinese" if locale == "zh" else "English",
                            "mode": mode,
                            "category": category,
                            "user_prompt": prompt,
                            "tool_results": tool_results,
                            "schema": {
                                "title": "string",
                                "executive_summary": "string",
                                "key_findings": ["string"],
                                "opportunities": ["string"],
                                "risks": ["string"],
                                "next_steps": ["string"],
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
        )
        result = enhanced.get("result") if isinstance(enhanced.get("result"), dict) else {}
        artifact = fallback_agent_artifact(prompt, mode, category, tool_results)
        artifact.update({key: result.get(key) for key in artifact.keys() if result.get(key)})
        return artifact, {
            "enabled": True,
            "status": "ok",
            "provider": enhanced.get("provider"),
            "model": enhanced.get("model"),
            "usage": enhanced.get("usage") or {},
        }
    except LLMUnavailable as exc:
        return fallback_agent_artifact(prompt, mode, category, tool_results), {
            "enabled": True,
            "status": "unavailable",
            "message": str(exc),
        }


def run_agent(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    mode = str(payload.get("agentMode") or payload.get("mode") or "market").strip().lower()
    if mode not in {"market", "competitor"}:
        mode = "market"
    category = agent_category_from_payload(payload)
    locale = str(payload.get("locale") or "zh")
    use_llm = payload.get("useLlm", True) is not False
    planned_tools, planner = plan_agent_tools(prompt, mode, use_llm)
    tool_results = [execute_agent_tool_with_timeout(tool_name, category, payload) for tool_name in planned_tools]
    artifact, llm_analysis = synthesize_agent_artifact(prompt, mode, category, tool_results, locale, use_llm)
    return {
        "run_id": hashlib.sha1(f"{prompt}-{now_iso()}".encode()).hexdigest()[:12],
        "generated_at": now_iso(),
        "mode": mode,
        "category": category,
        "prompt": prompt,
        "planner": planner,
        "tools": tool_results,
        "artifact": artifact,
        "llm_analysis": llm_analysis,
    }


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
    reddit_detail_limit = payload.get("redditDetailLimit")
    reddit_comments_per_post = payload.get("redditCommentsPerPost")
    posts, warnings, source_mode = collect_reddit(
        category,
        limit,
        time_range,
        mode,
        bypass_cache=bypass_cache,
        detail_limit=int(reddit_detail_limit) if reddit_detail_limit is not None else None,
        comments_per_post=int(reddit_comments_per_post) if reddit_comments_per_post is not None else None,
    )
    result = summarize_posts(category, posts, source_mode, warnings)
    result["data_volume"] = build_data_volume_stats(
        limit,
        posts,
        source_mode,
        use_llm,
        detail_limit_override=int(reddit_detail_limit) if reddit_detail_limit is not None else None,
        comments_per_post_override=int(reddit_comments_per_post) if reddit_comments_per_post is not None else None,
    )
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
        if parsed.path == "/api/settings/web-search":
            self.send_json(build_web_search_settings_response())
            return
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in {
            "/api/agent/run",
            "/api/analyze",
            "/api/analyze/amazon",
            "/api/analyze/youtube",
            "/api/analyze/tiktok",
            "/api/analyze/articles",
            "/api/analyze/combined",
            "/api/tiktok/login-browser",
            "/api/articles/discover",
            "/api/competitors/discover",
            "/api/competitors/analyze",
            "/api/competitors/tiktok-verify",
            "/api/competitors/cancel",
            "/api/history",
            "/api/settings/llm",
            "/api/settings/reddit",
            "/api/settings/research",
            "/api/settings/agent-reach",
            "/api/settings/agent-reach/reconnect",
            "/api/settings/web-search",
        }:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if parsed.path == "/api/settings/agent-reach/reconnect":
                result = reconnect_opencli_extension()
            elif parsed.path == "/api/agent/run":
                result = run_agent(payload)
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
            elif parsed.path == "/api/settings/web-search":
                result = update_web_search_settings(payload)
            elif parsed.path == "/api/analyze/amazon":
                result = analyze_amazon_category(payload)
            elif parsed.path == "/api/analyze/youtube":
                result = analyze_youtube_category(payload)
            elif parsed.path == "/api/analyze/tiktok":
                result = analyze_tiktok_category(payload)
            elif parsed.path == "/api/tiktok/login-browser":
                result = open_tiktok_login_browser()
            elif parsed.path == "/api/analyze/articles":
                result = analyze_articles(payload)
            elif parsed.path == "/api/articles/discover":
                result = discover_article_urls(payload)
            elif parsed.path == "/api/analyze/combined":
                result = analyze_combined_insight(payload)
            elif parsed.path == "/api/competitors/discover":
                result = discover_competitors(payload)
            elif parsed.path == "/api/competitors/analyze":
                result = analyze_competitor_deep_dive(payload)
            elif parsed.path == "/api/competitors/tiktok-verify":
                result = verify_competitor_tiktok(payload)
            elif parsed.path == "/api/competitors/cancel":
                result = cancel_competitor_analysis(payload)
            else:
                result = analyze_category(payload)
            self.send_json(result)
        except OperationCancelled as exc:
            self.send_json({"error": str(exc), "cancelled": True}, status=HTTPStatus.CONFLICT)
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

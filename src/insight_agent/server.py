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
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .agent_params import (
    adapt_agent_params_for_tool,
    agent_payload_from_params,
    normalize_agent_time_range,
    resolve_canonical_agent_params,
)
from .agent_skill_harness import parse_evidence_contract, parse_tool_policy
from .agent_tool_recovery import (
    SUCCESS_TOOL_STATUSES,
    assess_agent_tool_result,
    compact_attempt_result,
    final_status_after_exhaustion,
    retry_delay_seconds,
    retry_limit_for_assessment,
)
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
from .ingestion.tiktok_browser import fetch_tiktok_playwright
from .ingestion.youtube_ytdlp import fetch_youtube_ytdlp
from .llm import (
    LLMUnavailable,
    call_openai_compatible,  # noqa: F401 - compatibility hook used by tests and integrations
    call_openai_compatible_chat,
    enhance_amazon_report_with_llm,
    enhance_combined_insight_with_llm,
    enhance_competitor_deep_dive_with_llm,
    enhance_report_with_llm,
)
from .mcp_sellersprite import (
    build_sellersprite_input_payload,
    execute_sellersprite_agent_tool,
    get_sellersprite_tool_catalog,
    is_sellersprite_agent_tool,
)
from .mcp_sif import (
    build_sif_input_payload,
    execute_sif_agent_tool,
    get_sif_tool_catalog,
    is_sif_agent_tool,
)
from .report_charts import build_market_report_charts
from .settings import (
    DEFAULT_AMAZON_LLM_PRODUCT_LIMIT,
    DEFAULT_AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT,
    DEFAULT_LLM_COMMENT_SAMPLES_PER_POST,
    DEFAULT_LLM_EVIDENCE_POSTS,
    DEFAULT_REDDIT_USER_AGENT,
    MAX_RESEARCH_POST_LIMIT,
    build_agent_reach_settings_response,
    build_llm_settings_response,
    build_mcp_settings_response,
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
    update_mcp_settings,
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
SKILLS_DIR = PROJECT_ROOT / "skills"

CACHE_VERSION = "v4"
ANALYSIS_CACHE_TTL_SECONDS = 60 * 60 * 24
REDDIT_NATIVE_TIME_RANGES = {"day", "week", "month", "year", "all"}


class OperationCancelled(RuntimeError):
    """Raised when a long-running analysis is cancelled by the user."""


class HtmlReportGenerationError(RuntimeError):
    """Raised when the LLM cannot produce a valid self-contained HTML report."""

    def __init__(self, message: str, analysis: dict[str, Any]) -> None:
        super().__init__(message)
        self.analysis = analysis


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


def reddit_provider_time_range(time_range: str) -> str:
    if time_range in REDDIT_NATIVE_TIME_RANGES:
        return time_range
    days_match = re.fullmatch(r"(\d{1,5})d", time_range)
    if not days_match:
        return "year"
    days = int(days_match.group(1))
    if days <= 1:
        return "day"
    if days <= 7:
        return "week"
    if days <= 30:
        return "month"
    if days <= 365:
        return "year"
    return "all"


def time_range_cutoff(time_range: str, now: dt.datetime | None = None) -> dt.datetime | None:
    now = now or dt.datetime.now(dt.UTC)
    if time_range == "day":
        return now - dt.timedelta(days=1)
    if time_range == "week":
        return now - dt.timedelta(days=7)
    if time_range == "month":
        return now - dt.timedelta(days=30)
    days_match = re.fullmatch(r"(\d{1,5})d", time_range)
    if days_match:
        return now - dt.timedelta(days=max(1, int(days_match.group(1))))
    if time_range == "year":
        return now - dt.timedelta(days=365)
    return None


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


def filter_posts_by_time_range(posts: list[dict[str, Any]], time_range: str) -> tuple[list[dict[str, Any]], list[str]]:
    cutoff = time_range_cutoff(time_range)
    if not cutoff or not posts:
        return posts, []
    filtered: list[dict[str, Any]] = []
    dated_posts = 0
    for post in posts:
        created = parse_date(post.get("created_utc") or post.get("created_at") or post.get("date"))
        if not created:
            filtered.append(post)
            continue
        dated_posts += 1
        if created >= cutoff:
            filtered.append(post)
    warnings: list[str] = []
    dropped = len(posts) - len(filtered)
    if dropped:
        warnings.append(f"Filtered {dropped} Reddit posts outside requested time range {time_range}.")
    if dated_posts == 0:
        warnings.append(
            f"Could not verify requested time range {time_range} because collected Reddit posts had no parseable timestamps."
        )
    return filtered, warnings


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
    requested_time_range = normalize_agent_time_range(time_range) or "year"
    provider_time_range = reddit_provider_time_range(requested_time_range)
    provider_limit = (
        limit
        if requested_time_range in REDDIT_NATIVE_TIME_RANGES
        else min(MAX_RESEARCH_POST_LIMIT, max(limit * 3, limit + 30))
    )
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
            requested_time_range,
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
        posts, filter_warnings = filter_posts_by_time_range(posts, requested_time_range)
        warnings.extend(filter_warnings)
        write_cache(cache_path, {"posts": posts[:limit], "mode": source_mode})
        return posts[:limit], warnings, source_mode

    if mode in {"auto", "agent_reach"}:
        agent_reach_kwargs: dict[str, int] = {}
        if detail_limit is not None or comments_per_post is not None:
            agent_reach_kwargs = {
                "detail_limit": effective_detail_limit,
                "comments_per_post": effective_comments_per_post,
            }
        agent_reach_result = fetch_reddit_agent_reach(query, provider_limit, provider_time_range, **agent_reach_kwargs)
        warnings.extend(agent_reach_result.warnings)
        if agent_reach_result.items:
            posts = [item.to_legacy_post() for item in agent_reach_result.items]
            source_mode = "agent_reach"

    if not posts and mode in {"auto", "oauth"}:
        oauth_posts, oauth_warnings = fetch_reddit_oauth(query, provider_limit, provider_time_range)
        warnings.extend(oauth_warnings)
        if oauth_posts:
            posts = oauth_posts
            source_mode = "oauth"

    if not posts and mode in {"auto", "rss"}:
        rss_posts, rss_warnings = fetch_reddit_rss(query, provider_limit, provider_time_range, bypass_cache=bypass_cache)
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

    posts = dedupe_posts(posts)
    posts, filter_warnings = filter_posts_by_time_range(posts, requested_time_range)
    warnings.extend(filter_warnings)
    posts = posts[:limit]
    write_cache(cache_path, {"posts": posts, "mode": source_mode})
    return posts, warnings, source_mode


def parse_date(value: Any) -> dt.datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return dt.datetime.fromtimestamp(float(value), dt.UTC)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        try:
            return dt.datetime.fromtimestamp(float(text), dt.UTC)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


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
    "build_market_report_data": {
        "label": "MarketReportData builder",
        "description": "Compile collected tool results into a stable MarketReportData JSON structure before rendering a market insight report.",
    },
    "render_html_report": {
        "label": "HTML report renderer",
        "description": "Use the LLM to author the final evidence-based HTML report for the loaded Skill.",
    },
}


def agent_tool_catalog() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {name: dict(meta) for name, meta in AGENT_TOOL_CATALOG.items()}
    catalog.update(get_sif_tool_catalog())
    catalog.update(get_sellersprite_tool_catalog())
    return catalog

def markdown_section(markdown_text: str, heading: str) -> str:
    pattern = rf"^##\s+{re.escape(heading)}\s*$"
    match = re.search(pattern, markdown_text, flags=re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^##\s+", markdown_text[start:], flags=re.MULTILINE)
    end = start + next_match.start() if next_match else len(markdown_text)
    return markdown_text[start:end].strip()


def markdown_bullets(section: str) -> list[str]:
    return [line.strip()[2:].strip() for line in section.splitlines() if line.strip().startswith("- ")]


def parse_skill_value(value: str) -> Any:
    stripped = value.strip()
    if stripped.lower() == "true":
        return True
    if stripped.lower() == "false":
        return False
    if re.fullmatch(r"\d+", stripped):
        return int(stripped)
    return stripped


def markdown_table_rows(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and cells[0] not in {"字段", "Field"}:
            rows.append(cells)
    return rows


def first_markdown_paragraph(section: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", section) if part.strip()]
    return paragraphs[0] if paragraphs else ""


def extract_agent_skill_spec(markdown_text: str, path: Path) -> dict[str, Any]:
    title_match = re.search(r"^#\s+(.+)$", markdown_text, flags=re.MULTILINE)
    name = title_match.group(1).strip() if title_match else path.parent.name
    required_rows = markdown_table_rows(markdown_section(markdown_text, "Required Inputs"))
    optional_rows = markdown_table_rows(markdown_section(markdown_text, "Optional Defaults"))
    required = [row[0] for row in required_rows if row]
    required_descriptions = {
        row[0]: row[1]
        for row in required_rows
        if len(row) >= 2 and row[0]
    }
    defaults: dict[str, Any] = {}
    for row in optional_rows:
        if len(row) >= 2 and row[0]:
            defaults[row[0]] = parse_skill_value(row[1])
    html_template_path = path.parent / "assets" / "report-template.html"
    html_template = html_template_path.read_text(encoding="utf-8") if html_template_path.exists() else ""
    return {
        "skill_id": path.parent.name,
        "name": name,
        "description": first_markdown_paragraph(markdown_section(markdown_text, "What It Does")),
        "when_to_use": markdown_bullets(markdown_section(markdown_text, "When To Use")),
        "required_inputs_summary": required,
        "input_schema": {"required": required, "required_descriptions": required_descriptions, "defaults": defaults},
        "tool_policy": parse_tool_policy(markdown_text),
        "evidence_contract": parse_evidence_contract(markdown_text),
        "markdown": markdown_text,
        "source_path": str(path),
        "html_template": html_template,
        "html_template_path": str(html_template_path) if html_template else "",
    }


def load_agent_skill_registry() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    if not SKILLS_DIR.exists():
        return registry
    for skill_path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        if skill_path.parent.name.startswith("_"):
            continue
        try:
            skill = extract_agent_skill_spec(skill_path.read_text(encoding="utf-8"), skill_path)
        except Exception as exc:  # noqa: BLE001
            print(f"Skipping skill {skill_path}: {exc}")
            continue
        registry[str(skill["skill_id"])] = skill
    return registry


AGENT_SKILL_REGISTRY: dict[str, dict[str, Any]] = load_agent_skill_registry()


def agent_skill_manifests() -> list[dict[str, Any]]:
    return [
        {
            "skill_id": skill["skill_id"],
            "name": skill["name"],
            "description": skill["description"],
            "when_to_use": skill["when_to_use"],
            "required_inputs_summary": skill["required_inputs_summary"],
            "tool_policy": skill.get("tool_policy") or [],
            "evidence_contract": skill.get("evidence_contract") or [],
            "markdown": compact_text(str(skill.get("markdown") or ""), 2200),
        }
        for skill in AGENT_SKILL_REGISTRY.values()
    ]


def resolve_agent_skill_params(
    skill: dict[str, Any],
    payload: dict[str, Any],
    extracted_params: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    return resolve_canonical_agent_params(skill, payload, extracted_params)


def agent_payload_with_skill_params(payload: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    return agent_payload_from_params(payload, params)


def agent_event(
    seq: int,
    event_type: str,
    status: str,
    title: str,
    message: str = "",
    *,
    tool: str | None = None,
    duration_ms: int | None = None,
    data: dict[str, Any] | None = None,
    input_params: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    file_path: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    if event_type == "input":
        title = "接收用户输入"
        message = "正在判断是直接回复、补齐参数，还是调用工具执行任务。"
    event: dict[str, Any] = {
        "id": event_id or f"evt-{seq:03d}",
        "seq": seq,
        "type": event_type,
        "status": status,
        "title": title,
        "message": message,
        "timestamp": now_iso(),
    }
    if tool:
        event["tool"] = tool
    if duration_ms is not None:
        event["duration_ms"] = duration_ms
    if data:
        event["data"] = data
    if input_params is not None:
        event["input"] = input_params
    if output is not None:
        event["output"] = output
    if file_path:
        event["file_path"] = file_path
    return event


def agent_category_from_payload(payload: dict[str, Any]) -> str:
    category = str(payload.get("category") or "").strip()
    if category:
        return category
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    return str(params.get("category") or params.get("keyword") or "").strip()


def agent_brief_for_category(category: str) -> dict[str, str]:
    brief = dict(DEFAULT_COMPETITOR_DISCOVERY_BRIEF)
    if category:
        brief["coreKeywords"] = category
    return brief


def agent_tool_input_payload(tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
    if is_sif_agent_tool(tool_name):
        return build_sif_input_payload(tool_name, category, payload)
    if is_sellersprite_agent_tool(tool_name):
        return build_sellersprite_input_payload(tool_name, category, payload)
    return adapt_agent_params_for_tool(tool_name, category, payload)


def compact_agent_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    if is_sif_agent_tool(tool_name):
        return result
    if is_sellersprite_agent_tool(tool_name):
        return result
    if tool_name == "build_market_report_data":
        return result
    if tool_name == "render_html_report":
        return result
    if tool_name == "reddit_voc":
        return {
            "coverage": result.get("coverage"),
            "market_signal": result.get("market_signal"),
            "sentiment": result.get("sentiment"),
            "pain_points": result.get("pain_points", [])[:5],
            "brands": result.get("brands", [])[:8],
            "sizes": result.get("sizes", [])[:8],
            "posts": [
                {
                    "id": post.get("id"),
                    "title": post.get("title"),
                    "url": post.get("url"),
                    "subreddit": post.get("subreddit"),
                    "score": post.get("score"),
                    "comments": post.get("comments"),
                    "comment_sample_count": len(post_comment_items(post)),
                    "comment_items": post_comment_items(post),
                    "excerpt": compact_text(str(post.get("excerpt") or ""), 260),
                }
                for post in result.get("posts", [])
            ],
        }
    if tool_name == "amazon_shelf":
        products = result.get("products", [])
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
                    "image_url": product.get("image_url"),
                    "price": product.get("price_text"),
                    "rating": product.get("rating_value"),
                    "reviews": product.get("review_count"),
                    "review_sample_count": len(product.get("review_samples") or []),
                    "review_samples": product.get("review_samples") if isinstance(product.get("review_samples"), list) else [],
                    "badges": product.get("badges", [])[:4],
                }
                for product in products
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
                    "comment_samples": video.get("comment_samples") if isinstance(video.get("comment_samples"), list) else [],
                    "snippet": compact_text(tiktok_video_text(video), 260),
                }
                for video in result.get("videos", [])[:8]
            ],
        }
    return result


def agent_tool_summary(tool_name: str, result: dict[str, Any]) -> str:
    if is_sif_agent_tool(tool_name):
        return "Sif MCP returned structured evidence."
    if is_sellersprite_agent_tool(tool_name):
        return result.get("summary") or "SellerSprite MCP returned structured evidence."
    if tool_name == "build_market_report_data":
        summary = result.get("source_summary") if isinstance(result.get("source_summary"), dict) else {}
        return (
            f"MarketReportData compiled from {summary.get('successful_tool_count', 0)} successful tool(s), "
            f"{len(result.get('market_kpis') or [])} KPI(s), {len(result.get('evidence_map') or [])} evidence item(s)."
        )
    if tool_name == "render_html_report":
        return f"Rendered HTML report: {result.get('title') or 'HTML report'}."
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
    tool_input = agent_tool_input_payload(tool_name, category, payload)
    catalog = agent_tool_catalog()
    if is_sif_agent_tool(tool_name):
        return execute_sif_agent_tool(tool_name, tool_input)
    if is_sellersprite_agent_tool(tool_name):
        return execute_sellersprite_agent_tool(tool_name, tool_input)
    try:
        if tool_name == "reddit_voc":
            raw = analyze_category(tool_input)
        elif tool_name == "amazon_shelf":
            raw = analyze_amazon_category(tool_input)
        elif tool_name == "media_rankings":
            discovery = discover_article_urls(tool_input)
            urls = [item.get("url") for item in discovery.get("candidates", [])[:3] if item.get("url")]
            raw = analyze_articles(
                {
                    "category": category,
                    "urls": urls,
                    "limit": len(urls),
                    "bypassCache": bool(tool_input.get("bypassCache")),
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
            raw = analyze_tiktok_category(tool_input)
        elif tool_name == "build_market_report_data":
            raw = build_market_report_data(tool_input)
        elif tool_name == "render_html_report":
            raw = render_html_report_tool(tool_input)
        else:
            raise ValueError(f"Unknown agent tool: {tool_name}")
        return {
            "name": tool_name,
            "label": catalog[tool_name]["label"],
            "status": "ok",
            "summary": agent_tool_summary(tool_name, raw),
            "duration_ms": int((time.time() - started) * 1000),
            "input": tool_input,
            "data": compact_agent_result(tool_name, raw),
        }
    except HtmlReportGenerationError as exc:
        return {
            "name": tool_name,
            "label": catalog.get(tool_name, {}).get("label", tool_name),
            "status": "error",
            "summary": str(exc),
            "duration_ms": int((time.time() - started) * 1000),
            "input": tool_input,
            "data": {"html_analysis": exc.analysis},
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": tool_name,
            "label": catalog.get(tool_name, {}).get("label", tool_name),
            "status": "error",
            "summary": str(exc),
            "duration_ms": int((time.time() - started) * 1000),
            "input": tool_input,
            "data": {},
        }


def execute_agent_tool_once_with_timeout(
    tool_name: str,
    category: str,
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    started = time.time()
    catalog = agent_tool_catalog()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(execute_agent_tool, tool_name, category, payload)
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        return {
            "name": tool_name,
            "label": catalog.get(tool_name, {}).get("label", tool_name),
            "status": "error",
            "summary": f"Tool timed out after {timeout_seconds} seconds.",
            "duration_ms": int((time.time() - started) * 1000),
            "input": agent_tool_input_payload(tool_name, category, payload),
            "data": {},
        }
    finally:
        if future.done():
            executor.shutdown(wait=False, cancel_futures=True)


def execute_agent_tool_with_timeout(tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
    timeout_seconds = min(max(int(payload.get("agentToolTimeoutSeconds") or 600), 30), 1200)
    configured_retries = min(max(int(payload.get("agentToolRetryAttempts") or 2), 0), 3)
    if tool_name == "render_html_report":
        configured_retries = 0
    retry_delay_ms = min(max(int(payload.get("agentToolRetryDelayMs") or 300), 0), 5000)
    started = time.time()
    attempts: list[dict[str, Any]] = []
    final_result: dict[str, Any] | None = None
    final_assessment = None

    for attempt_index in range(1, configured_retries + 2):
        result = execute_agent_tool_once_with_timeout(tool_name, category, payload, timeout_seconds)
        assessment = assess_agent_tool_result(tool_name, result)
        attempts.append(compact_attempt_result(attempt_index, result, assessment))
        final_result = result
        final_assessment = assessment
        allowed_retries = retry_limit_for_assessment(assessment, configured_retries)
        if not assessment.retryable or attempt_index > allowed_retries:
            break
        time.sleep(retry_delay_seconds(attempt_index, retry_delay_ms))

    assert final_result is not None and final_assessment is not None
    total_duration_ms = int((time.time() - started) * 1000)
    final_status = final_assessment.status
    retryable = final_assessment.retryable and len(attempts) <= retry_limit_for_assessment(final_assessment, configured_retries)
    if final_assessment.retryable and len(attempts) > retry_limit_for_assessment(final_assessment, configured_retries):
        final_status = final_status_after_exhaustion(final_assessment)
        retryable = False
    if final_status in SUCCESS_TOOL_STATUSES and len(attempts) > 1:
        final_result["summary"] = f"{final_result.get('summary') or final_assessment.reason} Recovered after {len(attempts)} attempts."
    elif final_status not in SUCCESS_TOOL_STATUSES:
        final_result["summary"] = final_assessment.reason
    final_result["status"] = final_status
    final_result["outcome"] = final_assessment.outcome
    final_result["duration_ms"] = total_duration_ms
    final_result["recovery"] = {
        "attempt_count": len(attempts),
        "retried": len(attempts) > 1,
        "retryable": retryable,
        "attempts": attempts,
        "reason": final_assessment.reason,
        "suggested_next_actions": final_assessment.suggested_next_actions,
    }
    return final_result


def fallback_agent_artifact(prompt: str, mode: str, category: str, tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    ok_tools = [tool for tool in tool_results if tool.get("status") in SUCCESS_TOOL_STATUSES]
    findings = [f"{tool.get('label')}: {tool.get('summary')}" for tool in ok_tools]
    failed_tools = [tool for tool in tool_results if tool.get("status") not in SUCCESS_TOOL_STATUSES]
    return {
        "title": f"{category} {'爆款竞品分析' if mode == 'competitor' else '市场洞察'}",
        "executive_summary": "已完成工具调用；当前 LLM 不可用，因此先返回基于工具结果的保守摘要。",
        "kpis": kpi_from_tool_results(tool_results),
        "market_basics": findings[:4] or ["暂无成功的市场级工具结果。"],
        "price_and_margin": ["需要结合 SellerSprite/Sif 价格、销量代理、利润字段或 Amazon 货架样本继续判断。"],
        "competition": ["需要结合 Top ASIN、品牌集中度、评论门槛和货架占位继续判断竞争结构。"],
        "user_voice": ["需要 Reddit、Amazon 评论或 TikTok 评论样本补充用户痛点与场景语言。"],
        "key_findings": findings[:6] or ["暂无成功工具结果。"],
        "opportunities": [
            "优先查看成功工具的证据明细，再决定是否扩大抓取量。",
            "对 Amazon 高 review/high rating 商品做人工复核，避免把低证据商品误判为爆款。",
            "如需要社媒交叉验证，请确保 TikTok 登录状态可用后重新运行。",
        ],
        "opportunity_pool": [
            {
                "name": "证据补全型研发机会",
                "evidence": "当前报告主要来自已成功工具的摘要，需要补齐市场级与用户级证据后再进入企划会。",
                "priority": "B",
                "next_action": "优先补跑缺失的 Sif/SellerSprite/Amazon/Reddit 证据。",
            }
        ],
        "risks": [
            "公开数据只能作为方向性证据，不能等同真实销量。",
            "TikTok、文章和 Amazon 抓取可能受登录、反爬和页面结构影响。",
            "需要 SellerSprite/Helium10/JungleScout 类数据补齐搜索量、销量代理和季节性。",
        ],
        "data_gaps": [
            f"{tool.get('label') or tool.get('name')} 未成功：{tool.get('summary') or tool.get('error') or '未知原因'}"
            for tool in failed_tools[:8]
        ]
        or ["未发现明确失败工具；仍需人工检查样本覆盖与数据时间窗口。"],
        "next_steps": [
            "进入研究页查看各数据源原始证据。",
            "进入爆款竞品页确认候选并生成拆解。",
            "保存本轮结果到历史研究。",
        ],
        "prompt": prompt,
    }


def html_escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def render_html_list(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "<p class=\"empty\">暂无。</p>"
    return "<ul>" + "".join(f"<li>{html_escape(item)}</li>" for item in items[:12]) + "</ul>"


def compact_html_text(value: Any, limit: int = 220) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def html_number(value: Any) -> str:
    try:
        numeric = float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return html_escape(value)
    if numeric.is_integer():
        return f"{int(numeric):,}"
    return f"{numeric:,.1f}"


def first_tool_result(tool_results: list[dict[str, Any]], tool_name: str) -> dict[str, Any]:
    return next((tool for tool in tool_results if tool.get("name") == tool_name), {})


def successful_tool_results(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [tool for tool in tool_results if tool.get("status") in SUCCESS_TOOL_STATUSES]


def kpi_from_artifact(artifact: dict[str, Any]) -> list[dict[str, str]]:
    raw = artifact.get("kpis")
    if not isinstance(raw, list):
        return []
    kpis: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        value = str(item.get("value") or "").strip()
        if not label or not value:
            continue
        kpis.append(
            {
                "label": label,
                "value": value,
                "change": str(item.get("change") or "").strip(),
                "source": str(item.get("source") or "").strip(),
            }
        )
    return kpis[:8]


def kpi_from_tool_results(tool_results: list[dict[str, Any]]) -> list[dict[str, str]]:
    successful = successful_tool_results(tool_results)
    amazon = first_tool_result(tool_results, "amazon_shelf")
    amazon_metrics = amazon.get("data", {}).get("metrics", {}) if isinstance(amazon.get("data"), dict) else {}
    reddit = first_tool_result(tool_results, "reddit_voc")
    reddit_coverage = reddit.get("data", {}).get("coverage", {}) if isinstance(reddit.get("data"), dict) else {}
    tiktok = first_tool_result(tool_results, "tiktok_social")
    tiktok_metrics = tiktok.get("data", {}).get("metrics", {}) if isinstance(tiktok.get("data"), dict) else {}
    seller_tools = [tool for tool in successful if str(tool.get("name") or "").startswith("sellersprite_")]
    sif_tools = [tool for tool in successful if str(tool.get("name") or "").startswith("sif_")]
    kpis = [
        {"label": "成功数据源", "value": str(len(successful)), "change": "", "source": "Execution"},
        {"label": "Sif 信号", "value": str(len(sif_tools)), "change": "", "source": "Sif MCP"},
        {"label": "SellerSprite 信号", "value": str(len(seller_tools)), "change": "", "source": "SellerSprite MCP"},
    ]
    if amazon_metrics.get("products"):
        kpis.append({"label": "Amazon 商品样本", "value": html_number(amazon_metrics.get("products")), "change": "", "source": "Amazon"})
    if amazon_metrics.get("total_review_count"):
        kpis.append({"label": "Review/Rating 信号", "value": html_number(amazon_metrics.get("total_review_count")), "change": "", "source": "Amazon"})
    if reddit_coverage.get("posts"):
        kpis.append({"label": "Reddit 帖子", "value": html_number(reddit_coverage.get("posts")), "change": "", "source": "Reddit"})
    if tiktok_metrics.get("videos"):
        kpis.append({"label": "TikTok 视频", "value": html_number(tiktok_metrics.get("videos")), "change": "", "source": "TikTok"})
    return kpis[:8]


MARKET_REPORT_METRIC_LABELS = {
    "monthly_sales": "月销量",
    "monthlysales": "月销量",
    "sales": "销量",
    "monthly_revenue": "月销售额",
    "monthlyrevenue": "月销售额",
    "revenue": "销售额",
    "avg_price": "均价",
    "average_price": "均价",
    "price": "价格",
    "profit_margin": "利润率",
    "margin": "利润率",
    "return_rate": "退货率",
    "refund_rate": "退货率",
    "review_count": "评论数",
    "reviews": "评论数",
    "rating": "评分",
    "brand_count": "品牌数",
    "seller_count": "卖家数",
    "product_count": "商品数",
    "search_volume": "搜索量",
    "searchvolume": "搜索量",
    "click_share": "点击份额",
    "top3_click_share": "Top3 点击份额",
    "fba_rate": "FBA 占比",
    "a_plus_rate": "A+ 占比",
}


def market_report_slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def market_report_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) and value not in ("", None)


def market_report_float(value: Any) -> float | None:
    try:
        text = str(value).replace(",", "").replace("$", "").replace("%", "").strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def market_report_value_text(value: Any) -> str:
    if isinstance(value, (int, float)):
        return html_number(value)
    return compact_text(str(value or ""), 120)


def market_report_tool_source(tool: dict[str, Any]) -> str:
    name = str(tool.get("name") or "")
    if name.startswith("sif_"):
        return "Sif MCP"
    if name.startswith("sellersprite_"):
        return "SellerSprite MCP"
    if name == "reddit_voc":
        return "Reddit"
    if name == "tiktok_social":
        return "TikTok"
    if name == "media_rankings":
        return "Media"
    if name == "amazon_shelf":
        return "Amazon"
    return str(tool.get("label") or name or "Tool")


def market_report_evidence_items(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, tool in enumerate(tool_results, 1):
        if not isinstance(tool, dict):
            continue
        items.append(
            {
                "id": f"E{index:02d}",
                "tool": str(tool.get("name") or ""),
                "label": str(tool.get("label") or tool.get("name") or ""),
                "source": market_report_tool_source(tool),
                "status": str(tool.get("status") or ""),
                "summary": str(tool.get("summary") or ""),
                "file_path": str(tool.get("file_path") or ""),
            }
        )
    return items


def market_report_rows_from_nested(
    value: Any,
    *,
    include_terms: tuple[str, ...],
    exclude_terms: tuple[str, ...] = (),
    limit: int = 20,
    depth: int = 0,
) -> list[dict[str, Any]]:
    if depth > 7 or limit <= 0:
        return []
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        joined_keys = " ".join(str(key).lower() for key in value.keys())
        if any(term in joined_keys for term in include_terms) and not any(term in joined_keys for term in exclude_terms):
            scalar_items = {
                str(key): item
                for key, item in value.items()
                if market_report_scalar(item)
            }
            if scalar_items:
                rows.append(scalar_items)
        for item in value.values():
            if len(rows) >= limit:
                break
            rows.extend(
                market_report_rows_from_nested(
                    item,
                    include_terms=include_terms,
                    exclude_terms=exclude_terms,
                    limit=limit - len(rows),
                    depth=depth + 1,
                )
            )
    elif isinstance(value, list):
        for item in value:
            if len(rows) >= limit:
                break
            rows.extend(
                market_report_rows_from_nested(
                    item,
                    include_terms=include_terms,
                    exclude_terms=exclude_terms,
                    limit=limit - len(rows),
                    depth=depth + 1,
                )
            )
    return rows[:limit]


def market_report_metric_items(value: Any, evidence_id: str, limit: int = 10, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 6 or limit <= 0:
        return []
    items: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, raw_value in value.items():
            normalized = market_report_slug(key)
            label = MARKET_REPORT_METRIC_LABELS.get(normalized)
            if not label:
                for token, token_label in MARKET_REPORT_METRIC_LABELS.items():
                    if token in normalized and len(normalized) <= 42:
                        label = token_label
                        break
            if label and market_report_scalar(raw_value):
                items.append(
                    {
                        "label": label,
                        "value": market_report_value_text(raw_value),
                        "raw_value": raw_value,
                        "source": evidence_id,
                        "field": str(key),
                    }
                )
            if len(items) >= limit:
                return items[:limit]
        for raw_value in value.values():
            if len(items) >= limit:
                break
            items.extend(market_report_metric_items(raw_value, evidence_id, limit - len(items), depth + 1))
    elif isinstance(value, list):
        for raw_value in value[:20]:
            if len(items) >= limit:
                break
            items.extend(market_report_metric_items(raw_value, evidence_id, limit - len(items), depth + 1))
    return items[:limit]


def market_report_rows_with_evidence(
    tool_results: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    *,
    include_terms: tuple[str, ...],
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tool, evidence in zip(tool_results, evidence_items, strict=False):
        if tool.get("status") not in SUCCESS_TOOL_STATUSES:
            continue
        data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
        for row in market_report_rows_from_nested(data, include_terms=include_terms, limit=limit - len(rows)):
            if not row:
                continue
            rows.append({"evidence_id": evidence["id"], "source": evidence["source"], **row})
            if len(rows) >= limit:
                return rows
    return rows[:limit]


def market_report_primary_tool_payload(tool: dict[str, Any]) -> Any:
    data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
    nested_data = data.get("data")
    if isinstance(nested_data, (dict, list)):
        return nested_data
    transformed = {
        str(key): value
        for key, value in data.items()
        if key not in {"raw", "text", "parsed_content", "code", "message"}
    }
    if transformed:
        return transformed
    parsed = data.get("parsed_content") if isinstance(data.get("parsed_content"), dict) else {}
    parsed_data = parsed.get("data")
    if isinstance(parsed_data, (dict, list)):
        return parsed_data
    return parsed


def market_report_scalar_row(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if market_report_scalar(item)
    }


def market_report_preferred_value(value: dict[str, Any], key: str) -> Any:
    target = market_report_slug(key)
    for raw_key, item in value.items():
        if market_report_slug(raw_key) == target:
            return item
    return None


def market_report_selected_rows(
    tool_results: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    *,
    tool_names: tuple[str, ...],
    preferred_keys: tuple[str, ...] = (),
    include_terms: tuple[str, ...] = (),
    include_container: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Extract report rows from explicit source tools in priority order."""

    pairs = list(zip(tool_results, evidence_items, strict=False))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool_name in tool_names:
        for tool, evidence in pairs:
            if str(tool.get("name") or "") != tool_name or tool.get("status") not in SUCCESS_TOOL_STATUSES:
                continue
            payload = market_report_primary_tool_payload(tool)
            candidates: list[dict[str, Any]] = []
            if isinstance(payload, list):
                candidates.extend(market_report_scalar_row(item) for item in payload)
            elif isinstance(payload, dict):
                for key in preferred_keys:
                    preferred = market_report_preferred_value(payload, key)
                    if isinstance(preferred, list):
                        candidates.extend(market_report_scalar_row(item) for item in preferred)
                    elif isinstance(preferred, dict):
                        candidates.append(market_report_scalar_row(preferred))
                        nested_items = market_report_preferred_value(preferred, "items")
                        if isinstance(nested_items, list):
                            candidates.extend(market_report_scalar_row(item) for item in nested_items)
                if include_container and not candidates:
                    candidates.append(market_report_scalar_row(payload))
                if include_terms:
                    candidates.extend(
                        market_report_rows_from_nested(
                            payload,
                            include_terms=include_terms,
                            limit=max(limit * 2, 24),
                        )
                    )
            for candidate in candidates:
                if not candidate:
                    continue
                row = {"evidence_id": evidence["id"], "source": evidence["source"], **candidate}
                identity = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                if identity in seen:
                    continue
                seen.add(identity)
                rows.append(row)
                if len(rows) >= limit:
                    return rows
    return rows


def market_report_first_available_rows(
    tool_results: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    *,
    tool_names: tuple[str, ...],
    preferred_keys: tuple[str, ...] = (),
    include_terms: tuple[str, ...] = (),
    include_container: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    for tool_name in tool_names:
        rows = market_report_selected_rows(
            tool_results,
            evidence_items,
            tool_names=(tool_name,),
            preferred_keys=preferred_keys,
            include_terms=include_terms,
            include_container=include_container,
            limit=limit,
        )
        if rows:
            return rows
    return []


_GENERIC_CATEGORY_KEYWORD_TOKENS = {
    "amazon",
    "best",
    "for",
    "men",
    "product",
    "women",
    "woman",
}


def market_report_keyword_tokens(value: Any) -> set[str]:
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", str(value or "").lower()):
        if len(token) > 4 and token.endswith("s"):
            token = token[:-1]
        if len(token) >= 2:
            tokens.add(token)
    return tokens


def market_report_keyword_is_relevant(keyword: Any, category: str) -> bool:
    category_tokens = market_report_keyword_tokens(category)
    keyword_tokens = market_report_keyword_tokens(keyword)
    if not category_tokens or not keyword_tokens:
        return False
    specific_tokens = category_tokens - _GENERIC_CATEGORY_KEYWORD_TOKENS - {"bra"}
    if specific_tokens:
        return bool(specific_tokens & keyword_tokens)
    return bool(category_tokens & keyword_tokens)


def market_report_keyword_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    row = market_report_scalar_row(value)
    for nested_key in ("latest", "current"):
        nested = value.get(nested_key) if isinstance(value.get(nested_key), dict) else {}
        for key, item in market_report_scalar_row(nested).items():
            normalized_key = "search_volume" if key == "volume" else key
            row.setdefault(normalized_key, item)
    trend = value.get("trend") if isinstance(value.get("trend"), dict) else {}
    for key in ("direction", "yoy_change", "strength", "momentum"):
        if trend.get(key) not in (None, ""):
            row.setdefault(key, trend.get(key))
    volumes = value.get("volumes") if isinstance(value.get("volumes"), list) else []
    ranks = value.get("ranks") if isinstance(value.get("ranks"), list) else []
    if volumes:
        row.setdefault("search_volume", volumes[-1])
    if ranks:
        row.setdefault("rank", ranks[-1])
    return row


def market_report_keyword_rows(
    tool_results: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    *,
    category: str,
    limit: int = 24,
) -> list[dict[str, Any]]:
    pairs = list(zip(tool_results, evidence_items, strict=False))
    rows_by_keyword: dict[str, dict[str, Any]] = {}
    for tool_name in (
        "sif_market_get_keyword_history",
        "sif_market_get_keyword_demand",
        "sif_market_get_keyword_root_trend",
        "sellersprite_aba_research_weekly",
    ):
        for tool, evidence in pairs:
            if str(tool.get("name") or "") != tool_name or tool.get("status") not in SUCCESS_TOOL_STATUSES:
                continue
            payload = market_report_primary_tool_payload(tool)
            candidates: list[dict[str, Any]] = []
            if isinstance(payload, dict):
                preferred_keys = (
                    ("keywords",)
                    if tool_name == "sif_market_get_keyword_history"
                    else ("profiles",)
                    if tool_name == "sif_market_get_keyword_demand"
                    else ("items",)
                    if tool_name == "sellersprite_aba_research_weekly"
                    else ()
                )
                for key in preferred_keys:
                    preferred = market_report_preferred_value(payload, key)
                    if isinstance(preferred, list):
                        candidates.extend(item for item in preferred if isinstance(item, dict))
                if not preferred_keys:
                    candidates.append(payload)
            elif isinstance(payload, list):
                candidates.extend(item for item in payload if isinstance(item, dict))
            for candidate in candidates:
                row = market_report_keyword_snapshot(candidate)
                keyword = row.get("keyword") or row.get("query") or row.get("searchTerm") or row.get("term")
                if not keyword or not market_report_keyword_is_relevant(keyword, category):
                    continue
                identity = " ".join(str(keyword).lower().split())
                existing = rows_by_keyword.setdefault(
                    identity,
                    {"evidence_id": evidence["id"], "source": evidence["source"], "keyword": str(keyword)},
                )
                for key, item in row.items():
                    if item not in (None, "") and existing.get(key) in (None, ""):
                        existing[key] = item
                if len(rows_by_keyword) >= limit:
                    break
    return list(rows_by_keyword.values())[:limit]


def market_report_user_voice(tool_results: list[dict[str, Any]], evidence_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    voices: list[dict[str, Any]] = []
    for tool, evidence in zip(tool_results, evidence_items, strict=False):
        name = str(tool.get("name") or "")
        if tool.get("status") not in SUCCESS_TOOL_STATUSES or name not in {"reddit_voc", "tiktok_social", "media_rankings"}:
            continue
        data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
        if isinstance(data.get("pain_points"), list):
            for item in data["pain_points"][:8]:
                text = item.get("label") if isinstance(item, dict) else item
                if text:
                    voices.append({"theme": str(text), "source": evidence["source"], "evidence_id": evidence["id"]})
        if name == "reddit_voc":
            for post in data.get("posts", [])[:8] if isinstance(data.get("posts"), list) else []:
                if not isinstance(post, dict):
                    continue
                text = post.get("excerpt") or post.get("title")
                if text:
                    voices.append(
                        {
                            "theme": compact_text(text, 180),
                            "source": "Reddit",
                            "evidence_id": evidence["id"],
                            "url": post.get("url"),
                        }
                    )
        if name == "tiktok_social":
            for video in data.get("videos", [])[:6] if isinstance(data.get("videos"), list) else []:
                if not isinstance(video, dict):
                    continue
                text = video.get("snippet") or video.get("title")
                if text:
                    voices.append(
                        {
                            "theme": compact_text(text, 180),
                            "source": "TikTok",
                            "evidence_id": evidence["id"],
                            "url": video.get("url"),
                        }
                    )
        if name == "media_rankings":
            for article in data.get("articles", [])[:6] if isinstance(data.get("articles"), list) else []:
                if not isinstance(article, dict):
                    continue
                signals = article.get("product_signals") if isinstance(article.get("product_signals"), list) else []
                text = ", ".join(str(item) for item in signals[:3]) or article.get("title")
                if text:
                    voices.append(
                        {
                            "theme": compact_text(text, 180),
                            "source": article.get("domain") or "Media",
                            "evidence_id": evidence["id"],
                            "url": article.get("url"),
                        }
                    )
    return voices[:18]


def market_report_first_present(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    normalized_lookup = {market_report_slug(key): value for key, value in row.items()}
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
        slug = market_report_slug(key)
        if slug in normalized_lookup and normalized_lookup[slug] not in (None, ""):
            return normalized_lookup[slug]
    for raw_key, value in row.items():
        slug = market_report_slug(raw_key)
        if any(market_report_slug(key) in slug for key in keys) and value not in (None, ""):
            return value
    return None


def market_report_first_present_pair(row: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, Any] | None:
    normalized_lookup = {market_report_slug(key): (key, value) for key, value in row.items()}
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return key, row.get(key)
        slug = market_report_slug(key)
        match = normalized_lookup.get(slug)
        if match and match[1] not in (None, ""):
            return match
    for raw_key, value in row.items():
        slug = market_report_slug(raw_key)
        if any(market_report_slug(key) in slug for key in keys) and value not in (None, ""):
            return str(raw_key), value
    return None


def market_report_evidence_ids_from_rows(rows: Any, limit: int = 6) -> list[str]:
    ids: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        evidence_id = str(row.get("evidence_id") or "").strip()
        if evidence_id and evidence_id not in ids:
            ids.append(evidence_id)
        if len(ids) >= limit:
            break
    return ids


def market_report_success_evidence_ids(report_data: dict[str, Any], limit: int = 6) -> list[str]:
    ids = [
        str(item.get("id"))
        for item in report_data.get("evidence_map", [])
        if isinstance(item, dict) and item.get("status") in SUCCESS_TOOL_STATUSES and item.get("id")
    ]
    return ids[:limit]


def market_report_best_signal(
    rows: Any,
    *,
    label_keys: tuple[str, ...],
    value_keys: tuple[str, ...],
    prefer_low: bool = False,
) -> dict[str, Any] | None:
    if not isinstance(rows, list):
        return None
    best: dict[str, Any] | None = None
    fallback: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        label_pair = market_report_first_present_pair(row, label_keys)
        if not label_pair:
            continue
        value_pair = market_report_first_present_pair(row, value_keys)
        label = compact_text(str(label_pair[1]), 90)
        signal = {
            "label": label,
            "label_field": label_pair[0],
            "value": value_pair[1] if value_pair else "",
            "value_field": value_pair[0] if value_pair else "",
            "value_text": market_report_value_text(value_pair[1]) if value_pair else "",
            "numeric": market_report_float(value_pair[1]) if value_pair else None,
            "source": row.get("source"),
            "evidence_ids": market_report_evidence_ids_from_rows([row], 1),
        }
        if fallback is None:
            fallback = signal
        if signal["numeric"] is None:
            continue
        if best is None:
            best = signal
            continue
        if prefer_low and float(signal["numeric"]) < float(best["numeric"]):
            best = signal
        elif not prefer_low and float(signal["numeric"]) > float(best["numeric"]):
            best = signal
    return best or fallback


def market_report_signal_phrase(signal: dict[str, Any] | None, fallback: str) -> str:
    if not signal:
        return fallback
    value_text = str(signal.get("value_text") or "").strip()
    field = str(signal.get("value_field") or "").strip()
    suffix = f"{field}={value_text}" if field and value_text else value_text
    return f"{signal.get('label')}（{suffix}）" if suffix else str(signal.get("label") or fallback)


def market_report_core_signals(report_data: dict[str, Any]) -> dict[str, Any]:
    keyword_rows = report_data.get("keyword_trends") if isinstance(report_data.get("keyword_trends"), list) else []
    category_rows = report_data.get("category_benchmark") if isinstance(report_data.get("category_benchmark"), list) else []
    price_rows = report_data.get("price_distribution") if isinstance(report_data.get("price_distribution"), list) else []
    brand_rows = report_data.get("brand_competition") if isinstance(report_data.get("brand_competition"), list) else []
    product_rows = report_data.get("top_products") if isinstance(report_data.get("top_products"), list) else []
    keyword_signal = market_report_best_signal(
        keyword_rows,
        label_keys=("keyword", "query", "searchTerm", "term", "root"),
        value_keys=("search_volume", "searchVolume", "volume", "searches", "demand", "search_count"),
    ) or market_report_best_signal(
        keyword_rows,
        label_keys=("keyword", "query", "searchTerm", "term", "root"),
        value_keys=("rank", "abaRank", "ranking", "position"),
        prefer_low=True,
    )
    category_signal = market_report_best_signal(
        category_rows,
        label_keys=("category", "node", "department", "path", "market", "subcategory"),
        value_keys=("totalUnits", "monthly_sales", "monthlySales", "sales", "totalRevenue", "monthly_revenue", "monthlyRevenue", "revenue", "volume"),
    )
    price_signal = market_report_best_signal(
        price_rows,
        label_keys=("priceRange", "range", "price", "label", "bucket"),
        value_keys=("unitsRatio", "salesRatio", "share", "units", "sales", "revenue", "count", "value", "volume"),
    )
    brand_signal = market_report_best_signal(
        brand_rows,
        label_keys=("brand", "brandName", "seller", "merchant", "name"),
        value_keys=("totalUnitsRatio", "unitsRatio", "share", "totalUnits", "sales", "revenue", "count", "value", "volume"),
    )
    product_signal = market_report_best_signal(
        product_rows,
        label_keys=("asin", "product", "title", "name"),
        value_keys=("totalUnits", "monthly_orders", "units", "sales", "totalRevenue", "revenue", "reviews", "review_count", "rating_count", "value"),
    )
    evidence_ids = []
    for signal in (keyword_signal, category_signal, price_signal, brand_signal, product_signal):
        for evidence_id in signal.get("evidence_ids", []) if isinstance(signal, dict) else []:
            if evidence_id and evidence_id not in evidence_ids:
                evidence_ids.append(evidence_id)
    return {
        "keyword": keyword_signal,
        "category": category_signal,
        "price": price_signal,
        "brand": brand_signal,
        "product": product_signal,
        "evidence_ids": evidence_ids[:6] or market_report_success_evidence_ids(report_data),
    }


def market_report_verdict(report_data: dict[str, Any]) -> dict[str, str]:
    signals = market_report_core_signals(report_data)
    has_demand = bool(signals.get("keyword") or signals.get("category"))
    has_competition = bool(signals.get("brand") or signals.get("product"))
    has_price = bool(signals.get("price"))
    gap_count = len(report_data.get("data_gaps") or [])
    if has_demand and has_competition and has_price and gap_count <= 3:
        return {
            "label": "进入企划验证",
            "tone": "go",
            "body": "需求、竞争和价格信号都有结构化证据，适合进入 Hsia 周度企划会做机会排序。",
        }
    if has_demand and has_competition:
        return {
            "label": "先做机会排序",
            "tone": "watch",
            "body": "需求和竞争证据可用，但价格带或节点级门槛仍需补数；适合做方向筛选，不宜直接定 SKU。",
        }
    if has_demand:
        return {
            "label": "需求初筛可用",
            "tone": "watch",
            "body": "已经看到需求入口，但竞争结构和价格承接不足，当前更像候选市场扫描。",
        }
    return {
        "label": "暂缓结论",
        "tone": "hold",
        "body": "结构化市场信号不足，报告只能记录已调用证据和下一步补数动作。",
    }


def market_report_chart_points_from_rows(
    rows: Any,
    *,
    label_keys: tuple[str, ...],
    value_keys: tuple[str, ...],
    limit: int = 10,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    points: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = market_report_first_present(row, label_keys)
        value = market_report_first_present(row, value_keys)
        numeric = market_report_float(value)
        if label and numeric is not None:
            points.append({"label": compact_text(str(label), 42), "value": numeric})
        if len(points) >= limit:
            break
    return points


def market_report_priority_score(priority: Any) -> int:
    normalized = str(priority or "").strip().upper()
    if normalized == "A":
        return 88
    if normalized == "B":
        return 68
    if normalized == "C":
        return 46
    return 56


def market_report_chart_specs(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    chart_payload = build_market_report_charts(report_data)
    chart_specs = chart_payload.get("chart_specs") if isinstance(chart_payload, dict) else []
    return chart_specs if isinstance(chart_specs, list) else []
    charts: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter(
        item.get("source") for item in report_data.get("evidence_map", []) if isinstance(item, dict)
    )
    if source_counts:
        charts.append(
            {
                "id": "evidence_sources",
                "title": "本轮证据来源覆盖",
                "type": "donut",
                "data": [{"label": key, "value": value} for key, value in source_counts.items()],
            }
        )
    source_summary = report_data.get("source_summary") if isinstance(report_data.get("source_summary"), dict) else {}
    if source_summary:
        failed = market_report_float(source_summary.get("failed_tool_count")) or 0
        successful = market_report_float(source_summary.get("successful_tool_count")) or 0
        gaps = len(report_data.get("data_gaps") or [])
        charts.append(
            {
                "id": "data_readiness",
                "title": "数据可用性",
                "type": "donut",
                "data": [
                    {"label": "成功工具", "value": successful},
                    {"label": "失败工具", "value": failed},
                    {"label": "数据缺口", "value": gaps},
                ],
            }
        )
    keyword_points = market_report_chart_points_from_rows(
        report_data.get("keyword_trends"),
        label_keys=("keyword", "query", "searchTerm", "term", "root"),
        value_keys=("search_volume", "searchVolume", "volume", "searches", "demand", "rank", "abaRank"),
        limit=10,
    )
    if keyword_points:
        charts.append({"id": "keyword_volume", "title": "关键词需求/排名信号", "type": "bar", "data": keyword_points})
    category_points = market_report_chart_points_from_rows(
        report_data.get("category_benchmark"),
        label_keys=("category", "node", "department", "path", "market", "subcategory"),
        value_keys=("monthly_sales", "monthlySales", "sales", "monthly_revenue", "monthlyRevenue", "revenue", "volume"),
        limit=10,
    )
    if category_points:
        charts.append({"id": "category_benchmark", "title": "类目对标量化信号", "type": "bar", "data": category_points})
    brands = report_data.get("brand_competition") if isinstance(report_data.get("brand_competition"), list) else []
    brand_points = []
    for row in brands[:8]:
        if not isinstance(row, dict):
            continue
        label = row.get("brand") or row.get("brandName") or row.get("name")
        value = row.get("count") or row.get("sales") or row.get("share") or row.get("value")
        numeric = market_report_float(value)
        if label and numeric is not None:
            brand_points.append({"label": str(label), "value": numeric})
    if brand_points:
        charts.append({"id": "brand_competition", "title": "品牌竞争信号", "type": "bar", "data": brand_points})
    price_rows = report_data.get("price_distribution") if isinstance(report_data.get("price_distribution"), list) else []
    price_points = []
    for row in price_rows[:8]:
        if not isinstance(row, dict):
            continue
        label = row.get("priceRange") or row.get("range") or row.get("price") or row.get("label")
        value = row.get("sales") or row.get("count") or row.get("share") or row.get("value")
        numeric = market_report_float(value)
        if label and numeric is not None:
            price_points.append({"label": str(label), "value": numeric})
    if price_points:
        charts.append({"id": "price_distribution", "title": "价格带分布", "type": "bar", "data": price_points})
    opportunities = report_data.get("opportunity_pool") if isinstance(report_data.get("opportunity_pool"), list) else []
    if opportunities:
        charts.append(
            {
                "id": "opportunity_priority",
                "title": "机会优先级矩阵",
                "type": "matrix",
                "data": [
                    {
                        "label": str(item.get("name") or item.get("opportunity_name") or f"机会 {index + 1}"),
                        "value": market_report_priority_score(item.get("priority")),
                        "priority": str(item.get("priority") or "B"),
                    }
                    for index, item in enumerate(opportunities[:6])
                    if isinstance(item, dict)
                ],
            }
        )
    return charts[:8]


def market_report_analysis_sections(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    keyword_count = len(report_data.get("keyword_trends") or [])
    category_count = len(report_data.get("category_benchmark") or [])
    product_count = len(report_data.get("top_products") or [])
    brand_count = len(report_data.get("brand_competition") or [])
    gap_count = len(report_data.get("data_gaps") or [])
    signals = market_report_core_signals(report_data)
    verdict = market_report_verdict(report_data)
    evidence_ids = signals.get("evidence_ids") or market_report_success_evidence_ids(report_data)
    demand_phrase = market_report_signal_phrase(signals.get("keyword"), "暂未抽取到可命名的关键词需求锚点")
    category_phrase = market_report_signal_phrase(signals.get("category"), "类目规模字段不足")
    price_phrase = market_report_signal_phrase(signals.get("price"), "价格带承接字段不足")
    brand_phrase = market_report_signal_phrase(signals.get("brand"), "品牌集中度字段不足")
    product_phrase = market_report_signal_phrase(signals.get("product"), "Top 商品字段不足")
    return [
        {
            "id": "analysis_tldr",
            "title": "答案先行",
            "tone": "decision",
            "summary": f"{verdict['label']}：{verdict['body']}",
            "bullets": [
                f"需求锚点：{demand_phrase}；类目参照：{category_phrase}。",
                f"竞争锚点：{brand_phrase}；商品锚点：{product_phrase}。",
                f"价格锚点：{price_phrase}；当前有 {gap_count} 个需要在决策前说明的数据缺口。",
            ],
            "evidence_ids": evidence_ids,
        },
        {
            "id": "analysis_demand",
            "title": "需求：先看词，不先看货",
            "tone": "decision",
            "summary": "市场机会先由关键词需求和类目基本盘定义，再回到货架验证产品是否能承接。",
            "bullets": [
                f"本轮抽取 {keyword_count} 条关键词/ABA/搜索历史信号，核心入口是 {demand_phrase}。",
                f"类目侧抽取 {category_count} 条市场/节点/路径信号，当前参照点是 {category_phrase}。",
                "如果高需求词与长尾词根分散，Hsia 不应只押一个大词，而应拆成显小、支撑、平滑、全罩杯等可测试卖点组。",
            ],
            "evidence_ids": market_report_evidence_ids_from_rows(report_data.get("keyword_trends"), 4) or evidence_ids,
        },
        {
            "id": "analysis_so_what",
            "title": "So What：对 Hsia 的含义",
            "tone": "opportunity",
            "summary": "这份报告的作用是把市场信号翻译成研发验证优先级，而不是让团队复制头部商品。",
            "bullets": [
                f"优先围绕 {demand_phrase} 做卖点承接，而不是先从头部 ASIN 外观倒推产品。",
                f"如果 {price_phrase} 能被后续数据确认，价格带验证应独立成一条研发假设。",
                "每个机会都必须落到结构方向、价格假设、风险和下一步验证动作，避免只输出泛泛的“可关注”。",
            ],
            "evidence_ids": evidence_ids,
        },
        {
            "id": "analysis_competition",
            "title": "竞争与进入门槛判断",
            "tone": "risk",
            "summary": "竞争判断要分清“品牌集中度”“商品热度代理”和“关键词流量份额”，不能只凭一个 Top ASIN 下结论。",
            "bullets": [
                f"本轮抽取 {brand_count} 条品牌/卖家信号，当前竞争锚点是 {brand_phrase}。",
                f"本轮抽取 {product_count} 条 Top 商品/ASIN 信号，优先拆解对象是 {product_phrase}。",
                "如果品牌或商品信号集中，先拆评价门槛和结构差异；如果信号分散，优先找中腰部品牌未覆盖的卖点组合。",
            ],
            "evidence_ids": market_report_evidence_ids_from_rows([*(report_data.get("brand_competition") or []), *(report_data.get("top_products") or [])], 4) or evidence_ids,
        },
        {
            "id": "analysis_next",
            "title": "下一步验证优先级",
            "tone": "action",
            "summary": "下一轮不应继续堆工具数量，而应沿着最关键的证据缺口补数。",
            "bullets": [
                f"价格线：围绕 {price_phrase} 补齐销量占比、利润率或搜索购买比，决定是否能做主力款/升级款分层。",
                f"竞品线：围绕 {product_phrase} 做评论门槛、结构卖点和 Listing claim 拆解。",
                "数据线：若缺 category_node_id，先用 SellerSprite product_node 自动解析并校验节点，再补价格、品牌集中度、评分数分布和上架时间分布。",
            ],
            "evidence_ids": evidence_ids,
        },
    ]


def market_report_swot(report_data: dict[str, Any]) -> dict[str, list[str]]:
    keyword_count = len(report_data.get("keyword_trends") or [])
    category_count = len(report_data.get("category_benchmark") or [])
    gap_count = len(report_data.get("data_gaps") or [])
    signals = market_report_core_signals(report_data)
    keyword_phrase = market_report_signal_phrase(signals.get("keyword"), "关键词需求入口待补强")
    price_phrase = market_report_signal_phrase(signals.get("price"), "价格带证据待补强")
    competition_phrase = market_report_signal_phrase(signals.get("brand") or signals.get("product"), "竞争锚点待补强")
    return {
        "strengths": [
            f"已看到可跟进的需求入口：{keyword_phrase}。",
            f"本轮拿到 {keyword_count + category_count} 条关键词/类目结构化市场信号，适合做方向排序。",
        ],
        "weaknesses": [
            "如果缺少节点级数据，价格、品牌集中度和评分门槛只能做方向性判断。",
            f"当前仍有 {gap_count} 个数据缺口需要在企划会前说明。",
        ],
        "opportunities": [
            f"用 {keyword_phrase} 反推显小、支撑、平滑、全罩杯等可验证结构组合。",
            f"用 {price_phrase} 和 {competition_phrase} 筛选重点对标方向。",
        ],
        "threats": [
            f"{competition_phrase} 可能代表头部品牌心智、评价门槛或价格优势，需要拆解后再决定进入方式。",
            "公开工具字段缺失或口径差异会影响跨平台对比，需要保留人工复核节点。",
        ],
    }


def market_report_decision_matrix(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    signals = market_report_core_signals(report_data)
    keyword_score = min(95, 48 + len(report_data.get("keyword_trends") or []) * 3 + (12 if signals.get("keyword") else 0))
    competition_score = min(
        92,
        40
        + (len(report_data.get("brand_competition") or []) + len(report_data.get("top_products") or [])) * 2
        + (12 if signals.get("brand") or signals.get("product") else 0),
    )
    price_score = min(90, 36 + len(report_data.get("price_distribution") or []) * 4 + (14 if signals.get("price") else 0))
    gap_penalty = min(35, len(report_data.get("data_gaps") or []) * 5)
    readiness_score = max(30, min(95, int((keyword_score + competition_score + price_score) / 3) - gap_penalty))
    return [
        {
            "dimension": "需求强度",
            "score": keyword_score,
            "signal": market_report_signal_phrase(signals.get("keyword"), "关键词/ABA/搜索历史信号不足"),
            "recommendation": "优先确认核心词和长尾词根能否被 Hsia 产品结构与 Listing 语言承接。",
        },
        {
            "dimension": "竞争可进入性",
            "score": competition_score,
            "signal": market_report_signal_phrase(signals.get("brand") or signals.get("product"), "品牌集中度、Top ASIN、商品集中度不足"),
            "recommendation": "拆解头部品牌结构、评论门槛和流量份额，寻找非同质化切口。",
        },
        {
            "dimension": "价格/利润空间",
            "score": price_score,
            "signal": market_report_signal_phrase(signals.get("price"), "价格分布、销量/销售额、利润相关字段不足"),
            "recommendation": "把主力款、升级款和价格锚点分开验证，不用单一均价直接定价。",
        },
        {
            "dimension": "数据完备度",
            "score": readiness_score,
            "signal": f"{len(report_data.get('data_gaps') or [])} 个数据缺口",
            "recommendation": "补齐节点级数据后再做 SKU 组合和投产优先级决策。",
        },
    ]


def market_report_data_to_artifact(report_data: dict[str, Any]) -> dict[str, Any]:
    insights = report_data.get("insights") if isinstance(report_data.get("insights"), list) else []
    analysis_sections = report_data.get("analysis_sections") if isinstance(report_data.get("analysis_sections"), list) else []
    insight_text = [
        str(item.get("summary") or item.get("title") or "")
        for item in insights
        if isinstance(item, dict) and (item.get("summary") or item.get("title"))
    ]
    analysis_text = [
        str(item.get("summary") or item.get("title") or "")
        for item in analysis_sections
        if isinstance(item, dict) and (item.get("summary") or item.get("title"))
    ]
    opportunity_pool = report_data.get("opportunity_pool") if isinstance(report_data.get("opportunity_pool"), list) else []
    data_gaps = report_data.get("data_gaps") if isinstance(report_data.get("data_gaps"), list) else []
    kpis = report_data.get("market_kpis") if isinstance(report_data.get("market_kpis"), list) else []
    return {
        "title": report_data.get("title") or f"{report_data.get('category') or '市场'}洞察报告",
        "executive_summary": report_data.get("executive_summary") or "已完成 MarketReportData 编译，报告基于本轮工具证据生成。",
        "kpis": kpis,
        "market_basics": [*analysis_text[:3], *insight_text[:2]],
        "price_and_margin": [
            f"{len(report_data.get('price_distribution') or [])} 条价格/利润相关结构化记录。"
        ],
        "competition": [
            f"{len(report_data.get('brand_competition') or [])} 条品牌竞争记录，{len(report_data.get('top_products') or [])} 条商品/ASIN 记录。"
        ],
        "user_voice": [],
        "key_findings": insight_text[:6],
        "opportunity_pool": opportunity_pool,
        "opportunities": [
            str(item.get("name") or item.get("opportunity_name") or "")
            for item in opportunity_pool
            if isinstance(item, dict)
        ],
        "risks": data_gaps[:8],
        "data_gaps": data_gaps,
        "next_steps": report_data.get("next_actions") or [],
    }


def html_report_style_reference(skill_markdown: Any) -> str:
    text = str(skill_markdown or "")
    match = re.search(r"^###\s+HTML Report Style Reference\s*$", text, flags=re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^##\s+|^###\s+", text[start:], flags=re.MULTILINE)
    end = start + next_match.start() if next_match else len(text)
    return compact_text(text[start:end].strip(), 4200)


def market_report_compact_items(value: Any, *, limit: int = 10) -> list[Any]:
    if not isinstance(value, list):
        return []
    compacted: list[Any] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            compacted.append(compact_text(str(item), 240))
            continue
        record: dict[str, Any] = {}
        for key, raw_value in list(item.items())[:18]:
            if isinstance(raw_value, str):
                record[str(key)] = compact_text(raw_value, 280)
            elif isinstance(raw_value, int | float | bool) or raw_value is None:
                record[str(key)] = raw_value
            elif isinstance(raw_value, list):
                record[str(key)] = [
                    compact_text(str(child), 180) if not isinstance(child, int | float | bool) else child
                    for child in raw_value[:6]
                ]
            elif isinstance(raw_value, dict):
                record[str(key)] = {
                    str(child_key): (
                        child_value
                        if isinstance(child_value, int | float | bool) or child_value is None
                        else compact_text(str(child_value), 180)
                    )
                    for child_key, child_value in list(raw_value.items())[:8]
                }
            else:
                record[str(key)] = compact_text(str(raw_value), 180)
        compacted.append(record)
    return compacted


def market_report_llm_context(report_data: dict[str, Any]) -> dict[str, Any]:
    chart_specs = []
    for chart in report_data.get("chart_specs", []) if isinstance(report_data.get("chart_specs"), list) else []:
        if not isinstance(chart, dict):
            continue
        chart_specs.append(
            {
                "id": chart.get("id"),
                "title": chart.get("title"),
                "subtitle": chart.get("subtitle"),
                "type": chart.get("type"),
                "insight": chart.get("insight"),
                "x_label": chart.get("x_label"),
                "y_label": chart.get("y_label"),
                "unit": chart.get("unit"),
                "orientation": chart.get("orientation"),
                "value_format": chart.get("value_format"),
                "source": chart.get("source"),
                "quality_status": chart.get("quality_status"),
                "data": market_report_compact_items(chart.get("data"), limit=16),
            }
        )
        if len(chart_specs) >= 8:
            break
    return {
        "schema_version": report_data.get("schema_version"),
        "title": report_data.get("title"),
        "brand": report_data.get("brand"),
        "marketplace": report_data.get("marketplace"),
        "category": report_data.get("category"),
        "time_range": report_data.get("time_range"),
        "generated_at": report_data.get("generated_at"),
        "executive_summary": report_data.get("executive_summary"),
        "market_kpis": market_report_compact_items(report_data.get("market_kpis"), limit=14),
        "keyword_trends": market_report_compact_items(report_data.get("keyword_trends"), limit=12),
        "demand_trend": market_report_compact_items(report_data.get("demand_trend"), limit=14),
        "category_benchmark": market_report_compact_items(report_data.get("category_benchmark"), limit=10),
        "top_products": market_report_compact_items(report_data.get("top_products"), limit=10),
        "brand_competition": market_report_compact_items(report_data.get("brand_competition"), limit=10),
        "price_distribution": market_report_compact_items(report_data.get("price_distribution"), limit=10),
        "ratings_count_distribution": market_report_compact_items(report_data.get("ratings_count_distribution"), limit=10),
        "listing_date_distribution": market_report_compact_items(report_data.get("listing_date_distribution"), limit=10),
        "analysis_sections": market_report_compact_items(report_data.get("analysis_sections"), limit=8),
        "insights": market_report_compact_items(report_data.get("insights"), limit=10),
        "opportunity_pool": market_report_compact_items(report_data.get("opportunity_pool"), limit=10),
        "swot": report_data.get("swot") if isinstance(report_data.get("swot"), dict) else {},
        "decision_matrix": market_report_compact_items(report_data.get("decision_matrix"), limit=10),
        "chart_specs": chart_specs,
        "evidence_map": market_report_compact_items(report_data.get("evidence_map"), limit=18),
        "data_gaps": report_data.get("data_gaps") if isinstance(report_data.get("data_gaps"), list) else [],
    }


def normalize_llm_html_document(value: Any) -> str:
    html_content = str(value or "").strip()
    if html_content.startswith("{"):
        try:
            parsed = json.loads(html_content)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            result = parsed.get("result") if isinstance(parsed.get("result"), dict) else {}
            nested_html = result.get("html") or parsed.get("html")
            if nested_html:
                html_content = str(nested_html).strip()
    fence = re.match(r"^```(?:html)?\s*(.*?)\s*```$", html_content, flags=re.IGNORECASE | re.DOTALL)
    if fence:
        html_content = fence.group(1).strip()
    lowered = html_content.lower()
    start = lowered.find("<!doctype html")
    if start < 0:
        start = lowered.find("<html")
    end = lowered.rfind("</html>")
    if start >= 0 and end >= start:
        html_content = html_content[start : end + len("</html>")].strip()
    return html_content


def html_template_required_sections(template_html: Any) -> list[str]:
    return list(
        dict.fromkeys(
            re.findall(
                r"data-required-section\s*=\s*['\"]([^'\"]+)['\"]",
                str(template_html or ""),
                flags=re.IGNORECASE,
            )
        )
    )


def validate_llm_html_document(
    html_content: str,
    template_html: Any = "",
    required_chart_ids: Any = None,
) -> str:
    lowered = html_content.lower()
    if len(html_content) < 500:
        return "LLM HTML is too short to be a complete report."
    if "<html" not in lowered or "</html>" not in lowered:
        return "LLM HTML must be a complete HTML document."
    if "<style" not in lowered:
        return "LLM HTML must include inline CSS."
    forbidden_patterns = [
        r"<script(?:\s|>)",
        r"<script[^>]+src\s*=",
        r"<link[^>]+rel\s*=\s*['\"]?stylesheet",
        r"@import\s+url",
    ]
    for pattern in forbidden_patterns:
        if re.search(pattern, html_content, flags=re.IGNORECASE):
            if pattern == r"<script(?:\s|>)":
                return (
                    "LLM HTML must render in the sandboxed preview without JavaScript; "
                    "use static HTML, CSS, and populated inline SVG charts."
                )
            return "LLM HTML must be single-file and cannot load external scripts, styles, fonts, or CSS imports."
    for section_id in html_template_required_sections(template_html):
        pattern = rf"data-required-section\s*=\s*['\"]{re.escape(section_id)}['\"]"
        if not re.search(pattern, html_content, flags=re.IGNORECASE):
            return f"LLM HTML is missing required template section: {section_id}."
    for chart_id in required_chart_ids if isinstance(required_chart_ids, list) else []:
        normalized_id = str(chart_id or "").strip()
        if not normalized_id:
            continue
        pattern = rf"data-chart-id\s*=\s*['\"]{re.escape(normalized_id)}['\"]"
        if not re.search(pattern, html_content, flags=re.IGNORECASE):
            return f"LLM HTML is missing required business chart: {normalized_id}."
    chart_markup_error = validate_static_chart_markup(html_content, required_chart_ids)
    if chart_markup_error:
        return chart_markup_error
    return ""


class StaticChartMarkupInspector(HTMLParser):
    graphic_tags = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}

    def __init__(self, required_chart_ids: list[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.required_chart_ids = set(required_chart_ids)
        self.figure_stack: list[str] = []
        self.svg_depth = 0
        self.charts = {
            chart_id: {"figure_count": 0, "svg_count": 0, "graphic_count": 0}
            for chart_id in required_chart_ids
        }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        attr_map = {str(key).lower(): value for key, value in attrs}
        if normalized_tag == "figure":
            chart_id = str(attr_map.get("data-chart-id") or "")
            self.figure_stack.append(chart_id)
            if chart_id in self.required_chart_ids:
                self.charts[chart_id]["figure_count"] += 1

        chart_id = next(
            (candidate for candidate in reversed(self.figure_stack) if candidate in self.required_chart_ids),
            "",
        )
        if normalized_tag == "svg":
            self.svg_depth += 1
            if chart_id:
                self.charts[chart_id]["svg_count"] += 1
        elif chart_id and self.svg_depth > 0 and normalized_tag in self.graphic_tags:
            self.charts[chart_id]["graphic_count"] += 1

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "svg" and self.svg_depth > 0:
            self.svg_depth -= 1
        if normalized_tag == "figure" and self.figure_stack:
            self.figure_stack.pop()


def validate_static_chart_markup(html_content: str, required_chart_ids: Any) -> str:
    if not isinstance(required_chart_ids, list):
        return ""
    normalized_ids = [
        str(chart_id or "").strip()
        for chart_id in required_chart_ids
        if str(chart_id or "").strip()
    ]
    if not normalized_ids:
        return ""
    inspector = StaticChartMarkupInspector(normalized_ids)
    inspector.feed(html_content)
    for chart_id in normalized_ids:
        chart = inspector.charts[chart_id]
        if chart["svg_count"] == 0:
            return (
                f"Required business chart {chart_id} must contain a populated inline SVG; "
                "canvas and script-rendered charts are not supported in the sandboxed preview."
            )
        if chart["graphic_count"] == 0:
            return (
                f"Required business chart {chart_id} contains an empty SVG. "
                "Write visible path, rect, circle, line, polyline, or polygon data marks directly into the HTML."
            )
    return ""


def html_report_compact_value(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, str):
        return compact_text(value, 420 if depth < 3 else 220)
    if isinstance(value, list):
        if depth >= 4:
            return [compact_text(str(item), 180) for item in value[:6]]
        return [html_report_compact_value(item, depth=depth + 1) for item in value[:12]]
    if isinstance(value, dict):
        if depth >= 4:
            return {
                str(key): compact_text(str(child), 180)
                for key, child in list(value.items())[:10]
            }
        return {
            str(key): html_report_compact_value(child, depth=depth + 1)
            for key, child in list(value.items())[:24]
        }
    return compact_text(str(value), 240)


def html_report_first_http_url(value: Any) -> str:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    if isinstance(value, list):
        for item in value:
            found = html_report_first_http_url(item)
            if found:
                return found
    if isinstance(value, dict):
        for key in ("url", "image", "imageUrl", "image_url", "mainImage", "zoomImageUrl"):
            found = html_report_first_http_url(value.get(key))
            if found:
                return found
    return ""


def hot_product_required_image_urls(tool_results: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    product_urls: list[str] = []
    review_urls: list[str] = []
    for tool in tool_results:
        if not isinstance(tool, dict) or tool.get("status") not in SUCCESS_TOOL_STATUSES:
            continue
        name = str(tool.get("name") or "")
        data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
        if name == "sellersprite_market_product_concentration":
            selection = data.get("product_selection") if isinstance(data.get("product_selection"), dict) else {}
            for product in selection.get("selected") or []:
                if not isinstance(product, dict):
                    continue
                image_url = html_report_first_http_url(
                    product.get("imageUrl") or product.get("image_url") or product.get("image")
                )
                if image_url:
                    product_urls.append(image_url)
        if name == "sellersprite_market_research" and not product_urls:
            container = data.get("data") if isinstance(data.get("data"), dict) else {}
            for product in container.get("items") or []:
                if not isinstance(product, dict) or not product.get("asin"):
                    continue
                image_url = html_report_first_http_url(product)
                if image_url:
                    product_urls.append(image_url)
        if name == "sellersprite_review":
            container = data.get("data") if isinstance(data.get("data"), dict) else {}
            for review in container.get("items") or []:
                if not isinstance(review, dict):
                    continue
                image_url = html_report_first_http_url(review.get("images") or review.get("videos"))
                if image_url:
                    review_urls.append(image_url)
                    break
    return list(dict.fromkeys(product_urls))[:20], list(dict.fromkeys(review_urls))[:20]


def html_report_compact_tool_results(tool_results: Any, *, limit: int = 24) -> list[dict[str, Any]]:
    if not isinstance(tool_results, list):
        return []
    compacted: list[dict[str, Any]] = []
    for tool in tool_results[:limit]:
        if not isinstance(tool, dict):
            continue
        data = tool.get("data")
        if str(tool.get("name") or "") == "sellersprite_review" and isinstance(data, dict):
            review_container = data.get("data") if isinstance(data.get("data"), dict) else {}
            media_evidence = [
                item
                for item in review_container.get("items") or []
                if isinstance(item, dict) and (item.get("images") or item.get("videos"))
            ][:6]
            if media_evidence:
                data = {**data, "review_media_evidence": media_evidence}
        compacted_data = html_report_compact_value(data)
        if not isinstance(compacted_data, dict):
            compacted_data = {"value": compacted_data} if compacted_data not in (None, "") else {}
        compacted.append(
            {
                "name": tool.get("name"),
                "label": tool.get("label"),
                "status": tool.get("status"),
                "outcome": tool.get("outcome"),
                "summary": compact_text(str(tool.get("summary") or ""), 360),
                "input": {
                    str(key): compact_text(str(value), 180)
                    for key, value in list((tool.get("input") if isinstance(tool.get("input"), dict) else {}).items())[:16]
                    if key not in {"toolResults", "marketReportData", "skillMarkdown", "skillHtmlTemplate"}
                },
                "data": compacted_data,
            }
        )
    return compacted


def html_report_base_artifact(payload: dict[str, Any], report_data: dict[str, Any], tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    if report_data:
        existing = report_data.get("artifact") if isinstance(report_data.get("artifact"), dict) else {}
        return existing or market_report_data_to_artifact(report_data)
    return fallback_agent_artifact(
        str(payload.get("prompt") or ""),
        str(payload.get("mode") or "market"),
        str(payload.get("category") or ""),
        tool_results,
    )


def compose_html_report_with_llm(
    payload: dict[str, Any],
    *,
    locale: str = "zh",
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    report_data = payload.get("marketReportData") if isinstance(payload.get("marketReportData"), dict) else {}
    tool_results = payload.get("toolResults") if isinstance(payload.get("toolResults"), list) else []
    style_reference = html_report_style_reference(payload.get("skillMarkdown"))
    skill_html_template = str(payload.get("skillHtmlTemplate") or "")
    required_product_image_urls: list[str] = []
    required_review_image_urls: list[str] = []
    if str(payload.get("skillId") or "") == "hot_product_pain_analysis":
        required_product_image_urls, required_review_image_urls = hot_product_required_image_urls(tool_results)
    if not report_data and not tool_results:
        return "", {}, {"enabled": False, "status": "skipped", "message": "No report data or tool evidence was supplied."}
    report_context: dict[str, Any] = {
        "skill_id": payload.get("skillId"),
        "category": payload.get("category"),
        "brand": payload.get("brand"),
        "marketplace": payload.get("marketplace"),
        "time_range": payload.get("timeRange") or payload.get("time_range"),
        "generated_at": payload.get("generatedAt"),
        "mode": payload.get("mode"),
        "evidence_gaps": payload.get("evidenceGaps") if isinstance(payload.get("evidenceGaps"), list) else [],
    }
    if report_data:
        report_context["market_report_data"] = market_report_llm_context(report_data)
        report_context["report_data_schema"] = report_data.get("schema_version") or "market_report_data"
    else:
        report_context["tool_results"] = html_report_compact_tool_results(tool_results)

    required_sections = html_template_required_sections(skill_html_template)
    required_chart_ids = [
        str(chart.get("id"))
        for chart in report_data.get("chart_specs", [])
        if isinstance(chart, dict)
        and chart.get("id")
        and str(chart.get("quality_status") or "ready") == "ready"
    ][:5]
    request_payload = {
        "language": "Chinese" if locale == "zh" else "English",
        "user_prompt": payload.get("prompt") or "",
        "skill_markdown_excerpt": compact_text(str(payload.get("skillMarkdown") or ""), 5200),
        "style_reference_from_skill": style_reference,
        "skill_html_template": compact_text(skill_html_template, 18000),
        "required_template_sections": required_sections,
        "required_chart_ids": required_chart_ids,
        "required_product_image_urls": required_product_image_urls,
        "required_review_image_urls": required_review_image_urls,
        **report_context,
        "output_contract": {
            "format": "raw_html_only",
            "complete_document": True,
            "inline_css_required": True,
            "javascript_forbidden": True,
            "static_inline_svg_charts_required": bool(required_chart_ids),
            "external_dependencies_forbidden": True,
        },
    }
    system_message: dict[str, Any] = {
        "role": "system",
        "content": (
            "You are a senior product and R&D insight editor and HTML artifact designer for Hsia. "
            "Return only one complete HTML document beginning with <!doctype html> and ending with </html>. "
            "Do not return JSON, Markdown fences, commentary, or explanations outside the HTML. "
            "Use static HTML, inline CSS, and populated inline SVG only. Do not include JavaScript or canvas; "
            "the report preview is sandboxed and scripts never execute. Do not load external scripts, stylesheets, "
            "fonts, CSS imports, or CDNs. External product/review images are allowed only when their URLs "
            "appear in the supplied evidence. Do not invent metrics, ranks, ASINs, market size, search volume, "
            "sales, review quotes, or image URLs. Every important claim must show a nearby evidence handle. "
            "If evidence is missing, mark it as a data gap instead of filling it in."
            " Render every required chart id in a semantic <figure data-chart-id=\"...\"> element containing "
            "a populated inline <svg>; write all visible paths, bars, lines, points, labels, and axes directly "
            "into the HTML instead of creating an empty SVG for runtime population. "
            "For hot-product pain reports, render every supplied required product image URL and required review image URL "
            "as an <img> near its matching product or review evidence."
        ),
    }
    messages: list[dict[str, Any]] = [
        system_message,
        {
            "role": "user",
            "content": json.dumps(request_payload, ensure_ascii=False, default=str),
        },
    ]
    input_profile = {
        "request_chars": sum(len(str(message.get("content") or "")) for message in messages),
        "market_report_chars": len(json.dumps(report_context.get("market_report_data") or {}, ensure_ascii=False, default=str)),
        "tool_results_chars": len(json.dumps(report_context.get("tool_results") or [], ensure_ascii=False, default=str)),
        "skill_excerpt_chars": len(str(request_payload.get("skill_markdown_excerpt") or "")),
        "template_chars": len(str(request_payload.get("skill_html_template") or "")),
    }
    attempts: list[dict[str, Any]] = []
    last_error = "LLM did not return a usable self-contained HTML report."
    last_meta: dict[str, Any] = {}
    for attempt_index in range(1, 3):
        attempt_started = time.perf_counter()
        attempt_request_chars = sum(len(str(message.get("content") or "")) for message in messages)
        try:
            response = call_openai_compatible_chat(messages)
        except LLMUnavailable as exc:
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "unavailable",
                    "message": str(exc),
                    "duration_ms": int((time.perf_counter() - attempt_started) * 1000),
                    "request_chars": attempt_request_chars,
                }
            )
            return "", {}, {
                "enabled": True,
                "status": "unavailable",
                "message": str(exc),
                "input_profile": input_profile,
                "attempt_count": len(attempts),
                "attempts": attempts,
            }
        except Exception as exc:  # noqa: BLE001
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "error",
                    "message": str(exc),
                    "duration_ms": int((time.perf_counter() - attempt_started) * 1000),
                    "request_chars": attempt_request_chars,
                }
            )
            return "", {}, {
                "enabled": True,
                "status": "error",
                "message": str(exc),
                "input_profile": input_profile,
                "attempt_count": len(attempts),
                "attempts": attempts,
            }

        message = response.get("message") if isinstance(response.get("message"), dict) else {}
        raw_content = str(message.get("content") or "")
        html_content = normalize_llm_html_document(raw_content)
        validation_error = validate_llm_html_document(
            html_content,
            skill_html_template,
            required_chart_ids,
        )
        if not validation_error and (required_product_image_urls or required_review_image_urls):
            missing_image_urls = [
                url
                for url in [*required_product_image_urls, *required_review_image_urls]
                if url not in html_content
            ]
            if missing_image_urls:
                validation_error = (
                    "Generated HTML omitted required evidence image URL(s): "
                    + ", ".join(missing_image_urls[:4])
                )
        last_error = validation_error or ""
        last_meta = {
            "provider": response.get("provider"),
            "model": response.get("model"),
            "usage": response.get("usage") or {},
            "finish_reason": response.get("finish_reason"),
        }
        attempts.append(
            {
                "attempt": attempt_index,
                "status": "validation_failed" if validation_error else "ok",
                "message": validation_error,
                "duration_ms": int((time.perf_counter() - attempt_started) * 1000),
                "request_chars": attempt_request_chars,
                "finish_reason": response.get("finish_reason"),
                "usage": response.get("usage") or {},
                "response_chars": len(raw_content),
                "html_chars": len(html_content),
                "response_prefix": compact_text(raw_content, 240),
            }
        )
        if not validation_error:
            artifact = html_report_base_artifact(payload, report_data, tool_results)
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html_content, flags=re.IGNORECASE | re.DOTALL)
            html_title = html.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip() if title_match else ""
            artifact.setdefault("title", report_data.get("title") or html_title or "HTML 报告")
            artifact.setdefault("executive_summary", report_data.get("executive_summary") or "")
            return html_content, artifact, {
                "enabled": True,
                "status": "ok",
                **last_meta,
                "input_profile": input_profile,
                "attempt_count": len(attempts),
                "attempts": attempts,
                "quality_notes": [],
            }
        if attempt_index == 1:
            retry_payload = {
                **request_payload,
                "validation_feedback": {
                    "previous_error": validation_error,
                    "instruction": (
                        "The previous response failed HTML validation. Regenerate the complete report from the same "
                        "evidence and return raw HTML only, with no JSON, Markdown fence, preface, or trailing explanation."
                    ),
                },
            }
            messages = [
                system_message,
                {
                    "role": "user",
                    "content": json.dumps(retry_payload, ensure_ascii=False, default=str),
                },
            ]

    return "", {}, {
        "enabled": True,
        "status": "validation_failed",
        "message": last_error,
        **last_meta,
        "input_profile": input_profile,
        "attempt_count": len(attempts),
        "attempts": attempts,
    }


def build_market_report_data(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    if not category:
        raise ValueError("category is required for MarketReportData; do not default to an example category.")
    brand = str(payload.get("brand") or "Hsia")
    marketplace = str(payload.get("marketplace") or "US")
    time_range = str(payload.get("timeRange") or payload.get("time_range") or "90d")
    generated_at = str(payload.get("generatedAt") or now_iso())
    tool_results = [
        item
        for item in (payload.get("toolResults") if isinstance(payload.get("toolResults"), list) else [])
        if isinstance(item, dict)
        and str(item.get("name") or "") not in {"build_market_report_data", "build_market_report_charts", "render_html_report"}
    ]
    evidence_items = market_report_evidence_items(tool_results)
    successful = [tool for tool in tool_results if tool.get("status") in SUCCESS_TOOL_STATUSES]
    successful_tool_names = {str(tool.get("name") or "") for tool in successful}
    failed = [
        tool
        for tool in tool_results
        if tool.get("status") not in SUCCESS_TOOL_STATUSES
        and str(tool.get("name") or "") not in successful_tool_names
    ]
    kpis = kpi_from_tool_results(tool_results)
    seen_kpis = {(item.get("label"), item.get("source")) for item in kpis}
    for tool, evidence in zip(tool_results, evidence_items, strict=False):
        if tool.get("status") not in SUCCESS_TOOL_STATUSES:
            continue
        for metric in market_report_metric_items(tool.get("data"), evidence["id"], limit=6):
            key = (metric.get("label"), metric.get("source"))
            if key in seen_kpis:
                continue
            seen_kpis.add(key)
            kpis.append(
                {
                    "label": str(metric.get("label")),
                    "value": str(metric.get("value")),
                    "change": str(metric.get("field") or ""),
                    "source": str(metric.get("source") or evidence["id"]),
                }
            )
            if len(kpis) >= 12:
                break
        if len(kpis) >= 12:
            break
    keyword_trends = market_report_keyword_rows(
        tool_results,
        evidence_items,
        category=category,
        limit=24,
    )
    demand_trend = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_product_demand_trend",),
        preferred_keys=("items",),
        limit=18,
    )
    demand_metrics = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_product_demand_trend",),
        include_container=True,
        limit=2,
    )
    category_benchmark = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_research",),
        preferred_keys=("items",),
        include_terms=("category", "market", "node", "department", "subcategory", "path"),
        include_container=True,
        limit=18,
    )
    category_benchmark.extend(demand_metrics[:2])
    top_products = market_report_first_available_rows(
        tool_results,
        evidence_items,
        tool_names=(
            "sellersprite_market_product_concentration",
            "sif_market_get_keyword_competition",
            "sellersprite_market_research",
        ),
        preferred_keys=("top_competitors", "products", "items", "top10Images"),
        include_terms=("asin", "product", "listing", "title", "brand"),
        limit=30,
    )
    brand_competition = market_report_first_available_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_brand_concentration", "sellersprite_market_research"),
        preferred_keys=("brands", "items"),
        include_terms=("brand", "seller", "merchant"),
        limit=24,
    )
    price_distribution = market_report_first_available_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_price_distribution", "sellersprite_market_research"),
        preferred_keys=("price_distribution", "priceDistribution", "items"),
        include_terms=("price", "profit", "margin", "revenue", "sales", "distribution"),
        limit=24,
    )
    ratings_count_distribution = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_ratings_count_distribution",),
        preferred_keys=("items",),
        limit=16,
    )
    listing_date_distribution = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_listing_date_distribution",),
        preferred_keys=("items",),
        limit=16,
    )
    review_pain_points = market_report_user_voice(tool_results, evidence_items)
    data_gaps = [
        f"{tool.get('label') or tool.get('name')} 未成功：{tool.get('summary') or tool.get('outcome') or '未知原因'}"
        for tool in failed
    ]
    data_gaps.extend(
        str(gap.get("artifact_requirement") or f"缺少 {gap.get('tool')} 证据")
        for gap in payload.get("evidenceGaps", [])
        if isinstance(gap, dict)
    )
    if not keyword_trends:
        data_gaps.append("关键词趋势结构化字段不足，需补充 Sif/SellerSprite 关键词历史或 ABA 数据。")
    if not category_benchmark:
        data_gaps.append("类目对标结构化字段不足，需补充 SellerSprite market research 或节点级数据。")
    signal_context = {
        "keyword_trends": keyword_trends,
        "category_benchmark": category_benchmark,
        "top_products": top_products,
        "brand_competition": brand_competition,
        "price_distribution": price_distribution,
        "evidence_map": evidence_items,
        "data_gaps": list(dict.fromkeys(data_gaps))[:16],
    }
    signals = market_report_core_signals(signal_context)
    verdict = market_report_verdict(signal_context)
    success_evidence_ids = signals.get("evidence_ids") or [item["id"] for item in evidence_items if item.get("status") in SUCCESS_TOOL_STATUSES][:6]
    demand_phrase = market_report_signal_phrase(signals.get("keyword"), "关键词需求锚点不足")
    category_phrase = market_report_signal_phrase(signals.get("category"), "类目基本盘字段不足")
    price_phrase = market_report_signal_phrase(signals.get("price"), "价格带证据不足")
    brand_phrase = market_report_signal_phrase(signals.get("brand"), "品牌集中度证据不足")
    product_phrase = market_report_signal_phrase(signals.get("product"), "Top 商品证据不足")
    keyword_label = str((signals.get("keyword") or {}).get("label") or category)
    price_label = str((signals.get("price") or {}).get("label") or "主力价格带")
    competitor_label = str((signals.get("product") or signals.get("brand") or {}).get("label") or "头部竞品")
    insights = [
        {
            "id": "insight_market_base",
            "title": verdict["label"],
            "summary": f"{verdict['body']} 核心需求锚点是 {demand_phrase}，类目参照是 {category_phrase}。",
            "evidence_ids": success_evidence_ids,
        },
        {
            "id": "insight_competition",
            "title": "竞争锚点",
            "summary": f"品牌/卖家信号指向 {brand_phrase}，商品/ASIN 信号指向 {product_phrase}；进入方式应先拆门槛，再谈差异化。",
            "evidence_ids": market_report_evidence_ids_from_rows([*brand_competition[:2], *top_products[:2]], 4) or success_evidence_ids,
        },
        {
            "id": "insight_price",
            "title": "价格与边界",
            "summary": f"价格/利润相关记录 {len(price_distribution)} 条，当前价格锚点是 {price_phrase}；若缺少节点级分布，只能作为方向性假设。",
            "evidence_ids": market_report_evidence_ids_from_rows(price_distribution, 4) or success_evidence_ids,
        },
    ]
    opportunity_pool = [
        {
            "name": f"{keyword_label} 需求承接款",
            "market_evidence": f"需求锚点：{demand_phrase}；类目参照：{category_phrase}。",
            "competitor_evidence": f"货架/竞品参照：{product_phrase}；品牌参照：{brand_phrase}。",
            "product_direction": "把显小、全罩杯、侧收、上托支撑和平滑外观拆成可测试结构组合。",
            "risk": "关键词强不等于新品能承接，必须确认头部 ASIN 的评价门槛、价格带和卖点表达。",
            "priority": "A" if keyword_trends and (top_products or brand_competition) else "B",
            "next_action": "把高需求词拆成主词、长尾词和场景词，映射到 Hsia 的结构卖点、尺码覆盖和 Listing claim。",
            "evidence_ids": market_report_evidence_ids_from_rows(keyword_trends, 4),
        },
        {
            "name": f"{price_label} 价格带验证",
            "market_evidence": f"价格、销量、销售额或利润相关记录 {len(price_distribution)} 条；当前锚点：{price_phrase}。",
            "competitor_evidence": f"对应竞品参照：{brand_phrase} / {product_phrase}。",
            "product_direction": "把主力款与升级款拆开验证，不用单一均价直接决定 Hsia 的价格架构。",
            "risk": "如果价格数据来自关键词/类目搜索而非节点级分布，不能直接推导利润空间。",
            "priority": "A" if price_distribution and (brand_competition or top_products) else "B",
            "next_action": "补齐价格带销量占比、搜索购买比和利润率字段，再决定 Hsia 是否做主力价位或升级款价位。",
            "evidence_ids": market_report_evidence_ids_from_rows(price_distribution, 4),
        },
        {
            "name": f"拆解 {competitor_label} 的进入门槛",
            "market_evidence": f"类目/市场对标记录 {len(category_benchmark)} 条，用于判断该竞品是否代表市场基本盘。",
            "competitor_evidence": f"品牌锚点：{brand_phrase}；商品锚点：{product_phrase}。",
            "product_direction": "拆评价门槛、功能 claim、尺码覆盖、颜色结构和主图表达，找 Hsia 能差异化而非照搬的切口。",
            "risk": "Top 商品热度代理可能来自评论数、销量代理或排名字段，不能等同真实销量。",
            "priority": "A" if brand_competition and top_products else "B",
            "next_action": "筛出 Top ASIN 和品牌集中度最高的对标对象，进入爆款竞品拆解。",
            "evidence_ids": market_report_evidence_ids_from_rows([*brand_competition[:2], *top_products[:2]], 4),
        },
        {
            "name": "节点级补数与新品窗口验证",
            "market_evidence": f"数据缺口 {len(data_gaps)} 个，类目对标记录 {len(category_benchmark)} 条。",
            "competitor_evidence": "节点级需求趋势、价格分布、评分数分布和上架时间分布会直接影响新品机会判断。",
            "product_direction": "补数后再决定 SKU 数、尺码深度、颜色优先级和新品上市节奏。",
            "risk": "自动类目节点解析仍无唯一高置信结果时，报告只能给方向排序，不能输出最终进入门槛。",
            "priority": "B" if data_gaps else "C",
            "next_action": "先用 SellerSprite product_node 自动解析并校验 nodeIdPath，再复跑节点级工具；只有候选仍有歧义时才让用户选择。",
            "evidence_ids": market_report_evidence_ids_from_rows(category_benchmark, 4),
        },
    ]
    report_data: dict[str, Any] = {
        "schema_version": "market_report_data.v1",
        "title": f"{brand} {marketplace}市场 {category} 洞察报告",
        "brand": brand,
        "marketplace": marketplace,
        "category": category,
        "time_range": time_range,
        "generated_at": generated_at,
        "source_summary": {
            "tool_count": len(tool_results),
            "successful_tool_count": len(successful),
            "failed_tool_count": len(failed),
        },
        "market_kpis": kpis[:12],
        "keyword_trends": keyword_trends,
        "demand_trend": demand_trend,
        "category_benchmark": category_benchmark,
        "top_products": top_products,
        "brand_competition": brand_competition,
        "price_distribution": price_distribution,
        "ratings_count_distribution": ratings_count_distribution,
        "listing_date_distribution": listing_date_distribution,
        "review_pain_points": review_pain_points,
        "insights": insights,
        "opportunity_pool": opportunity_pool,
        "evidence_map": evidence_items,
        "data_gaps": list(dict.fromkeys(data_gaps))[:16],
        "next_actions": [
            "用 SellerSprite/Sif 补齐缺失的节点级或关键词级指标，再更新 MarketReportData。",
            "将 Top 商品、关键词需求和价格带信号映射为爆款基因候选。",
            "在企划会中确认 Hsia 要优先验证的价格带、结构方向和风险假设。",
        ],
    }
    report_data["analysis_sections"] = market_report_analysis_sections(report_data)
    report_data["swot"] = market_report_swot(report_data)
    report_data["decision_matrix"] = market_report_decision_matrix(report_data)
    report_data["chart_specs"] = market_report_chart_specs(report_data)
    report_signals = market_report_core_signals(report_data)
    report_verdict = market_report_verdict(report_data)
    report_data["executive_summary"] = (
        f"{report_verdict['label']}。本轮围绕 {marketplace} {category} 的核心判断是："
        f"先用 {market_report_signal_phrase(report_signals.get('keyword'), '关键词需求锚点')} 判断需求入口，"
        f"再用 {market_report_signal_phrase(report_signals.get('brand') or report_signals.get('product'), '竞争锚点')} 判断进入门槛，"
        f"最后用 {market_report_signal_phrase(report_signals.get('price'), '价格带锚点')} 验证 Hsia 的价格与结构假设。"
        f"报告已沉淀 {len(opportunity_pool)} 个研发机会；若涉及节点级市场规模、价格分布或新品进入门槛，"
        "需先补齐缺口再进入 SKU 决策。"
    )
    report_data["artifact"] = market_report_data_to_artifact(report_data)
    return report_data


def render_html_report_tool(payload: dict[str, Any]) -> dict[str, Any]:
    report_data = payload.get("marketReportData") if isinstance(payload.get("marketReportData"), dict) else {}
    if not payload.get("useLlm"):
        raise RuntimeError("render_html_report requires LLM-authored HTML. Enable useLlm=true; no template renderer is available.")
    chart_specs = payload.get("chartSpecs") if isinstance(payload.get("chartSpecs"), list) else []
    if report_data and chart_specs:
        report_data = {**report_data, "chart_specs": chart_specs}
    elif report_data and (not isinstance(report_data.get("chart_specs"), list) or not report_data.get("chart_specs")):
        chart_payload = build_market_report_charts(report_data)
        generated_specs = chart_payload.get("chart_specs") if isinstance(chart_payload, dict) else []
        if isinstance(generated_specs, list):
            report_data = {**report_data, "chart_specs": generated_specs}
    render_payload = dict(payload)
    if report_data:
        render_payload["marketReportData"] = report_data
    html_content, artifact, html_analysis = compose_html_report_with_llm(
        render_payload,
        locale="zh",
    )
    if not html_content:
        status = html_analysis.get("status") or "error"
        detail = html_analysis.get("message") or "LLM did not return a usable self-contained HTML report."
        raise HtmlReportGenerationError(
            f"LLM HTML generation failed ({status}): {detail}",
            html_analysis,
        )
    if not artifact:
        artifact = (
            report_data.get("artifact")
            if isinstance(report_data.get("artifact"), dict)
            else market_report_data_to_artifact(report_data)
        )
    return {
        "format": "html",
        "title": report_data.get("title") or artifact.get("title") or "HTML 报告",
        "html": html_content,
        "market_report_data": report_data,
        "artifact": artifact,
        "renderer": "llm-html",
        "html_analysis": html_analysis,
    }


def write_agent_run_json(run_id: str, filename: str, payload: Any) -> str:
    run_dir = CACHE_DIR / "agent-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / filename
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(temporary, path)
    return str(path)


def write_agent_run_text(run_id: str, filename: str, content: str) -> str:
    run_dir = CACHE_DIR / "agent-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


def read_agent_output_file(path_value: str) -> dict[str, Any]:
    if not path_value:
        raise ValueError("path is required")
    requested = Path(path_value).expanduser().resolve()
    allowed_root = (CACHE_DIR / "agent-runs").resolve()
    try:
        requested.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError("file is outside the agent output directory") from exc
    if requested.suffix.lower() not in {".json", ".md", ".html"}:
        raise ValueError("only JSON, Markdown, and HTML output files can be opened")
    if not requested.exists() or not requested.is_file():
        raise ValueError("output file was not found")
    if requested.suffix.lower() == ".md":
        return {
            "name": requested.name,
            "path": str(requested),
            "format": "markdown",
            "content": requested.read_text(encoding="utf-8"),
        }
    if requested.suffix.lower() == ".html":
        return {
            "name": requested.name,
            "path": str(requested),
            "format": "html",
            "content": requested.read_text(encoding="utf-8"),
        }
    return {
        "name": requested.name,
        "path": str(requested),
        "format": "json",
        "content": json.loads(requested.read_text(encoding="utf-8")),
    }


AGENT_PARAM_LABELS = {
    "brand": {"zh": "品牌", "en": "brand"},
    "marketplace": {"zh": "市场", "en": "marketplace"},
    "category": {"zh": "品类", "en": "category"},
    "time_range": {"zh": "时间范围", "en": "time range"},
}

AGENT_PARAM_SUGGESTIONS = {
    "brand": ["Hsia / 遐"],
    "marketplace": ["US", "美国站(com)"],
    "category": ["sports bra", "minimizer bra", "full coverage bra"],
    "time_range": ["最近30天", "最近90天", "最近一年"],
}


def load_agent_run(run_id: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[a-f0-9]{12}", run_id or ""):
        return None
    path = CACHE_DIR / "agent-runs" / run_id / "run.json"
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def load_agent_run_state(run_id: str) -> dict[str, Any] | None:
    completed = load_agent_run(run_id)
    if completed:
        return {
            "run_id": run_id,
            "status": completed.get("status") or "ok",
            "updated_at": completed.get("generated_at"),
            "events": completed.get("events") or [],
            "result": completed,
        }
    if not re.fullmatch(r"[a-f0-9]{12}", run_id or ""):
        return None
    path = CACHE_DIR / "agent-runs" / run_id / "progress.json"
    if not path.exists() or not path.is_file():
        return None
    try:
        progress = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return {
        "run_id": run_id,
        "status": progress.get("status") or "running",
        "updated_at": progress.get("updated_at"),
        "events": progress.get("events") or [],
        "error": progress.get("error"),
        "progress": progress,
    }


def build_agent_clarification(
    skill: dict[str, Any],
    missing_params: list[str],
    resolved_params: dict[str, Any],
    locale: str,
) -> dict[str, Any]:
    language = "en" if locale == "en" else "zh"
    labels = [
        AGENT_PARAM_LABELS.get(param, {}).get(language, param)
        for param in missing_params
    ]
    if language == "en":
        message = (
            f"I loaded {skill.get('name')}, but need these inputs before running tools: "
            f"{', '.join(labels)}."
        )
        question_prefix = "Please confirm"
    else:
        message = (
            f"我已加载「{skill.get('name')}」，但执行工具前还需要确认："
            f"{'、'.join(labels)}。"
        )
        question_prefix = "请确认"
    questions = [
        {
            "field": param,
            "label": AGENT_PARAM_LABELS.get(param, {}).get(language, param),
            "question": f"{question_prefix}{AGENT_PARAM_LABELS.get(param, {}).get(language, param)}",
            "suggestions": AGENT_PARAM_SUGGESTIONS.get(param, []),
        }
        for param in missing_params
    ]
    return {
        "status": "needs_input",
        "message": message,
        "missing_params": missing_params,
        "resolved_params": resolved_params,
        "questions": questions,
    }


def build_clarification_artifact(
    prompt: str,
    mode: str,
    category: str,
    clarification: dict[str, Any],
    locale: str,
) -> dict[str, Any]:
    if locale == "en":
        return {
            "title": "More inputs needed",
            "executive_summary": clarification["message"],
            "key_findings": [f"Missing input: {question['label']}" for question in clarification.get("questions", [])],
            "opportunities": ["After the user confirms the missing inputs, continue the same selected skill."],
            "risks": ["No data tools were run yet, so no market conclusion has been generated."],
            "next_steps": ["Reply with the missing inputs in one sentence."],
            "prompt": prompt,
            "mode": mode,
            "category": category,
        }
    return {
        "title": "需要补齐参数",
        "executive_summary": clarification["message"],
        "key_findings": [f"缺少参数：{question['label']}" for question in clarification.get("questions", [])],
        "opportunities": ["用户补齐参数后，继续执行同一个 Skill。"],
        "risks": ["当前还没有调用数据工具，因此不会生成市场结论。"],
        "next_steps": ["请用一句话补充缺少的参数。"],
        "prompt": prompt,
        "mode": mode,
        "category": category,
    }


def analyze_category(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    if not category:
        raise ValueError("category is required")
    limit = int(payload.get("limit") or 25)
    limit = max(5, min(limit, MAX_RESEARCH_POST_LIMIT))
    time_range = normalize_agent_time_range(payload.get("timeRange")) or "year"
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


def run_agent(payload: dict[str, Any], emit_event: Any | None = None) -> dict[str, Any]:
    from .agent_runtime import AgentRuntimeDeps, LangGraphAgentRuntime

    runtime = LangGraphAgentRuntime(
        AgentRuntimeDeps(
            now_iso=now_iso,
            load_agent_run=load_agent_run,
            write_json=write_agent_run_json,
            write_text=write_agent_run_text,
            agent_event=agent_event,
            category_from_payload=agent_category_from_payload,
            call_chat=call_openai_compatible_chat,
            skill_registry=lambda: AGENT_SKILL_REGISTRY,
            skill_manifests=agent_skill_manifests,
            resolve_skill_params=resolve_agent_skill_params,
            payload_with_skill_params=agent_payload_with_skill_params,
            tool_input_payload=agent_tool_input_payload,
            execute_tool=execute_agent_tool_with_timeout,
            build_clarification=build_agent_clarification,
            build_clarification_artifact=build_clarification_artifact,
            tool_catalog=agent_tool_catalog,
            cache_dir=lambda: CACHE_DIR,
            render_html_report=render_html_report_tool,
        )
    )
    return runtime.run(payload, emit_event=emit_event)


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
        if parsed.path == "/api/settings/llm":
            self.send_json(build_llm_settings_response())
            return
        if parsed.path == "/api/settings/mcp":
            self.send_json(build_mcp_settings_response())
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
        if parsed.path == "/api/agent/output-file":
            query = urllib.parse.parse_qs(parsed.query)
            path_value = query.get("path", [""])[0]
            try:
                self.send_json(read_agent_output_file(path_value))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path.startswith("/api/agent/runs/"):
            run_id = parsed.path.removeprefix("/api/agent/runs/").strip("/")
            state = load_agent_run_state(run_id)
            if state is None:
                self.send_json({"error": "Agent run was not found."}, status=HTTPStatus.NOT_FOUND)
            else:
                self.send_json(state)
            return
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in {
            "/api/agent/run",
            "/api/agent/run/stream",
            "/api/settings/llm",
            "/api/settings/mcp",
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
            elif parsed.path == "/api/agent/run/stream":
                self.send_agent_run_stream(payload)
                return
            elif parsed.path == "/api/settings/llm":
                result = update_llm_settings(payload)
            elif parsed.path == "/api/settings/mcp":
                result = update_mcp_settings(payload)
            elif parsed.path == "/api/settings/reddit":
                result = update_reddit_settings(payload)
            elif parsed.path == "/api/settings/research":
                result = update_research_settings(payload)
            elif parsed.path == "/api/settings/agent-reach":
                result = update_agent_reach_settings(payload)
            elif parsed.path == "/api/settings/web-search":
                result = update_web_search_settings(payload)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_json(result)
        except OperationCancelled as exc:
            self.send_json({"error": str(exc), "cancelled": True}, status=HTTPStatus.CONFLICT)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": f"Analysis failed: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:
        self.send_error(HTTPStatus.NOT_FOUND)

    def send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_sse(self, event_name: str, payload: dict[str, Any]) -> None:
        body = (
            f"event: {event_name}\n"
            f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
        ).encode()
        self.wfile.write(body)
        self.wfile.flush()

    def send_agent_run_stream(self, payload: dict[str, Any]) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()

        connected = True

        def safe_send(event_name: str, event_payload: dict[str, Any]) -> None:
            nonlocal connected
            if not connected:
                return
            try:
                self.send_sse(event_name, event_payload)
            except (BrokenPipeError, ConnectionResetError, OSError):
                connected = False

        try:
            result = run_agent(payload, emit_event=lambda event: safe_send("event", event))
            safe_send("result", result)
        except ValueError as exc:
            safe_send("error", {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            safe_send("error", {"error": f"Analysis failed: {exc}"})


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

from __future__ import annotations

import base64
import concurrent.futures
import copy
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import queue
import re
import threading
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
    bounded_int,
    normalize_agent_time_range,
    resolve_agent_tool_params,
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
from .bra_attributes import build_bra_attribute_distribution, is_bra_category
from .fastmoss_competitor_shop_report import (
    build_tiktok_bra_competitor_shop_report_data,
    tiktok_bra_competitor_shop_report_data_to_artifact,
)
from .fastmoss_market_report import build_fastmoss_market_report_data
from .fastmoss_new_product_report import (
    build_tiktok_new_product_report_data,
    tiktok_new_product_report_data_to_artifact,
)
from .flint_chart_mcp import render_report_charts_via_flint
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
from .market_analysis_coverage import (
    build_market_dimension_results,
    build_tool_methodology,
    evaluate_market_analysis_coverage,
)
from .market_data_dedup import run_market_data_dedup
from .market_product_identity import (
    product_family_report_rows,
    resolve_market_product_identity,
)
from .mcp_fastmoss import (
    build_fastmoss_input_payload,
    execute_fastmoss_agent_tool,
    get_fastmoss_tool_catalog,
    is_fastmoss_agent_tool,
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
from .report_charts import (
    build_market_report_charts,
    repair_missing_or_empty_chart_figures,
    replace_compiled_chart_figures,
    replace_degraded_chart_figures,
    replace_server_rendered_chart_figures,
)
from .report_insight_synthesis import (
    fallback_report_insight_narrative,
    normalize_report_insight_narrative,
)
from .report_metric_analysis import (
    attach_metric_facts,
    available_metric_catalog_for_skill,
    calculate_metric_analysis,
    default_metric_proposals,
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
from .tool_capabilities import ToolCapabilityRegistry
from .tool_capabilities.local import build_reddit_voc_capability

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
AGENT_STREAM_HEARTBEAT_SECONDS = 15.0
ACTIVE_AGENT_RUN_IDS: set[str] = set()
ACTIVE_AGENT_RUN_LOCK = threading.Lock()
HTML_REPORT_DATA_BUILDERS = {
    "build_market_report_data",
    "build_tiktok_new_product_report_data",
    "build_tiktok_bra_competitor_shop_report_data",
    "build_trend_report_data",
    "build_competitor_product_report_data",
    "build_hot_product_pain_report_data",
}
HTML_REPORT_MAX_OUTPUT_TOKENS = 100_000


class OperationCancelled(RuntimeError):
    """Raised when a long-running analysis is cancelled by the user."""


class HtmlReportGenerationError(RuntimeError):
    """Raised when the LLM cannot produce a valid self-contained HTML report."""

    def __init__(self, message: str, analysis: dict[str, Any]) -> None:
        super().__init__(message)
        self.analysis = analysis


class MarkdownReportGenerationError(RuntimeError):
    """Raised when the LLM cannot produce a valid evidence-linked Markdown report."""

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
    reddit_report = (
        item.get("reddit_report") if isinstance(item.get("reddit_report"), dict) else None
    )
    amazon_report = (
        item.get("amazon_report") if isinstance(item.get("amazon_report"), dict) else None
    )
    youtube_report = (
        item.get("youtube_report") if isinstance(item.get("youtube_report"), dict) else None
    )
    tiktok_report = (
        item.get("tiktok_report") if isinstance(item.get("tiktok_report"), dict) else None
    )
    combined_report = (
        item.get("combined_report") if isinstance(item.get("combined_report"), dict) else None
    )
    article_report = (
        item.get("article_report") if isinstance(item.get("article_report"), dict) else None
    )
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
        "article_count": int(
            ((article_report or {}).get("data_volume") or {}).get("collected_articles") or 0
        ),
        "evidence_items": int(
            ((combined_report or {}).get("data_summary") or {}).get("evidence_items") or 0
        ),
    }


def list_research_history() -> dict[str, Any]:
    items = sorted(
        read_history_items(), key=lambda item: str(item.get("saved_at", "")), reverse=True
    )
    return {
        "items": [history_summary(item) for item in items],
        "storage_path": history_storage_path(),
    }


def save_research_history(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    reddit_report = (
        payload.get("reddit_report") if isinstance(payload.get("reddit_report"), dict) else None
    )
    amazon_report = (
        payload.get("amazon_report") if isinstance(payload.get("amazon_report"), dict) else None
    )
    youtube_report = (
        payload.get("youtube_report") if isinstance(payload.get("youtube_report"), dict) else None
    )
    tiktok_report = (
        payload.get("tiktok_report") if isinstance(payload.get("tiktok_report"), dict) else None
    )
    combined_report = (
        payload.get("combined_report") if isinstance(payload.get("combined_report"), dict) else None
    )
    article_report = (
        payload.get("article_report") if isinstance(payload.get("article_report"), dict) else None
    )
    if not category:
        category = str(
            (
                (
                    combined_report
                    or reddit_report
                    or amazon_report
                    or youtube_report
                    or tiktok_report
                    or article_report
                    or {}
                ).get("category")
            )
            or ""
        ).strip()
    if not category:
        raise ValueError("category is required")
    if not any(
        (
            reddit_report,
            amazon_report,
            youtube_report,
            tiktok_report,
            combined_report,
            article_report,
        )
    ):
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


def fetch_reddit_oauth(
    query: str, limit: int, time_range: str
) -> tuple[list[dict[str, Any]], list[str]]:
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


def filter_posts_by_time_range(
    posts: list[dict[str, Any]], time_range: str
) -> tuple[list[dict[str, Any]], list[str]]:
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
        warnings.append(
            f"Filtered {dropped} Reddit posts outside requested time range {time_range}."
        )
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
    effective_comments_per_post = int_setting(
        settings_values, "AGENT_REACH_COMMENTS_PER_POST", 20, 0, 200
    )
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
    cached = (
        None if bypass_cache else read_cache(cache_path, ttl_seconds=ANALYSIS_CACHE_TTL_SECONDS)
    )
    if bypass_cache:
        warnings.append("Bypassed local cache for this run.")
    if cached:
        cached_posts = cached["posts"]
        cached_mode = cached["mode"]
        wants_comment_bodies = effective_detail_limit > 0 and effective_comments_per_post > 0
        cached_missing_comment_bodies = (
            cached_mode == "agent_reach"
            and bool(cached_posts)
            and sum(len(post_comment_items(post)) for post in cached_posts) == 0
        )
        if (
            cached_missing_comment_bodies
            and wants_comment_bodies
            and agent_reach_health().get("ready")
        ):
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
        agent_reach_result = fetch_reddit_agent_reach(
            query, provider_limit, provider_time_range, **agent_reach_kwargs
        )
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
        rss_posts, rss_warnings = fetch_reddit_rss(
            query, provider_limit, provider_time_range, bypass_cache=bypass_cache
        )
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


def build_trend_series(
    month_counts: Counter[str], minimum_months: int = 6
) -> list[dict[str, int | str]]:
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
        len(post_comment_items(post)[:ai_comment_sample_limit]) for post in ai_posts
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


def summarize_posts(
    category: str, posts: list[dict[str, Any]], source_mode: str, warnings: list[str]
) -> dict[str, Any]:
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
    confidence = (
        "Medium" if source_mode in {"agent_reach", "oauth", "rss"} and len(posts) >= 15 else "Low"
    )
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
            "summary": make_market_summary(
                category, posts, subreddit_counts, topic_counts, confidence
            ),
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

    result = fetch_amazon_opencli(
        category, limit, keyword_limit=keyword_limit, bypass_cache=bypass_cache
    )
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
    brand_counts = Counter(
        product.get("brand") or brand_from_title(str(product.get("title") or ""))
        for product in products
    )
    brand_counts.pop("", None)
    prices = [
        float(product["price_value"])
        for product in products
        if isinstance(product.get("price_value"), int | float)
    ]
    ratings = [
        float(product["rating_value"])
        for product in products
        if isinstance(product.get("rating_value"), int | float)
    ]
    review_counts = [
        int(product["review_count"])
        for product in products
        if isinstance(product.get("review_count"), int | float)
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
        len((product.get("review_samples") or [])[:ai_review_samples_per_product])
        for product in ai_products
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
    return [
        {"name": name, "count": sum(1 for price in prices if predicate(price))}
        for name, predicate in bands
    ]


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


def should_exclude_competitor_product(
    product: dict[str, Any], brief: dict[str, str]
) -> tuple[bool, str]:
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
        reasons.append(
            f"Amazon review count {review_count:,} is enough for a promising breakout read."
        )
    elif review_count >= COMPETITOR_MIN_REVIEW_COUNT:
        risks.append(
            f"Amazon review count {review_count:,} is directional but still thin for breakout status."
        )
    else:
        risks.append(
            f"Amazon review count {review_count:,} is too low to call this a breakout competitor."
        )

    if rating >= 4.3:
        reasons.append(f"Rating {rating:.1f} suggests broad buyer satisfaction.")
    elif rating >= COMPETITOR_MIN_RATING:
        reasons.append(f"Rating {rating:.1f} clears the minimum satisfaction gate.")
    elif rating > 0:
        risks.append(f"Rating {rating:.1f} is below the breakout satisfaction gate.")
    else:
        risks.append("No rating was collected.")

    if review_evidence_count:
        reasons.append(
            f"{review_evidence_count} review samples are available for qualitative teardown."
        )
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
    keyword_limit = int(
        payload.get("amazonKeywordLimit") or os.getenv("AMAZON_KEYWORD_LIMIT", "8") or 8
    )
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
    query = str(
        payload.get("query")
        or build_competitor_discovery_query(brief)
        or DEFAULT_COMPETITOR_DISCOVERY_QUERY
    ).strip()
    if not query:
        raise ValueError("query is required")
    limit = int(payload.get("limit") or os.getenv("AMAZON_PRODUCT_LIMIT", "20") or 20)
    limit = max(1, min(limit, 100))
    keyword_limit = int(
        payload.get("amazonKeywordLimit") or os.getenv("AMAZON_KEYWORD_LIMIT", "8") or 8
    )
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
            {
                "strong_breakout": 4,
                "needs_tiktok_validation": 3,
                "watchlist": 2,
                "low_evidence": 1,
            }.get(item.get("breakout_tier"), 0),
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
            "evidence_items_count": sum(
                1 + len(candidate["review_evidence"]) for candidate in candidates
            ),
            "last_run_at": now_iso(),
            "failure_reason": ""
            if products
            else "Amazon provider returned no products for this query.",
            "next_action": "Review breakout tiers, run TikTok validation on promising candidates, then confirm items for teardown."
            if products
            else "Check OpenCLI Amazon access, broaden keywords, or rerun with bypass cache.",
        },
        "data_volume": {
            "requested_products": limit * max(1, len(queries)),
            "requested_products_per_query": limit,
            "query_count": len(queries),
            "queries": queries,
            "per_query_counts": [
                {"query": query, "count": per_query_counts.get(query, 0)} for query in queries
            ],
            "raw_collected_products": sum(per_query_counts.get(query, 0) for query in queries),
            "unique_products": len(products),
            "excluded_products": len(excluded),
            "candidate_count": len(candidates),
            "strong_breakout_candidates": sum(
                1 for candidate in candidates if candidate.get("breakout_tier") == "strong_breakout"
            ),
            "needs_tiktok_validation_candidates": sum(
                1
                for candidate in candidates
                if candidate.get("breakout_tier") == "needs_tiktok_validation"
            ),
            "low_evidence_candidates": sum(
                1 for candidate in candidates if candidate.get("breakout_tier") == "low_evidence"
            ),
        },
        "summary": {
            "candidate_count": len(candidates),
            "high_priority": sum(1 for candidate in candidates if candidate["priority"] == "High"),
            "medium_priority": sum(
                1 for candidate in candidates if candidate["priority"] == "Medium"
            ),
            "strong_breakout": sum(
                1 for candidate in candidates if candidate.get("breakout_tier") == "strong_breakout"
            ),
            "needs_tiktok_validation": sum(
                1
                for candidate in candidates
                if candidate.get("breakout_tier") == "needs_tiktok_validation"
            ),
            "low_evidence": sum(
                1 for candidate in candidates if candidate.get("breakout_tier") == "low_evidence"
            ),
            "brands": [
                {"name": name, "count": count} for name, count in brand_counts.most_common(12)
            ],
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
        "matched_queries": product.get("matched_queries")
        if isinstance(product.get("matched_queries"), list)
        else [],
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
        reasons.append(
            f"Matches the brief's category/user language: {', '.join(matched_terms[:5])}."
        )
    else:
        risks.append(
            "Weak explicit match to the brief's category, user, or brand-direction language."
        )

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
            reasons.append(
                f"Price sits in the brief's upgrade-test {brief['upgradePriceBand']} band."
            )
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
        reasons.append(
            f"Size language overlaps the brief's {brief['coreSizes']} target: {', '.join(size_matches[:3])}."
        )
    else:
        size_score = 0
        risks.append(
            f"No explicit evidence for the brief's {brief['coreSizes']} size lane was collected."
        )
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

    matched_queries = (
        product.get("matched_queries") if isinstance(product.get("matched_queries"), list) else []
    )
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
    reviews = (
        product.get("review_samples") if isinstance(product.get("review_samples"), list) else []
    )
    evidence = []
    for review in reviews[:5]:
        if not isinstance(review, dict):
            continue
        body = compact_text(
            f"{review.get('title') or ''}: {review.get('body') or ''}".strip(": "), 320
        )
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
    tiktok_status = (
        (product.get("tiktok_validation") or {})
        if isinstance(product.get("tiktok_validation"), dict)
        else {}
    ).get("status") or ""
    has_quality_evidence = (
        review_evidence_count > 0
        or review_count >= COMPETITOR_STRONG_REVIEW_COUNT
        or tiktok_status == "verified"
    )
    if (
        score >= 72
        and review_count >= COMPETITOR_PROMISING_REVIEW_COUNT
        and rating >= COMPETITOR_MIN_RATING
        and has_quality_evidence
    ):
        return "High"
    if score >= 52 and review_count >= COMPETITOR_MIN_REVIEW_COUNT and rating >= 3.8:
        return "Medium"
    return "Low"


def competitor_tiktok_query(candidate: dict[str, Any], brief: dict[str, str] | None = None) -> str:
    brand = clean_text(str(candidate.get("brand") or ""))
    title = clean_text(str(candidate.get("title") or ""))
    category_terms = "minimizer bra large bust review"
    if brief and brief.get("coreKeywords"):
        first_keyword = (
            split_brief_terms(brief["coreKeywords"])[0]
            if split_brief_terms(brief["coreKeywords"])
            else ""
        )
        if first_keyword:
            category_terms = f"{first_keyword} review"
    title_without_brand = title
    if brand:
        title_without_brand = re.sub(
            rf"\b{re.escape(brand)}\b", "", title_without_brand, flags=re.I
        )
    title_words = [
        word
        for word in re.split(r"[^A-Za-z0-9]+", title_without_brand)
        if len(word) >= 3
        and word.lower()
        not in {"women", "womens", "woman", "plus", "size", "with", "for", "and", "the"}
    ][:6]
    if brand:
        return clean_text(f"{brand} {' '.join(title_words[:3])} {category_terms}")
    return clean_text(f"{' '.join(title_words)} {category_terms}") or category_terms


def score_tiktok_competitor_validation(
    candidate: dict[str, Any], videos: list[dict[str, Any]]
) -> dict[str, Any]:
    brand = str(candidate.get("brand") or "").lower().strip()
    title_terms = [
        word
        for word in re.split(r"[^a-z0-9]+", str(candidate.get("title") or "").lower())
        if len(word) >= 4
        and word not in {"women", "womens", "with", "support", "coverage", "minimizer", "brassiere"}
    ][:8]
    category_terms = [
        "minimizer",
        "large bust",
        "full coverage",
        "support",
        "smoothing",
        "bra",
        "review",
        "try on",
        "try-on",
    ]
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
                "title": compact_text(
                    video.get("title") or video.get("caption") or "TikTok video", 180
                ),
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
    weight = float(
        score_weights.get("tiktokProof", DEFAULT_COMPETITOR_SCORE_WEIGHTS["tiktokProof"])
    )
    weighted_points = round(raw_points * weight, 1)
    updated["score"] = int(
        round(max(0, min(100, int(candidate.get("score") or 0) + weighted_points)))
    )
    breakdown = list(
        candidate.get("score_breakdown")
        if isinstance(candidate.get("score_breakdown"), list)
        else []
    )
    breakdown = [
        item
        for item in breakdown
        if not (isinstance(item, dict) and item.get("key") == "tiktokProof")
    ]
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
        updated["risks"] = unique_strings([*validation["risks"], *(candidate.get("risks") or [])])[
            :6
        ]
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
    updated_candidate = apply_tiktok_validation_to_competitor(
        raw_candidate, validation, score_weights
    )
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

    review_samples = (
        raw.get("review_samples") if isinstance(raw.get("review_samples"), list) else []
    )
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
        "matched_queries": raw.get("matched_queries")
        if isinstance(raw.get("matched_queries"), list)
        else [],
        "score": raw.get("score"),
        "priority": raw.get("priority"),
    }


def competitor_product_search_phrase(product: dict[str, Any], max_words: int = 12) -> str:
    brand = clean_text(str(product.get("brand") or ""))
    title = clean_text(str(product.get("title") or ""))
    title = re.sub(
        r"\b(?:women'?s|for women|amazon|prime|store|visit the)\b", " ", title, flags=re.I
    )
    title = re.sub(r"[|:()\[\]{}]", " ", title)
    words = [word for word in re.split(r"\s+", title) if word]
    if brand:
        words = [word for word in words if word.casefold() != brand.casefold()]
    core_title = " ".join(words[:max_words])
    phrase = clean_text(f"{brand} {core_title}".strip())
    return (
        phrase
        or title
        or str(product.get("asin") or "").strip()
        or str(product.get("product_url") or "").strip()
    )


def competitor_category_context(product: dict[str, Any], payload: dict[str, Any]) -> str:
    category = str(payload.get("category") or "").strip()
    if category:
        return category
    brief = (
        normalize_competitor_brief(payload)
        if isinstance(payload.get("brief"), dict)
        else DEFAULT_COMPETITOR_DISCOVERY_BRIEF
    )
    product_phrase = competitor_product_search_phrase(product, max_words=8)
    return clean_text(
        f"{product_phrase} {brief.get('category') or ''} {brief.get('coreKeywords') or ''}"
    )


def collect_competitor_amazon_product(
    product: dict[str, Any],
    review_limit: int,
    bypass_cache: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    target = str(product.get("asin") or product.get("product_url") or "").strip()
    cache_path = cache_key([CACHE_VERSION, "competitor-amazon-product", target, str(review_limit)])
    cached = (
        None if bypass_cache else read_cache(cache_path, ttl_seconds=ANALYSIS_CACHE_TTL_SECONDS)
    )
    if isinstance(cached, dict) and isinstance(cached.get("product"), dict):
        return cached["product"], ["Loaded competitor Amazon product/reviews from local cache."]

    warnings: list[str] = []
    enriched = dict(product)
    if not target:
        warnings.append(
            "No ASIN or Amazon product URL is available, so Amazon detail/review reads were skipped."
        )
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
    reviews = (
        product.get("review_samples") if isinstance(product.get("review_samples"), list) else []
    )
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
        dates = [
            date
            for date in (
                parse_amazon_review_date(str(review.get("date_text") or "")) for review in reviews
            )
            if date
        ]
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
        "confidence": "Medium"
        if isinstance(review_count, int | float) and int(review_count) >= 1000 and reviews
        else "Low",
        "caveats": [
            "Amazon true unit sales are not public in this MVP.",
            "Review count, rating, badges, rank, and sponsorship are proxy signals, not revenue or market share.",
            "Reliable sales sizing needs paid third-party Amazon estimates, seller-owned data, or repeated BSR/rank snapshots.",
        ],
    }


def competitor_web_search_queries(
    product: dict[str, Any], category: str, limit: int = 4
) -> list[str]:
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
            provider_name, results, query_warnings = web_search_query(
                query, 5, bypass_cache=bypass_cache
            )
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
            score, source_type, reasons = score_competitor_web_candidate(
                product, category, title, snippet, domain, url
            )
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
    return compact_text(
        f"{review.get('title') or ''}: {review.get('body') or ''}".strip(": "), limit
    )


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

    reviews = (
        product.get("review_samples") if isinstance(product.get("review_samples"), list) else []
    )
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

    for post_index, post in enumerate(
        (reddit_report or {}).get("posts", [])[:ai_reddit_post_limit], start=1
    ):
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
        snippets = (
            article.get("evidence_snippets")
            if isinstance(article.get("evidence_snippets"), list)
            else []
        )
        excerpt = " ".join(str(snippet) for snippet in snippets[:2]) or str(
            article.get("title") or ""
        )
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
    top_pain = ((reddit_report or {}).get("pain_points") or [{}])[0].get(
        "topic"
    ) or "fit/support language"
    default_ids = [item["id"] for item in evidence_pool[:3]]
    amazon_ids = [item["id"] for item in evidence_pool if item["source"] == "amazon"][
        :3
    ] or default_ids[:1]
    reddit_ids = [item["id"] for item in evidence_pool if item["source"] == "reddit"][
        :3
    ] or default_ids[:1]
    web_ids = [item["id"] for item in evidence_pool if item["source"] == "web"][:2] or default_ids[
        :1
    ]
    mixed_ids = (
        unique_ids([*(amazon_ids[:1]), *(reddit_ids[:1]), *(web_ids[:1])]) or default_ids[:1]
    )
    proxy_summary = (
        "; ".join(f"{item['name']}: {item['value']}" for item in sales_proxy.get("signals", [])[:3])
        or "limited public proxy signals"
    )
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
            "text": str(
                verdict_raw.get("text")
                or f"{category} has directional competitor evidence, but sales confidence remains limited."
            ),
            "citations": resolve_citations(
                verdict_raw.get("citation_ids"), evidence_pool, fallback_ids
            ),
        },
        "breakout_assessment": normalize_insight_items(
            raw.get("breakout_assessment"), 3, evidence_pool, fallback_ids, "爆款判断"
        ),
        "why_it_sells": normalize_insight_items(
            raw.get("why_it_sells"), 3, evidence_pool, fallback_ids, "可能热卖原因"
        ),
        "user_love": normalize_insight_items(
            raw.get("user_love"), 3, evidence_pool, fallback_ids, "用户喜欢"
        ),
        "user_complaints": normalize_insight_items(
            raw.get("user_complaints"), 3, evidence_pool, fallback_ids, "用户抱怨"
        ),
        "rd_teardown": normalize_insight_items(
            raw.get("rd_teardown"), 3, evidence_pool, fallback_ids, "研发拆解"
        ),
        "brand_communication": normalize_insight_items(
            raw.get("brand_communication"), 3, evidence_pool, fallback_ids, "品牌沟通"
        ),
        "sales_proxy_interpretation": normalize_insight_items(
            raw.get("sales_proxy_interpretation"),
            2,
            evidence_pool,
            fallback_ids,
            "销量代理解读",
        ),
        "risks": normalize_insight_items(raw.get("risks"), 3, evidence_pool, fallback_ids, "风险"),
        "evidence_chain": normalize_chain_items(
            raw.get("evidence_chain"), evidence_pool, fallback_ids
        ),
        "data_gaps": normalize_insight_items(
            raw.get("data_gaps"), 3, evidence_pool, fallback_ids, "数据缺口"
        ),
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
        min(
            int(
                payload.get("amazonReviewLimit")
                or values.get("COMPETITOR_AMAZON_REVIEW_LIMIT", "80")
                or 80
            ),
            300,
        ),
    )
    reddit_limit = max(
        5,
        min(
            int(
                payload.get("redditLimit") or values.get("INSIGHT_RESEARCH_POST_LIMIT", "50") or 50
            ),
            MAX_RESEARCH_POST_LIMIT,
        ),
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

    web_sources = (
        discover_competitor_web_sources(
            product,
            category,
            web_candidate_limit,
            bypass_cache=bypass_cache,
            run_id=run_id,
        )
        if web_candidate_limit
        else {
            "source_mode": "web_search_skipped",
            "queries": [],
            "candidates": [],
            "articles": [],
            "warnings": ["Brand/web source discovery was skipped because webCandidateLimit is 0."],
            "data_volume": {
                "query_count": 0,
                "raw_results": 0,
                "candidate_count": 0,
                "readable_sources": 0,
                "failed_sources": 0,
                "per_query_counts": [],
            },
        }
    )
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
        raw = build_fallback_competitor_deep_dive_raw(
            category, product, reddit_report, sales_proxy, evidence_pool
        )

    narrative = normalize_competitor_deep_dive_report(category, raw, evidence_pool)
    reviews = (
        product.get("review_samples") if isinstance(product.get("review_samples"), list) else []
    )
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
            "web_candidates": int(
                (web_sources.get("data_volume") or {}).get("candidate_count") or 0
            ),
            "web_sources_read": int(
                (web_sources.get("data_volume") or {}).get("readable_sources") or 0
            ),
            "ai_review_limit": ai_review_limit,
            "ai_reviews": min(len(reviews), ai_review_limit),
            "ai_reddit_post_limit": ai_reddit_post_limit,
            "ai_reddit_posts": min(
                int(reddit_report["data_volume"]["collected_posts"]), ai_reddit_post_limit
            ),
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


def build_article_search_queries(
    category: str, limit: int = 12, include_industry_reports: bool = True
) -> list[str]:
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
        raise ValueError(
            f"{provider.label} API key is not configured. Add it in Settings > Web Search."
        )
    credentials = {"api_key": api_key}
    if provider.requires_search_engine_id and provider.search_engine_id_env:
        search_engine_id = values.get(provider.search_engine_id_env, "")
        if not configured_secret(search_engine_id):
            raise ValueError(
                f"{provider.label} search engine id is not configured. Add it in Settings > Web Search."
            )
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
        if all(
            isinstance(item, dict) and (item.get("url") or item.get("link") or item.get("href"))
            for item in payload
        ):
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
    call_expr = (
        f'exa.web_search_exa(query: "{escaped_query}", numResults: {max(1, min(count, 20))})'
    )
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
            "snippet": item.get("snippet")
            or item.get("description")
            or item.get("text")
            or item.get("content")
            or "",
            "published": item.get("publishedDate")
            or item.get("published_date")
            or item.get("date")
            or "",
            "image_url": item.get("imageUrl")
            or item.get("image_url")
            or item.get("image")
            or item.get("thumbnail")
            or "",
        }
        for item in raw_results
        if isinstance(item, dict)
    ]


def web_search_time_options(
    time_range: str,
    *,
    now: dt.datetime | None = None,
) -> dict[str, str]:
    """Translate the canonical agent time window into provider-neutral date hints."""
    normalized = normalize_agent_time_range(time_range)
    if not normalized or normalized == "all":
        return {}
    reference = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    cutoff = time_range_cutoff(normalized, reference)
    if cutoff is None:
        return {}
    days = max(1, (reference.date() - cutoff.date()).days)
    native_range = reddit_provider_time_range(normalized)
    return {
        "time_range": normalized,
        "native_range": native_range if native_range != "all" else "",
        "start_date": cutoff.date().isoformat(),
        "end_date": reference.date().isoformat(),
        "days": str(days),
    }


def agent_reach_time_preference(query: str, options: dict[str, str]) -> str:
    """Give Exa a readable ideal-page description instead of recency keyword spam."""
    if not options:
        return query
    start_date = options.get("start_date", "")
    end_date = options.get("end_date", "")
    if not start_date or not end_date:
        return query
    return clean_text(
        f"{query}. Prefer an editorial page published from {start_date} through {end_date}; "
        "when that window has no strong match, prefer a page about the current or upcoming "
        "fashion season rather than a company, course, or software product page."
    )


def rank_web_search_results_by_time(
    results: list[dict[str, Any]], time_range: str
) -> list[dict[str, Any]]:
    """Post-rank dated results while retaining undated/seasonal fallback candidates."""
    normalized = normalize_agent_time_range(time_range)
    if not normalized:
        return results
    indexed = list(enumerate(results))
    recency_rank = {"recent": 0, "undated": 1, "background": 2}
    indexed.sort(
        key=lambda pair: (
            recency_rank.get(
                trend_recency_status(pair[1].get("published"), normalized),
                1,
            ),
            pair[0],
        )
    )
    return [item for _index, item in indexed]


def web_search_query(
    query: str,
    count: int,
    bypass_cache: bool = False,
    *,
    time_range: str = "",
    agent_reach_query: str = "",
    search_lang: str = "",
    country: str = "",
) -> tuple[str, list[dict[str, Any]], list[str]]:
    provider, credentials = search_provider_credentials()
    date_options = web_search_time_options(time_range)
    effective_query = (
        agent_reach_time_preference(agent_reach_query or query, date_options)
        if provider == "agent_reach"
        else query
    )
    cache_path = cache_key(
        [
            CACHE_VERSION,
            "web-search",
            provider,
            effective_query,
            str(count),
            json.dumps(date_options, sort_keys=True),
            search_lang,
            country,
        ]
    )
    if not bypass_cache:
        cached = read_cache(cache_path, ANALYSIS_CACHE_TTL_SECONDS)
        if isinstance(cached, dict) and isinstance(cached.get("results"), list):
            return provider, cached["results"], []

    warnings: list[str] = []
    if provider == "agent_reach":
        results = search_agent_reach_exa(effective_query, count)
    elif provider == "brave":
        brave_params: dict[str, Any] = {
            "q": query,
            "count": max(1, min(count, 10)),
            "country": country or "us",
            "search_lang": search_lang or "en",
            "spellcheck": 1,
        }
        if date_options.get("start_date") and date_options.get("end_date"):
            brave_params["freshness"] = f"{date_options['start_date']}to{date_options['end_date']}"
        params = urllib.parse.urlencode(brave_params)
        body = http_get(
            f"https://api.search.brave.com/res/v1/web/search?{params}",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": credentials["api_key"],
            },
            timeout=25,
        )
        payload = json.loads(body.decode("utf-8"))
        raw_results = (
            ((payload.get("web") or {}).get("results") or []) if isinstance(payload, dict) else []
        )
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
        tavily_payload: dict[str, Any] = {
            "api_key": credentials["api_key"],
            "query": query,
            "search_depth": "basic",
            "max_results": max(1, min(count, 10)),
            "include_answer": False,
            "include_raw_content": False,
        }
        native_range = date_options.get("native_range")
        if native_range in {"day", "week", "month", "year"}:
            tavily_payload["time_range"] = native_range
        if date_options.get("start_date") and date_options.get("end_date"):
            tavily_payload["start_date"] = date_options["start_date"]
            tavily_payload["end_date"] = date_options["end_date"]
        body = http_post_json(
            "https://api.tavily.com/search",
            tavily_payload,
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
        google_params: dict[str, Any] = {
            "key": credentials["api_key"],
            "cx": credentials["search_engine_id"],
            "q": query,
            "num": max(1, min(count, 10)),
        }
        if country:
            google_params["gl"] = country
        if search_lang:
            google_params["lr"] = "lang_zh-CN" if search_lang.startswith("zh") else "lang_en"
        if date_options.get("days"):
            google_params["dateRestrict"] = f"d{date_options['days']}"
        params = urllib.parse.urlencode(google_params)
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

    results = rank_web_search_results_by_time(results, time_range)
    write_cache(cache_path, {"results": results})
    if not results:
        warnings.append(f"No search results returned for query: {query}")
    return provider, results, warnings


def score_article_search_candidate(
    category: str, title: str, snippet: str, domain: str, url: str
) -> tuple[int, str, list[str]]:
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

    queries = build_article_search_queries(
        category, query_limit, include_industry_reports=include_industry_reports
    )
    candidates_by_url: dict[str, dict[str, Any]] = {}
    per_query_counts: list[dict[str, Any]] = []
    warnings: list[str] = []
    raw_results = 0
    provider_name = selected_web_search_provider(read_settings_values()).name

    for query in queries:
        try:
            provider_name, results, query_warnings = web_search_query(
                query, results_per_query, bypass_cache=bypass_cache
            )
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
            score, source_type, reasons = score_article_search_candidate(
                category, title, snippet, domain, url
            )
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
        key=lambda item: (
            int(item.get("score") or 0),
            -int(item.get("rank") or 99),
            item.get("domain") in ARTICLE_REVIEW_DOMAINS,
        ),
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
    body = http_get(reader_url, headers={"Accept": "text/plain"}, timeout=35).decode(
        "utf-8", errors="replace"
    )
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


TREND_PLATFORM_TARGETS: tuple[dict[str, Any], ...] = (
    {
        "platform_id": "wgsn",
        "name": "WGSN",
        "domains": {"wgsn.com", "wgsnchina.cn"},
        "seed_url": "https://www.wgsn.com/en/products/fashion-design",
    },
    {
        "platform_id": "diexun",
        "name": "蝶讯 / DICTION DNEXT",
        "domains": {"diexun.com", "diction-style.com"},
        "seed_url": "https://www.diction-style.com/",
    },
    {
        "platform_id": "pinterest",
        "name": "Pinterest",
        "domains": {"pinterest.com"},
        "seed_url": "https://www.pinterest.com/search/pins/",
    },
)

TREND_QUERY_DIMENSIONS: tuple[dict[str, str], ...] = (
    {
        "dimension": "overview",
        "en": "fashion trend forecast consumer direction",
        "zh": "流行趋势 趋势预测 消费方向",
    },
    {
        "dimension": "colour",
        "en": "colour color palette forecast",
        "zh": "色彩 颜色 流行色 配色",
    },
    {
        "dimension": "materials",
        "en": "fabric material textile texture innovation",
        "zh": "面料 材质 纱线 肌理 工艺",
    },
    {
        "dimension": "silhouette",
        "en": "silhouette shape structure construction fit",
        "zh": "廓形 版型 结构 轮廓",
    },
    {
        "dimension": "details",
        "en": "style detail trim print pattern design",
        "zh": "风格 细节 辅料 图案 印花 款式",
    },
    {
        "dimension": "visual",
        "en": "visual inspiration moodboard editorial lookbook",
        "zh": "视觉灵感 情绪板 款式图 设计图",
    },
)

TREND_MAX_IMAGES_PER_PAGE = 12
TREND_MAX_IMAGES_PER_PLATFORM = 48
TREND_MAX_REPORT_IMAGES = 36

TREND_INTIMATES_TERMS = {
    "intimate",
    "intimates",
    "lingerie",
    "bra",
    "bras",
    "brassiere",
    "underwear",
    "undergarment",
    "内衣",
    "女士内衣",
    "文胸",
    "胸罩",
    "贴身衣物",
}

TREND_IMAGE_EXCLUDE_TERMS = (
    "logo",
    "icon",
    "avatar",
    "sprite",
    "badge",
    "placeholder",
    "tracking",
    "pixel",
    "favicon",
    "emoji",
    "default_open_graph",
    "dictionfun",
    "site-logo",
    "brand-logo",
    "spinner",
    "course",
    "company-profile",
    "company_profile",
    "about_us",
    "profile-banner",
)

TREND_NON_IMAGE_EXTENSIONS = (
    ".mp4",
    ".webm",
    ".mov",
    ".m4v",
    ".avi",
    ".m3u8",
    ".pdf",
    ".zip",
)

TREND_SIGNAL_TERMS = (
    "colour",
    "color",
    "palette",
    "fabric",
    "material",
    "textile",
    "texture",
    "silhouette",
    "style",
    "trend",
    "print",
    "pattern",
    "detail",
    "色彩",
    "颜色",
    "面料",
    "材质",
    "纹理",
    "廓形",
    "风格",
    "趋势",
    "图案",
    "工艺",
    "细节",
    "款式",
)

TREND_CONCEPT_PATTERNS = (
    re.compile(
        r"\b(?:(?:electric|luminous|digital|cobalt|sky|powder|ice|navy|midnight|ocean|"
        r"cornflower|butter|lemon|sunshine|cherry|scarlet|burgundy|wine|blush|dusty|hot|"
        r"bubblegum|lavender|lilac|plum|emerald|sage|mint|olive|chocolate|mocha|caramel|"
        r"sand|ivory|cream|silver|gold|metallic)\s+)?"
        r"(?:blue|red|pink|purple|green|yellow|brown|orange|neutral|white|black)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:sheer|stretch|recycled|floral|geometric|embroidered|technical|"
        r"lightweight|soft|glossy|matte|delicate)\s+)?"
        r"(?:lace|mesh|satin|silk|cotton|jersey|knit|tulle|organza|velvet|leather|"
        r"microfibre|microfiber)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:soft romance|opulent romance|quiet luxury|modern femininity|dark romance|"
        r"sporty minimalism|sculptural minimalism|retro futurism|vintage glamour|"
        r"ethereal femininity|utility chic|bohemian romance|futuristic sensuality)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"[\u4e00-\u9fff]{0,4}(?:蕾丝|网纱|缎面|真丝|刺绣|针织|薄纱|欧根纱|天鹅绒|"
        r"镂空|流苏|褶皱|荷叶边|蝴蝶结|金属感|透明感|光泽感|浪漫主义|极简主义|"
        r"复古未来|静奢风|芭蕾风)",
    ),
)

TREND_CONCEPT_STOP_WORDS = {
    "black",
    "white",
    "neutral",
    "trend",
    "fashion trend",
    "colour",
    "color",
    "fabric",
    "material",
    "style",
    "key colours",
    "key colors",
    "global colour forecast",
    "global color forecast",
    "面料",
    "色彩",
    "趋势",
    "款式",
}


class PublicTrendPageParser(HTMLParser):
    capture_tags = {"title", "h1", "h2", "h3", "p", "li", "figcaption"}
    ignored_tags = {"style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.capture_depth = 0
        self.ignored_depth = 0
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []
        self.description = ""
        self.image_url = ""
        self.image_candidates: list[dict[str, Any]] = []
        self.published_candidates: list[str] = []
        self.updated_candidates: list[str] = []
        self.time_depth = 0
        self.time_parts: list[str] = []
        self.json_ld_depth = 0
        self.json_ld_parts: list[str] = []
        self.json_ld_documents: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        attr_map = {str(key).lower(): str(value or "") for key, value in attrs}
        if normalized == "script":
            script_type = attr_map.get("type", "").lower()
            if "ld+json" in script_type:
                self.json_ld_depth += 1
                self.json_ld_parts = []
            else:
                self.ignored_depth += 1
            return
        if normalized in self.ignored_tags:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if normalized == "meta":
            meta_key = (attr_map.get("property") or attr_map.get("name") or "").lower()
            content = clean_text(attr_map.get("content"))
            if meta_key in {"description", "og:description", "twitter:description"} and content:
                if not self.description or meta_key == "og:description":
                    self.description = content
            if meta_key in {"og:image", "twitter:image"} and content and not self.image_url:
                self.image_url = content
            if meta_key in {"og:image", "twitter:image", "twitter:image:src"} and content:
                self.image_candidates.append({"url": content, "alt": "", "source": meta_key})
            if (
                meta_key
                in {
                    "article:published_time",
                    "datepublished",
                    "publishdate",
                    "published_time",
                    "date",
                }
                and content
            ):
                self.published_candidates.append(content)
            if (
                meta_key
                in {
                    "article:modified_time",
                    "og:updated_time",
                    "datemodified",
                    "last-modified",
                }
                and content
            ):
                self.updated_candidates.append(content)
        if normalized == "link":
            rel = attr_map.get("rel", "").lower()
            href = attr_map.get("href", "")
            if "image_src" in rel and href:
                self.image_candidates.append({"url": href, "alt": "", "source": "link:image_src"})
        if normalized in {"img", "source"}:
            raw_url = (
                attr_map.get("src")
                or attr_map.get("data-src")
                or attr_map.get("data-lazy-src")
                or attr_map.get("data-original")
                or ""
            )
            srcset = attr_map.get("srcset") or attr_map.get("data-srcset") or ""
            if srcset:
                srcset_urls = [
                    part.strip().split(" ", 1)[0] for part in srcset.split(",") if part.strip()
                ]
                if srcset_urls:
                    raw_url = srcset_urls[-1]
            if raw_url:
                self.image_candidates.append(
                    {
                        "url": raw_url,
                        "alt": clean_text(attr_map.get("alt") or attr_map.get("title") or ""),
                        "source": normalized,
                        "width": attr_map.get("width") or "",
                        "height": attr_map.get("height") or "",
                    }
                )
        if normalized == "time":
            self.time_depth += 1
            datetime_value = attr_map.get("datetime") or attr_map.get("content") or ""
            if datetime_value:
                self.published_candidates.append(datetime_value)
        if normalized in self.capture_tags:
            self.capture_depth += 1
        if normalized == "title":
            self.title_depth += 1

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized == "script":
            if self.json_ld_depth:
                self.json_ld_depth -= 1
                document = "".join(self.json_ld_parts).strip()
                if document:
                    self.json_ld_documents.append(document)
                self.json_ld_parts = []
            elif self.ignored_depth:
                self.ignored_depth -= 1
            return
        if normalized in self.ignored_tags and self.ignored_depth:
            self.ignored_depth -= 1
            return
        if self.ignored_depth:
            return
        if normalized in self.capture_tags and self.capture_depth:
            self.capture_depth -= 1
        if normalized == "title" and self.title_depth:
            self.title_depth -= 1
        if normalized == "time" and self.time_depth:
            self.time_depth -= 1
            time_text = clean_text(" ".join(self.time_parts))
            if time_text:
                self.published_candidates.append(time_text)
            self.time_parts = []

    def handle_data(self, data: str) -> None:
        if self.json_ld_depth:
            self.json_ld_parts.append(data)
            return
        if self.ignored_depth:
            return
        cleaned = clean_text(data)
        if not cleaned:
            return
        if self.title_depth:
            self.title_parts.append(cleaned)
        if self.capture_depth:
            self.body_parts.append(cleaned)
        if self.time_depth:
            self.time_parts.append(cleaned)


def parse_trend_datetime(value: Any) -> dt.datetime | None:
    parsed = parse_date(value)
    if parsed:
        return parsed
    text = clean_text(str(value or ""))
    if not text:
        return None
    try:
        parsed_email = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        parsed_email = None
    if parsed_email:
        return parsed_email.replace(tzinfo=parsed_email.tzinfo or dt.UTC).astimezone(dt.UTC)

    normalized = text.replace("年", "-").replace("月", "-").replace("日", "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    for date_format in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
    ):
        try:
            return dt.datetime.strptime(normalized, date_format).replace(tzinfo=dt.UTC)
        except ValueError:
            continue
    match = re.search(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", normalized)
    if match:
        try:
            return dt.datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=dt.UTC
            )
        except ValueError:
            return None
    return None


def trend_datetime_iso(value: Any) -> str:
    parsed = parse_trend_datetime(value)
    return parsed.isoformat() if parsed else ""


def trend_recency_status(
    published: Any,
    time_range: str,
    *,
    now: dt.datetime | None = None,
) -> str:
    parsed = parse_trend_datetime(published)
    if not parsed:
        return "undated"
    reference = now or dt.datetime.now(dt.UTC)
    if parsed > reference + dt.timedelta(days=2):
        return "undated"
    cutoff = time_range_cutoff(time_range, reference)
    if cutoff is None:
        return "recent"
    return "recent" if parsed >= cutoff else "background"


def trend_json_ld_values(documents: list[str]) -> dict[str, list[Any]]:
    collected: dict[str, list[Any]] = defaultdict(list)

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for child in value:
                visit(child)
            return
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in {"datepublished", "uploaddate"}:
                collected["published"].append(child)
            elif normalized in {"datemodified", "dateupdated"}:
                collected["updated"].append(child)
            elif normalized in {"image", "thumbnailurl", "contenturl"}:
                collected["images"].append(child)
            visit(child)

    for document in documents:
        try:
            visit(json.loads(document))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return collected


def trend_json_ld_image_candidates(values: list[Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, str):
            candidates.append({"url": value, "alt": "", "source": "json_ld"})
        elif isinstance(value, list):
            candidates.extend(trend_json_ld_image_candidates(value))
        elif isinstance(value, dict):
            raw_url = value.get("url") or value.get("contentUrl") or value.get("thumbnailUrl")
            if raw_url:
                candidates.append(
                    {
                        "url": raw_url,
                        "alt": clean_text(str(value.get("caption") or value.get("name") or "")),
                        "source": "json_ld",
                        "width": value.get("width") or "",
                        "height": value.get("height") or "",
                    }
                )
    return candidates


def trend_markdown_image_candidates(markdown: str) -> list[dict[str, Any]]:
    return [
        {"url": match.group(2).strip(), "alt": clean_text(match.group(1)), "source": "markdown"}
        for match in re.finditer(r"!\[([^\]]*)]\((https?://[^\s)]+)(?:\s+[^)]*)?\)", markdown)
    ]


def safe_trend_image_url(raw_url: Any, page_url: str) -> str:
    value = str(raw_url or "").strip()
    if not value or any(ord(character) < 32 for character in value):
        return ""
    absolute = urllib.parse.urljoin(page_url, value)
    parsed = urllib.parse.urlsplit(absolute)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return ""
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        return ""
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", hostname):
        octets = [int(part) for part in hostname.split(".")]
        if (
            octets[0] in {10, 127}
            or (octets[0] == 169 and octets[1] == 254)
            or (octets[0] == 172 and 16 <= octets[1] <= 31)
            or (octets[0] == 192 and octets[1] == 168)
        ):
            return ""
    page_host = article_domain(page_url)
    allowed_suffixes = {
        "wgsn.com",
        "wgsnchina.cn",
        "diexun.com",
        "diction-style.com",
        "pinterest.com",
        "pinimg.com",
    }
    same_page_domain = bool(page_host) and domain_matches(hostname, {page_host})
    if not same_page_domain and not domain_matches(hostname, allowed_suffixes):
        return ""
    lowered_path = urllib.parse.unquote(parsed.path).lower()
    if lowered_path.endswith((".svg", *TREND_NON_IMAGE_EXTENSIONS)) or any(
        term in lowered_path for term in TREND_IMAGE_EXCLUDE_TERMS
    ):
        return ""
    return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))


def trend_image_canonical_key(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    path = re.sub(r"/(?:\d+x|originals)/", "/_size_/", parsed.path, flags=re.IGNORECASE)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    stable_query = [
        (key, value)
        for key, value in query
        if key.lower() not in {"width", "height", "w", "h", "format"}
    ]
    return urllib.parse.urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            urllib.parse.urlencode(stable_query),
            "",
        )
    )


def normalize_trend_images(
    page_url: str,
    candidates: list[dict[str, Any]],
    *,
    limit: int = TREND_MAX_IMAGES_PER_PAGE,
) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        image_url = safe_trend_image_url(candidate.get("url"), page_url)
        if not image_url:
            continue
        width = candidate.get("width")
        height = candidate.get("height")
        try:
            if width and height and (int(width) < 64 or int(height) < 64):
                continue
        except (TypeError, ValueError):
            pass
        canonical_key = trend_image_canonical_key(image_url)
        if canonical_key in seen:
            continue
        seen.add(canonical_key)
        images.append(
            {
                "image_url": image_url,
                "canonical_key": canonical_key,
                "alt_text": compact_text(clean_text(str(candidate.get("alt") or "")), 240),
                "origin": str(candidate.get("source") or "page"),
                "width": width or "",
                "height": height or "",
                "source_page_url": page_url,
                "rights_note": "Public-page visual preview; retain the source link and do not remove watermarks.",
            }
        )
        if len(images) >= limit:
            break
    return images


def trend_category_terms(category: str) -> set[str]:
    lowered = category.lower()
    terms = {
        term.lower()
        for term in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", category)
        if len(term) >= 2
    }
    explicit_intimates_phrases = {
        "women's intimates",
        "womens intimates",
        "intimate apparel",
        "lingerie",
        "underwear",
        "女士内衣",
        "文胸",
        "胸罩",
        "贴身衣物",
    }
    if terms & TREND_INTIMATES_TERMS or any(
        phrase in lowered for phrase in explicit_intimates_phrases
    ):
        terms.update(TREND_INTIMATES_TERMS)
    return terms


def trend_category_query_text(category: str, platform_id: str) -> str:
    terms = trend_category_terms(category)
    if terms & TREND_INTIMATES_TERMS:
        if platform_id == "diexun":
            return "女士内衣"
        return "lingerie"
    return category


def trend_text_has_term(text: str, term: str) -> bool:
    normalized_text = text.lower()
    normalized_term = term.lower().strip()
    if not normalized_term:
        return False
    if re.search(r"[^\x00-\x7f]", normalized_term):
        return normalized_term in normalized_text
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])",
            normalized_text,
        )
    )


def trend_dimension_matches(text: str) -> list[str]:
    matches: list[str] = []
    for item in TREND_QUERY_DIMENSIONS:
        terms = f"{item['en']} {item['zh']}".lower().split()
        if any(trend_text_has_term(text, term) for term in terms):
            matches.append(item["dimension"])
    return list(dict.fromkeys(matches))


def trend_relevance_status(text: str, category: str) -> tuple[str, int]:
    category_matches = sum(
        1 for term in trend_category_terms(category) if trend_text_has_term(text, term)
    )
    dimension_matches = len(trend_dimension_matches(text))
    if category_matches:
        return "category_specific", min(100, 60 + category_matches * 8 + dimension_matches * 3)
    if dimension_matches:
        return "adjacent", min(59, 25 + dimension_matches * 5)
    return "generic", 5


def infer_trend_published(candidates: list[Any], text: str = "") -> str:
    for candidate in candidates:
        normalized = trend_datetime_iso(candidate)
        if normalized:
            return normalized
    date_patterns = (
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}\b",
        r"\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b",
        r"20\d{2}年\d{1,2}月\d{1,2}日",
    )
    for pattern in date_patterns:
        match = re.search(pattern, text[:3000], flags=re.IGNORECASE)
        if match:
            normalized = trend_datetime_iso(match.group(0))
            if normalized:
                return normalized
    return ""


def trend_evidence_snippets(text: str, category: str, limit: int = 8) -> list[str]:
    category_terms = [
        term.lower()
        for term in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", category)
        if len(term) >= 2
    ]
    sentences = re.split(r"(?<=[.!?。！？])|[\r\n]+", text)
    snippets: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        cleaned = compact_text(clean_text(sentence), 320)
        if len(cleaned) < 25:
            continue
        lowered = cleaned.lower()
        has_trend_signal = any(term in lowered for term in TREND_SIGNAL_TERMS)
        has_category_signal = any(term in lowered for term in category_terms)
        if not has_trend_signal and not has_category_signal:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        snippets.append(cleaned)
        if len(snippets) >= limit:
            break
    if not snippets and text:
        snippets.append(compact_text(text, 320))
    return snippets


def fetch_public_trend_page(
    url: str,
    category: str,
    *,
    bypass_cache: bool = False,
    timeout: int = 10,
) -> dict[str, Any]:
    cache_path = cache_key([CACHE_VERSION, "public-trend-page-v2", category, url])
    if not bypass_cache:
        cached = read_cache(cache_path, ANALYSIS_CACHE_TTL_SECONDS)
        if isinstance(cached, dict) and cached.get("url"):
            return cached

    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36"
        ),
    }
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=max(5, min(timeout, 30))) as response:
        raw = response.read(1_500_001)
        final_url = response.geturl()
        content_type = str(response.headers.get("Content-Type") or "")
        charset = response.headers.get_content_charset() or "utf-8"
        status_code = int(getattr(response, "status", 200) or 200)
    truncated = len(raw) > 1_500_000
    markup = raw[:1_500_000].decode(charset, errors="replace")
    parser = PublicTrendPageParser()
    parser.feed(markup)
    json_ld = trend_json_ld_values(parser.json_ld_documents)
    title = compact_text(clean_text(" ".join(parser.title_parts)), 180) or article_domain(final_url)
    description = compact_text(parser.description, 500)
    text = clean_text(" ".join([description, *parser.body_parts]))
    if len(text) < 40:
        raise ValueError("Public page returned too little readable text")
    published = infer_trend_published(
        [*parser.published_candidates, *(json_ld.get("published") or [])],
        text,
    )
    updated = infer_trend_published(
        [*parser.updated_candidates, *(json_ld.get("updated") or [])],
    )
    images = normalize_trend_images(
        final_url,
        [
            *parser.image_candidates,
            *trend_json_ld_image_candidates(json_ld.get("images") or []),
        ],
    )
    image_url = images[0]["image_url"] if images else ""
    lowered = text.lower()
    access_notes: list[str] = []
    if any(
        term in lowered
        for term in ("sign in", "log in", "subscribe", "membership", "登录", "会员", "订阅")
    ):
        access_notes.append(
            "Page may expose only a public preview or login prompt; do not infer gated report content."
        )
    if truncated:
        access_notes.append(
            "Response exceeded the public-page size cap and was truncated before parsing."
        )
    page = {
        "title": title,
        "url": url,
        "final_url": final_url,
        "domain": article_domain(final_url),
        "status_code": status_code,
        "content_type": content_type,
        "access_mode": "direct_http",
        "description": description,
        "image_url": image_url,
        "image_urls": [item["image_url"] for item in images],
        "images": images,
        "published": published,
        "updated": updated,
        "readable_chars": len(text),
        "evidence_snippets": trend_evidence_snippets(text, category),
        "access_notes": access_notes,
        "fetched_at": now_iso(),
    }
    write_cache(cache_path, page)
    return page


def fetch_public_trend_page_with_fallback(
    url: str,
    category: str,
    *,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    direct_error = ""
    try:
        return fetch_public_trend_page(url, category, bypass_cache=bypass_cache)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        direct_error = str(exc)

    reader_url = f"https://r.jina.ai/{url}"
    try:
        markdown = http_get(reader_url, headers={"Accept": "text/plain"}, timeout=10).decode(
            "utf-8",
            errors="replace",
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise ValueError(f"direct HTTP failed: {direct_error}; Jina Reader failed: {exc}") from exc
    text = article_markdown_to_text(markdown)
    if len(text) < 40:
        raise ValueError(
            f"direct HTTP failed: {direct_error}; Jina Reader returned too little readable text"
        )
    images = normalize_trend_images(url, trend_markdown_image_candidates(markdown))
    return {
        "title": article_title_from_markdown(markdown, url),
        "url": url,
        "final_url": url,
        "domain": article_domain(url),
        "status_code": 200,
        "content_type": "text/markdown",
        "access_mode": "jina_reader",
        "description": "",
        "image_url": images[0]["image_url"] if images else "",
        "image_urls": [item["image_url"] for item in images],
        "images": images,
        "published": infer_trend_published([], text),
        "updated": "",
        "readable_chars": len(text),
        "evidence_snippets": trend_evidence_snippets(text, category),
        "access_notes": [f"Direct HTTP failed before the Jina Reader fallback: {direct_error}"],
        "fetched_at": now_iso(),
    }


def trend_query_days(payload: dict[str, Any]) -> tuple[str, int]:
    time_range = normalize_agent_time_range(payload.get("timeRange")) or "30d"
    days_match = re.fullmatch(r"(\d{1,5})d", time_range)
    if days_match:
        return time_range, int(days_match.group(1))
    return time_range, {"day": 1, "week": 7, "month": 30, "year": 365}.get(time_range, 30)


def _trend_year(value: str) -> int | None:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    if year < 100:
        year += 2000
    return year if 2020 <= year <= 2099 else None


def default_trend_target_seasons(*, now: dt.datetime | None = None) -> list[str]:
    reference = now or dt.datetime.now(dt.UTC)
    year = reference.year
    if reference.month <= 3:
        return [f"S/S {year % 100:02d}", f"A/W {year % 100:02d}/{(year + 1) % 100:02d}"]
    if reference.month <= 8:
        return [f"A/W {year % 100:02d}/{(year + 1) % 100:02d}", f"S/S {(year + 1) % 100:02d}"]
    return [
        f"S/S {(year + 1) % 100:02d}",
        f"A/W {(year + 1) % 100:02d}/{(year + 2) % 100:02d}",
    ]


def infer_trend_target_seasons(
    payload: dict[str, Any], *, now: dt.datetime | None = None
) -> list[str]:
    """Infer normalized fashion seasons from canonical inputs and free-form context."""
    source = clean_text(
        " ".join(
            str(payload.get(key) or "")
            for key in (
                "targetSeason",
                "target_season",
                "trendContext",
                "trend_context",
                "designGoal",
                "design_goal",
                "prompt",
                "category",
            )
        )
    )
    seasons: list[str] = []

    season_token = (
        r"(?P<season>s\s*[/.-]?\s*s|spring\s*[/&-]?\s*summer|春夏|"
        r"a\s*[/.-]?\s*w|autumn\s*[/&-]?\s*winter|fall\s*[/&-]?\s*winter|秋冬)"
    )
    year_token = r"(?P<year>20\d{2}|\d{2})(?:\s*[/.-]\s*(?P<next>20\d{2}|\d{2}))?"
    patterns = (
        re.compile(rf"{season_token}\s*['’]?\s*{year_token}", re.IGNORECASE),
        re.compile(rf"{year_token}\s*{season_token}", re.IGNORECASE),
    )
    for pattern in patterns:
        for match in pattern.finditer(source):
            year = _trend_year(match.group("year"))
            if not year:
                continue
            season = re.sub(r"\s+", "", match.group("season").lower())
            is_spring = season in {"ss", "s/s", "s.s", "s-s", "春夏"} or "spring" in season
            if is_spring:
                seasons.append(f"S/S {year % 100:02d}")
                continue
            next_year = _trend_year(match.group("next") or "") or year + 1
            seasons.append(f"A/W {year % 100:02d}/{next_year % 100:02d}")

    if not seasons:
        reference = now or dt.datetime.now(dt.UTC)
        lower_source = source.lower()
        defaults = default_trend_target_seasons(now=reference)
        if any(token in lower_source for token in ("spring", "summer", "春夏", "s/s", "ss")):
            seasons.append(next(item for item in defaults if item.startswith("S/S")))
        elif any(
            token in lower_source for token in ("autumn", "fall", "winter", "秋冬", "a/w", "aw")
        ):
            seasons.append(next(item for item in defaults if item.startswith("A/W")))
        else:
            years = [_trend_year(value) for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", source)]
            explicit_year = next((year for year in years if year), None)
            if explicit_year:
                seasons.extend(
                    [
                        f"S/S {explicit_year % 100:02d}",
                        f"A/W {explicit_year % 100:02d}/{(explicit_year + 1) % 100:02d}",
                    ]
                )
            else:
                seasons.extend(defaults)
    return list(dict.fromkeys(seasons))[:3]


def trend_season_query_text(season: str, platform_id: str) -> str:
    if platform_id != "diexun":
        return season
    spring = re.fullmatch(r"S/S\s+(\d{2})", season, flags=re.IGNORECASE)
    if spring:
        return f"20{spring.group(1)}春夏"
    autumn = re.fullmatch(r"A/W\s+(\d{2})/(\d{2})", season, flags=re.IGNORECASE)
    if autumn:
        return f"20{autumn.group(1)}/{autumn.group(2)}秋冬"
    return season


def trend_season_variants(season: str) -> list[str]:
    variants = [season]
    spring = re.fullmatch(r"S/S\s+(\d{2})", season, flags=re.IGNORECASE)
    if spring:
        year = spring.group(1)
        variants.extend([f"SS{year}", f"SS {year}", f"20{year} spring summer", f"20{year}春夏"])
    autumn = re.fullmatch(r"A/W\s+(\d{2})/(\d{2})", season, flags=re.IGNORECASE)
    if autumn:
        first, second = autumn.groups()
        variants.extend(
            [
                f"AW{first}/{second}",
                f"AW {first}/{second}",
                f"20{first}/20{second} autumn winter",
                f"20{first}/{second}秋冬",
            ]
        )
    return variants


def trend_season_match_score(text: str, seasons: list[str]) -> int:
    lowered = clean_text(text).lower()
    score = 0
    for season in seasons:
        if any(variant.lower() in lowered for variant in trend_season_variants(season)):
            score += 1
    return score


def extract_trend_concepts(
    platforms: list[dict[str, Any]],
    payload: dict[str, Any],
    *,
    limit: int = 10,
) -> list[str]:
    """Extract concrete visual vocabulary for second-stage Pinterest expansion."""
    weighted_texts: list[tuple[str, int]] = []
    context = clean_text(
        " ".join(
            str(payload.get(key) or "")
            for key in ("trendContext", "trend_context", "designGoal", "design_goal")
        )
    )
    if context:
        weighted_texts.append((context, 3))
    for platform in platforms:
        for result in platform.get("search_results") or []:
            weighted_texts.append((str(result.get("title") or ""), 3))
            weighted_texts.append((str(result.get("snippet") or ""), 1))
        for page in platform.get("pages") or []:
            weighted_texts.append((str(page.get("title") or ""), 4))
            weighted_texts.append((str(page.get("description") or ""), 2))
            for snippet in page.get("evidence_snippets") or []:
                weighted_texts.append((str(snippet), 1))

    scores: Counter[str] = Counter()
    display: dict[str, str] = {}
    first_seen: dict[str, int] = {}
    order = 0

    def add_concept(value: str, weight: int) -> None:
        nonlocal order
        concept = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", clean_text(value))
        concept = re.sub(
            r"(?i)\s+(?:highlight|confirmed|forecast|prediction|predictions)$",
            "",
            concept,
        ).strip(" ,.;:：、-|/()[]")
        key = concept.casefold()
        if not concept or key in TREND_CONCEPT_STOP_WORDS or len(concept) < 3:
            return
        scores[key] += weight
        display.setdefault(key, concept)
        first_seen.setdefault(key, order)
        order += 1

    for text, weight in weighted_texts:
        cleaned = clean_text(text)
        if not cleaned:
            continue
        for pattern in TREND_CONCEPT_PATTERNS:
            for match in pattern.finditer(cleaned):
                add_concept(match.group(0), weight)
        for match in re.finditer(r"#([A-Za-z][A-Za-z0-9]{2,})", cleaned):
            hashtag = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", match.group(1))
            add_concept(hashtag, weight + 2)
        heading_patterns = (
            r"#{1,4}\s*([A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+){0,3})",
            r"(?i)(?:key|confirmed|highlight)\s+(?:colour|color|style|theme|material|"
            r"fabric|print|detail|silhouette)\s*(?:--|[-:–—])\s*"
            r"([A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+){0,3})",
        )
        for pattern in heading_patterns:
            for match in re.finditer(pattern, cleaned):
                add_concept(match.group(1), weight + 1)

        # Editorial headlines often carry the useful visual phrase (for example
        # "Underwater Romance") without a colour/material keyword. Preserve short
        # title fragments after stripping platform, season, category and report boilerplate.
        if weight < 3:
            continue
        for raw_fragment in re.split(r"[|｜:：—–•·]", cleaned):
            fragment = re.sub(
                r"(?i)\b(?:wgsn|dnext|diction|diexun|fashion|trend|trends|forecast|"
                r"report|analysis|direction|directions|editorial|collection|latest|"
                r"spring|summer|autumn|fall|winter|ss|aw)\b",
                " ",
                raw_fragment,
            )
            fragment = re.sub(r"\b20\d{2}(?:\s*[/.-]\s*\d{2,4})?\b", " ", fragment)
            fragment = re.sub(
                r"(?:流行趋势|趋势预测|趋势报告|主题企划|春夏|秋冬|蝶讯|女士内衣|内衣)",
                " ",
                fragment,
            )
            fragment = clean_text(re.sub(r"[()\[\]{}]", " ", fragment))
            ascii_words = re.findall(r"[A-Za-z][A-Za-z'-]*", fragment)
            chinese_chars = re.findall(r"[\u4e00-\u9fff]", fragment)
            if ascii_words and 2 <= len(ascii_words) <= 5:
                if not all(
                    word.casefold() in {"the", "for", "and", "of", "key", "new", "women"}
                    for word in ascii_words
                ):
                    add_concept(" ".join(ascii_words), max(1, weight - 1))
            elif chinese_chars and 2 <= len(chinese_chars) <= 12:
                add_concept("".join(chinese_chars), max(1, weight - 1))
    ranked = sorted(scores, key=lambda key: (-scores[key], first_seen[key], key))
    return [display[key] for key in ranked[: max(1, min(limit, 12))]]


def trend_query_spec(
    platform_id: str,
    query_id: str,
    dimension: str,
    query: str,
    agent_reach_query: str,
    *,
    target_season: str = "",
) -> dict[str, str]:
    return {
        "query_id": f"{platform_id}_{query_id}",
        "dimension": dimension,
        "query": clean_text(query),
        "agent_reach_query": clean_text(agent_reach_query),
        "target_season": target_season,
        "search_lang": "zh-hans" if platform_id == "diexun" else "en",
        "country": "cn" if platform_id == "diexun" else "us",
    }


def trend_platform_search_queries(
    target: dict[str, Any], payload: dict[str, Any]
) -> list[dict[str, str]]:
    category = clean_text(str(payload.get("category") or "fashion"))
    marketplace = clean_text(str(payload.get("marketplace") or "Global"))
    platform_id = str(target.get("platform_id") or "")
    category_query = trend_category_query_text(category, platform_id)
    market_query = "" if marketplace.lower() == "global" else marketplace
    seasons = infer_trend_target_seasons(payload)
    primary_season = seasons[0]
    queries: list[dict[str, str]] = []
    if platform_id == "wgsn":
        domain_query = "(site:wgsn.com OR site:wgsnchina.cn)"
        for index, season in enumerate(seasons[:2], start=1):
            queries.append(
                trend_query_spec(
                    platform_id,
                    f"season_{index}",
                    "overview",
                    f'{domain_query} {category_query} "{season}" trend forecast {market_query}',
                    f"A public WGSN editorial forecast about {season} {category_query} trends"
                    + (f" for {market_query}" if market_query else ""),
                    target_season=season,
                )
            )
        wgsn_topics = (
            ("colour", "colour", "key colours", "key colour direction"),
            ("materials", "materials", "materials forecast", "fabric and material direction"),
            ("catwalk", "silhouette", "catwalk silhouettes", "catwalk silhouette direction"),
            ("details", "details", "design details", "design detail direction"),
            ("big_ideas", "overview", "Big Ideas", "Big Ideas fashion forecast"),
            ("intimates", "visual", "intimates lingerie", "intimates editorial inspiration"),
        )
        for query_id, dimension, keyword, description in wgsn_topics:
            queries.append(
                trend_query_spec(
                    platform_id,
                    query_id,
                    dimension,
                    f'{domain_query} {category_query} "{primary_season}" "{keyword}" {market_query}',
                    f"A public WGSN {description} page for {primary_season} {category_query}"
                    + (f" in {market_query}" if market_query else ""),
                    target_season=primary_season,
                )
            )
    elif platform_id == "diexun":
        domain_query = "(site:diction-style.com OR site:diexun.com)"
        for index, season in enumerate(seasons[:2], start=1):
            season_zh = trend_season_query_text(season, platform_id)
            queries.append(
                trend_query_spec(
                    platform_id,
                    f"season_{index}",
                    "overview",
                    f"{domain_query} {category_query} {season_zh} 趋势 {market_query}",
                    f"蝶讯 DNEXT 官方网站中关于{season_zh}{category_query}流行趋势的编辑内容",
                    target_season=season,
                )
            )
        diexun_topics = (
            ("colour", "colour", "色彩趋势"),
            ("materials", "materials", "面料趋势"),
            ("theme", "overview", "主题企划"),
            ("styles", "silhouette", "单品款式趋势"),
            ("details", "details", "细节工艺趋势"),
            ("runway", "visual", "秀场品牌趋势"),
        )
        season_zh = trend_season_query_text(primary_season, platform_id)
        for query_id, dimension, keyword in diexun_topics:
            queries.append(
                trend_query_spec(
                    platform_id,
                    query_id,
                    dimension,
                    f"{domain_query} {category_query} {season_zh} {keyword} {market_query}",
                    f"蝶讯 DNEXT 官方网站中关于{season_zh}{category_query}{keyword}的专业编辑页面",
                    target_season=primary_season,
                )
            )
    else:
        domain_query = "site:pinterest.com"
        concepts = unique_strings(
            [
                clean_text(str(item))
                for item in (payload.get("trendConcepts") or payload.get("trend_concepts") or [])
                if clean_text(str(item))
            ]
        )[:8]
        for index, concept in enumerate(concepts, start=1):
            dimensions = trend_dimension_matches(concept)
            queries.append(
                trend_query_spec(
                    platform_id,
                    f"concept_{index}",
                    dimensions[0] if dimensions else "visual",
                    f'{domain_query} {category_query} "{concept}" moodboard',
                    f"A Pinterest board or individual Pin showing {concept} inspiration for "
                    f"{category_query}, with clear design imagery rather than shopping listings",
                    target_season=primary_season,
                )
            )
        pinterest_topics = (
            ("season", "overview", f'"{primary_season}" trend moodboard', "trend moodboard"),
            ("colour", "colour", "colour palette", "colour palette inspiration"),
            ("materials", "materials", "fabric texture", "fabric and texture inspiration"),
            ("details", "details", "design details editorial", "design detail editorial"),
        )
        for query_id, dimension, keyword, description in pinterest_topics:
            queries.append(
                trend_query_spec(
                    platform_id,
                    query_id,
                    dimension,
                    f"{domain_query} {category_query} {keyword}",
                    f"A Pinterest board or individual Pin with {description} for {category_query}",
                    target_season=primary_season,
                )
            )

    deduplicated: list[dict[str, str]] = []
    seen_queries: set[str] = set()
    for query_spec in queries:
        key = query_spec["query"].lower()
        if key in seen_queries:
            continue
        seen_queries.add(key)
        deduplicated.append(query_spec)
    return deduplicated


def trend_platform_search_query(target: dict[str, Any], payload: dict[str, Any]) -> str:
    queries = trend_platform_search_queries(target, payload)
    return queries[0]["query"] if queries else ""


def official_trend_search_results(
    raw_results: list[dict[str, Any]],
    domains: set[str],
    limit: int,
    *,
    query_id: str = "",
    dimension: str = "overview",
    target_season: str = "",
) -> list[dict[str, Any]]:
    official: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_results:
        url = normalize_discovery_url(str(item.get("url") or ""))
        if not url or url in seen or not domain_matches(article_domain(url), domains):
            continue
        if trend_page_is_low_value(url):
            continue
        seen.add(url)
        snippet = compact_text(clean_text(str(item.get("snippet") or "")), 500)
        published = ""
        if not trend_url_is_pinterest_ideas(url):
            published = infer_trend_published(
                [item.get("published")], f"{item.get('title') or ''} {snippet}"
            )
        image_candidates = [
            {
                "url": item.get("image_url"),
                "alt": item.get("title") or "",
                "source": "search_result",
            },
            *trend_markdown_image_candidates(str(item.get("snippet") or "")),
        ]
        images = normalize_trend_images(url, image_candidates, limit=3)
        official.append(
            {
                "title": compact_text(
                    clean_text(str(item.get("title") or article_domain(url))), 180
                ),
                "url": url,
                "domain": article_domain(url),
                "snippet": snippet,
                "published": published,
                "image_url": images[0]["image_url"] if images else "",
                "image_urls": [image["image_url"] for image in images],
                "images": images,
                "query_ids": [query_id] if query_id else [],
                "query_dimensions": [dimension],
                "target_seasons": [target_season] if target_season else [],
                "evidence_level": "indexed_public_preview",
            }
        )
        if len(official) >= limit:
            break
    return official


def trend_platform_seed_url(target: dict[str, Any], category: str) -> str:
    seed_url = str(target.get("seed_url") or "")
    if str(target.get("platform_id") or "") != "pinterest":
        return ""
    query = urllib.parse.urlencode({"q": f"{category} color fabric silhouette style trend"})
    return f"{seed_url}?{query}"


def canonical_trend_page_key(url: str) -> str:
    normalized = normalize_discovery_url(url)
    if not normalized:
        return ""
    parsed = urllib.parse.urlsplit(normalized)
    hostname = (parsed.hostname or "").lower()
    path = re.sub(r"/+", "/", parsed.path or "/")
    if hostname.endswith("pinterest.com"):
        pin_match = re.search(r"/pin/(\d+)", path)
        if pin_match:
            return f"pinterest:pin:{pin_match.group(1)}"
    stable_query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"fbclid", "gclid", "ref", "source", "share"}
    ]
    return urllib.parse.urlunsplit(
        (
            "https",
            hostname,
            path.rstrip("/") or "/",
            urllib.parse.urlencode(sorted(stable_query)),
            "",
        )
    )


def trend_url_is_pinterest_ideas(url: str) -> bool:
    parsed = urllib.parse.urlsplit(str(url or ""))
    return (parsed.hostname or "").lower().endswith("pinterest.com") and re.match(
        r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?ideas(?:/|$)",
        re.sub(r"/+", "/", parsed.path or "/").lower(),
    ) is not None


def trend_page_is_low_value(url: str) -> bool:
    parsed = urllib.parse.urlsplit(str(url or ""))
    hostname = (parsed.hostname or "").lower()
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/").lower() or "/"
    segments = {segment for segment in path.split("/") if segment}
    if segments & {"login", "signin", "sign-in", "signup", "sign-up", "register"}:
        return True
    if hostname.endswith(("wgsn.com", "wgsnchina.cn")) and segments & {
        "products",
        "product",
        "features",
        "feature",
        "solutions",
        "platform",
        "about",
        "contact",
        "demo",
    }:
        return True
    if hostname.endswith(("diexun.com", "diction-style.com")) and (
        segments
        & {
            "about_us",
            "about-us",
            "about",
            "app",
            "course",
            "courses",
            "profile",
            "company",
            "intro",
            "download",
        }
        or any(
            marker in path
            for marker in (
                "about_us",
                "company-profile",
                "company_profile",
                "course-detail",
                "course_detail",
            )
        )
    ):
        return True
    if hostname.endswith("pinterest.com") and segments & {
        "business",
        "advertising",
        "shopping",
        "pin-builder",
    }:
        return True
    return False


def trend_page_is_generic_hub(url: str) -> bool:
    parsed = urllib.parse.urlsplit(str(url or ""))
    hostname = (parsed.hostname or "").lower()
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/").lower() or "/"
    if trend_page_is_low_value(url):
        return True
    if hostname.endswith(("wgsn.com", "wgsnchina.cn")) and re.fullmatch(
        r"/(?:[a-z]{2}(?:-[a-z]{2})?/)?blog",
        path,
    ):
        return True
    if hostname.endswith(("diexun.com", "diction-style.com")) and (
        path in {"/app", "/app/index.html"} or "news-index" in path or path in {"/fashion", "/news"}
    ):
        return True
    if hostname.endswith("pinterest.com") and (
        re.match(r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?search(?:/|$)", path) or path == "/"
    ):
        return True
    return False


def merge_trend_search_results(
    results: list[dict[str, Any]],
    category: str,
    time_range: str,
    target_seasons: list[str] | None = None,
) -> list[dict[str, Any]]:
    requested_seasons = target_seasons or []
    merged: dict[str, dict[str, Any]] = {}
    for item in results:
        url = str(item.get("url") or "")
        if trend_page_is_low_value(url):
            continue
        key = canonical_trend_page_key(url)
        if not key:
            continue
        existing = merged.get(key)
        if existing is None:
            existing = dict(item)
            existing["canonical_url"] = key
            existing["query_ids"] = list(dict.fromkeys(item.get("query_ids") or []))
            existing["query_dimensions"] = list(dict.fromkeys(item.get("query_dimensions") or []))
            existing["target_seasons"] = list(dict.fromkeys(item.get("target_seasons") or []))
            existing["images"] = list(item.get("images") or [])
            merged[key] = existing
        else:
            existing["query_ids"] = list(
                dict.fromkeys([*(existing.get("query_ids") or []), *(item.get("query_ids") or [])])
            )
            existing["query_dimensions"] = list(
                dict.fromkeys(
                    [
                        *(existing.get("query_dimensions") or []),
                        *(item.get("query_dimensions") or []),
                    ]
                )
            )
            existing["target_seasons"] = list(
                dict.fromkeys(
                    [*(existing.get("target_seasons") or []), *(item.get("target_seasons") or [])]
                )
            )
            if len(str(item.get("snippet") or "")) > len(str(existing.get("snippet") or "")):
                existing["snippet"] = item.get("snippet")
            if not existing.get("published") and item.get("published"):
                existing["published"] = item.get("published")
            existing["images"] = [*(existing.get("images") or []), *(item.get("images") or [])]
            existing["images"] = normalize_trend_images(url, existing["images"], limit=3)
            existing["image_urls"] = [image["image_url"] for image in existing["images"]]
            existing["image_url"] = existing["image_urls"][0] if existing["image_urls"] else ""

    for item in merged.values():
        evidence_text = f"{item.get('title') or ''} {item.get('snippet') or ''}"
        relevance_status, relevance_score = trend_relevance_status(evidence_text, category)
        path = urllib.parse.urlsplit(str(item.get("url") or "")).path or "/"
        if path in {"", "/"}:
            relevance_status = "generic"
            relevance_score = min(relevance_score, 5)
        published = (
            ""
            if trend_url_is_pinterest_ideas(str(item.get("url") or ""))
            else infer_trend_published([item.get("published")], evidence_text)
        )
        item["published"] = published
        item["recency_status"] = trend_recency_status(published, time_range)
        item["relevance_status"] = relevance_status
        item["relevance_score"] = relevance_score
        item["target_season_score"] = trend_season_match_score(
            evidence_text,
            requested_seasons or list(item.get("target_seasons") or []),
        )

    relevance_rank = {"category_specific": 0, "adjacent": 1, "generic": 2}

    def candidate_priority(item: dict[str, Any]) -> int:
        recency = str(item.get("recency_status") or "undated")
        relevance = str(item.get("relevance_status") or "generic")
        if recency == "recent" and relevance == "category_specific":
            return 0
        if int(item.get("target_season_score") or 0) and relevance != "generic":
            return 1
        if recency == "recent" and relevance == "adjacent":
            return 2
        if recency == "undated" and relevance != "generic":
            return 3
        if recency == "background" and relevance != "generic":
            return 4
        return 5

    return sorted(
        merged.values(),
        key=lambda item: (
            candidate_priority(item),
            relevance_rank.get(str(item.get("relevance_status") or "generic"), 2),
            -int(item.get("target_season_score") or 0),
            -int(item.get("relevance_score") or 0),
            str(item.get("title") or ""),
        ),
    )


def enrich_trend_page(
    page: dict[str, Any],
    candidate: dict[str, Any],
    category: str,
    time_range: str,
    target_seasons: list[str] | None = None,
) -> dict[str, Any]:
    enriched = dict(page)
    page_url = str(page.get("final_url") or page.get("url") or "")
    pinterest_ideas = trend_url_is_pinterest_ideas(page_url)
    published = (
        "" if pinterest_ideas else str(page.get("published") or candidate.get("published") or "")
    )
    updated = "" if pinterest_ideas else str(page.get("updated") or "")
    effective_date = updated or published
    evidence_text = " ".join(
        [
            str(page.get("title") or candidate.get("title") or ""),
            str(page.get("description") or candidate.get("snippet") or ""),
            *(str(item) for item in page.get("evidence_snippets") or []),
        ]
    )
    relevance_status, relevance_score = trend_relevance_status(evidence_text, category)
    path = urllib.parse.urlsplit(str(page.get("final_url") or page.get("url") or "")).path or "/"
    generic_hub = trend_page_is_generic_hub(page_url)
    if path in {"", "/"} or generic_hub:
        relevance_status = "generic"
        relevance_score = min(relevance_score, 5)
    dimensions = list(
        dict.fromkeys(
            [
                *(candidate.get("query_dimensions") or []),
                *trend_dimension_matches(evidence_text),
            ]
        )
    )
    evidence_status = (
        "qualified"
        if relevance_status == "category_specific"
        else "supporting"
        if relevance_status == "adjacent" and dimensions
        else "generic"
    )
    target_season_score = trend_season_match_score(
        evidence_text,
        target_seasons or list(candidate.get("target_seasons") or []),
    )
    images: list[dict[str, Any]] = []
    for image in page.get("images") or []:
        if not isinstance(image, dict):
            continue
        images.append(
            {
                **image,
                "source_page_url": str(
                    page.get("final_url") or page.get("url") or candidate.get("url") or ""
                ),
                "source_page_title": str(page.get("title") or candidate.get("title") or ""),
                "published_at": published,
                "recency_status": trend_recency_status(effective_date, time_range),
                "relevance_status": relevance_status,
                "query_dimensions": dimensions,
                "target_season_score": target_season_score,
                "page_kind": "generic_hub" if generic_hub else "content_page",
            }
        )
    enriched.update(
        {
            "published": published,
            "updated": updated,
            "effective_date": effective_date,
            "recency_status": trend_recency_status(effective_date, time_range),
            "relevance_status": relevance_status,
            "relevance_score": relevance_score,
            "target_season_score": target_season_score,
            "evidence_status": evidence_status,
            "page_kind": "generic_hub" if generic_hub else "content_page",
            "query_ids": candidate.get("query_ids") or [],
            "query_dimensions": dimensions,
            "images": images,
            "image_urls": [image.get("image_url") for image in images if image.get("image_url")],
            "image_url": next(
                (str(image.get("image_url")) for image in images if image.get("image_url")), ""
            ),
        }
    )
    return enriched


def trend_platform_visual_evidence(
    platform_id: str,
    pages: list[dict[str, Any]],
    search_results: list[dict[str, Any]],
    category: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for page in pages:
        for image in page.get("images") or []:
            if not isinstance(image, dict) or not image.get("image_url"):
                continue
            candidates.append(
                {
                    **image,
                    "platform_id": platform_id,
                    "evidence_level": "public_page_declared_image",
                }
            )
    for result in search_results:
        if str(result.get("relevance_status") or "generic") == "generic":
            continue
        for image in result.get("images") or []:
            if not isinstance(image, dict) or not image.get("image_url"):
                continue
            candidates.append(
                {
                    **image,
                    "platform_id": platform_id,
                    "source_page_url": result.get("url"),
                    "source_page_title": result.get("title"),
                    "published_at": result.get("published"),
                    "recency_status": result.get("recency_status"),
                    "relevance_status": result.get("relevance_status"),
                    "query_dimensions": result.get("query_dimensions") or [],
                    "target_season_score": result.get("target_season_score") or 0,
                    "page_kind": "search_preview",
                    "evidence_level": "indexed_public_preview_image",
                }
            )
    category_terms = trend_category_terms(category)

    def visual_quality(item: dict[str, Any]) -> int:
        image_text = f"{item.get('alt_text') or ''} {item.get('source_page_title') or ''}"
        image_category_match = any(trend_text_has_term(image_text, term) for term in category_terms)
        score = {"category_specific": 45, "adjacent": 24}.get(
            str(item.get("relevance_status") or "generic"),
            0,
        )
        score += min(20, int(item.get("target_season_score") or 0) * 10)
        score += {"recent": 10, "undated": 6, "background": 2}.get(
            str(item.get("recency_status") or "undated"),
            4,
        )
        score += 10 if item.get("evidence_level") == "public_page_declared_image" else 4
        score += 5 if str(item.get("page_kind") or "content_page") == "content_page" else 0
        score += 5 if image_category_match else 0
        score += min(4, len(item.get("query_dimensions") or []))
        return score

    def visual_rank(item: dict[str, Any]) -> tuple[int, str]:
        return (-visual_quality(item), str(item.get("source_page_url") or ""))

    for candidate in candidates:
        candidate["quality_score"] = visual_quality(candidate)
    candidates.sort(key=visual_rank)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    for candidate in candidates:
        key = str(
            candidate.get("canonical_key")
            or trend_image_canonical_key(str(candidate.get("image_url") or ""))
        )
        if not key or key in seen:
            continue
        seen.add(key)
        source_key = canonical_trend_page_key(str(candidate.get("source_page_url") or "")) or key
        grouped[source_key].append(candidate)

    source_keys = sorted(
        grouped,
        key=lambda source_key: visual_rank(grouped[source_key][0]),
    )
    selected: list[dict[str, Any]] = []
    while source_keys and len(selected) < TREND_MAX_IMAGES_PER_PLATFORM:
        remaining_keys: list[str] = []
        for source_key in source_keys:
            group = grouped[source_key]
            if not group:
                continue
            selected.append(group.pop(0))
            if group:
                remaining_keys.append(source_key)
            if len(selected) >= TREND_MAX_IMAGES_PER_PLATFORM:
                break
        source_keys = remaining_keys
    return selected


def crawl_one_trend_platform(target: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    category = clean_text(str(payload.get("category") or ""))
    time_range = normalize_agent_time_range(payload.get("timeRange")) or "30d"
    target_seasons = infer_trend_target_seasons(payload)
    query_specs = trend_platform_search_queries(target, payload)
    results_per_query = max(
        1,
        min(int(payload.get("resultsPerQuery") or payload.get("resultsPerPlatform") or 10), 20),
    )
    page_read_limit = max(1, min(int(payload.get("pageReadLimit") or 30), 50))
    bypass_cache = bool(payload.get("bypassCache"))
    domains = set(target.get("domains") or set())
    warnings: list[str] = []
    providers: list[str] = []
    all_search_results: list[dict[str, Any]] = []
    query_runs: list[dict[str, Any]] = []
    raw_result_count = 0

    def run_search(
        query_spec: dict[str, str], requested_time_range: str
    ) -> tuple[str, list[dict[str, Any]], list[str]]:
        query = query_spec["query"]
        try:
            return web_search_query(
                query,
                results_per_query,
                bypass_cache=bypass_cache,
                time_range=requested_time_range,
                agent_reach_query=query_spec.get("agent_reach_query", ""),
                search_lang=query_spec.get("search_lang", ""),
                country=query_spec.get("country", ""),
            )
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            # Preserve compatibility with integrations wrapping the old callback signature.
            return web_search_query(
                query,
                results_per_query,
                bypass_cache=bypass_cache,
            )

    for query_spec in query_specs:
        try:
            provider, raw_results, search_warnings = run_search(query_spec, time_range)
            date_fallback_used = False
            strict_raw_result_count = len(raw_results)
            official = official_trend_search_results(
                raw_results,
                domains,
                results_per_query,
                query_id=query_spec["query_id"],
                dimension=query_spec["dimension"],
                target_season=query_spec.get("target_season", ""),
            )
            if not official and web_search_time_options(time_range):
                fallback_provider, fallback_results, fallback_warnings = run_search(query_spec, "")
                fallback_official = official_trend_search_results(
                    fallback_results,
                    domains,
                    results_per_query,
                    query_id=query_spec["query_id"],
                    dimension=query_spec["dimension"],
                    target_season=query_spec.get("target_season", ""),
                )
                if fallback_official:
                    provider = fallback_provider
                    raw_results = fallback_results
                    official = fallback_official
                    search_warnings = [*search_warnings, *fallback_warnings]
                    date_fallback_used = True
            providers.append(provider)
            raw_result_count += len(raw_results)
            warnings.extend(search_warnings)
            all_search_results.extend(official)
            query_runs.append(
                {
                    **query_spec,
                    "provider": provider,
                    "raw_result_count": len(raw_results),
                    "strict_raw_result_count": strict_raw_result_count,
                    "official_result_count": len(official),
                    "date_fallback_used": date_fallback_used,
                }
            )
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            warning = f"{target['name']} {query_spec['dimension']} search failed: {exc}"
            warnings.append(warning)
            query_runs.append(
                {
                    **query_spec,
                    "provider": "",
                    "raw_result_count": 0,
                    "official_result_count": 0,
                    "warning": warning,
                }
            )

    search_results = merge_trend_search_results(
        all_search_results,
        category,
        time_range,
        target_seasons,
    )
    seed_url = trend_platform_seed_url(target, category)
    seed_key = canonical_trend_page_key(seed_url)
    candidate_keys = {str(item.get("canonical_url") or "") for item in search_results}
    candidates = list(search_results)
    if seed_url and seed_key not in candidate_keys:
        candidates.append(
            {
                "title": target.get("name"),
                "url": seed_url,
                "canonical_url": seed_key,
                "snippet": "",
                "published": "",
                "recency_status": "undated",
                "relevance_status": "generic",
                "relevance_score": 0,
                "query_ids": [],
                "query_dimensions": ["overview"],
                "images": [],
            }
        )
    pages: list[dict[str, Any]] = []
    page_errors: list[str] = []
    discarded_page_count = 0
    attempted_page_count = 0
    candidate_index = 0
    while candidate_index < len(candidates) and len(pages) < page_read_limit:
        batch = candidates[candidate_index : candidate_index + min(6, page_read_limit - len(pages))]
        candidate_index += len(batch)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(batch))) as executor:
            futures = [
                executor.submit(
                    fetch_public_trend_page_with_fallback,
                    str(candidate.get("url") or ""),
                    category,
                    bypass_cache=bypass_cache,
                )
                for candidate in batch
            ]
            for candidate, future in zip(batch, futures, strict=False):
                attempted_page_count += 1
                url = str(candidate.get("url") or "")
                try:
                    page = enrich_trend_page(
                        future.result(),
                        candidate,
                        category,
                        time_range,
                        target_seasons,
                    )
                except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                    page_errors.append(f"Failed to read {url}: {exc}")
                    continue
                if page.get("evidence_status") in {"qualified", "supporting"}:
                    pages.append(page)
                else:
                    discarded_page_count += 1
    warnings.extend(page_errors)

    snippets = unique_strings(
        [
            *(snippet for page in pages for snippet in page.get("evidence_snippets") or []),
            *(str(item.get("snippet") or "") for item in search_results),
        ]
    )[:30]
    accessed = bool(pages or search_results)
    access_status = "readable" if pages else "search_only" if search_results else "unavailable"
    qualified_pages = sum(1 for page in pages if page.get("evidence_status") == "qualified")
    supporting_pages = sum(1 for page in pages if page.get("evidence_status") == "supporting")
    recent_pages = sum(1 for page in pages if page.get("recency_status") == "recent")
    background_pages = sum(1 for page in pages if page.get("recency_status") == "background")
    undated_pages = sum(1 for page in pages if page.get("recency_status") == "undated")
    visual_evidence = trend_platform_visual_evidence(
        str(target["platform_id"]),
        pages,
        search_results,
        category,
    )
    return {
        "platform_id": target["platform_id"],
        "name": target["name"],
        "official_domains": sorted(domains),
        "search_query": query_specs[0]["query"] if query_specs else "",
        "search_queries": query_specs,
        "target_seasons": target_seasons,
        "query_runs": query_runs,
        "query_count": len(query_specs),
        "search_provider": ", ".join(dict.fromkeys(providers)),
        "raw_result_count": raw_result_count,
        "unique_candidate_count": len(search_results),
        "search_result_count": len(search_results),
        "search_results": search_results,
        "page_read_target": page_read_limit,
        "page_attempt_count": attempted_page_count,
        "page_read_count": len(pages),
        "pages": pages,
        "qualified_page_count": qualified_pages,
        "supporting_page_count": supporting_pages,
        "recent_page_count": recent_pages,
        "background_page_count": background_pages,
        "undated_page_count": undated_pages,
        "discarded_page_count": discarded_page_count,
        "visual_evidence": visual_evidence,
        "visual_count": len(visual_evidence),
        "accessed": accessed,
        "access_status": access_status,
        "evidence_status": "qualified"
        if qualified_pages
        else "supporting"
        if supporting_pages
        else "insufficient",
        "evidence_snippets": snippets,
        "warnings": warnings,
    }


def failed_trend_platform_result(
    target: dict[str, Any], payload: dict[str, Any], exc: Exception
) -> dict[str, Any]:
    query_specs = trend_platform_search_queries(target, payload)
    return {
        "platform_id": target["platform_id"],
        "name": target["name"],
        "official_domains": sorted(target["domains"]),
        "search_query": query_specs[0]["query"] if query_specs else "",
        "search_queries": query_specs,
        "target_seasons": infer_trend_target_seasons(payload),
        "query_runs": [],
        "query_count": len(query_specs),
        "search_provider": "",
        "raw_result_count": 0,
        "unique_candidate_count": 0,
        "search_result_count": 0,
        "search_results": [],
        "page_read_target": int(payload.get("pageReadLimit") or 30),
        "page_attempt_count": 0,
        "page_read_count": 0,
        "pages": [],
        "qualified_page_count": 0,
        "supporting_page_count": 0,
        "recent_page_count": 0,
        "background_page_count": 0,
        "undated_page_count": 0,
        "discarded_page_count": 0,
        "visual_evidence": [],
        "visual_count": 0,
        "accessed": False,
        "access_status": "unavailable",
        "evidence_status": "insufficient",
        "evidence_snippets": [],
        "warnings": [f"Platform collection failed: {exc}"],
    }


def crawl_trend_platforms(payload: dict[str, Any]) -> dict[str, Any]:
    category = clean_text(str(payload.get("category") or ""))
    if not category:
        raise ValueError("category is required")

    targets = {str(target["platform_id"]): target for target in TREND_PLATFORM_TARGETS}
    collected: dict[str, dict[str, Any]] = {}
    editorial_targets = [targets["wgsn"], targets["diexun"]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(editorial_targets)) as executor:
        futures = {
            executor.submit(crawl_one_trend_platform, target, payload): target
            for target in editorial_targets
        }
        for future, target in futures.items():
            platform_id = str(target["platform_id"])
            try:
                collected[platform_id] = future.result()
            except Exception as exc:  # noqa: BLE001 - one platform must not erase the others.
                collected[platform_id] = failed_trend_platform_result(target, payload, exc)

    supplied_concepts = [
        clean_text(str(item))
        for item in (payload.get("trendConcepts") or payload.get("trend_concepts") or [])
        if clean_text(str(item))
    ]
    extracted_concepts = extract_trend_concepts(
        [collected["wgsn"], collected["diexun"]],
        payload,
        limit=10,
    )
    trend_concepts = unique_strings([*supplied_concepts, *extracted_concepts])[:12]
    pinterest_payload = {**payload, "trendConcepts": trend_concepts}
    try:
        collected["pinterest"] = crawl_one_trend_platform(
            targets["pinterest"],
            pinterest_payload,
        )
    except Exception as exc:  # noqa: BLE001 - preserve the editorial platform results.
        collected["pinterest"] = failed_trend_platform_result(
            targets["pinterest"],
            pinterest_payload,
            exc,
        )

    platforms = [collected[str(target["platform_id"])] for target in TREND_PLATFORM_TARGETS]
    accessed_platforms = sum(1 for item in platforms if item.get("accessed"))
    readable_platforms = sum(1 for item in platforms if item.get("page_read_count"))
    search_only_platforms = sum(
        1 for item in platforms if item.get("access_status") == "search_only"
    )
    qualified_platforms = sum(1 for item in platforms if item.get("qualified_page_count"))
    total_readable_pages = sum(int(item.get("page_read_count") or 0) for item in platforms)
    total_recent_pages = sum(int(item.get("recent_page_count") or 0) for item in platforms)
    total_background_pages = sum(int(item.get("background_page_count") or 0) for item in platforms)
    total_undated_pages = sum(int(item.get("undated_page_count") or 0) for item in platforms)
    report_image_limit = max(
        1, min(int(payload.get("reportImageLimit") or 36), TREND_MAX_REPORT_IMAGES)
    )
    visual_by_key: dict[str, dict[str, Any]] = {}
    for platform in platforms:
        for candidate in platform.get("visual_evidence") or []:
            key = str(
                candidate.get("canonical_key")
                or trend_image_canonical_key(str(candidate.get("image_url") or ""))
            )
            if not key:
                continue
            existing = visual_by_key.get(key)
            if not existing or int(candidate.get("quality_score") or 0) > int(
                existing.get("quality_score") or 0
            ):
                visual_by_key[key] = candidate
    visual_pool = [
        candidate
        for candidate in visual_by_key.values()
        if int(candidate.get("quality_score") or 0) >= 20
        and not trend_page_is_low_value(str(candidate.get("source_page_url") or ""))
    ]
    available_visual_count = len(visual_pool)
    visual_evidence: list[dict[str, Any]] = []
    platform_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    while visual_pool and len(visual_evidence) < report_image_limit:
        best_index = max(
            range(len(visual_pool)),
            key=lambda index: (
                int(visual_pool[index].get("quality_score") or 0)
                - platform_counts[str(visual_pool[index].get("platform_id") or "")] * 3
                - source_counts[
                    canonical_trend_page_key(str(visual_pool[index].get("source_page_url") or ""))
                ]
                * 2,
                int(visual_pool[index].get("target_season_score") or 0),
                str(visual_pool[index].get("source_page_url") or ""),
            ),
        )
        candidate = visual_pool.pop(best_index)
        platform_id = str(candidate.get("platform_id") or "")
        source_key = canonical_trend_page_key(str(candidate.get("source_page_url") or ""))
        platform_counts[platform_id] += 1
        source_counts[source_key] += 1
        visual_evidence.append(
            {
                **candidate,
                "visual_id": f"V{len(visual_evidence) + 1:03d}",
            }
        )
    warnings = unique_strings(
        [str(warning) for item in platforms for warning in item.get("warnings") or []]
    )
    return {
        "category": category,
        "marketplace": str(payload.get("marketplace") or "Global"),
        "time_range": normalize_agent_time_range(payload.get("timeRange")) or "30d",
        "target_seasons": infer_trend_target_seasons(payload),
        "trend_concepts": trend_concepts,
        "generated_at": now_iso(),
        "source_mode": "agent_reach_search_plus_public_page_crawler",
        "coverage": {
            "required_platforms": len(TREND_PLATFORM_TARGETS),
            "accessed_platforms": accessed_platforms,
            "readable_platforms": readable_platforms,
            "search_only_platforms": search_only_platforms,
            "qualified_platforms": qualified_platforms,
            "readable_pages": total_readable_pages,
            "recent_pages": total_recent_pages,
            "background_pages": total_background_pages,
            "undated_pages": total_undated_pages,
            "complete": accessed_platforms == len(TREND_PLATFORM_TARGETS),
            "qualified_complete": qualified_platforms == len(TREND_PLATFORM_TARGETS),
        },
        "platforms": platforms,
        "visual_evidence": visual_evidence,
        "visual_coverage": {
            "available": available_visual_count,
            "selected_for_report": len(visual_evidence),
            "report_image_limit": report_image_limit,
            "by_platform": {
                platform_id: sum(
                    1
                    for visual in visual_evidence
                    if str(visual.get("platform_id") or "") == platform_id
                )
                for platform_id in ("wgsn", "diexun", "pinterest")
            },
            "source_pages": len(
                {
                    canonical_trend_page_key(str(visual.get("source_page_url") or ""))
                    for visual in visual_evidence
                    if visual.get("source_page_url")
                }
            ),
        },
        "warnings": warnings,
        "method": {
            "notes": [
                "Every run targets WGSN, 蝶讯 DNEXT, and Pinterest; other sources cannot substitute for a missing target platform.",
                "Discovery uses the configured web-search provider (Agent Reach/Exa when selected), then reads public pages with direct HTTP and a Jina Reader fallback.",
                "Search-result snippets are labeled indexed_public_preview and are not treated as full report bodies.",
                "WGSN and 蝶讯 DNEXT are collected first; concrete colour, material, and style concepts from their public titles and previews then drive a second Pinterest visual-expansion stage.",
                "Each platform uses its own short editorial vocabulary instead of sharing one long keyword string.",
                "Brave, Tavily, and Google receive native date parameters; Agent Reach receives a readable date preference, and all dated results are ranked again after retrieval.",
                "Current or upcoming target-season pages remain useful fallback material when the recent window has no strong match.",
                "Page-read limits count successful relevant/supporting pages, so failed or generic homepage reads do not consume the useful-page target.",
                "The crawler does not authenticate, bypass paywalls, or expose gated report content.",
                "Pinterest /ideas/ collection updates are kept undated and are never treated as individual Pin publication dates.",
                "Visual evidence is globally quality-ranked with a small diversity nudge, not filled to equal platform quotas.",
            ],
        },
    }


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
    if any(
        phrase in lowered
        for phrase in ["best bras", "best minimizer", "top bras", "best full coverage"]
    ):
        return "public_ranking"
    if any(
        phrase in lowered
        for phrase in ["reviewed", "tested", "editor-tested", "lab-tested", "expert-approved"]
    ):
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


def score_article_authority(
    domain: str, source_type: str, title: str, text: str
) -> tuple[int, str, list[str], list[str]]:
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
    if re.search(
        r"\b(?:20[1-3][0-9]|Jan\.?|Feb\.?|Mar\.?|Apr\.?|May|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Oct\.?|Nov\.?|Dec\.?)\b",
        text[:2200],
    ):
        score += 7
        evidence.append("Date or update metadata detected.")
    else:
        cautions.append("No clear publish/update date was detected.")

    if any(
        phrase in lowered
        for phrase in [
            "tested",
            "reviewed",
            "lab",
            "expert",
            "editor",
            "dermatologist",
            "fit specialist",
        ]
    ):
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
        cautions.append(
            "Commerce/affiliate disclosure detected; treat rankings as directional, not neutral."
        )
    if len(text) < 700:
        score -= 10
        cautions.append(
            "Readable text is short; article may be paywalled, truncated, or weakly extracted."
        )

    score = max(0, min(100, score))
    if score >= 70:
        level = "High"
    elif score >= 45:
        level = "Medium"
    else:
        level = "Low"
    return score, level, evidence[:6], cautions[:5]


def article_snippets(text: str, brands: list[str], signals: list[str]) -> list[str]:
    needles = [brand.lower() for brand in brands] + [
        signal.split(" / ", 1)[0].lower() for signal in signals
    ]
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
            "high_authority_articles": sum(
                1 for article in articles if article["authority_level"] == "High"
            ),
            "medium_authority_articles": sum(
                1 for article in articles if article["authority_level"] == "Medium"
            ),
            "low_authority_articles": sum(
                1 for article in articles if article["authority_level"] == "Low"
            ),
            "evidence_snippets": evidence_items,
        },
        "summary": {
            "top_domains": [
                {"name": name, "count": count} for name, count in domain_counts.most_common(10)
            ],
            "top_brands": [
                {"name": name, "count": count} for name, count in brand_counts.most_common(12)
            ],
            "top_signals": [
                {"name": name, "count": count} for name, count in signal_counts.most_common(12)
            ],
            "source_types": [
                {"name": name, "count": count} for name, count in source_type_counts.most_common(6)
            ],
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
    cached = (
        None if bypass_cache else read_cache(cache_path, ttl_seconds=ANALYSIS_CACHE_TTL_SECONDS)
    )
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
    view_counts = [
        int(video["view_count"]) for video in videos if isinstance(video.get("view_count"), int)
    ]
    like_counts = [
        int(video["like_count"]) for video in videos if isinstance(video.get("like_count"), int)
    ]
    comment_counts = [
        int(video["comment_count"])
        for video in videos
        if isinstance(video.get("comment_count"), int)
    ]
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
    top_topic = (
        topic_counts.most_common(1)[0][0]
        if topic_counts
        else "No repeated product pain point detected"
    )
    total_views = sum(view_counts)
    market_score = min(
        100,
        int(
            20 + len(videos) * 2 + min(35, total_views.bit_length() * 3) + min(20, comment_samples)
        ),
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
            "evidence_items_count": len(videos)
            + comment_samples
            + sum(1 for video in videos if video.get("transcript")),
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
        "channels": [
            {"name": name, "count": count} for name, count in channel_counts.most_common(12)
        ],
        "pain_points": pain_points,
        "brands": [{"name": name, "count": count} for name, count in brand_counts.most_common(12)],
        "product_signals": [
            {"name": name, "count": count} for name, count in signal_counts.most_common(12)
        ],
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
        "transcript_video_limit": max(
            0, min(int(payload.get("youtubeTranscriptVideoLimit", 5)), 20)
        ),
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
    cached = (
        None if bypass_cache else read_cache(cache_path, ttl_seconds=ANALYSIS_CACHE_TTL_SECONDS)
    )
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
    view_counts = [
        int(video["view_count"]) for video in videos if isinstance(video.get("view_count"), int)
    ]
    like_counts = [
        int(video["like_count"]) for video in videos if isinstance(video.get("like_count"), int)
    ]
    comment_counts = [
        int(video["comment_count"])
        for video in videos
        if isinstance(video.get("comment_count"), int)
    ]
    share_counts = [
        int(video["share_count"]) for video in videos if isinstance(video.get("share_count"), int)
    ]
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
        hashtag_counts.update(
            str(tag).lstrip("#") for tag in video.get("hashtags") or [] if str(tag).strip()
        )
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
    top_topic = (
        topic_counts.most_common(1)[0][0]
        if topic_counts
        else "No repeated product pain point detected"
    )
    total_views = sum(view_counts)
    total_likes = sum(like_counts)
    market_score = min(
        100,
        int(
            15 + len(videos) * 2 + min(35, total_views.bit_length() * 3) + min(25, comment_samples)
        ),
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
            "videos_with_comment_samples": sum(
                1 for video in videos if video.get("comment_samples")
            ),
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
        "authors": [
            {"name": name, "count": count} for name, count in author_counts.most_common(12)
        ],
        "hashtags": [
            {"name": name, "count": count} for name, count in hashtag_counts.most_common(16)
        ],
        "pain_points": pain_points,
        "brands": [{"name": name, "count": count} for name, count in brand_counts.most_common(12)],
        "product_signals": [
            {"name": name, "count": count} for name, count in signal_counts.most_common(12)
        ],
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
                "reddit_posts": int(
                    ((reddit_report or {}).get("coverage") or {}).get("posts") or 0
                ),
                "reddit_comments": int(
                    ((reddit_report or {}).get("data_volume") or {}).get("collected_comments") or 0
                ),
                "amazon_products": int(
                    ((amazon_report or {}).get("metrics") or {}).get("products") or 0
                ),
                "amazon_review_samples": int(
                    ((amazon_report or {}).get("metrics") or {}).get("review_samples") or 0
                ),
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
        bullets = (
            product.get("bullet_points") if isinstance(product.get("bullet_points"), list) else []
        )
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
        reviews = (
            product.get("review_samples") if isinstance(product.get("review_samples"), list) else []
        )
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
    top_pain = ((reddit_report or {}).get("pain_points") or [{}])[0].get(
        "topic"
    ) or "fit and comfort signals"
    amazon_metrics = (amazon_report or {}).get("metrics") or {}
    price_avg = amazon_metrics.get("price_avg")
    review_total = amazon_metrics.get("total_review_count") or 0
    default_ids = [item["id"] for item in evidence_pool[:3]]
    reddit_ids = [item["id"] for item in evidence_pool if item["source"] == "reddit"][
        :2
    ] or default_ids[:1]
    amazon_ids = [item["id"] for item in evidence_pool if item["source"] == "amazon"][
        :2
    ] or default_ids[:1]
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
        "text": str(
            verdict_raw.get("text")
            or f"{category} has directional evidence, but needs stronger sales and trend data."
        ),
        "citations": resolve_citations(
            verdict_raw.get("citation_ids"), evidence_pool, fallback_ids
        ),
    }
    return {
        "verdict": verdict,
        "opportunities": normalize_insight_items(
            raw.get("opportunities"), 3, evidence_pool, fallback_ids, "机会"
        ),
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
        "evidence_chain": normalize_chain_items(
            raw.get("evidence_chain"), evidence_pool, fallback_ids
        ),
        "data_gaps": normalize_insight_items(
            raw.get("data_gaps"), 3, evidence_pool, fallback_ids, "数据缺口"
        ),
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
        item = (
            raw_items[index]
            if index < len(raw_items) and isinstance(raw_items[index], dict)
            else {}
        )
        normalized.append(
            {
                "title": str(item.get("title") or f"{fallback_title} {index + 1}"),
                "detail": str(
                    item.get("detail") or "Needs review against the cited evidence before action."
                ),
                "citations": resolve_citations(
                    item.get("citation_ids"), evidence_pool, rotate_ids(fallback_ids, index)
                ),
            }
        )
    return normalized


def normalize_chain_items(
    items: Any, evidence_pool: list[dict[str, Any]], fallback_ids: list[str]
) -> list[dict[str, Any]]:
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
                "citations": resolve_citations(
                    item.get("citation_ids"), evidence_pool, rotate_ids(fallback_ids, index)
                ),
            }
        )
    return normalized


def resolve_citations(
    ids: Any, evidence_pool: list[dict[str, Any]], fallback_ids: list[str]
) -> list[dict[str, Any]]:
    evidence_by_id = {item["id"]: item for item in evidence_pool}
    requested_ids = ids if isinstance(ids, list) else []
    resolved = [
        evidence_by_id[item_id]
        for item_id in requested_ids
        if isinstance(item_id, str) and item_id in evidence_by_id
    ]
    if not resolved:
        resolved = [
            evidence_by_id[item_id] for item_id in fallback_ids if item_id in evidence_by_id
        ]
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


AGENT_TOOL_CATALOG: dict[str, dict[str, Any]] = {
    "amazon_shelf": {
        "label": "Amazon shelf",
        "description": "Collect Amazon search/product/review evidence for price, rating, review volume, claims, and brands.",
    },
    "media_rankings": {
        "label": "Media/ranking articles",
        "description": "Discover and read US media reviews, public rankings, and accessible report pages.",
    },
    "trend_platforms": {
        "label": "WGSN / 蝶讯 / Pinterest trend crawler",
        "description": (
            "Visit WGSN, 蝶讯, and Pinterest separately through domain-targeted web search and public-page "
            "reading; return color, fabric, silhouette, and style evidence with per-platform access status."
        ),
        "source": "agent_reach_crawler",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Target fashion or product category.",
                },
                "marketplace": {"type": "string", "description": "Target market or region."},
                "timeRange": {"type": "string", "description": "Research time window."},
                "resultsPerQuery": {"type": "integer", "minimum": 1, "maximum": 20},
                "resultsPerPlatform": {"type": "integer", "minimum": 1, "maximum": 20},
                "pageReadLimit": {"type": "integer", "minimum": 1, "maximum": 50},
                "reportImageLimit": {"type": "integer", "minimum": 1, "maximum": 36},
                "bypassCache": {"type": "boolean"},
            },
            "required": ["category"],
            "additionalProperties": True,
        },
    },
    "tiktok_social": {
        "label": "TikTok social validation",
        "description": "Collect TikTok videos and detail-page comment samples for social visibility and creator/user language.",
    },
    "build_market_report_data": {
        "label": "MarketReportData builder",
        "description": "Compile collected tool results into a stable MarketReportData JSON structure before rendering a market insight report.",
    },
    "build_tiktok_new_product_report_data": {
        "label": "TikTok new-product report data builder",
        "description": (
            "Compile FastMoss US L3 Bras new-product ranking, hard-filter non-bra and out-of-range "
            "price rows before ranking, retain shop name/shop_id, and join product details plus "
            "complete daily sales trends into stable TikTokNewProductReportData before rendering."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "build_tiktok_bra_competitor_shop_report_data": {
        "label": "TikTok bra competitor-shop report data builder",
        "description": (
            "Compile a 50-shop FastMoss US L3 Bras candidate pool and join the selected 10 "
            "shops' base, product, channel, trend, and creator evidence by seller_id into stable "
            "TikTokBraCompetitorShopReportData before rendering."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "build_trend_report_data": {
        "label": "TrendReportData builder",
        "description": (
            "Compile WGSN, Diexun, and Pinterest collection results into a dated, deduplicated, "
            "source-linked TrendReportData structure with a visual-evidence whitelist."
        ),
    },
    "build_competitor_product_report_data": {
        "label": "CompetitorProductReportData builder",
        "description": (
            "Compile one-ASIN SellerSprite, Sif, review, and Reddit evidence into a versioned, "
            "bounded CompetitorProductReportData structure before HTML rendering."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "build_hot_product_pain_report_data": {
        "label": "HotProductPainReportData builder",
        "description": (
            "Compile category-validated head-product, review, Sif sales-proxy, and keyword evidence "
            "into versioned, bounded HotProductPainReportData before HTML rendering."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "build_product_design_brief_data": {
        "label": "ProductDesignBriefData builder",
        "description": "Compile product-design research evidence into stable, cited ProductDesignBriefData before rendering.",
    },
    "render_html_report": {
        "label": "HTML 渲染 Agent",
        "description": "Use the LLM to author the final evidence-based HTML report for the loaded Skill.",
    },
    "render_markdown_report": {
        "label": "Markdown report renderer",
        "description": "Use the LLM to author an evidence-linked Markdown R&D brief from compiled ProductDesignBriefData.",
    },
}

AGENT_TOOL_CAPABILITY_REGISTRY = ToolCapabilityRegistry(
    [
        build_reddit_voc_capability(
            resolve_params=resolve_agent_tool_params,
            bounded_int=bounded_int,
            adapter=lambda tool_input: analyze_category(tool_input),
        )
    ]
)


def agent_tool_catalog() -> dict[str, dict[str, Any]]:
    catalog = AGENT_TOOL_CAPABILITY_REGISTRY.catalog()
    catalog.update({name: dict(meta) for name, meta in AGENT_TOOL_CATALOG.items()})
    catalog.update(get_fastmoss_tool_catalog())
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
    return [
        line.strip()[2:].strip() for line in section.splitlines() if line.strip().startswith("- ")
    ]


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
    required_descriptions = {row[0]: row[1] for row in required_rows if len(row) >= 2 and row[0]}
    defaults: dict[str, Any] = {}
    for row in optional_rows:
        if len(row) >= 2 and row[0]:
            defaults[row[0]] = parse_skill_value(row[1])
    html_template_path = path.parent / "assets" / "report-template.html"
    html_template = (
        html_template_path.read_text(encoding="utf-8") if html_template_path.exists() else ""
    )
    return {
        "skill_id": path.parent.name,
        "name": name,
        "description": first_markdown_paragraph(markdown_section(markdown_text, "What It Does")),
        "when_to_use": markdown_bullets(markdown_section(markdown_text, "When To Use")),
        "required_inputs_summary": required,
        "input_schema": {
            "required": required,
            "required_descriptions": required_descriptions,
            "defaults": defaults,
        },
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


def agent_payload_with_skill_params(
    payload: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
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


def agent_tool_input_payload(
    tool_name: str, category: str, payload: dict[str, Any]
) -> dict[str, Any]:
    if tool_name in AGENT_TOOL_CAPABILITY_REGISTRY:
        return AGENT_TOOL_CAPABILITY_REGISTRY.get(tool_name).normalize_input(category, payload)
    if is_fastmoss_agent_tool(tool_name):
        return build_fastmoss_input_payload(tool_name, category, payload)
    if is_sif_agent_tool(tool_name):
        return build_sif_input_payload(tool_name, category, payload)
    if is_sellersprite_agent_tool(tool_name):
        return build_sellersprite_input_payload(tool_name, category, payload)
    return adapt_agent_params_for_tool(tool_name, category, payload)


def compact_agent_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    if tool_name in AGENT_TOOL_CAPABILITY_REGISTRY:
        return AGENT_TOOL_CAPABILITY_REGISTRY.get(tool_name).shape_result(result)
    if is_fastmoss_agent_tool(tool_name):
        return result
    if is_sif_agent_tool(tool_name):
        return result
    if is_sellersprite_agent_tool(tool_name):
        return result
    if tool_name in {
        "build_market_report_data",
        "build_tiktok_new_product_report_data",
        "build_tiktok_bra_competitor_shop_report_data",
        "build_trend_report_data",
        "build_competitor_product_report_data",
        "build_hot_product_pain_report_data",
        "build_product_design_brief_data",
    }:
        return result
    if tool_name in {"render_html_report", "render_markdown_report"}:
        return result
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
                    "review_samples": product.get("review_samples")
                    if isinstance(product.get("review_samples"), list)
                    else [],
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
                    "evidence_snippets": article.get("evidence_snippets", [])[:6],
                    "cautions": article.get("cautions", [])[:4],
                }
                for article in result.get("articles", [])[:12]
            ],
            "data_volume": result.get("data_volume"),
            "warnings": result.get("warnings", [])[:8],
        }
    if tool_name == "trend_platforms":
        return {
            "category": result.get("category"),
            "marketplace": result.get("marketplace"),
            "time_range": result.get("time_range"),
            "generated_at": result.get("generated_at"),
            "source_mode": result.get("source_mode"),
            "coverage": result.get("coverage"),
            "visual_evidence": result.get("visual_evidence", [])[:TREND_MAX_REPORT_IMAGES],
            "visual_coverage": result.get("visual_coverage"),
            "platforms": [
                {
                    "platform_id": platform.get("platform_id"),
                    "name": platform.get("name"),
                    "official_domains": platform.get("official_domains"),
                    "search_query": platform.get("search_query"),
                    "search_queries": platform.get("search_queries", []),
                    "query_runs": platform.get("query_runs", []),
                    "query_count": platform.get("query_count"),
                    "search_provider": platform.get("search_provider"),
                    "raw_result_count": platform.get("raw_result_count"),
                    "unique_candidate_count": platform.get("unique_candidate_count"),
                    "search_result_count": platform.get("search_result_count"),
                    "search_results": platform.get("search_results", [])[:120],
                    "page_read_target": platform.get("page_read_target"),
                    "page_attempt_count": platform.get("page_attempt_count"),
                    "page_read_count": platform.get("page_read_count"),
                    "pages": platform.get("pages", [])[:50],
                    "qualified_page_count": platform.get("qualified_page_count"),
                    "supporting_page_count": platform.get("supporting_page_count"),
                    "recent_page_count": platform.get("recent_page_count"),
                    "background_page_count": platform.get("background_page_count"),
                    "undated_page_count": platform.get("undated_page_count"),
                    "discarded_page_count": platform.get("discarded_page_count"),
                    "visual_evidence": platform.get("visual_evidence", [])[
                        :TREND_MAX_IMAGES_PER_PLATFORM
                    ],
                    "visual_count": platform.get("visual_count"),
                    "accessed": platform.get("accessed"),
                    "access_status": platform.get("access_status"),
                    "evidence_status": platform.get("evidence_status"),
                    "evidence_snippets": platform.get("evidence_snippets", [])[:12],
                    "warnings": platform.get("warnings", [])[:8],
                }
                for platform in result.get("platforms", [])
                if isinstance(platform, dict)
            ],
            "warnings": result.get("warnings", [])[:16],
            "method": result.get("method"),
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
                    "comment_samples": video.get("comment_samples")
                    if isinstance(video.get("comment_samples"), list)
                    else [],
                    "snippet": compact_text(tiktok_video_text(video), 260),
                }
                for video in result.get("videos", [])[:12]
            ],
        }
    return result


def agent_tool_summary(tool_name: str, result: dict[str, Any]) -> str:
    if tool_name in AGENT_TOOL_CAPABILITY_REGISTRY:
        return AGENT_TOOL_CAPABILITY_REGISTRY.get(tool_name).summarize(result)
    if is_fastmoss_agent_tool(tool_name):
        return result.get("summary") or "FastMoss MCP returned structured evidence."
    if is_sif_agent_tool(tool_name):
        return "Sif MCP returned structured evidence."
    if is_sellersprite_agent_tool(tool_name):
        return result.get("summary") or "SellerSprite MCP returned structured evidence."
    if tool_name == "build_market_report_data":
        summary = (
            result.get("source_summary") if isinstance(result.get("source_summary"), dict) else {}
        )
        return (
            f"MarketReportData compiled from {summary.get('successful_tool_count', 0)} successful tool(s), "
            f"{len(result.get('market_kpis') or [])} KPI(s), {len(result.get('evidence_map') or [])} evidence item(s)."
        )
    if tool_name == "build_tiktok_new_product_report_data":
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        return (
            "TikTokNewProductReportData compiled "
            f"{summary.get('candidate_count', 0)} candidate(s) and "
            f"{summary.get('head_product_count', 0)} head product(s); "
            f"details {summary.get('detail_success_count', 0)}/"
            f"{summary.get('head_product_count', 0)}, trends "
            f"{summary.get('trend_success_count', 0)}/"
            f"{summary.get('head_product_count', 0)}."
        )
    if tool_name == "build_tiktok_bra_competitor_shop_report_data":
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        return (
            "TikTokBraCompetitorShopReportData compiled "
            f"{summary.get('candidate_count', 0)} competitor candidate(s) and "
            f"{summary.get('analyzed_shop_count', 0)} standard shop analysis row(s); "
            f"{summary.get('complete_shop_count', 0)} complete."
        )
    if tool_name == "build_trend_report_data":
        summary = (
            result.get("source_summary") if isinstance(result.get("source_summary"), dict) else {}
        )
        visual_coverage = (
            result.get("visual_coverage") if isinstance(result.get("visual_coverage"), dict) else {}
        )
        return (
            f"TrendReportData compiled from {summary.get('readable_pages', 0)} readable page(s), "
            f"{summary.get('recent_pages', 0)} within the requested window, "
            f"and {visual_coverage.get('selected_for_report', 0)} visual evidence item(s)."
        )
    if tool_name in {
        "build_competitor_product_report_data",
        "build_hot_product_pain_report_data",
    }:
        summary = result.get("source_summary") if isinstance(result.get("source_summary"), dict) else {}
        return (
            f"{result.get('schema_version') or 'ReportData'} compiled from "
            f"{summary.get('successful_tool_count', 0)} successful tool result(s) and "
            f"{len(result.get('evidence_sources') or [])} bounded evidence source(s)."
        )
    if tool_name == "build_product_design_brief_data":
        summary = (
            result.get("source_summary") if isinstance(result.get("source_summary"), dict) else {}
        )
        volume = result.get("data_volume") if isinstance(result.get("data_volume"), dict) else {}
        actual = volume.get("actual") if isinstance(volume.get("actual"), dict) else {}
        return (
            f"ProductDesignBriefData compiled from {summary.get('successful_tool_count', 0)} successful tool(s), "
            f"{actual.get('unique_products', 0)} product(s), {actual.get('reviews', 0)} review(s), "
            f"and {len(result.get('evidence_map') or [])} evidence item(s)."
        )
    if tool_name == "render_html_report":
        return f"Rendered HTML report: {result.get('title') or 'HTML report'}."
    if tool_name == "render_markdown_report":
        return f"Rendered Markdown report: {result.get('title') or 'Markdown report'}."
    if tool_name == "amazon_shelf":
        metrics = result.get("metrics") or {}
        return f"{metrics.get('products', 0)} Amazon products, {metrics.get('total_review_count', 0)} review/rating signals."
    if tool_name == "media_rankings":
        data_volume = result.get("data_volume") or {}
        return f"{data_volume.get('collected_articles', 0)} readable articles."
    if tool_name == "trend_platforms":
        coverage = result.get("coverage") if isinstance(result.get("coverage"), dict) else {}
        visual_coverage = (
            result.get("visual_coverage") if isinstance(result.get("visual_coverage"), dict) else {}
        )
        return (
            f"Accessed {coverage.get('accessed_platforms', 0)}/{coverage.get('required_platforms', 3)} "
            f"required trend platforms; read {coverage.get('readable_pages', 0)} effective public page(s), "
            f"including {coverage.get('recent_pages', 0)} within the requested window, and selected "
            f"{visual_coverage.get('selected_for_report', 0)} visual evidence item(s)."
        )
    if tool_name == "tiktok_social":
        metrics = result.get("metrics") or {}
        data_volume = result.get("data_volume") or {}
        return f"{metrics.get('videos', 0)} TikTok videos, {data_volume.get('comment_samples', 0)} comment samples."
    return "Tool completed."


def execute_agent_tool(tool_name: str, category: str, payload: dict[str, Any]) -> dict[str, Any]:
    if tool_name in AGENT_TOOL_CAPABILITY_REGISTRY:
        return AGENT_TOOL_CAPABILITY_REGISTRY.execute(tool_name, category, payload)
    started = time.time()
    tool_input = agent_tool_input_payload(tool_name, category, payload)
    catalog = agent_tool_catalog()
    if is_fastmoss_agent_tool(tool_name):
        return execute_fastmoss_agent_tool(
            tool_name,
            tool_input,
            bypass_cache=bool(payload.get("bypassCache")),
        )
    if is_sif_agent_tool(tool_name):
        return execute_sif_agent_tool(
            tool_name, tool_input, bypass_cache=bool(payload.get("bypassCache"))
        )
    if is_sellersprite_agent_tool(tool_name):
        return execute_sellersprite_agent_tool(
            tool_name,
            tool_input,
            bypass_cache=bool(payload.get("bypassCache")),
        )
    try:
        if tool_name == "amazon_shelf":
            raw = analyze_amazon_category(tool_input)
        elif tool_name == "media_rankings":
            discovery = discover_article_urls(tool_input)
            provided_urls, provided_warnings = extract_article_urls(
                {"urls": tool_input.get("urls") or []}
            )
            discovered_urls = [
                item.get("url") for item in discovery.get("candidates", []) if item.get("url")
            ]
            candidate_limit = max(1, min(int(tool_input.get("candidateLimit") or 8), 20))
            urls = list(dict.fromkeys([*provided_urls, *discovered_urls]))[:candidate_limit]
            raw = (
                analyze_articles(
                    {
                        "category": category,
                        "urls": urls,
                        "limit": len(urls),
                        "bypassCache": bool(tool_input.get("bypassCache")),
                    }
                )
                if urls
                else {
                    "category": category,
                    "generated_at": now_iso(),
                    "summary": {"collected_articles": 0},
                    "data_volume": {"collected_articles": 0},
                    "articles": [],
                    "warnings": discovery.get("warnings", [])
                    + ["No article URLs were selected for reading."],
                }
            )
            raw["discovery"] = discovery
            raw["provided_urls"] = provided_urls
            raw["warnings"] = list(
                dict.fromkeys([*(raw.get("warnings") or []), *provided_warnings])
            )
        elif tool_name == "trend_platforms":
            raw = crawl_trend_platforms(tool_input)
        elif tool_name == "tiktok_social":
            raw = analyze_tiktok_category(tool_input)
        elif tool_name == "build_market_report_data":
            raw = build_market_report_data(tool_input)
        elif tool_name == "build_tiktok_new_product_report_data":
            raw = build_tiktok_new_product_report_data(tool_input)
        elif tool_name == "build_tiktok_bra_competitor_shop_report_data":
            raw = build_tiktok_bra_competitor_shop_report_data(tool_input)
        elif tool_name == "build_trend_report_data":
            raw = build_trend_report_data(tool_input)
        elif tool_name == "build_competitor_product_report_data":
            raw = build_competitor_product_report_data(tool_input)
        elif tool_name == "build_hot_product_pain_report_data":
            raw = build_hot_product_pain_report_data(tool_input)
        elif tool_name == "build_product_design_brief_data":
            raw = build_product_design_brief_data(tool_input)
        elif tool_name == "render_html_report":
            raw = render_html_report_tool(tool_input)
        elif tool_name == "render_markdown_report":
            raw = render_markdown_report_tool(tool_input)
        else:
            raise ValueError(f"Unknown agent tool: {tool_name}")
        if tool_name in HTML_REPORT_DATA_BUILDERS and isinstance(raw, dict):
            raw = attach_metric_facts(raw)
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
    except MarkdownReportGenerationError as exc:
        return {
            "name": tool_name,
            "label": catalog.get(tool_name, {}).get("label", tool_name),
            "status": "error",
            "summary": str(exc),
            "duration_ms": int((time.time() - started) * 1000),
            "input": tool_input,
            "data": {"markdown_analysis": exc.analysis},
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


def agent_tool_recovery_defaults(tool_name: str) -> tuple[int, int, bool]:
    if tool_name in AGENT_TOOL_CAPABILITY_REGISTRY:
        recovery = AGENT_TOOL_CAPABILITY_REGISTRY.get(tool_name).recovery
        return (
            recovery.default_timeout_seconds,
            recovery.default_retry_attempts,
            recovery.retryable,
        )
    return 600, 2, True


def execute_agent_tool_with_timeout(
    tool_name: str, category: str, payload: dict[str, Any]
) -> dict[str, Any]:
    default_timeout, default_retries, capability_retryable = agent_tool_recovery_defaults(
        tool_name
    )
    timeout_value = payload.get("agentToolTimeoutSeconds")
    retry_value = payload.get("agentToolRetryAttempts")
    timeout_seconds = min(
        max(int(default_timeout if timeout_value is None else timeout_value), 30), 1200
    )
    configured_retries = min(
        max(int(default_retries if retry_value is None else retry_value), 0), 3
    )
    if not capability_retryable:
        configured_retries = 0
    if tool_name in {"render_html_report", "render_markdown_report"} or tool_name.startswith(
        "build_"
    ):
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
    retryable = final_assessment.retryable and len(attempts) <= retry_limit_for_assessment(
        final_assessment, configured_retries
    )
    if final_assessment.retryable and len(attempts) > retry_limit_for_assessment(
        final_assessment, configured_retries
    ):
        final_status = final_status_after_exhaustion(final_assessment)
        retryable = False
    if final_status in SUCCESS_TOOL_STATUSES and len(attempts) > 1:
        final_result["summary"] = (
            f"{final_result.get('summary') or final_assessment.reason} Recovered after {len(attempts)} attempts."
        )
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


def fallback_agent_artifact(
    prompt: str, mode: str, category: str, tool_results: list[dict[str, Any]]
) -> dict[str, Any]:
    ok_tools = [tool for tool in tool_results if tool.get("status") in SUCCESS_TOOL_STATUSES]
    findings = [f"{tool.get('label')}: {tool.get('summary')}" for tool in ok_tools]
    failed_tools = [
        tool for tool in tool_results if tool.get("status") not in SUCCESS_TOOL_STATUSES
    ]
    return {
        "title": f"{category} {'爆款竞品分析' if mode == 'competitor' else '市场洞察'}",
        "executive_summary": "已完成工具调用；当前 LLM 不可用，因此先返回基于工具结果的保守摘要。",
        "kpis": kpi_from_tool_results(tool_results),
        "market_basics": findings[:4] or ["暂无成功的市场级工具结果。"],
        "price_and_margin": [
            "需要结合 SellerSprite/Sif 价格、销量代理、利润字段或 Amazon 货架样本继续判断。"
        ],
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
        return '<p class="empty">暂无。</p>'
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
    amazon_metrics = (
        amazon.get("data", {}).get("metrics", {}) if isinstance(amazon.get("data"), dict) else {}
    )
    reddit = first_tool_result(tool_results, "reddit_voc")
    reddit_coverage = (
        reddit.get("data", {}).get("coverage", {}) if isinstance(reddit.get("data"), dict) else {}
    )
    tiktok = first_tool_result(tool_results, "tiktok_social")
    tiktok_metrics = (
        tiktok.get("data", {}).get("metrics", {}) if isinstance(tiktok.get("data"), dict) else {}
    )
    seller_tools = [
        tool for tool in successful if str(tool.get("name") or "").startswith("sellersprite_")
    ]
    sif_tools = [tool for tool in successful if str(tool.get("name") or "").startswith("sif_")]
    kpis = [
        {"label": "成功数据源", "value": str(len(successful)), "change": "", "source": "Execution"},
        {"label": "Sif 信号", "value": str(len(sif_tools)), "change": "", "source": "Sif MCP"},
        {
            "label": "SellerSprite 信号",
            "value": str(len(seller_tools)),
            "change": "",
            "source": "SellerSprite MCP",
        },
    ]
    if amazon_metrics.get("products"):
        kpis.append(
            {
                "label": "Amazon 商品样本",
                "value": html_number(amazon_metrics.get("products")),
                "change": "",
                "source": "Amazon",
            }
        )
    if amazon_metrics.get("total_review_count"):
        kpis.append(
            {
                "label": "Review/Rating 信号",
                "value": html_number(amazon_metrics.get("total_review_count")),
                "change": "",
                "source": "Amazon",
            }
        )
    if reddit_coverage.get("posts"):
        kpis.append(
            {
                "label": "Reddit 帖子",
                "value": html_number(reddit_coverage.get("posts")),
                "change": "",
                "source": "Reddit",
            }
        )
    if tiktok_metrics.get("videos"):
        kpis.append(
            {
                "label": "TikTok 视频",
                "value": html_number(tiktok_metrics.get("videos")),
                "change": "",
                "source": "TikTok",
            }
        )
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
    if name == "trend_platforms":
        return "WGSN / 蝶讯 / Pinterest"
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
        if any(term in joined_keys for term in include_terms) and not any(
            term in joined_keys for term in exclude_terms
        ):
            scalar_items = {
                str(key): item for key, item in value.items() if market_report_scalar(item)
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


def market_report_metric_items(
    value: Any, evidence_id: str, limit: int = 10, depth: int = 0
) -> list[dict[str, Any]]:
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
            items.extend(
                market_report_metric_items(raw_value, evidence_id, limit - len(items), depth + 1)
            )
    elif isinstance(value, list):
        for raw_value in value[:20]:
            if len(items) >= limit:
                break
            items.extend(
                market_report_metric_items(raw_value, evidence_id, limit - len(items), depth + 1)
            )
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
        for row in market_report_rows_from_nested(
            data, include_terms=include_terms, limit=limit - len(rows)
        ):
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
    return {str(key): item for key, item in value.items() if market_report_scalar(item)}


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
            if (
                str(tool.get("name") or "") != tool_name
                or tool.get("status") not in SUCCESS_TOOL_STATUSES
            ):
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
                            candidates.extend(
                                market_report_scalar_row(item) for item in nested_items
                            )
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
                row = {
                    "evidence_id": evidence["id"],
                    "source": evidence["source"],
                    "source_tool": evidence["tool"],
                    **candidate,
                }
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
        "sellersprite_keyword_research",
        "sellersprite_keyword_research_trends",
    ):
        for tool, evidence in pairs:
            if (
                str(tool.get("name") or "") != tool_name
                or tool.get("status") not in SUCCESS_TOOL_STATUSES
            ):
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
                    if tool_name
                    in {
                        "sellersprite_aba_research_weekly",
                        "sellersprite_keyword_research",
                        "sellersprite_keyword_research_trends",
                    }
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
                keyword = (
                    row.get("keyword")
                    or row.get("query")
                    or row.get("searchTerm")
                    or row.get("term")
                )
                if not keyword or not market_report_keyword_is_relevant(keyword, category):
                    continue
                identity = " ".join(str(keyword).lower().split())
                existing = rows_by_keyword.setdefault(
                    identity,
                    {
                        "evidence_id": evidence["id"],
                        "source": evidence["source"],
                        "source_tool": evidence["tool"],
                        "keyword": str(keyword),
                    },
                )
                for key, item in row.items():
                    if item not in (None, "") and existing.get(key) in (None, ""):
                        existing[key] = item
                if len(rows_by_keyword) >= limit:
                    break
    return list(rows_by_keyword.values())[:limit]


def market_report_user_voice(
    tool_results: list[dict[str, Any]], evidence_items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    voices: list[dict[str, Any]] = []
    for tool, evidence in zip(tool_results, evidence_items, strict=False):
        name = str(tool.get("name") or "")
        if tool.get("status") not in SUCCESS_TOOL_STATUSES or name not in {
            "reddit_voc",
            "tiktok_social",
            "media_rankings",
            "sellersprite_review",
        }:
            continue
        data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
        if isinstance(data.get("pain_points"), list):
            for item in data["pain_points"][:8]:
                text = item.get("label") if isinstance(item, dict) else item
                if text:
                    voices.append(
                        {
                            "theme": str(text),
                            "source": evidence["source"],
                            "evidence_id": evidence["id"],
                        }
                    )
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
            for article in (
                data.get("articles", [])[:6] if isinstance(data.get("articles"), list) else []
            ):
                if not isinstance(article, dict):
                    continue
                signals = (
                    article.get("product_signals")
                    if isinstance(article.get("product_signals"), list)
                    else []
                )
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
        if name == "sellersprite_review":
            review_payload = market_report_primary_tool_payload(tool)
            review_items: list[dict[str, Any]] = []
            if isinstance(review_payload, list):
                review_items = [item for item in review_payload if isinstance(item, dict)]
            elif isinstance(review_payload, dict):
                raw_items = market_report_preferred_value(review_payload, "items")
                if isinstance(raw_items, list):
                    review_items = [item for item in raw_items if isinstance(item, dict)]
            for review in review_items[:24]:
                review_text = (
                    review.get("content")
                    or review.get("body")
                    or review.get("text")
                    or review.get("title")
                )
                if not review_text:
                    continue
                rating = market_report_float(
                    review.get("star") or review.get("rating") or review.get("score")
                )
                voices.append(
                    {
                        "theme": compact_text(str(review_text), 320),
                        "rating": rating,
                        "review_group": (
                            "low_star"
                            if rating is not None and rating <= 2
                            else "tradeoff"
                            if rating == 3
                            else "high_star"
                            if rating is not None and rating >= 4
                            else "unknown"
                        ),
                        "asin": review.get("asin") or review.get("productAsin"),
                        "date": review.get("date") or review.get("reviewDate"),
                        "source": evidence["source"],
                        "source_tool": evidence["tool"],
                        "evidence_id": evidence["id"],
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


def market_report_first_present_pair(
    row: dict[str, Any], keys: tuple[str, ...]
) -> tuple[str, Any] | None:
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
    keyword_rows = (
        report_data.get("keyword_trends")
        if isinstance(report_data.get("keyword_trends"), list)
        else []
    )
    category_rows = (
        report_data.get("category_benchmark")
        if isinstance(report_data.get("category_benchmark"), list)
        else []
    )
    price_rows = (
        report_data.get("price_distribution")
        if isinstance(report_data.get("price_distribution"), list)
        else []
    )
    brand_rows = (
        report_data.get("brand_competition")
        if isinstance(report_data.get("brand_competition"), list)
        else []
    )
    product_rows = (
        report_data.get("top_products") if isinstance(report_data.get("top_products"), list) else []
    )
    keyword_signal = market_report_best_signal(
        keyword_rows,
        label_keys=("keyword", "query", "searchTerm", "term", "root"),
        value_keys=(
            "search_volume",
            "searchVolume",
            "volume",
            "searches",
            "demand",
            "search_count",
        ),
    ) or market_report_best_signal(
        keyword_rows,
        label_keys=("keyword", "query", "searchTerm", "term", "root"),
        value_keys=("rank", "abaRank", "ranking", "position"),
        prefer_low=True,
    )
    category_signal = market_report_best_signal(
        category_rows,
        label_keys=("category", "node", "department", "path", "market", "subcategory"),
        value_keys=(
            "totalUnits",
            "monthly_sales",
            "monthlySales",
            "sales",
            "totalRevenue",
            "monthly_revenue",
            "monthlyRevenue",
            "revenue",
            "volume",
        ),
    )
    price_signal = market_report_best_signal(
        price_rows,
        label_keys=("priceRange", "range", "price", "label", "bucket"),
        value_keys=(
            "unitsRatio",
            "salesRatio",
            "share",
            "units",
            "sales",
            "revenue",
            "count",
            "value",
            "volume",
        ),
    )
    brand_signal = market_report_best_signal(
        brand_rows,
        label_keys=("brand", "brandName", "seller", "merchant", "name"),
        value_keys=(
            "totalUnitsRatio",
            "unitsRatio",
            "share",
            "totalUnits",
            "sales",
            "revenue",
            "count",
            "value",
            "volume",
        ),
    )
    product_signal = market_report_best_signal(
        product_rows,
        label_keys=("asin", "product", "title", "name"),
        value_keys=(
            "totalUnits",
            "monthly_orders",
            "units",
            "sales",
            "totalRevenue",
            "revenue",
            "reviews",
            "review_count",
            "rating_count",
            "value",
        ),
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
    source_summary = (
        report_data.get("source_summary")
        if isinstance(report_data.get("source_summary"), dict)
        else {}
    )
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
        value_keys=(
            "search_volume",
            "searchVolume",
            "volume",
            "searches",
            "demand",
            "rank",
            "abaRank",
        ),
        limit=10,
    )
    if keyword_points:
        charts.append(
            {
                "id": "keyword_volume",
                "title": "关键词需求/排名信号",
                "type": "bar",
                "data": keyword_points,
            }
        )
    category_points = market_report_chart_points_from_rows(
        report_data.get("category_benchmark"),
        label_keys=("category", "node", "department", "path", "market", "subcategory"),
        value_keys=(
            "monthly_sales",
            "monthlySales",
            "sales",
            "monthly_revenue",
            "monthlyRevenue",
            "revenue",
            "volume",
        ),
        limit=10,
    )
    if category_points:
        charts.append(
            {
                "id": "category_benchmark",
                "title": "类目对标量化信号",
                "type": "bar",
                "data": category_points,
            }
        )
    brands = (
        report_data.get("brand_competition")
        if isinstance(report_data.get("brand_competition"), list)
        else []
    )
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
        charts.append(
            {
                "id": "brand_competition",
                "title": "品牌竞争信号",
                "type": "bar",
                "data": brand_points,
            }
        )
    price_rows = (
        report_data.get("price_distribution")
        if isinstance(report_data.get("price_distribution"), list)
        else []
    )
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
        charts.append(
            {"id": "price_distribution", "title": "价格带分布", "type": "bar", "data": price_points}
        )
    opportunities = (
        report_data.get("opportunity_pool")
        if isinstance(report_data.get("opportunity_pool"), list)
        else []
    )
    if opportunities:
        charts.append(
            {
                "id": "opportunity_priority",
                "title": "机会优先级矩阵",
                "type": "matrix",
                "data": [
                    {
                        "label": str(
                            item.get("name") or item.get("opportunity_name") or f"机会 {index + 1}"
                        ),
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
    demand_phrase = market_report_signal_phrase(
        signals.get("keyword"), "暂未抽取到可命名的关键词需求锚点"
    )
    category_phrase = market_report_signal_phrase(signals.get("category"), "类目规模字段不足")
    price_phrase = market_report_signal_phrase(signals.get("price"), "价格带承接字段不足")
    brand_phrase = market_report_signal_phrase(signals.get("brand"), "品牌集中度字段不足")
    product_phrase = market_report_signal_phrase(signals.get("product"), "Top 商品字段不足")
    coverage = (
        report_data.get("analysis_coverage")
        if isinstance(report_data.get("analysis_coverage"), dict)
        else {}
    )
    coverage_summary = coverage.get("summary") if isinstance(coverage.get("summary"), dict) else {}
    coverage_dimensions = (
        coverage.get("dimensions") if isinstance(coverage.get("dimensions"), list) else []
    )
    missing_p0 = [
        str(item.get("name") or item.get("dimension_id") or "未知维度")
        for item in coverage_dimensions
        if isinstance(item, dict)
        and item.get("priority") == "P0"
        and item.get("status") != "covered"
    ]
    deduplication = (
        report_data.get("deduplication")
        if isinstance(report_data.get("deduplication"), dict)
        else {}
    )
    dedup_applied = bool(deduplication.get("applied"))
    dedup_scope = str(deduplication.get("scope") or "")
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
            "id": "analysis_coverage",
            "title": "分析维度与数据口径",
            "tone": "evidence",
            "summary": (
                f"P0 市场分析维度已覆盖 {coverage_summary.get('p0_covered', 0)}/"
                f"{coverage_summary.get('p0_total', 0)}；"
                f"{'商品身份归并已执行，其他数据仍为透传' if dedup_applied and dedup_scope == 'product_identity_only' else '通用数据去重仅预留接口、尚未执行'}。"
            ),
            "bullets": [
                "覆盖矩阵回答的是本轮证据能否支持具体市场问题，不代表调用工具越多，报告就越可靠。",
                (
                    "待补维度：" + "、".join(missing_p0[:8])
                    if missing_p0
                    else "P0 核心维度均已有对应工具证据。"
                ),
                (
                    "商品身份审计已执行；仅携带 family_id 的 M09、M17 和文胸属性可使用唯一商品家族数，其他数据仍为透传。"
                    if dedup_applied and dedup_scope == "product_identity_only"
                    else "当前不得把原始行数表述为去重后的唯一关键词、唯一商品或唯一市场总量。"
                ),
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
            "evidence_ids": market_report_evidence_ids_from_rows(
                report_data.get("keyword_trends"), 4
            )
            or evidence_ids,
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
            "evidence_ids": market_report_evidence_ids_from_rows(
                [
                    *(report_data.get("brand_competition") or []),
                    *(report_data.get("top_products") or []),
                ],
                4,
            )
            or evidence_ids,
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
    competition_phrase = market_report_signal_phrase(
        signals.get("brand") or signals.get("product"), "竞争锚点待补强"
    )
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
    keyword_score = min(
        95,
        48
        + len(report_data.get("keyword_trends") or []) * 3
        + (12 if signals.get("keyword") else 0),
    )
    competition_score = min(
        92,
        40
        + (
            len(report_data.get("brand_competition") or [])
            + len(report_data.get("top_products") or [])
        )
        * 2
        + (12 if signals.get("brand") or signals.get("product") else 0),
    )
    price_score = min(
        90,
        36
        + len(report_data.get("price_distribution") or []) * 4
        + (14 if signals.get("price") else 0),
    )
    gap_penalty = min(35, len(report_data.get("data_gaps") or []) * 5)
    readiness_score = max(
        30, min(95, int((keyword_score + competition_score + price_score) / 3) - gap_penalty)
    )
    return [
        {
            "dimension": "需求强度",
            "score": keyword_score,
            "signal": market_report_signal_phrase(
                signals.get("keyword"), "关键词/ABA/搜索历史信号不足"
            ),
            "recommendation": "优先确认核心词和长尾词根能否被 Hsia 产品结构与 Listing 语言承接。",
        },
        {
            "dimension": "竞争可进入性",
            "score": competition_score,
            "signal": market_report_signal_phrase(
                signals.get("brand") or signals.get("product"),
                "品牌集中度、Top ASIN、商品集中度不足",
            ),
            "recommendation": "拆解头部品牌结构、评论门槛和流量份额，寻找非同质化切口。",
        },
        {
            "dimension": "价格/利润空间",
            "score": price_score,
            "signal": market_report_signal_phrase(
                signals.get("price"), "价格分布、销量/销售额、利润相关字段不足"
            ),
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
    analysis_sections = (
        report_data.get("analysis_sections")
        if isinstance(report_data.get("analysis_sections"), list)
        else []
    )
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
    opportunity_pool = (
        report_data.get("opportunity_pool")
        if isinstance(report_data.get("opportunity_pool"), list)
        else []
    )
    data_gaps = (
        report_data.get("data_gaps") if isinstance(report_data.get("data_gaps"), list) else []
    )
    kpis = (
        report_data.get("market_kpis") if isinstance(report_data.get("market_kpis"), list) else []
    )
    return {
        "title": report_data.get("title") or f"{report_data.get('category') or '市场'}洞察报告",
        "executive_summary": report_data.get("executive_summary")
        or "已完成 MarketReportData 编译，报告基于本轮工具证据生成。",
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


def html_report_analysis_contract(skill_markdown: Any) -> str:
    text = str(skill_markdown or "")
    sections: list[str] = []
    for heading in (
        "What It Does",
        "Recommended Tool Use",
        "Analysis Dimension Coverage",
        "VoM–VoS Decision Logic",
        "Evidence Contract",
        "Output Rules",
    ):
        content = markdown_section(text, heading)
        if content:
            sections.append(f"## {heading}\n{content}")
    return compact_text("\n\n".join(sections), 16000)


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
                    compact_text(str(child), 180)
                    if not isinstance(child, int | float | bool)
                    else child
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


def market_report_compact_product_reviews(
    value: Any,
    *,
    product_limit: int = 12,
    review_limit: int = 30,
) -> list[dict[str, Any]]:
    """Preserve bounded review evidence as structured rows for VOC synthesis."""

    if not isinstance(value, list):
        return []
    compacted: list[dict[str, Any]] = []
    for item in value[:product_limit]:
        if not isinstance(item, dict):
            continue
        record = {
            key: item.get(key)
            for key in (
                "product_id",
                "sample_size",
                "text_sample_size",
                "rating_only_sample_size",
                "total_review_count",
                "evidence_id",
                "evidence_ids",
                "retrieval_scopes",
                "source_tool",
            )
            if key in item
        }
        reviews: list[dict[str, Any]] = []
        raw_reviews = item.get("reviews")
        if isinstance(raw_reviews, list):
            for review in raw_reviews[:review_limit]:
                if not isinstance(review, dict):
                    continue
                reviews.append(
                    {
                        key: (
                            compact_text(raw_value, 600)
                            if isinstance(raw_value, str)
                            else raw_value
                        )
                        for key in (
                            "product_id",
                            "review_id",
                            "rating",
                            "date",
                            "content",
                            "sku",
                            "like_count",
                            "media_urls",
                            "evidence_id",
                            "source_page",
                            "time_range_days",
                        )
                        if (raw_value := review.get(key)) is not None
                    }
                )
        record["reviews"] = reviews
        compacted.append(record)
    return compacted


def market_report_compact_chart_value(value: Any, *, depth: int = 0) -> Any:
    """Keep chart data structured while bounding the LLM context size."""

    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, str):
        return compact_text(value, 280)
    if isinstance(value, list):
        limit = 16 if depth == 0 else 8
        return [market_report_compact_chart_value(item, depth=depth + 1) for item in value[:limit]]
    if isinstance(value, dict):
        if depth >= 4:
            return compact_text(str(value), 240)
        return {
            str(key): market_report_compact_chart_value(child, depth=depth + 1)
            for key, child in list(value.items())[:20]
        }
    return compact_text(str(value), 240)


def market_report_llm_context(report_data: dict[str, Any]) -> dict[str, Any]:
    chart_specs = []
    for chart in (
        report_data.get("chart_specs", [])
        if isinstance(report_data.get("chart_specs"), list)
        else []
    ):
        if not isinstance(chart, dict):
            continue
        chart_specs.append(
            {
                "id": chart.get("id"),
                "dimension_id": chart.get("dimension_id"),
                "market_question": chart.get("market_question"),
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
                "evidence_ids": chart.get("evidence_ids") or [],
                "quality_status": chart.get("quality_status"),
                "field_semantics": market_report_compact_chart_value(
                    chart.get("field_semantics")
                ),
                "placement": market_report_compact_chart_value(
                    chart.get("placement")
                ),
                "sample_contract": market_report_compact_chart_value(
                    chart.get("sample_contract")
                ),
                "coverage_summary": market_report_compact_chart_value(
                    chart.get("coverage_summary")
                ),
                "rendering_contract": market_report_compact_chart_value(
                    chart.get("rendering_contract")
                ),
                "data": market_report_compact_chart_value(chart.get("data")),
            }
        )
    methodology_context = [
        {
            "tool": item.get("tool"),
            "role": "methodology_only",
            "mcp_description": compact_text(str(item.get("mcp_description") or ""), 640),
            "analysis_dimensions": item.get("analysis_dimensions") or [],
            "market_questions": item.get("market_questions") or [],
            "allowed_conclusions": item.get("allowed_conclusions") or [],
            "limitations": item.get("limitations") or [],
        }
        for item in (
            report_data.get("tool_methodology")
            if isinstance(report_data.get("tool_methodology"), list)
            else []
        )
        if isinstance(item, dict)
    ]
    return {
        "schema_version": report_data.get("schema_version"),
        "title": report_data.get("title"),
        "brand": report_data.get("brand"),
        "marketplace": report_data.get("marketplace"),
        "category": report_data.get("category"),
        "category_node_id": report_data.get("category_node_id"),
        "time_range": report_data.get("time_range"),
        "generated_at": report_data.get("generated_at"),
        "executive_summary": report_data.get("executive_summary"),
        "market_kpis": market_report_compact_items(report_data.get("market_kpis"), limit=14),
        "keyword_trends": market_report_compact_items(report_data.get("keyword_trends"), limit=12),
        "keyword_opportunities": market_report_compact_items(
            report_data.get("keyword_opportunities"), limit=16
        ),
        "keyword_competition": market_report_compact_items(
            report_data.get("keyword_competition"), limit=16
        ),
        "demand_trend": market_report_compact_items(report_data.get("demand_trend"), limit=14),
        "node_demand_quality": market_report_compact_items(
            report_data.get("node_demand_quality"), limit=8
        ),
        "category_benchmark": market_report_compact_items(
            report_data.get("category_benchmark"), limit=10
        ),
        "market_statistics": market_report_compact_items(
            report_data.get("market_statistics"), limit=12
        ),
        "top_products": market_report_compact_items(report_data.get("top_products"), limit=10),
        "bra_attribute_distribution": report_data.get("bra_attribute_distribution")
        if isinstance(report_data.get("bra_attribute_distribution"), dict)
        else {},
        "brand_competition": market_report_compact_items(
            report_data.get("brand_competition"), limit=10
        ),
        "seller_competition": market_report_compact_items(
            report_data.get("seller_competition"), limit=10
        ),
        "price_distribution": market_report_compact_items(
            report_data.get("price_distribution"), limit=10
        ),
        "rating_distribution": market_report_compact_items(
            report_data.get("rating_distribution"), limit=10
        ),
        "ratings_count_distribution": market_report_compact_items(
            report_data.get("ratings_count_distribution"), limit=10
        ),
        "listing_date_distribution": market_report_compact_items(
            report_data.get("listing_date_distribution"), limit=10
        ),
        "listing_trend_distribution": market_report_compact_items(
            report_data.get("listing_trend_distribution"), limit=12
        ),
        "seller_type_distribution": market_report_compact_items(
            report_data.get("seller_type_distribution"), limit=10
        ),
        "seller_country_distribution": market_report_compact_items(
            report_data.get("seller_country_distribution"), limit=10
        ),
        "content_distribution": market_report_compact_items(
            report_data.get("content_distribution"), limit=10
        ),
        "period_contract": report_data.get("period_contract")
        if isinstance(report_data.get("period_contract"), dict)
        else {},
        "research_boundary": report_data.get("research_boundary")
        if isinstance(report_data.get("research_boundary"), dict)
        else {},
        "segment_query_summary": report_data.get("segment_query_summary")
        if isinstance(report_data.get("segment_query_summary"), dict)
        else {},
        "fastmoss_segment_products": market_report_compact_items(
            report_data.get("fastmoss_segment_products"), limit=24
        ),
        "fastmoss_proxy_category_products": market_report_compact_items(
            report_data.get("fastmoss_proxy_category_products"), limit=12
        ),
        "fastmoss_category_trend": market_report_compact_items(
            report_data.get("fastmoss_category_trend"), limit=16
        ),
        "fastmoss_creator_matrix": market_report_compact_items(
            report_data.get("fastmoss_creator_matrix"), limit=16
        ),
        "fastmoss_top_creators": market_report_compact_items(
            report_data.get("fastmoss_top_creators"), limit=12
        ),
        "fastmoss_top_shops": market_report_compact_items(
            report_data.get("fastmoss_top_shops"), limit=12
        ),
        "fastmoss_product_trends": market_report_compact_items(
            report_data.get("fastmoss_product_trends"), limit=12
        ),
        "fastmoss_product_creators": market_report_compact_items(
            report_data.get("fastmoss_product_creators"), limit=12
        ),
        "fastmoss_product_videos": market_report_compact_items(
            report_data.get("fastmoss_product_videos"), limit=12
        ),
        "fastmoss_channel_attribution": market_report_compact_items(
            report_data.get("fastmoss_channel_attribution"),
            limit=12,
        ),
        "fastmoss_product_reviews": market_report_compact_product_reviews(
            report_data.get("fastmoss_product_reviews"),
            product_limit=12,
            review_limit=30,
        ),
        "external_demand_trend": market_report_compact_items(
            report_data.get("external_demand_trend"), limit=12
        ),
        "product_universe": market_report_compact_items(
            report_data.get("product_universe"), limit=20
        ),
        "review_pain_points": market_report_compact_items(
            report_data.get("review_pain_points"), limit=18
        ),
        "insight_narrative": html_report_insight_narrative_context(
            report_data.get("insight_narrative") or {}
        ),
        "insights": market_report_compact_items(report_data.get("insights"), limit=10),
        "opportunity_pool": market_report_compact_items(
            report_data.get("opportunity_pool"), limit=10
        ),
        "chart_specs": chart_specs,
        "non_chart_presentations": html_report_compact_value(
            report_data.get("non_chart_presentations") or []
        ),
        "summary_chart_ids": report_data.get("summary_chart_ids")
        if isinstance(report_data.get("summary_chart_ids"), list)
        else [],
        "tool_methodology": methodology_context,
        "deduplication": report_data.get("deduplication")
        if isinstance(report_data.get("deduplication"), dict)
        else {},
        "metric_facts": market_report_compact_items(
            report_data.get("metric_facts"), limit=80
        ),
        "derived_metrics": market_report_compact_items(
            report_data.get("derived_metrics"), limit=24
        ),
        "metric_analysis": market_report_compact_chart_value(
            report_data.get("metric_analysis")
        ),
        "evidence_map": market_report_compact_items(report_data.get("evidence_map"), limit=32),
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


SUMMARY_CHART_SINGLE_COLUMN_MARKER = "insight-agent-summary-chart-single-column"
SUMMARY_CHART_SINGLE_COLUMN_CSS = f"""
/* {SUMMARY_CHART_SINGLE_COLUMN_MARKER} */
.summary-charts-single-column .summary-chart-layout,
.summary-charts-single-column .chart-grid,
.summary-charts-single-column .summary-chart-grid {{
  display: grid !important;
  grid-template-columns: minmax(0, 1fr) !important;
  grid-auto-flow: row !important;
  gap: 24px !important;
}}
.summary-charts-single-column .summary-chart-layout > figure[data-chart-id],
.summary-charts-single-column .chart-grid > figure[data-chart-id],
.summary-charts-single-column .summary-chart-grid > figure[data-chart-id] {{
  grid-column: 1 / -1 !important;
  width: 100% !important;
  max-width: none !important;
  min-width: 0 !important;
  margin-left: 0 !important;
  margin-right: 0 !important;
}}
.summary-charts-single-column figure[data-chart-id] svg {{
  display: block !important;
  width: 100% !important;
  max-width: none !important;
  height: auto !important;
}}
"""


def html_opening_tag_with_class(opening_tag: str, class_name: str) -> str:
    class_match = re.search(
        r"\bclass\s*=\s*(['\"])(.*?)\1",
        opening_tag,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if class_match:
        existing = class_match.group(2).split()
        if class_name in existing:
            return opening_tag
        classes = " ".join([*existing, class_name])
        return opening_tag[: class_match.start(2)] + classes + opening_tag[class_match.end(2) :]
    close_index = opening_tag.rfind(">")
    if close_index < 0:
        return opening_tag
    return opening_tag[:close_index] + f' class="{class_name}"' + opening_tag[close_index:]


def html_opening_tag_with_attribute(opening_tag: str, name: str, value: str) -> str:
    attribute_match = re.search(
        rf"\b{re.escape(name)}\s*=\s*(['\"])(.*?)\1",
        opening_tag,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if attribute_match:
        return (
            opening_tag[: attribute_match.start(2)] + value + opening_tag[attribute_match.end(2) :]
        )
    close_index = opening_tag.rfind(">")
    if close_index < 0:
        return opening_tag
    return opening_tag[:close_index] + f' {name}="{value}"' + opening_tag[close_index:]


def align_summary_svg_edge_labels(section_html: str) -> str:
    """Keep labels near the right edge inside each summary SVG viewBox."""

    svg_pattern = re.compile(r"<svg\b[^>]*>.*?</svg\s*>", flags=re.IGNORECASE | re.DOTALL)

    def align_svg(match: re.Match[str]) -> str:
        svg_markup = match.group(0)
        opening_end = svg_markup.find(">") + 1
        opening_tag = svg_markup[:opening_end]
        viewbox_match = re.search(
            r"\bviewBox\s*=\s*(['\"])(.*?)\1",
            opening_tag,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not viewbox_match:
            return svg_markup
        try:
            min_x, _, width, _ = [float(part) for part in viewbox_match.group(2).split()]
        except (TypeError, ValueError):
            return svg_markup
        if width <= 0:
            return svg_markup
        threshold = min_x + width * 0.94
        safe_x = min_x + width - max(4.0, width * 0.014)

        def align_text(text_match: re.Match[str]) -> str:
            text_tag = text_match.group(0)
            x_match = re.search(
                r"\bx\s*=\s*(['\"])(-?\d+(?:\.\d+)?)\1",
                text_tag,
                flags=re.IGNORECASE,
            )
            if not x_match or float(x_match.group(2)) < threshold:
                return text_tag
            updated = html_opening_tag_with_attribute(text_tag, "x", f"{safe_x:g}")
            return html_opening_tag_with_attribute(updated, "text-anchor", "end")

        return re.sub(r"<text\b[^>]*>", align_text, svg_markup, flags=re.IGNORECASE | re.DOTALL)

    return svg_pattern.sub(align_svg, section_html)


def enforce_summary_chart_single_column(html_content: str) -> str:
    """Keep a legacy core-chart overview full-width when an older template still emits one."""

    if not html_content or SUMMARY_CHART_SINGLE_COLUMN_MARKER in html_content:
        return html_content
    heading_pattern = re.compile(
        r"<h([1-6])\b[^>]*>(?:(?!</h\1\s*>).)*核心图表速览(?:(?!</h\1\s*>).)*</h\1\s*>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    heading = heading_pattern.search(html_content)
    if not heading:
        return html_content
    section_matches = list(
        re.finditer(
            r"<section\b[^>]*>", html_content[: heading.start()], flags=re.IGNORECASE | re.DOTALL
        )
    )
    if not section_matches:
        return html_content
    section_open = section_matches[-1]
    prior_section_close = html_content.rfind("</section", section_open.end(), heading.start())
    if prior_section_close >= 0:
        return html_content

    section_tag = html_opening_tag_with_class(section_open.group(0), "summary-charts-single-column")
    result = html_content[: section_open.start()] + section_tag + html_content[section_open.end() :]
    heading = heading_pattern.search(result, section_open.start() + len(section_tag))
    if not heading:
        return html_content
    section_close = re.search(r"</section\s*>", result[heading.end() :], flags=re.IGNORECASE)
    if section_close:
        section_end = heading.end() + section_close.start()
    else:
        section_end = len(result)
    first_figure = re.search(
        r"<figure\b[^>]*\bdata-chart-id\s*=",
        result[heading.end() : section_end],
        flags=re.IGNORECASE | re.DOTALL,
    )
    if first_figure:
        figure_start = heading.end() + first_figure.start()
        container_matches = list(
            re.finditer(
                r"<div\b[^>]*>",
                result[heading.end() : figure_start],
                flags=re.IGNORECASE | re.DOTALL,
            )
        )
        if container_matches:
            container = container_matches[-1]
            container_start = heading.end() + container.start()
            container_end = heading.end() + container.end()
            container_tag = html_opening_tag_with_class(container.group(0), "summary-chart-layout")
            result = result[:container_start] + container_tag + result[container_end:]

    heading = heading_pattern.search(result, section_open.start())
    if heading:
        summary_section_start = result.lower().rfind("<section", 0, heading.start())
        summary_section_close = re.search(
            r"</section\s*>", result[heading.end() :], flags=re.IGNORECASE
        )
        if summary_section_start >= 0 and summary_section_close:
            summary_section_end = heading.end() + summary_section_close.end()
            section_html = result[summary_section_start:summary_section_end]
            aligned_section = align_summary_svg_edge_labels(section_html)
            result = result[:summary_section_start] + aligned_section + result[summary_section_end:]

    style_close = re.search(r"</style\s*>", result, flags=re.IGNORECASE)
    if not style_close:
        return html_content
    return (
        result[: style_close.start()]
        + SUMMARY_CHART_SINGLE_COLUMN_CSS
        + result[style_close.start() :]
    )


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


class TrendVisualMarkupInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.figure_stack: list[str] = []
        self.images_by_visual_id: dict[str, list[str]] = defaultdict(list)
        self.all_image_sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        attr_map = {str(key).lower(): str(value or "") for key, value in attrs}
        if normalized_tag == "figure":
            self.figure_stack.append(attr_map.get("data-visual-id", ""))
            return
        if normalized_tag != "img":
            return
        source = attr_map.get("src", "").strip()
        if not source:
            return
        self.all_image_sources.append(source)
        visual_id = next((item for item in reversed(self.figure_stack) if item), "")
        if visual_id:
            self.images_by_visual_id[visual_id].append(source)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "figure" and self.figure_stack:
            self.figure_stack.pop()


def inspect_trend_visual_markup(html_content: str) -> TrendVisualMarkupInspector:
    inspector = TrendVisualMarkupInspector()
    inspector.feed(html_content)
    return inspector


TREND_VISUAL_ATLAS_CSS = """
.trend-visual-atlas{margin:40px auto;max-width:1200px;padding:0 24px}
.trend-visual-atlas__grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px}
.trend-visual-card{margin:0;border:1px solid rgba(33,33,33,.14);background:#fff;border-radius:14px;overflow:hidden}
.trend-visual-card a{display:block;color:inherit;text-decoration:none}
.trend-visual-card img{display:block;width:100%;aspect-ratio:4/3;object-fit:cover;background:#eee}
.trend-visual-card figcaption{padding:12px;font-size:12px;line-height:1.55;color:#4a4742}
.trend-visual-card__meta{display:block;margin-top:4px;color:#77716a}
"""


def ensure_trend_visual_atlas(
    html_content: str,
    visual_evidence: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    if not html_content or not visual_evidence:
        return html_content, []
    inspector = inspect_trend_visual_markup(html_content)
    missing: list[dict[str, Any]] = []
    for visual in visual_evidence:
        visual_id = str(visual.get("visual_id") or "")
        image_url = str(visual.get("image_url") or "")
        if not visual_id or not image_url:
            continue
        if image_url not in inspector.images_by_visual_id.get(visual_id, []):
            missing.append(visual)
    if not missing:
        return html_content, []

    cards: list[str] = []
    for visual in missing:
        visual_id = str(visual.get("visual_id") or "")
        image_url = str(visual.get("image_url") or "")
        platform_id = str(visual.get("platform_id") or "").upper()
        source_url = str(visual.get("source_page_url") or image_url)
        source_title = str(visual.get("source_page_title") or "灵感来源")
        published_at = str(visual.get("published_at") or "")
        date_label = published_at[:10] if published_at else ""
        caption = " · ".join(item for item in (platform_id, date_label, source_title) if item)
        cards.append(
            f'<figure class="trend-visual-card" data-visual-id="{html_escape(visual_id)}">'
            f'<a href="{html_escape(source_url)}" target="_blank" rel="noopener noreferrer">'
            f'<img src="{html_escape(image_url)}" alt="{html_escape(source_title)}" '
            'loading="lazy" decoding="async" referrerpolicy="no-referrer"></a>'
            f"<figcaption>{html_escape(caption)}"
            '<span class="trend-visual-card__meta">点击图片查看原始来源</span>'
            "</figcaption></figure>"
        )
    atlas = (
        '<section class="trend-visual-atlas" data-required-section="additional-inspiration">'
        "<h2>更多灵感素材</h2>"
        "<p>以下素材可继续用于情绪板拼贴与细节延展；点击图片可回到原始页面。</p>"
        f'<div class="trend-visual-atlas__grid">{"".join(cards)}</div></section>'
    )
    result = html_content
    style_close = re.search(r"</style\s*>", result, flags=re.IGNORECASE)
    if style_close and "trend-visual-atlas__grid" not in result:
        result = (
            result[: style_close.start()] + TREND_VISUAL_ATLAS_CSS + result[style_close.start() :]
        )
    body_close = re.search(r"</body\s*>", result, flags=re.IGNORECASE)
    if body_close:
        result = result[: body_close.start()] + atlas + result[body_close.start() :]
    else:
        result += atlas
    return result, [str(item.get("visual_id") or "") for item in missing]


def validate_trend_visual_markup(
    html_content: str,
    required_visuals: Any,
) -> str:
    if not isinstance(required_visuals, list) or not required_visuals:
        return ""
    normalized = [
        item
        for item in required_visuals
        if isinstance(item, dict) and item.get("visual_id") and item.get("image_url")
    ]
    if not normalized:
        return ""
    if re.search(r"<(?:source|image)\b[^>]*(?:srcset|href)\s*=", html_content, flags=re.IGNORECASE):
        return "Trend report HTML must render approved visuals with plain img src attributes only."
    if re.search(
        r"(?:background(?:-image)?|content)\s*:[^;{}]*url\s*\(",
        html_content,
        flags=re.IGNORECASE,
    ):
        return "Trend report HTML cannot load visual evidence through CSS URLs."
    inspector = inspect_trend_visual_markup(html_content)
    allowed_urls = {str(item.get("image_url")) for item in normalized}
    for visual in normalized:
        visual_id = str(visual.get("visual_id") or "")
        image_url = str(visual.get("image_url") or "")
        if image_url not in inspector.images_by_visual_id.get(visual_id, []):
            return f"LLM HTML is missing required trend visual {visual_id} with its approved image URL."
    unexpected = [source for source in inspector.all_image_sources if source not in allowed_urls]
    if unexpected:
        return "Trend report HTML contains an image URL outside the approved visual-evidence whitelist."
    if len(inspector.all_image_sources) != len(set(inspector.all_image_sources)):
        return "Trend report HTML repeats visual-evidence images; each approved image must appear only once."
    return ""


def validate_llm_html_document(
    html_content: str,
    template_html: Any = "",
    required_chart_ids: Any = None,
    required_trend_visuals: Any = None,
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
        r"\son[a-z]+\s*=",
        r"<(?:iframe|object|embed|base)(?:\s|>)",
        r"javascript\s*:",
    ]
    for pattern in forbidden_patterns:
        if re.search(pattern, html_content, flags=re.IGNORECASE):
            if pattern == r"<script(?:\s|>)":
                return (
                    "Final HTML must render in the sandboxed preview without JavaScript; "
                    "analytical charts must use server-injected static inline SVG."
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
    visual_markup_error = validate_trend_visual_markup(html_content, required_trend_visuals)
    if visual_markup_error:
        return visual_markup_error
    return ""


def validate_tiktok_new_product_table_markup(html_content: str) -> str:
    headers = [
        html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip().lower()
        for match in re.finditer(
            r"<th\b[^>]*>(.*?)</th>",
            html_content,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]
    normalized_headers = {re.sub(r"\s+", " ", header) for header in headers if header}
    if not any(header in {"店铺名称", "shop name", "shop"} for header in normalized_headers):
        return "TikTok new-product ranking table must include a visible Shop Name column."
    if not any(
        header.replace(" ", "_") == "shop_id" for header in normalized_headers
    ):
        return "TikTok new-product ranking table must include a visible shop_id column."
    return ""


class StaticChartMarkupInspector(HTMLParser):
    graphic_tags = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}

    def __init__(self, required_chart_ids: list[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.required_chart_ids = set(required_chart_ids)
        self.figure_stack: list[dict[str, Any]] = []
        self.svg_stack: list[dict[str, int] | None] = []
        self.charts = {
            chart_id: {"figures": []}
            for chart_id in required_chart_ids
        }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        attr_map = {str(key).lower(): value for key, value in attrs}
        if normalized_tag == "figure":
            chart_id = str(attr_map.get("data-chart-id") or "")
            figure: dict[str, Any] = {"chart_id": chart_id, "svgs": []}
            self.figure_stack.append(figure)
            if chart_id in self.required_chart_ids:
                self.charts[chart_id]["figures"].append(figure)

        active_figure = next(
            (
                candidate
                for candidate in reversed(self.figure_stack)
                if candidate.get("chart_id") in self.required_chart_ids
            ),
            None,
        )
        if normalized_tag == "svg":
            svg = {"graphic_count": 0} if active_figure else None
            self.svg_stack.append(svg)
            if active_figure is not None and svg is not None:
                active_figure["svgs"].append(svg)
        elif (
            active_figure is not None
            and self.svg_stack
            and self.svg_stack[-1] is not None
            and normalized_tag in self.graphic_tags
        ):
            self.svg_stack[-1]["graphic_count"] += 1

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "svg" and self.svg_stack:
            self.svg_stack.pop()
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
        figures = chart["figures"]
        if len(figures) != 1:
            return (
                f"Required business chart {chart_id} must appear exactly once; "
                f"found {len(figures)} figures."
            )
        svgs = figures[0]["svgs"]
        if not svgs:
            return (
                f"Required business chart {chart_id} is missing its server-injected inline SVG; "
                "canvas and script-rendered charts are not supported in the sandboxed preview."
            )
        if len(svgs) != 1:
            return (
                f"Required business chart {chart_id} must contain exactly one inline SVG; "
                f"found {len(svgs)}."
            )
        if svgs[0]["graphic_count"] == 0:
            return (
                f"Required business chart {chart_id} still contains an empty SVG after server chart injection."
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
                str(key): compact_text(str(child), 180) for key, child in list(value.items())[:10]
            }
        return {
            str(key): html_report_compact_value(child, depth=depth + 1)
            for key, child in list(value.items())[:24]
        }
    return compact_text(str(value), 240)


def html_report_insight_narrative_context(value: Any) -> dict[str, Any]:
    """Compact narrative fields without truncating sections or per-chart interpretations."""

    narrative = value if isinstance(value, dict) else {}
    compacted = {
        str(key): html_report_compact_value(child)
        for key, child in narrative.items()
        if key not in {"sections", "chart_insights"}
    }
    compacted["sections"] = [
        {
            **{
                str(key): html_report_compact_value(child)
                for key, child in section.items()
                if key != "insights"
            },
            "insights": [
                html_report_compact_value(insight)
                for insight in section.get("insights") or []
                if isinstance(insight, dict)
            ],
        }
        for section in narrative.get("sections") or []
        if isinstance(section, dict)
    ]
    compacted["chart_insights"] = [
        html_report_compact_value(insight)
        for insight in narrative.get("chart_insights") or []
        if isinstance(insight, dict)
    ]
    return compacted


def html_report_compact_review_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"value": compact_text(str(value), 1200)}
    compacted: dict[str, Any] = {}
    for key, child in value.items():
        normalized_key = str(key)
        if isinstance(child, str):
            # Preserve the substance of every collected review for the report
            # author. A generous per-field guard prevents one pathological
            # review from consuming the entire model context.
            limit = 2000 if normalized_key in {"content", "body", "text", "review"} else 600
            compacted[normalized_key] = compact_text(child, limit)
        elif normalized_key in {"images", "videos"} and isinstance(child, list):
            compacted[normalized_key] = [compact_text(str(item), 600) for item in child[:12]]
        else:
            compacted[normalized_key] = html_report_compact_value(child, depth=2)
    return compacted


def html_report_compact_review_data(value: dict[str, Any]) -> dict[str, Any]:
    compacted = {
        str(key): html_report_compact_value(child) for key, child in value.items() if key != "data"
    }
    container = value.get("data") if isinstance(value.get("data"), dict) else {}
    items = [html_report_compact_review_item(item) for item in container.get("items") or []]
    compacted["data"] = {
        str(key): html_report_compact_value(child)
        for key, child in container.items()
        if key != "items"
    }
    compacted["data"]["items"] = items
    compacted["data"]["report_input_review_count"] = len(items)
    return compacted


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


COMPETITOR_REVIEW_IMAGE_DEFAULT_LIMIT = 60
COMPETITOR_REVIEW_IMAGE_MAX_LIMIT = 120
COMPETITOR_REVIEW_GALLERY_MARKER = "<!-- INSIGHT_AGENT_REVIEW_GALLERY -->"


def html_report_http_urls(value: Any) -> list[str]:
    """Return every distinct HTTP(S) URL embedded in a media field."""
    urls: list[str] = []
    if isinstance(value, str):
        urls.extend(re.findall(r"https?://[^\s,;\"'<>]+", value))
    elif isinstance(value, list):
        for item in value:
            urls.extend(html_report_http_urls(item))
    elif isinstance(value, dict):
        for key in ("url", "image", "imageUrl", "image_url", "mainImage", "zoomImageUrl"):
            urls.extend(html_report_http_urls(value.get(key)))
    return list(dict.fromkeys(urls))


def competitor_review_image_evidence(
    tool_results: list[dict[str, Any]],
    *,
    limit: int = COMPETITOR_REVIEW_IMAGE_DEFAULT_LIMIT,
) -> tuple[list[dict[str, Any]], int]:
    """Select review images while covering distinct reviews before extra images."""
    bounded_limit = max(1, min(int(limit), COMPETITOR_REVIEW_IMAGE_MAX_LIMIT))
    review_groups: list[dict[str, Any]] = []
    review_number = 0
    for tool in tool_results:
        if (
            not isinstance(tool, dict)
            or tool.get("status") not in SUCCESS_TOOL_STATUSES
            or str(tool.get("name") or "") != "sellersprite_review"
        ):
            continue
        review_input = tool.get("input") if isinstance(tool.get("input"), dict) else {}
        asin = str(review_input.get("asin") or "").strip().upper()
        data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
        container = data.get("data") if isinstance(data.get("data"), dict) else data
        for review in container.get("items") or []:
            if not isinstance(review, dict):
                continue
            image_urls = html_report_http_urls(review.get("images"))
            if not image_urls:
                continue
            review_number += 1
            sku_values = review.get("skus") or review.get("sku") or []
            if not isinstance(sku_values, list):
                sku_values = [sku_values]
            review_groups.append(
                {
                    "review_key": f"{asin or 'ASIN'}-media-{review_number}",
                    "asin": asin,
                    "star": review.get("star") or review.get("rating"),
                    "title": compact_text(str(review.get("title") or ""), 180),
                    "author": compact_text(str(review.get("author") or ""), 100),
                    "date": review.get("date")
                    or review.get("reviewDate")
                    or review.get("review_date"),
                    "skus": [
                        compact_text(str(item), 120) for item in sku_values if str(item).strip()
                    ],
                    "excerpt": compact_text(
                        str(
                            review.get("content")
                            or review.get("body")
                            or review.get("text")
                            or review.get("review")
                            or ""
                        ),
                        260,
                    ),
                    "image_urls": image_urls,
                }
            )

    available_urls = {url for group in review_groups for url in group.get("image_urls") or []}
    selected: list[dict[str, Any]] = []
    selected_urls: set[str] = set()
    max_images_per_review = max(
        (len(group.get("image_urls") or []) for group in review_groups),
        default=0,
    )
    # Round-robin by image position. This represents as many different buyer
    # reviews as possible before adding the second/third image from one review.
    for image_index in range(max_images_per_review):
        for group in review_groups:
            image_urls = group.get("image_urls") or []
            if image_index >= len(image_urls):
                continue
            image_url = image_urls[image_index]
            if image_url in selected_urls:
                continue
            selected_urls.add(image_url)
            selected.append(
                {key: value for key, value in group.items() if key != "image_urls"}
                | {
                    "image_url": image_url,
                    "image_position": image_index + 1,
                }
            )
            if len(selected) >= bounded_limit:
                return selected, len(available_urls)
    return selected, len(available_urls)


def competitor_review_image_limit(payload: dict[str, Any]) -> int:
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    raw_limit = payload.get("reportImageLimit") or params.get("report_image_limit")
    try:
        parsed = int(raw_limit)
    except (TypeError, ValueError):
        parsed = COMPETITOR_REVIEW_IMAGE_DEFAULT_LIMIT
    return max(1, min(parsed, COMPETITOR_REVIEW_IMAGE_MAX_LIMIT))


def ensure_competitor_review_image_gallery(
    html_content: str,
    image_evidence: list[dict[str, Any]],
    *,
    available_count: int,
) -> tuple[str, int]:
    """Insert an evidence-bound buyer-image gallery into the fit/VOC section."""
    if not html_content:
        return html_content, 0
    if 'data-review-gallery="seller-review-images"' in html_content:
        return html_content.replace(COMPETITOR_REVIEW_GALLERY_MARKER, ""), 0
    if not image_evidence:
        return html_content.replace(COMPETITOR_REVIEW_GALLERY_MARKER, ""), 0

    groups: dict[str, dict[str, Any]] = {}
    for item in image_evidence:
        image_url = str(item.get("image_url") or "")
        if not image_url.startswith(("http://", "https://")):
            continue
        review_key = str(item.get("review_key") or image_url)
        group = groups.setdefault(review_key, {**item, "image_urls": []})
        if image_url not in group["image_urls"]:
            group["image_urls"].append(image_url)
    if not groups:
        return html_content.replace(COMPETITOR_REVIEW_GALLERY_MARKER, ""), 0

    def escaped(value: Any) -> str:
        return html.escape(str(value or ""), quote=True)

    cards: list[str] = []
    rendered_count = 0
    for group in groups.values():
        star = escaped(group.get("star") or "未知")
        title = escaped(group.get("title") or "买家评论")
        asin = str(group.get("asin") or "")
        sku_label = " · ".join(str(item) for item in group.get("skus") or [] if str(item).strip())
        review_date = str(group.get("date") or "")
        meta_parts = [part for part in (asin, sku_label, review_date) if part]
        excerpt = escaped(group.get("excerpt"))
        excerpt_html = f"<p>{excerpt}</p>" if excerpt else ""
        images = []
        for image_index, image_url in enumerate(group.get("image_urls") or [], start=1):
            rendered_count += 1
            images.append(
                '<img loading="lazy" decoding="async" '
                f'src="{escaped(image_url)}" '
                f'alt="买家返图 · {star}星 · {title} · 第{image_index}张">'
            )
        cards.append(
            '<article class="review-gallery-card">'
            f'<div class="review-gallery-media">{"".join(images)}</div>'
            '<div class="review-gallery-copy">'
            f'<div class="review-gallery-title"><span>{star}★</span><strong>{title}</strong></div>'
            f'<p class="review-gallery-meta">{escaped(" · ".join(meta_parts))}</p>'
            f"{excerpt_html}"
            "</div></article>"
        )

    gallery = (
        '<div class="review-image-gallery" data-review-gallery="seller-review-images">'
        '<div class="review-gallery-heading"><div><h3>评论区买家返图</h3>'
        "<p>仅使用 SellerSprite 评论证据中的原始图片 URL；先覆盖不同评论，再补充同一评论的多张图片。</p>"
        "</div>"
        f"<span>已展示 {rendered_count} / {max(available_count, rendered_count)} 张去重返图 · "
        f"{len(groups)} 条带图评论</span></div>"
        f'<div class="review-gallery-grid">{"".join(cards)}</div>'
        '<p class="source-line">来源：SellerSprite MCP · sellersprite_review · 评论区买家上传图片；图片仅作为可观察证据，不单独证明产品根因。</p>'
        "</div>"
    )
    style = """<style id="insight-agent-review-gallery-style">
.review-image-gallery{margin-top:24px;padding-top:22px;border-top:1px solid #e5e7eb}
.review-gallery-heading{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:14px}
.review-gallery-heading h3{margin:0 0 5px}.review-gallery-heading p{margin:0;color:#667085;font-size:13px}
.review-gallery-heading>span{flex:0 0 auto;padding:6px 10px;border-radius:999px;background:#fff4e8;color:#9a4b00;font-size:12px;font-weight:700}
.review-gallery-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}
.review-gallery-card{margin:0;border:1px solid #e5e7eb;border-radius:12px;background:#fff;overflow:hidden}
.review-gallery-media{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:#e5e7eb}
.review-gallery-media img{display:block;width:100%;height:190px;object-fit:contain;background:#f8fafc}
.review-gallery-media img:only-child{grid-column:1/-1;height:260px}
.review-gallery-copy{padding:12px}.review-gallery-title{display:flex;gap:8px;align-items:flex-start}
.review-gallery-title span{flex:0 0 auto;color:#b45309;font-size:12px;font-weight:800}.review-gallery-title strong{font-size:14px;line-height:1.45}
.review-gallery-copy p{margin:7px 0 0;color:#475467;font-size:12px;line-height:1.55}.review-gallery-copy .review-gallery-meta{color:#98a2b3}
@media(max-width:640px){.review-gallery-heading{display:block}.review-gallery-heading>span{display:inline-block;margin-top:10px}.review-gallery-grid{grid-template-columns:1fr}}
</style>"""
    if "insight-agent-review-gallery-style" not in html_content:
        head_close = re.search(r"</head\s*>", html_content, flags=re.IGNORECASE)
        if head_close:
            html_content = (
                html_content[: head_close.start()] + style + html_content[head_close.start() :]
            )

    if COMPETITOR_REVIEW_GALLERY_MARKER in html_content:
        html_content = html_content.replace(COMPETITOR_REVIEW_GALLERY_MARKER, gallery, 1)
        html_content = html_content.replace(COMPETITOR_REVIEW_GALLERY_MARKER, "")
    else:
        fit_section = re.search(
            r'<section\b[^>]*data-required-section=["\']fit-voc["\'][^>]*>',
            html_content,
            flags=re.IGNORECASE,
        )
        insert_at = -1
        if fit_section:
            following_section = re.search(
                r'</section\s*>\s*(?=<section\b[^>]*data-required-section=["\']comparison["\'])',
                html_content[fit_section.end() :],
                flags=re.IGNORECASE,
            )
            if following_section:
                insert_at = fit_section.end() + following_section.start()
        if insert_at < 0:
            body_close = re.search(r"</body\s*>", html_content, flags=re.IGNORECASE)
            insert_at = body_close.start() if body_close else len(html_content)
        html_content = html_content[:insert_at] + gallery + html_content[insert_at:]
    return html_content, rendered_count


def hot_product_required_image_urls(
    tool_results: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    reviewed_asins: list[str] = []
    product_images_by_asin: dict[str, str] = {}
    latest_selected_product_urls: list[str] = []
    review_urls: list[str] = []
    for tool in tool_results:
        if not isinstance(tool, dict) or tool.get("status") not in SUCCESS_TOOL_STATUSES:
            continue
        name = str(tool.get("name") or "")
        data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
        if name == "sellersprite_market_product_concentration":
            selection = (
                data.get("product_selection")
                if isinstance(data.get("product_selection"), dict)
                else {}
            )
            selected_product_urls: list[str] = []
            products = [
                product
                for collection_name in ("selected", "eligible_candidates")
                for product in (selection.get(collection_name) or [])
                if isinstance(product, dict)
            ]
            for product in products:
                if not isinstance(product, dict):
                    continue
                image_url = html_report_first_http_url(
                    product.get("imageUrl") or product.get("image_url") or product.get("image")
                )
                asin = str(product.get("asin") or "").strip().upper()
                if asin and image_url:
                    product_images_by_asin[asin] = image_url
                if product in (selection.get("selected") or []) and image_url:
                    selected_product_urls.append(image_url)
            if selected_product_urls:
                latest_selected_product_urls = selected_product_urls
        if name == "sellersprite_market_research":
            container = data.get("data") if isinstance(data.get("data"), dict) else {}
            for product in container.get("items") or []:
                if not isinstance(product, dict) or not product.get("asin"):
                    continue
                image_url = html_report_first_http_url(product)
                asin = str(product.get("asin") or "").strip().upper()
                if asin and image_url and asin not in product_images_by_asin:
                    product_images_by_asin[asin] = image_url
        if name == "sellersprite_review":
            review_input = tool.get("input") if isinstance(tool.get("input"), dict) else {}
            reviewed_asin = str(review_input.get("asin") or "").strip().upper()
            if reviewed_asin and reviewed_asin not in reviewed_asins:
                reviewed_asins.append(reviewed_asin)
            container = data.get("data") if isinstance(data.get("data"), dict) else {}
            for review in container.get("items") or []:
                if not isinstance(review, dict):
                    continue
                image_url = html_report_first_http_url(review.get("images") or review.get("videos"))
                if image_url:
                    review_urls.append(image_url)
                    break
    product_urls = [
        product_images_by_asin[asin] for asin in reviewed_asins if asin in product_images_by_asin
    ]
    if not product_urls:
        product_urls = latest_selected_product_urls
    return list(dict.fromkeys(product_urls))[:20], list(dict.fromkeys(review_urls))[:20]


def html_report_compact_tool_results(
    tool_results: Any, *, limit: int | None = None
) -> list[dict[str, Any]]:
    if not isinstance(tool_results, list):
        return []
    effective_limit = limit
    if effective_limit is None:
        has_fastmoss_evidence = any(
            isinstance(tool, dict) and str(tool.get("name") or "").startswith("mcp__fastmoss__")
            for tool in tool_results
        )
        # FastMoss market workflows intentionally fan out across US/MX and then
        # append per-product trend/creator/video evidence. Keep the late calls;
        # the old generic 24-tool cap silently removed them from the renderer.
        effective_limit = 48 if has_fastmoss_evidence else 24
    compacted: list[dict[str, Any]] = []
    for tool in tool_results[:effective_limit]:
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
            compacted_data = html_report_compact_review_data(data)
        else:
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
                    for key, value in list(
                        (tool.get("input") if isinstance(tool.get("input"), dict) else {}).items()
                    )[:16]
                    if key
                    not in {
                        "toolResults",
                        "marketReportData",
                        "tiktokNewProductReportData",
                        "skillMarkdown",
                        "skillHtmlTemplate",
                    }
                },
                "data": compacted_data,
            }
        )
    return compacted


def trend_report_data_to_artifact(report_data: dict[str, Any]) -> dict[str, Any]:
    category = str(report_data.get("category") or "流行趋势")
    target_seasons = [str(item) for item in report_data.get("target_seasons") or [] if item]
    trend_concepts = [str(item) for item in report_data.get("trend_concepts") or [] if item]
    design_goal = str(report_data.get("design_goal") or "为下一季产品设计提供灵感与转译方向")
    return {
        "title": report_data.get("title") or f"{category} 流行趋势报告",
        "executive_summary": report_data.get("executive_summary")
        or f"围绕 {category} 整理色彩、面料、廓形与风格灵感，并转译为下一季可继续发展的设计方向。",
        "kpis": [],
        "market_basics": [
            f"设计目标：{design_goal}",
            *([f"目标季：{'、'.join(target_seasons)}"] if target_seasons else []),
        ],
        "price_and_margin": [],
        "competition": [],
        "user_voice": [],
        "key_findings": trend_concepts[:8],
        "opportunities": report_data.get("next_actions") or [],
        "opportunity_pool": trend_concepts[:12],
        "risks": [],
        "data_gaps": [],
        "next_steps": report_data.get("next_actions") or [],
    }


def trend_report_llm_context(report_data: dict[str, Any]) -> dict[str, Any]:
    evidence_map = [
        item for item in report_data.get("evidence_map") or [] if isinstance(item, dict)
    ]
    recency_rank = {"recent": 0, "undated": 1, "background": 2}
    relevance_rank = {"category_specific": 0, "adjacent": 1, "generic": 2}
    evidence_ranked = sorted(
        evidence_map,
        key=lambda item: (
            0 if item.get("source_type") == "public_page" else 1,
            recency_rank.get(str(item.get("recency_status") or "undated"), 1),
            relevance_rank.get(str(item.get("relevance_status") or "generic"), 2),
            str(item.get("evidence_id") or ""),
        ),
    )
    detailed_evidence: list[dict[str, Any]] = []
    for item in evidence_ranked[:120]:
        detailed_evidence.append(
            {
                "platform_id": item.get("platform_id"),
                "platform_name": item.get("platform_name"),
                "source_type": item.get("source_type"),
                "title": item.get("title"),
                "url": item.get("url"),
                "published": item.get("published"),
                "updated": item.get("updated"),
                "query_dimensions": item.get("query_dimensions") or [],
                "trend_signals": (item.get("evidence_snippets") or [])[:6],
            }
        )
    source_index = [
        {
            "platform_id": item.get("platform_id"),
            "title": item.get("title"),
            "url": item.get("url"),
            "published": item.get("published"),
        }
        for item in evidence_map
    ]
    visual_inspiration = [
        {
            "visual_id": item.get("visual_id"),
            "image_url": item.get("image_url"),
            "platform_id": item.get("platform_id"),
            "source_page_title": item.get("source_page_title"),
            "source_page_url": item.get("source_page_url"),
            "published_at": item.get("published_at"),
            "alt_text": item.get("alt_text"),
            "query_dimensions": item.get("query_dimensions") or [],
        }
        for item in report_data.get("visual_evidence") or []
        if isinstance(item, dict) and item.get("visual_id") and item.get("image_url")
    ]
    return {
        "schema_version": report_data.get("schema_version"),
        "category": report_data.get("category"),
        "marketplace": report_data.get("marketplace"),
        "time_range": report_data.get("time_range"),
        "generated_at": report_data.get("generated_at"),
        "design_goal": report_data.get("design_goal"),
        "target_user": report_data.get("target_user"),
        "target_seasons": report_data.get("target_seasons") or [],
        "trend_concepts": report_data.get("trend_concepts") or [],
        "editorial_brief": report_data.get("editorial_brief") or {},
        "insight_narrative": html_report_insight_narrative_context(
            report_data.get("insight_narrative") or {}
        ),
        "derived_metrics": html_report_compact_value(
            report_data.get("derived_metrics") or []
        ),
        "metric_analysis": html_report_compact_value(
            report_data.get("metric_analysis") or {}
        ),
        "source_material": detailed_evidence,
        "visual_inspiration": visual_inspiration,
        "source_appendix": {
            "sources": source_index,
        },
    }


def build_trend_report_data(payload: dict[str, Any]) -> dict[str, Any]:
    category = clean_text(str(payload.get("category") or ""))
    if not category:
        raise ValueError(
            "category is required for TrendReportData; do not default to an example category."
        )
    tool_results = [
        item
        for item in (
            payload.get("toolResults") if isinstance(payload.get("toolResults"), list) else []
        )
        if isinstance(item, dict)
    ]
    trend_source = (
        payload.get("trendPlatformsData")
        if isinstance(payload.get("trendPlatformsData"), dict)
        else {}
    )
    if not trend_source:
        for tool in reversed(tool_results):
            if (
                str(tool.get("name") or "") == "trend_platforms"
                and str(tool.get("status") or "") in SUCCESS_TOOL_STATUSES
                and isinstance(tool.get("data"), dict)
            ):
                trend_source = tool["data"]
                break
    if not trend_source or not isinstance(trend_source.get("platforms"), list):
        raise ValueError("TrendReportData requires one successful trend_platforms result.")

    marketplace = clean_text(
        str(payload.get("marketplace") or trend_source.get("marketplace") or "Global")
    )
    time_range = (
        normalize_agent_time_range(payload.get("timeRange") or trend_source.get("time_range"))
        or "30d"
    )
    generated_at = str(payload.get("generatedAt") or trend_source.get("generated_at") or now_iso())
    platforms = [item for item in trend_source.get("platforms") or [] if isinstance(item, dict)]
    evidence_map: list[dict[str, Any]] = []
    source_ids: dict[tuple[str, str], str] = {}
    platform_summaries: list[dict[str, Any]] = []

    for platform in platforms:
        platform_id = str(platform.get("platform_id") or "")
        platform_name = str(platform.get("name") or platform_id)
        seen_urls: set[str] = set()
        for source_type, rows in (
            ("public_page", platform.get("pages") or []),
            ("indexed_preview", platform.get("search_results") or []),
        ):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("final_url") or row.get("url") or "")
                canonical_url = canonical_trend_page_key(url)
                if not canonical_url or canonical_url in seen_urls:
                    continue
                seen_urls.add(canonical_url)
                published = str(row.get("published") or "")
                updated = str(row.get("updated") or "")
                recency_status = str(
                    row.get("recency_status")
                    or trend_recency_status(updated or published, time_range)
                )
                evidence_id = f"T{len(evidence_map) + 1:03d}"
                images = [item for item in row.get("images") or [] if isinstance(item, dict)]
                evidence = {
                    "evidence_id": evidence_id,
                    "platform_id": platform_id,
                    "platform_name": platform_name,
                    "source_type": source_type,
                    "evidence_level": (
                        "public_page_body"
                        if source_type == "public_page"
                        else "indexed_public_preview"
                    ),
                    "title": compact_text(str(row.get("title") or url), 240),
                    "url": url,
                    "domain": article_domain(url),
                    "published": published,
                    "updated": updated,
                    "recency_status": recency_status,
                    "relevance_status": row.get("relevance_status") or "generic",
                    "relevance_score": row.get("relevance_score") or 0,
                    "evidence_status": row.get("evidence_status")
                    or ("supporting" if source_type == "public_page" else "indexed_preview"),
                    "query_ids": list(dict.fromkeys(row.get("query_ids") or [])),
                    "query_dimensions": list(dict.fromkeys(row.get("query_dimensions") or [])),
                    "evidence_snippets": (
                        [str(item) for item in row.get("evidence_snippets") or []]
                        if source_type == "public_page"
                        else [str(row.get("snippet") or "")]
                    )[:8],
                    "image_urls": [
                        str(item.get("image_url")) for item in images if item.get("image_url")
                    ][:TREND_MAX_IMAGES_PER_PAGE],
                    "access_mode": row.get("access_mode")
                    or (
                        "indexed_search_preview"
                        if source_type == "indexed_preview"
                        else "public_page"
                    ),
                    "access_notes": [str(item) for item in row.get("access_notes") or []][:6],
                }
                evidence["evidence_snippets"] = [
                    snippet for snippet in evidence["evidence_snippets"] if snippet
                ]
                evidence_map.append(evidence)
                source_ids[(platform_id, canonical_url)] = evidence_id

        platform_summaries.append(
            {
                "platform_id": platform_id,
                "name": platform_name,
                "official_domains": platform.get("official_domains") or [],
                "access_status": platform.get("access_status") or "unavailable",
                "evidence_status": platform.get("evidence_status") or "insufficient",
                "search_provider": platform.get("search_provider") or "",
                "query_count": int(platform.get("query_count") or 0),
                "search_queries": platform.get("search_queries") or [],
                "query_runs": platform.get("query_runs") or [],
                "raw_result_count": int(platform.get("raw_result_count") or 0),
                "unique_candidate_count": int(platform.get("unique_candidate_count") or 0),
                "page_read_target": int(platform.get("page_read_target") or 0),
                "page_attempt_count": int(platform.get("page_attempt_count") or 0),
                "page_read_count": int(platform.get("page_read_count") or 0),
                "qualified_page_count": int(platform.get("qualified_page_count") or 0),
                "supporting_page_count": int(platform.get("supporting_page_count") or 0),
                "recent_page_count": int(platform.get("recent_page_count") or 0),
                "background_page_count": int(platform.get("background_page_count") or 0),
                "undated_page_count": int(platform.get("undated_page_count") or 0),
                "discarded_page_count": int(platform.get("discarded_page_count") or 0),
                "visual_count": int(platform.get("visual_count") or 0),
                "warnings": [str(item) for item in platform.get("warnings") or []][:12],
            }
        )

    report_image_limit = max(
        1,
        min(
            int(
                payload.get("reportImageLimit")
                or (trend_source.get("visual_coverage") or {}).get("report_image_limit")
                or 36
            ),
            TREND_MAX_REPORT_IMAGES,
        ),
    )
    visual_evidence: list[dict[str, Any]] = []
    seen_visuals: set[str] = set()
    for raw_visual in trend_source.get("visual_evidence") or []:
        if not isinstance(raw_visual, dict):
            continue
        source_url = str(raw_visual.get("source_page_url") or "")
        image_url = safe_trend_image_url(
            raw_visual.get("image_url"), source_url or str(raw_visual.get("image_url") or "")
        )
        canonical_key = trend_image_canonical_key(image_url) if image_url else ""
        if not image_url or not canonical_key or canonical_key in seen_visuals:
            continue
        seen_visuals.add(canonical_key)
        platform_id = str(raw_visual.get("platform_id") or "")
        visual_evidence.append(
            {
                "visual_id": f"V{len(visual_evidence) + 1:03d}",
                "image_url": image_url,
                "canonical_key": canonical_key,
                "platform_id": platform_id,
                "source_page_url": source_url,
                "source_page_title": compact_text(
                    str(raw_visual.get("source_page_title") or source_url), 200
                ),
                "source_evidence_id": source_ids.get(
                    (platform_id, canonical_trend_page_key(source_url)), ""
                ),
                "published_at": raw_visual.get("published_at") or "",
                "recency_status": raw_visual.get("recency_status") or "undated",
                "relevance_status": raw_visual.get("relevance_status") or "generic",
                "query_dimensions": raw_visual.get("query_dimensions") or [],
                "evidence_level": raw_visual.get("evidence_level") or "public_page_declared_image",
                "alt_text": compact_text(str(raw_visual.get("alt_text") or ""), 240),
                "rights_note": raw_visual.get("rights_note")
                or "Public-page visual preview; retain the source link and do not remove watermarks.",
                "analysis_rule": "Visual reference only; do not infer colour, fabric, silhouette, or popularity from the image alone.",
            }
        )
        if len(visual_evidence) >= report_image_limit:
            break

    coverage = (
        trend_source.get("coverage") if isinstance(trend_source.get("coverage"), dict) else {}
    )
    readable_pages = sum(int(item.get("page_read_count") or 0) for item in platform_summaries)
    recent_pages = sum(int(item.get("recent_page_count") or 0) for item in platform_summaries)
    background_pages = sum(
        int(item.get("background_page_count") or 0) for item in platform_summaries
    )
    undated_pages = sum(int(item.get("undated_page_count") or 0) for item in platform_summaries)
    accessed_platforms = sum(
        1 for item in platform_summaries if item.get("access_status") != "unavailable"
    )
    source_notes: list[str] = []
    for item in platform_summaries:
        if item.get("access_status") == "unavailable":
            source_notes.append(f"{item.get('name')} 本轮未取得可用公开页面。")
        elif item.get("access_status") == "search_only":
            source_notes.append(f"{item.get('name')} 本轮仅取得公开索引预览。")
    if not recent_pages and (background_pages or undated_pages):
        source_notes.append(
            f"{time_range} 内公开编辑页面较少，已补充与当前或未来目标季相关的公开素材。"
        )
    source_notes = unique_strings(source_notes)
    target_seasons = [
        str(item) for item in trend_source.get("target_seasons") or [] if str(item).strip()
    ]
    trend_concepts = [
        str(item) for item in trend_source.get("trend_concepts") or [] if str(item).strip()
    ]
    editorial_brief = {
        "purpose": "为服装设计人员提供视觉灵感与可转译的产品方向，而不是验证型数据报告。",
        "theme_count": {"minimum": 4, "maximum": 6},
        "theme_requirements": [
            "一句主题叙事与情绪关键词",
            "色彩组合与使用比例建议",
            "面料、材质与肌理方向",
            "廓形、结构与细节语言",
            "2–4 条可进入草图或选料阶段的设计提示",
        ],
        "visuals_per_theme": {
            "target_minimum": 6,
            "target_maximum": 10,
            "rule": "只使用与主题相关的白名单图片；不足时少用，不重复、不以无关图补数。",
        },
        "source_treatment": "来源平台、页面日期与链接仅放在图片说明或文末简短来源索引。",
        "forbidden_sections": [
            "证据边界",
            "验证矩阵",
            "数据完整性与未完成任务",
            "平台覆盖率表",
            "跨源审计矩阵",
        ],
    }
    query_summary = {
        "executed_queries": sum(int(item.get("query_count") or 0) for item in platform_summaries),
        "raw_results": sum(int(item.get("raw_result_count") or 0) for item in platform_summaries),
        "unique_candidates": sum(
            int(item.get("unique_candidate_count") or 0) for item in platform_summaries
        ),
        "attempted_pages": sum(
            int(item.get("page_attempt_count") or 0) for item in platform_summaries
        ),
        "effective_pages": readable_pages,
        "discarded_pages": sum(
            int(item.get("discarded_page_count") or 0) for item in platform_summaries
        ),
    }
    report_data: dict[str, Any] = {
        "schema_version": "trend_report_data.v1",
        "title": f"{category} 流行趋势报告",
        "category": category,
        "marketplace": marketplace,
        "time_range": time_range,
        "generated_at": generated_at,
        "design_goal": payload.get("designGoal") or "",
        "target_user": payload.get("targetUser") or "服装产品设计团队",
        "target_seasons": target_seasons,
        "trend_concepts": trend_concepts,
        "editorial_brief": editorial_brief,
        "coverage": coverage,
        "query_summary": query_summary,
        "platforms": platform_summaries,
        "evidence_map": evidence_map,
        "source_summary": {
            "accessed_platforms": accessed_platforms,
            "readable_pages": readable_pages,
            "recent_pages": recent_pages,
            "background_pages": background_pages,
            "undated_pages": undated_pages,
            "evidence_items": len(evidence_map),
            "public_page_evidence": sum(
                1 for item in evidence_map if item.get("source_type") == "public_page"
            ),
            "indexed_preview_evidence": sum(
                1 for item in evidence_map if item.get("source_type") == "indexed_preview"
            ),
        },
        "visual_evidence": visual_evidence,
        "visual_coverage": {
            "available": int(
                (trend_source.get("visual_coverage") or {}).get("available") or len(visual_evidence)
            ),
            "selected_for_report": len(visual_evidence),
            "report_image_limit": report_image_limit,
            "by_platform": {
                platform_id: sum(
                    1 for item in visual_evidence if item.get("platform_id") == platform_id
                )
                for platform_id in ("wgsn", "diexun", "pinterest")
            },
            "source_pages": len(
                {
                    canonical_trend_page_key(str(item.get("source_page_url") or ""))
                    for item in visual_evidence
                    if item.get("source_page_url")
                }
            ),
        },
        "source_notes": source_notes,
        "data_gaps": [],
        "next_actions": [
            "从最契合品牌的 2–3 个主题建立色卡、面料卡与细节样板。",
            "把每个主题的设计提示转成草图组合，并做跨主题混搭探索。",
            "保留图片原始页面链接，并遵守来源网站的版权与使用条款。",
        ],
        "method": trend_source.get("method") or {},
    }
    report_data["executive_summary"] = (
        f"围绕 {category} 汇集 WGSN、蝶讯与 Pinterest 的公开趋势与视觉素材，"
        "将色彩、面料、廓形和细节信号组织为可直接进入情绪板、选料与草图阶段的设计主题。"
    )
    report_data["artifact"] = trend_report_data_to_artifact(report_data)
    return report_data


def html_report_base_artifact(
    payload: dict[str, Any], report_data: dict[str, Any], tool_results: list[dict[str, Any]]
) -> dict[str, Any]:
    if report_data:
        existing = (
            report_data.get("artifact") if isinstance(report_data.get("artifact"), dict) else {}
        )
        if existing:
            return existing
        if str(report_data.get("schema_version") or "").startswith("trend_report_data"):
            return trend_report_data_to_artifact(report_data)
        if str(report_data.get("schema_version") or "").startswith(
            "tiktok_new_product_report_data"
        ):
            return tiktok_new_product_report_data_to_artifact(report_data)
        if str(report_data.get("schema_version") or "").startswith(
            "tiktok_bra_competitor_shop_report_data"
        ):
            return tiktok_bra_competitor_shop_report_data_to_artifact(report_data)
        return market_report_data_to_artifact(report_data)
    return fallback_agent_artifact(
        str(payload.get("prompt") or ""),
        str(payload.get("mode") or "market"),
        str(payload.get("category") or ""),
        tool_results,
    )


def analyze_market_report_node(payload: dict[str, Any]) -> dict[str, Any]:
    """Plan fixed secondary metrics with an LLM, then validate and calculate in code."""

    started = time.perf_counter()
    report_data = payload.get("reportData") if isinstance(payload.get("reportData"), dict) else {}
    if report_data and not isinstance(report_data.get("metric_facts"), list):
        # Compatibility for checkpoints produced before metric_facts.v1.
        report_data = attach_metric_facts(report_data)
    skill = payload.get("skill") if isinstance(payload.get("skill"), dict) else {}
    skill_id = str(skill.get("skill_id") or payload.get("skillId") or "")
    canonical_catalog = available_metric_catalog_for_skill(skill_id)
    facts = (
        report_data.get("metric_facts")
        if isinstance(report_data.get("metric_facts"), list)
        else []
    )
    fact_prompt = [
        {
            "fact_id": fact.get("fact_id"),
            "concept": fact.get("concept"),
            "value": fact.get("value"),
            "unit": fact.get("unit"),
            "period_key": fact.get("period_key"),
            "marketplace": fact.get("marketplace"),
            "category": fact.get("category"),
            "entity_type": fact.get("entity_type"),
            "entity_id": fact.get("entity_id"),
            "scope_key": fact.get("scope_key"),
            "observation_key": fact.get("observation_key"),
            "denominator_scope": fact.get("denominator_scope"),
            "sample_complete": fact.get("sample_complete"),
            "evidence_ids": fact.get("evidence_ids") or [],
            "source_path": fact.get("source_path"),
        }
        for fact in facts
        if isinstance(fact, dict)
    ][:240]
    proposals: list[dict[str, Any]]
    planner: dict[str, Any]
    use_llm = bool(payload.get("useLlm", True))
    if not facts or not canonical_catalog:
        proposals = []
        planner = {
            "mode": "not_applicable",
            "status": "ok",
            "message": "Builder 未提供可匹配的 metric_facts 或当前 Skill 没有开放二级指标。",
        }
    elif not use_llm:
        proposals = default_metric_proposals(facts, canonical_catalog)
        planner = {
            "mode": "deterministic_fallback",
            "status": "ok",
            "message": "LLM 已禁用，使用保守的同对象、同周期事实匹配。",
        }
    else:
        selection_request = {
            "role": "secondary_metric_selection_agent",
            "task": {
                "skill_id": skill_id,
                "user_task": compact_text(str(skill.get("prompt") or ""), 1200),
                "resolved_params": skill.get("params")
                if isinstance(skill.get("params"), dict)
                else {},
            },
            "instruction": (
                "只选择对当前任务有解释价值、且能由给定 metric_facts 支撑的固定二级指标。"
                "你不能发明公式、修改值、自己计算，也不能绑定目录外的指标或不存在的 fact_id。"
                "参数必须来自同一市场、实体和可比周期；不确定时不要选择。"
            ),
            "available_metrics": canonical_catalog,
            "metric_facts": fact_prompt,
            "output_schema": {
                "proposals": [
                    {
                        "metric_id": "one available metric_id",
                        "bindings": {"contract_binding_name": "MF001 or [MF001, MF002, MF003]"},
                        "rationale": "为什么该指标与当前任务相关",
                    }
                ]
            },
        }
        try:
            response = call_openai_compatible_chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是数据分析指标选择 Agent。你只负责从固定目录选择指标并绑定事实，"
                            "所有校验与计算由确定性脚本完成。只返回 JSON。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(selection_request, ensure_ascii=False, default=str),
                    },
                ]
            )
            message = response.get("message") if isinstance(response.get("message"), dict) else {}
            parsed = parse_json_loose(str(message.get("content") or ""))
            raw_proposals = (
                parsed.get("proposals")
                if isinstance(parsed, dict) and isinstance(parsed.get("proposals"), list)
                else None
            )
            if raw_proposals is None:
                raise ValueError("指标选择 Agent 未返回 proposals 数组。")
            proposals = [item for item in raw_proposals if isinstance(item, dict)][:24]
            planner = {
                "mode": "llm_selection",
                "status": "ok",
                "provider": response.get("provider"),
                "model": response.get("model"),
                "usage": response.get("usage") or {},
            }
        except Exception as exc:  # noqa: BLE001
            proposals = default_metric_proposals(facts, canonical_catalog)
            planner = {
                "mode": "deterministic_fallback",
                "status": "planner_error",
                "message": compact_text(str(exc), 400),
            }
    planner["duration_ms"] = int((time.perf_counter() - started) * 1000)
    analysis = calculate_metric_analysis(
        report_data,
        proposals,
        skill_id=skill_id,
        planner=planner,
    )
    analysis["metric_facts"] = facts
    return analysis


def report_insight_prompt_context(
    report_data: dict[str, Any], *, skill_id: str
) -> dict[str, Any]:
    schema_version = str(report_data.get("schema_version") or "")
    if schema_version.startswith("trend_report_data"):
        context = trend_report_llm_context(report_data)
    elif "market_report_data" in schema_version:
        context = market_report_llm_context(report_data)
    else:
        compacted = html_report_compact_value(report_data)
        context = compacted if isinstance(compacted, dict) else {}
    context = dict(context)
    for key in (
        "analysis_sections",
        "swot",
        "decision_matrix",
        "data_gaps",
        "metric_gaps",
        "evidence_gaps",
        "report_quality",
        "source_notes",
        "insight_narrative",
    ):
        context.pop(key, None)
    artifact = context.get("artifact")
    if isinstance(artifact, dict):
        context["artifact"] = {
            key: value
            for key, value in artifact.items()
            if key not in {"risks", "data_gaps", "warnings"}
        }
    context["skill_id"] = skill_id
    return context


def synthesize_report_insights_node(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate evidence-linked narrative blocks after deterministic metric analysis."""

    started = time.perf_counter()
    report_data = payload.get("reportData") if isinstance(payload.get("reportData"), dict) else {}
    skill = payload.get("skill") if isinstance(payload.get("skill"), dict) else {}
    skill_id = str(skill.get("skill_id") or payload.get("skillId") or "")
    fallback = fallback_report_insight_narrative(report_data, skill_id=skill_id)
    if not report_data:
        return fallback
    if not bool(payload.get("useLlm", True)):
        fallback["generator"] = {
            "mode": "deterministic_fallback",
            "status": "ok",
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        return fallback

    request_payload = {
        "role": "report_insight_synthesis_agent",
        "task": {
            "skill_id": skill_id,
            "user_task": compact_text(str(skill.get("prompt") or ""), 1600),
            "resolved_params": (
                skill.get("params") if isinstance(skill.get("params"), dict) else {}
            ),
        },
        "instruction": (
            "Turn only supported report evidence into reader-facing analytical prose. Do not impose a "
            "fixed section count, insight count, or charts-per-insight limit; include every supported insight "
            "needed by the task. Cross-chart section insights should follow observation -> interpretation -> "
            "optional business implication -> optional action and cite existing evidence_ids. Use calculated derived metrics "
            "when relevant, but never recompute metrics. Do not invent values, causal effects, market "
            "size, demographics, or thresholds. Correlation must not be written as causation. Omit an "
            "unsupported dimension completely: never write that data is missing, evidence is "
            "insufficient, a conclusion cannot be reached, or a task remains unfinished. Do not create "
            "a data-completeness section. Prefer specific conclusions over generic methodology prose. "
            "Treat chart_specs as explanatory evidence rather than a separate gallery. Emit exactly one "
            "chart_insight for every ready chart_spec. Each chart_insight must identify one chart_id, state the "
            "specific values, ranking, movement, or distribution visible in that chart, and provide the most useful "
            "bounded interpretation supported by its data. A business_implication and action are optional: include "
            "them only when the chart genuinely changes a business decision. Methodology, boundary, and coverage "
            "charts should instead explain scope, denominator, confidence, or the limit they place on conclusions. "
            "Do not force every chart toward a recommendation, and never leave a ready chart uninterpreted. "
            "Items in non_chart_presentations are deliberately not charts: use them only for supported text-section "
            "insights and never emit a chart_insight for them. Source counts alone must not be interpreted as sample "
            "representativeness."
        ),
        "skill_analysis_contract": html_report_analysis_contract(
            str(payload.get("skillMarkdown") or "")
        ),
        "report_context": report_insight_prompt_context(report_data, skill_id=skill_id),
        "output_schema": {
            "sections": [
                {
                    "section_id": "stable_snake_case_id",
                    "title": "reader-facing Chinese section title",
                    "insights": [
                        {
                            "conclusion": "clear evidence-bounded conclusion",
                            "observation": "specific supported data observation",
                            "interpretation": "what the observation means without causal overreach",
                            "business_implication": "optional; why it matters for the current task",
                            "action": "optional bounded action supported by the evidence",
                            "evidence_ids": ["existing evidence id"],
                            "confidence": "high | medium | low",
                        }
                    ],
                }
            ],
            "chart_insights": [
                {
                    "chart_id": "one existing ready chart id; every ready id appears exactly once",
                    "section_id": "business section that should contain the chart",
                    "section_title": "reader-facing Chinese section title",
                    "conclusion": "optional concise takeaway",
                    "observation": "specific values, ranking, change, or distribution visible in the chart",
                    "interpretation": "what the pattern means without causal overreach",
                    "business_implication": "optional; how it changes a decision or priority",
                    "action": "optional bounded next action",
                    "evidence_ids": ["existing evidence ids when available"],
                    "interpretation_type": "business | methodology | scope | confidence | descriptive",
                    "confidence": "high | medium | low",
                }
            ],
        },
    }
    try:
        response = call_openai_compatible_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the independent insight-synthesis node for versioned HTML report "
                        "data. Return JSON only. Write dense but readable analysis from supported "
                        "evidence; silently omit unsupported topics and all missing-data prose."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(request_payload, ensure_ascii=False, default=str),
                },
            ]
        )
        message = response.get("message") if isinstance(response.get("message"), dict) else {}
        parsed = parse_json_loose(str(message.get("content") or ""))
        normalized = normalize_report_insight_narrative(
            parsed,
            report_data=report_data,
            skill_id=skill_id,
        )
        if (
            not normalized.get("sections")
            and not normalized.get("chart_insights")
            and (fallback.get("sections") or fallback.get("chart_insights"))
        ):
            normalized = fallback
            generator_status = "fallback_after_empty_llm_result"
        else:
            generator_status = "ok"
        normalized["generator"] = {
            "mode": "llm_structured_synthesis",
            "status": generator_status,
            "provider": response.get("provider"),
            "model": response.get("model"),
            "usage": response.get("usage") or {},
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        return normalized
    except Exception as exc:  # noqa: BLE001
        fallback["generator"] = {
            "mode": "deterministic_fallback",
            "status": "llm_error",
            "message": compact_text(str(exc), 400),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        return fallback


def report_review_is_approved(review: dict[str, Any]) -> bool:
    if review.get("approved") is True:
        return True
    decision = str(review.get("decision") or review.get("status") or "").strip().lower()
    return decision in {"approve", "approved", "pass", "passed"}


def review_html_report_with_llm(
    html_content: str,
    *,
    review_round: int,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    review_request = {
        "role": "html_report_approval_agent",
        "review_round": review_round,
        "instruction": (
            "Independently audit the supplied HTML against its versioned ReportData and "
            "the Skill analysis contract. Review numerical consistency, metric meaning, denominator, "
            "keyword/market/time scope, evidence traceability, conclusion strength, required sections, "
            "section ordering against the Skill Output Rules, and chart-to-prose consistency. Treat "
            "chart/prose composition as a major presentation requirement: every chart listed in "
            "chart_layout_contract.required_chart_bindings must share the same semantic insight section and insight-chart-block "
            "with its observation and interpretation, plus any supported conclusion, business implication, or action; "
            "the nearby prose must explain the visible pattern and its analytical meaning, scope, confidence, or decision "
            "significance. Reject chart atlases, "
            "two or more consecutive chart-only blocks, a batch of prose followed by a batch of charts, "
            "any side-by-side chart/explanation layout, or CSS "
            "that prevents the chart from using the full content width. At every viewport, the figure must "
            "appear above insight-explanation in one column, and compiled SVGs must scale responsively to "
            "the available width. Every required chart, including charts recovered by the server, "
            "must have a specific observation and bounded interpretation directly underneath it "
            "in the same semantic block. Business implication and action are required only when supported by the "
            "chart; a title, source line, or generic methodology "
            "caption alone is a major issue. Verify that "
            "dimensions marked text_only in chart_manifest or listed in non_chart_presentations remain "
            "structured prose, definition lists, facts, or compact tables; reject invented charts for those "
            "dimensions. In particular, sample-source counts do not prove representativeness. "
            "every visible secondary metric "
            "comes from status=calculated derived_metrics, that rejected metrics were not recomputed, "
            "and that unavailable or rejected metrics were silently omitted. Do not require a visible data-gap, "
            "unavailable-dimension, or unfinished-task section. If a displayed claim lacks support, instruct the "
            "renderer to remove or narrow that claim rather than adding gap prose. Do not rewrite the report. "
            "Report every numerical, scope, evidence, completeness, chart-consistency, or chart/prose-layout "
            "blocker or major issue. Approve only when no blocker, major factual-consistency issue, or major "
            "presentation issue remains."
        ),
        "report_data": request_payload.get("report_data") or {},
        "report_data_pruning_manifest": (
            request_payload.get("report_data_pruning_manifest") or {}
        ),
        "skill_analysis_contract": request_payload.get("skill_analysis_contract") or "",
        "skill_markdown_excerpt": request_payload.get("skill_markdown_excerpt") or "",
        "required_chart_ids": request_payload.get("required_chart_ids") or [],
        "summary_chart_ids": request_payload.get("summary_chart_ids") or [],
        "chart_layout_contract": request_payload.get("chart_layout_contract") or {},
        "html": html_content,
        "output_schema": {
            "decision": "approve | revise",
            "summary": "short Chinese review summary",
            "issues": [
                {
                    "severity": "blocker | major | minor",
                    "category": "numeric | metric | scope | evidence | conclusion | completeness | presentation",
                    "location": "section or chart id",
                    "expected": "what ReportData or the Skill requires",
                    "actual": "what the HTML says",
                    "evidence_ids": ["E01"],
                    "repair_instruction": "specific instruction for the rendering agent in this run",
                }
            ],
        },
    }
    system_message = {
        "role": "system",
        "content": (
            "You are the independent factual-consistency approval agent for Hsia HTML reports. "
            "Return JSON only, with decision=approve or decision=revise. Do not output HTML or Markdown. "
            "The supplied HTML is the only current report and claim surface. The supplied ReportData "
            "is a complete factual review view of the Builder output after allow-listed authoring/runtime "
            "fields were removed: no retained collection was sampled and no retained string was truncated. "
            "Resolve exact-duplicate $ref entries through report_data_pruning_manifest.aliases. Removed "
            "legacy authoring fields are not missing evidence and must not be treated as current claims. "
            "Approve only when the HTML is consistent with the supplied ReportData and Skill "
            "contract. Keep issues concrete and repairable. Do not invent evidence, metrics, joint distributions, "
            "causal claims, or validated thresholds. Market size or growth alone does not prove entrant "
            "viability, and separate marginal distributions do not prove a combined product configuration."
        ),
    }
    try:
        response = call_openai_compatible_chat(
            [
                system_message,
                {
                    "role": "user",
                    "content": json.dumps(review_request, ensure_ascii=False, default=str),
                },
            ]
        )
        message = response.get("message") if isinstance(response.get("message"), dict) else {}
        raw_content = str(message.get("content") or "")
        parsed = parse_json_loose(raw_content)
        if not isinstance(parsed, dict):
            return {
                "round": review_round,
                "status": "invalid_response",
                "decision": "revise",
                "approved": False,
                "summary": "审批 Agent 未返回可解析的结构化结果。",
                "issues": [
                    {
                        "severity": "major",
                        "category": "approval_response",
                        "location": "whole_report",
                        "expected": "结构化 JSON 审批结果",
                        "actual": compact_text(raw_content, 240),
                        "repair_instruction": "重新检查整份报告与 ReportData 的一致性后再输出完整 HTML。",
                        "evidence_ids": [],
                    }
                ],
                "provider": response.get("provider"),
                "model": response.get("model"),
                "usage": response.get("usage") or {},
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
        issues = [
            html_report_compact_value(item)
            for item in (parsed.get("issues") if isinstance(parsed.get("issues"), list) else [])
            if isinstance(item, dict)
        ][:20]
        normalized = {
            "round": review_round,
            "status": "ok",
            "decision": str(parsed.get("decision") or parsed.get("status") or "revise").lower(),
            "approved": report_review_is_approved(parsed),
            "summary": compact_text(str(parsed.get("summary") or ""), 600),
            "issues": issues,
            "provider": response.get("provider"),
            "model": response.get("model"),
            "usage": response.get("usage") or {},
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        if normalized["approved"]:
            normalized["decision"] = "approve"
        else:
            normalized["decision"] = "revise"
        return normalized
    except Exception as exc:  # noqa: BLE001
        return {
            "round": review_round,
            "status": "error",
            "decision": "revise",
            "approved": False,
            "summary": f"审批 Agent 调用失败：{compact_text(str(exc), 300)}",
            "issues": [
                {
                    "severity": "major",
                    "category": "approval_unavailable",
                    "location": "whole_report",
                    "expected": "完成独立审批",
                    "actual": compact_text(str(exc), 240),
                    "repair_instruction": "重新检查整份报告与 ReportData 的一致性后再输出完整 HTML。",
                    "evidence_ids": [],
                }
            ],
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }


def red_team_html_report_with_llm(
    html_content: str,
    *,
    review_round: int,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    red_team_request = {
        "role": "html_report_strategy_red_team_agent",
        "review_round": review_round,
        "instruction": (
            "Challenge no more than five load-bearing claims that materially enable product selection, "
            "resource allocation, pricing, positioning, sourcing, or market entry. Do not repeat numerical "
            "or layout QA already owned by the factual approval node. For each selected claim, steelman the "
            "strongest version supported by ReportData, identify observable and falsifiable fails-if "
            "conditions, name the current evidence IDs, specify the exact missing comparison/field/window "
            "when relevant, and give a measurable kill criterion. A threshold may be called validated only "
            "when supplied by or deterministically derivable from ReportData or the Skill contract; otherwise "
            "label it as a proposed decision rule. If the claim exceeds current evidence, the in-run repair "
            "must narrow, rewrite, or remove the claim, never add visible missing-data prose. Give the cheapest "
            "bounded evidence action for a future run separately. Do not request or call tools in this review. "
            "Make the final approve-or-revise decision from the supplied HTML, ReportData, and Skill contract. "
            "Approve when the report contains no load-bearing claim that materially overstates the supplied evidence."
        ),
        "report_data": request_payload.get("report_data") or {},
        "report_data_pruning_manifest": (
            request_payload.get("report_data_pruning_manifest") or {}
        ),
        "skill_analysis_contract": request_payload.get("skill_analysis_contract") or "",
        "skill_markdown_excerpt": request_payload.get("skill_markdown_excerpt") or "",
        "html": html_content,
        "output_schema": {
            "decision": "approve | revise",
            "summary": "short Chinese strategic red-team summary",
            "reviewed_claim_count": 0,
            "findings": [
                {
                    "severity": "blocker | major | minor",
                    "location": "section or chart id",
                    "claim": "exact claim or faithful paraphrase",
                    "decision_enabled": "business decision enabled by the claim",
                    "steelman": "strongest version supported by current evidence",
                    "fails_if": ["observable falsifying condition"],
                    "evidence_ids": ["E01"],
                    "missing_evidence": [
                        "specific missing field, scope, time window, or comparison"
                    ],
                    "kill_criterion": {
                        "type": "evidence_based | proposed_rule | unavailable",
                        "value": "measurable threshold or stop condition",
                        "basis": "why this threshold is valid or still proposed",
                    },
                    "fixable_in_revision": True,
                    "revision_action": "rewrite | narrow | remove | none",
                    "repair_instruction": "specific instruction for the rendering agent",
                    "next_run_evidence_action": "cheapest bounded evidence action",
                }
            ],
        },
    }
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the independent strategy red-team node for Hsia HTML reports. The supplied "
                    "HTML is the only current claim surface. ReportData is the complete factual review view "
                    "of the Builder output after allow-listed legacy authoring/runtime fields were removed; "
                    "no retained collection was sampled and no retained string was truncated. Resolve "
                    "exact-duplicate $ref entries through report_data_pruning_manifest.aliases. Removed "
                    "legacy authoring fields are not current claims. "
                    "You have no source-data tools in this review; decide from the supplied HTML, ReportData, "
                    "and Skill contract. Return JSON only. Do not perform generic proofreading or repeat factual "
                    "QA. Keep findings evidence-bounded, falsifiable, and decision-specific."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(red_team_request, ensure_ascii=False, default=str),
            },
        ]
        response = call_openai_compatible_chat(messages)
        message = response.get("message") if isinstance(response.get("message"), dict) else {}
        parsed = parse_json_loose(str(message.get("content") or ""))
        if not isinstance(parsed, dict):
            raise ValueError("红队 Agent 未返回可解析的 JSON。")
        raw_findings = (
            parsed.get("findings") if isinstance(parsed.get("findings"), list) else []
        )[:5]
        findings: list[dict[str, Any]] = []
        incomplete_count = 0
        for raw in raw_findings:
            if not isinstance(raw, dict):
                incomplete_count += 1
                continue
            compacted = html_report_compact_value(raw)
            if not isinstance(compacted, dict):
                incomplete_count += 1
                continue
            fails_if = (
                compacted.get("fails_if")
                if isinstance(compacted.get("fails_if"), list)
                else []
            )
            kill_criterion = (
                compacted.get("kill_criterion")
                if isinstance(compacted.get("kill_criterion"), dict)
                else {}
            )
            required_text = [
                compacted.get("claim"),
                compacted.get("decision_enabled"),
                compacted.get("steelman"),
                compacted.get("repair_instruction"),
            ]
            if (
                not all(str(item or "").strip() for item in required_text)
                or not fails_if
                or not str(kill_criterion.get("type") or "").strip()
            ):
                incomplete_count += 1
                continue
            findings.append(compacted)
        decision = str(parsed.get("decision") or "revise").strip().lower()
        severe_findings = [
            item
            for item in findings
            if str(item.get("severity") or "").lower() in {"blocker", "major"}
        ]
        structurally_invalid = bool(raw_findings) and incomplete_count > 0
        approved = decision in {"approve", "approved", "pass", "passed"}
        if severe_findings or structurally_invalid:
            approved = False
        return {
            "schema_version": "report_red_team_review.v1",
            "round": review_round,
            "status": "invalid_response" if structurally_invalid else "ok",
            "decision": "approve" if approved else "revise",
            "approved": approved,
            "summary": compact_text(
                str(parsed.get("summary") or "红队审查已完成。"), 600
            ),
            "reviewed_claim_count": max(
                len(findings),
                int(parsed.get("reviewed_claim_count") or 0)
                if str(parsed.get("reviewed_claim_count") or "0").strip().isdigit()
                else 0,
            ),
            "findings": findings,
            "issues": findings,
            "internal_audit": {
                "raw_finding_count": len(raw_findings),
                "accepted_finding_count": len(findings),
                "incomplete_finding_count": incomplete_count,
            },
            "provider": response.get("provider"),
            "model": response.get("model"),
            "usage": response.get("usage") or {},
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "schema_version": "report_red_team_review.v1",
            "round": review_round,
            "status": "error",
            "decision": "revise",
            "approved": False,
            "summary": f"红队 Agent 调用失败：{compact_text(str(exc), 300)}",
            "reviewed_claim_count": 0,
            "findings": [],
            "issues": [
                {
                    "severity": "major",
                    "category": "red_team_unavailable",
                    "location": "whole_report",
                    "repair_instruction": (
                        "保留已验证事实，只保留证据链最完整的关键结论并删除无证据扩展。"
                    ),
                }
            ],
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }


def revise_html_report_with_llm(
    html_content: str,
    review: dict[str, Any],
    *,
    revision_round: int,
    request_payload: dict[str, Any],
    report_data: dict[str, Any],
    skill_html_template: str,
    required_chart_ids: list[str],
    chart_render_bundle: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    started = time.perf_counter()
    required_chart_id_set = set(required_chart_ids)
    required_chart_specs = [
        chart
        for chart in report_data.get("chart_specs") or []
        if isinstance(chart, dict) and str(chart.get("id") or "") in required_chart_id_set
    ]
    revision_request = {
        "role": "html_report_rendering_agent",
        "revision_round": revision_round,
        "instruction": (
            "Revise the current HTML according to every approval issue. Preserve correct content, styling, "
            "required chart figure positions, evidence handles, and supported prose already in the current HTML. "
            "Recompose chart-backed insights instead of collecting text and charts separately. For every "
            "required_chart_binding, keep its observation immediately above an "
            "insight-chart-layout that contains the bound figure, followed underneath by the interpretation, "
            "business implication, and optional action when those fields are present. "
            "At every viewport, use one column: let each chart occupy the full content width, then place "
            "insight-explanation below it. Ensure compiled SVGs scale to the available width. "
            "For every unbound_required_chart_id, retain the chart and add a specific observation and bounded "
            "interpretation below it using only its chart_spec; add business implication or action only when "
            "the chart supports them. Never create "
            "consecutive chart-only blocks or separate prose/chart batches. "
            "Keep every non_chart_presentations item as structured prose, facts, a definition list, or a compact "
            "table; never turn a text_only dimension into a chart or claim that source count proves "
            "representativeness. "
            "Remove unsupported claims instead of adding missing-data, unavailable-dimension, or unfinished-task "
            "explanations. For every required "
            "chart, retain only a semantic figure with the exact data-chart-id and an empty svg placeholder; "
            "do not draw, label, or modify analytical chart marks because the server will inject the validated "
            "chart after revision. Use only the supplied "
            "ReportData and Skill contract. Use only status=calculated derived_metrics; never recompute "
            "rejected or absent secondary metrics. Return one complete raw HTML document and nothing else."
        ),
        "approval_review": review,
        "report_data": request_payload.get("report_data") or {},
        "report_data_pruning_manifest": (
            request_payload.get("report_data_pruning_manifest") or {}
        ),
        "skill_analysis_contract": request_payload.get("skill_analysis_contract") or "",
        "skill_markdown_excerpt": request_payload.get("skill_markdown_excerpt") or "",
        "required_chart_ids": required_chart_ids,
        "summary_chart_ids": request_payload.get("summary_chart_ids") or [],
        "chart_layout_contract": request_payload.get("chart_layout_contract") or {},
        "output_contract": request_payload.get("output_contract") or {},
        "current_html": html_content,
    }
    try:
        response = call_openai_compatible_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the HTML rendering agent revising a Hsia report after "
                        "independent approval feedback. Return only one complete HTML document. Do not return "
                        "JSON, Markdown, commentary, or a change log. The supplied ReportData is the same "
                        "complete factual review view used by both approval branches; resolve exact-duplicate "
                        "$ref entries through report_data_pruning_manifest.aliases. The current HTML is the "
                        "only current prose source. Do not invent evidence or metrics."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(revision_request, ensure_ascii=False, default=str),
                },
            ],
            max_tokens=HTML_REPORT_MAX_OUTPUT_TOKENS,
        )
        message = response.get("message") if isinstance(response.get("message"), dict) else {}
        revised_html = normalize_llm_html_document(message.get("content"))
        server_rendered_chart_ids: list[str] = []
        if revised_html:
            revised_html, server_rendered_chart_ids = replace_server_rendered_chart_figures(
                revised_html,
                required_chart_specs,
            )
        compiled_chart_ids: list[str] = []
        if revised_html and chart_render_bundle:
            revised_html, compiled_chart_ids = replace_compiled_chart_figures(
                revised_html,
                required_chart_specs,
                chart_render_bundle,
            )
        degraded_chart_ids: list[str] = []
        if revised_html and chart_render_bundle:
            revised_html, degraded_chart_ids = replace_degraded_chart_figures(
                revised_html,
                required_chart_specs,
                chart_render_bundle,
            )
        recovered_chart_ids: list[str] = []
        if revised_html:
            revised_html, recovered_chart_ids = repair_missing_or_empty_chart_figures(
                revised_html,
                required_chart_specs,
            )
        revised_html = enforce_summary_chart_single_column(revised_html)
        validation_error = validate_llm_html_document(
            revised_html,
            skill_html_template,
            required_chart_ids,
        )
        if validation_error:
            return html_content, {
                "round": revision_round,
                "status": "validation_failed",
                "applied": False,
                "message": validation_error,
                "provider": response.get("provider"),
                "model": response.get("model"),
                "finish_reason": response.get("finish_reason"),
                "max_tokens_requested": HTML_REPORT_MAX_OUTPUT_TOKENS,
                "usage": response.get("usage") or {},
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
        return revised_html, {
            "round": revision_round,
            "status": "ok",
            "applied": True,
            "message": "",
            "provider": response.get("provider"),
            "model": response.get("model"),
            "finish_reason": response.get("finish_reason"),
            "max_tokens_requested": HTML_REPORT_MAX_OUTPUT_TOKENS,
            "usage": response.get("usage") or {},
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "server_rendered_chart_ids": server_rendered_chart_ids,
            "compiled_chart_ids": compiled_chart_ids,
            "degraded_chart_ids": degraded_chart_ids,
            "recovered_chart_ids": recovered_chart_ids,
        }
    except Exception as exc:  # noqa: BLE001
        return html_content, {
            "round": revision_round,
            "status": "error",
            "applied": False,
            "message": compact_text(str(exc), 400),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }


def report_insight_chart_bindings(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten validated narrative/chart relationships for rendering and review."""

    narrative = (
        report_data.get("insight_narrative")
        if isinstance(report_data.get("insight_narrative"), dict)
        else {}
    )
    sections = narrative.get("sections") if isinstance(narrative.get("sections"), list) else []
    bindings: list[dict[str, Any]] = []
    seen_chart_ids: set[str] = set()
    chart_specs_by_id = {
        str(chart.get("id")): chart
        for chart in report_data.get("chart_specs") or []
        if isinstance(chart, dict) and chart.get("id")
    }
    unified_chart_insights = (
        narrative.get("chart_insights")
        if isinstance(narrative.get("chart_insights"), list)
        else []
    )
    for insight in unified_chart_insights:
        if not isinstance(insight, dict):
            continue
        chart_id = str(insight.get("chart_id") or "")
        if not chart_id or chart_id in seen_chart_ids:
            continue
        chart_spec = chart_specs_by_id.get(chart_id) or {}
        seen_chart_ids.add(chart_id)
        bindings.append(
            {
                "section_id": str(insight.get("section_id") or "chart_analysis"),
                "section_title": compact_text(
                    str(insight.get("section_title") or "图表分析"), 120
                ),
                "conclusion": compact_text(
                    str(insight.get("conclusion") or chart_spec.get("title") or ""),
                    500,
                ),
                "observation": compact_text(
                    str(insight.get("observation") or ""), 700
                ),
                "interpretation": compact_text(
                    str(insight.get("interpretation") or ""), 700
                ),
                "business_implication": compact_text(
                    str(insight.get("business_implication") or ""), 700
                ),
                "action": compact_text(str(insight.get("action") or ""), 500),
                "evidence_ids": [
                    str(item)
                    for item in insight.get("evidence_ids") or []
                    if str(item)
                ][:12],
                "chart_ids": [chart_id],
                "binding_role": "chart_insight",
                "interpretation_type": str(
                    insight.get("interpretation_type") or "descriptive"
                ),
            }
        )
    if bindings:
        return bindings

    # Backward compatibility for persisted narratives that predate chart_insights.
    for section in sections:
        if not isinstance(section, dict):
            continue
        insights = section.get("insights") if isinstance(section.get("insights"), list) else []
        for insight in insights:
            if not isinstance(insight, dict):
                continue
            chart_ids = [
                str(chart_id)
                for chart_id in insight.get("chart_ids") or []
                if str(chart_id) and str(chart_id) not in seen_chart_ids
            ]
            if not chart_ids:
                continue
            seen_chart_ids.update(chart_ids)
            bindings.append(
                {
                    "section_id": str(section.get("section_id") or ""),
                    "section_title": compact_text(str(section.get("title") or ""), 120),
                    "conclusion": compact_text(str(insight.get("conclusion") or ""), 500),
                    "observation": compact_text(str(insight.get("observation") or ""), 700),
                    "interpretation": compact_text(
                        str(insight.get("interpretation") or ""), 700
                    ),
                    "business_implication": compact_text(
                        str(insight.get("business_implication") or ""), 700
                    ),
                    "action": compact_text(str(insight.get("action") or ""), 500),
                    "evidence_ids": [
                        str(item) for item in insight.get("evidence_ids") or [] if str(item)
                    ][:12],
                    "chart_ids": chart_ids,
                    "binding_role": "chart_insight",
                }
            )
    supplementary = (
        narrative.get("supplementary_chart_insights")
        if isinstance(narrative.get("supplementary_chart_insights"), list)
        else []
    )
    for insight in supplementary:
        if not isinstance(insight, dict):
            continue
        chart_id = str(insight.get("chart_id") or "")
        if not chart_id or chart_id in seen_chart_ids:
            continue
        seen_chart_ids.add(chart_id)
        bindings.append(
            {
                "section_id": str(
                    insight.get("section_id") or "chart_analysis"
                ),
                "section_title": compact_text(
                    str(insight.get("section_title") or "图表分析"), 120
                ),
                "conclusion": compact_text(
                    str(insight.get("conclusion") or ""), 500
                ),
                "observation": compact_text(
                    str(insight.get("observation") or ""), 700
                ),
                "interpretation": compact_text(
                    str(insight.get("interpretation") or ""), 700
                ),
                "business_implication": compact_text(
                    str(insight.get("business_implication") or ""), 700
                ),
                "action": compact_text(str(insight.get("action") or ""), 500),
                "evidence_ids": [
                    str(item)
                    for item in insight.get("evidence_ids") or []
                    if str(item)
                ][:12],
                "chart_ids": [chart_id],
                "binding_role": "chart_insight",
            }
        )
    return bindings


def report_display_chart_specs(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every ready chart; narrative coverage is handled before HTML rendering."""

    return [
        chart
        for chart in report_data.get("chart_specs") or []
        if isinstance(chart, dict)
        and chart.get("id")
        and str(chart.get("quality_status") or "ready") == "ready"
    ]


def report_chart_layout_contract(
    report_data: dict[str, Any], required_chart_ids: list[str]
) -> dict[str, Any]:
    bindings = report_insight_chart_bindings(report_data)
    bound_chart_ids = {
        chart_id
        for binding in bindings
        for chart_id in binding.get("chart_ids") or []
        if chart_id
    }
    return {
        "binding_source": "insight_narrative",
        "required_chart_bindings": bindings,
        "unbound_required_chart_ids": [
            chart_id for chart_id in required_chart_ids if chart_id not in bound_chart_ids
        ],
        "semantic_structure": {
            "section": 'section.insight-section[data-insight-section="<section_id>"]',
            "bound_block": "article.insight-chart-block",
            "conclusion": "h3.insight-conclusion",
            "observation": "p.insight-observation",
            "chart_and_explanation": "div.insight-chart-layout",
            "explanation": "div.insight-explanation",
        },
        "reading_order": [
            "conclusion",
            "observation",
            "chart",
            "interpretation",
            "business_implication",
            "optional_action",
        ],
        "desktop_layout": "single column with a full-width chart above its explanation",
        "mobile_layout": "single column with the chart above its explanation",
        "chart_insight_contract": {
            "one_per_ready_chart": True,
            "required_fields": ["observation", "interpretation"],
            "optional_fields": ["conclusion", "business_implication", "action"],
            "count_limits": None,
        },
        "chart_only_atlas_forbidden": True,
        "separate_text_and_chart_batches_forbidden": True,
        "side_by_side_chart_explanation_forbidden": True,
    }


_REVIEW_REPORT_DATA_AUTHORING_FIELDS = frozenset(
    {
        "insight_narrative",
        "analysis_sections",
        "swot",
        "decision_matrix",
        "artifact",
        "executive_summary",
        "insights",
        "opportunity_pool",
        "next_actions",
    }
)

_REVIEW_REPORT_DATA_RUNTIME_PATHS = frozenset(
    {
        ("metric_analysis", "calculation_audit", "planner", "provider"),
        ("metric_analysis", "calculation_audit", "planner", "model"),
        ("metric_analysis", "calculation_audit", "planner", "usage"),
        ("metric_analysis", "calculation_audit", "planner", "duration_ms"),
    }
)

_REVIEW_REPORT_DATA_GENERATED_PATHS = frozenset(
    {
        ("chart_specs", "[]", "insight"),
    }
)


def _review_report_data_canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _prune_review_report_data_fields(
    value: Any,
    *,
    removed_paths: list[dict[str, str]],
) -> Any:
    """Copy ReportData while deleting only explicitly classified non-fact fields."""

    if not isinstance(value, dict):
        return copy.deepcopy(value)

    copied = copy.deepcopy(value)
    for key in sorted(_REVIEW_REPORT_DATA_AUTHORING_FIELDS):
        if key in copied:
            copied.pop(key)
            removed_paths.append(
                {
                    "path": key,
                    "reason": "stale_authoring_output",
                }
            )

    for field_path in sorted(_REVIEW_REPORT_DATA_RUNTIME_PATHS):
        parent: Any = copied
        for part in field_path[:-1]:
            if not isinstance(parent, dict) or part not in parent:
                parent = None
                break
            parent = parent[part]
        leaf = field_path[-1]
        if isinstance(parent, dict) and leaf in parent:
            parent.pop(leaf)
            removed_paths.append(
                {
                    "path": ".".join(field_path),
                    "reason": "llm_runtime_metadata",
                }
            )

    for field_path in sorted(_REVIEW_REPORT_DATA_GENERATED_PATHS):
        if _remove_review_report_data_path(copied, field_path):
            removed_paths.append(
                {
                    "path": ".".join(field_path).replace(".[]", "[]"),
                    "reason": "stale_chart_authoring_output",
                }
            )
    return copied


def _remove_review_report_data_path(value: Any, field_path: tuple[str, ...]) -> bool:
    if not field_path:
        return False
    part, *remaining = field_path
    if part == "[]":
        if not isinstance(value, list):
            return False
        removed = False
        for item in value:
            removed = _remove_review_report_data_path(
                item, tuple(remaining)
            ) or removed
        return removed
    if not isinstance(value, dict) or part not in value:
        return False
    if not remaining:
        value.pop(part)
        return True
    return _remove_review_report_data_path(value[part], tuple(remaining))


def _review_report_data_path_label(path: tuple[str, ...]) -> str:
    return ".".join(path).replace(".[]", "[]")


def _review_report_data_path_is_removed(path: tuple[str, ...]) -> bool:
    patterns = [
        *((field,) for field in _REVIEW_REPORT_DATA_AUTHORING_FIELDS),
        *_REVIEW_REPORT_DATA_RUNTIME_PATHS,
        *_REVIEW_REPORT_DATA_GENERATED_PATHS,
    ]
    return any(
        len(path) >= len(pattern)
        and all(
            expected == "[]" or expected == actual
            for expected, actual in zip(
                pattern, path[: len(pattern)], strict=True
            )
        )
        for pattern in patterns
    )


def _review_report_data_retained_mutations(
    source: Any,
    retained: Any,
    *,
    path: tuple[str, ...] = (),
) -> tuple[list[str], list[str], list[str]]:
    """Compare source and wire data while ignoring only allow-listed removed paths."""

    if _review_report_data_path_is_removed(path):
        return [], [], []
    path_label = _review_report_data_path_label(path) or "<root>"
    if type(source) is not type(retained):
        string_mutations = (
            [path_label] if isinstance(source, str) or isinstance(retained, str) else []
        )
        collection_mutations = (
            [path_label] if isinstance(source, list) or isinstance(retained, list) else []
        )
        return [path_label], string_mutations, collection_mutations

    mutations: list[str] = []
    string_mutations: list[str] = []
    collection_mutations: list[str] = []
    if isinstance(source, dict):
        source_keys = set(source)
        retained_keys = set(retained)
        for key in sorted(source_keys | retained_keys, key=str):
            child_path = (*path, str(key))
            if _review_report_data_path_is_removed(child_path):
                continue
            if key not in source or key not in retained:
                child_label = _review_report_data_path_label(child_path)
                mutations.append(child_label)
                child_value = source.get(key) if key in source else retained.get(key)
                if isinstance(child_value, str):
                    string_mutations.append(child_label)
                if isinstance(child_value, list):
                    collection_mutations.append(child_label)
                continue
            child_mutations = _review_report_data_retained_mutations(
                source[key],
                retained[key],
                path=child_path,
            )
            mutations.extend(child_mutations[0])
            string_mutations.extend(child_mutations[1])
            collection_mutations.extend(child_mutations[2])
    elif isinstance(source, list):
        if len(source) != len(retained):
            mutations.append(path_label)
            collection_mutations.append(path_label)
        for source_item, retained_item in zip(source, retained, strict=False):
            child_mutations = _review_report_data_retained_mutations(
                source_item,
                retained_item,
                path=(*path, "[]"),
            )
            mutations.extend(child_mutations[0])
            string_mutations.extend(child_mutations[1])
            collection_mutations.extend(child_mutations[2])
    elif source != retained:
        mutations.append(path_label)
        if isinstance(source, str):
            string_mutations.append(path_label)
    return mutations, string_mutations, collection_mutations


def _review_report_data_collection_lengths(
    value: Any,
    *,
    path: str = "",
    result: dict[str, list[int]] | None = None,
) -> dict[str, list[int]]:
    """Collect logical list sizes without copying, truncating, or sampling list items."""

    result = result if result is not None else {}
    if isinstance(value, list):
        if path:
            result.setdefault(path, []).append(len(value))
        child_path = f"{path}[]" if path else "[]"
        for item in value:
            _review_report_data_collection_lengths(item, path=child_path, result=result)
    elif isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            _review_report_data_collection_lengths(child, path=child_path, result=result)
    return result


def _review_report_data_collection_manifest(
    before: dict[str, list[int]],
    after: dict[str, list[int]],
) -> dict[str, dict[str, int]]:
    collection_counts: dict[str, dict[str, int]] = {}
    for path in sorted(set(before) | set(after)):
        before_lengths = before.get(path, [])
        after_lengths = after.get(path, [])
        if len(before_lengths) == 1 and len(after_lengths) == 1:
            collection_counts[path] = {
                "before": before_lengths[0],
                "after": after_lengths[0],
            }
            continue
        collection_counts[path] = {
            "before": sum(before_lengths),
            "after": sum(after_lengths),
            "occurrences_before": len(before_lengths),
            "occurrences_after": len(after_lengths),
        }
    return collection_counts


def _deduplicate_review_report_data(
    pruned_data: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Replace only byte-equivalent non-empty top-level subtrees with explicit aliases."""

    review_data = copy.deepcopy(pruned_data)
    seen: dict[tuple[str, str], tuple[str, str]] = {}
    aliases: list[dict[str, Any]] = []
    for key, value in pruned_data.items():
        if not isinstance(value, list | dict) or not value:
            continue
        canonical_json = _review_report_data_canonical_json(value)
        digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        value_type = "list" if isinstance(value, list) else "dict"
        seen_key = (value_type, digest)
        prior = seen.get(seen_key)
        if prior is None:
            seen[seen_key] = (key, canonical_json)
            continue
        canonical_key, prior_json = prior
        if prior_json != canonical_json:
            continue
        escaped_key = canonical_key.replace("~", "~0").replace("/", "~1")
        item_count = len(value)
        review_data[key] = {
            "$ref": f"#/{escaped_key}",
            "$deduplicated": True,
            "logical_type": value_type,
            "logical_item_count": item_count,
        }
        aliases.append(
            {
                "path": key,
                "canonical_path": canonical_key,
                "sha256": digest,
                "item_count": item_count,
            }
        )
    return review_data, aliases


def _resolve_review_report_data_aliases(
    review_data: dict[str, Any],
    aliases: list[dict[str, Any]],
) -> dict[str, Any]:
    resolved = copy.deepcopy(review_data)
    for alias in aliases:
        path = str(alias.get("path") or "")
        canonical_path = str(alias.get("canonical_path") or "")
        if not path or canonical_path not in resolved:
            continue
        resolved[path] = copy.deepcopy(resolved[canonical_path])
    return resolved


def build_review_report_data(
    report_data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a complete factual approval view without legacy generic compaction.

    Field deletion is allow-listed, exact duplicate subtrees become transparent
    references, and factual collections and strings are never sampled or truncated.
    """

    source_data = report_data if isinstance(report_data, dict) else {}
    removed_paths: list[dict[str, str]] = []
    pruned_data = _prune_review_report_data_fields(
        source_data,
        removed_paths=removed_paths,
    )
    if not isinstance(pruned_data, dict):
        pruned_data = {}

    logical_before_counts = _review_report_data_collection_lengths(pruned_data)
    review_data, aliases = _deduplicate_review_report_data(pruned_data)
    logical_review_data = _resolve_review_report_data_aliases(review_data, aliases)
    logical_after_counts = _review_report_data_collection_lengths(logical_review_data)
    collection_counts = _review_report_data_collection_manifest(
        logical_before_counts,
        logical_after_counts,
    )

    (
        unexpected_mutations,
        unexpected_string_mutations,
        unexpected_collection_mutations,
    ) = _review_report_data_retained_mutations(source_data, logical_review_data)
    unexpected_mutations = sorted(set(unexpected_mutations))
    unexpected_string_mutations = sorted(set(unexpected_string_mutations))
    unexpected_collection_mutations = sorted(set(unexpected_collection_mutations))

    collection_mismatch = any(
        counts.get("before") != counts.get("after")
        or counts.get("occurrences_before", 1) != counts.get("occurrences_after", 1)
        for counts in collection_counts.values()
    )
    source_json = _review_report_data_canonical_json(source_data)
    review_json = _review_report_data_canonical_json(review_data)
    manifest = {
        "schema_version": "review_report_data_pruning.v1",
        "source_schema_version": str(source_data.get("schema_version") or ""),
        "source_sha256": hashlib.sha256(source_json.encode("utf-8")).hexdigest(),
        "review_data_sha256": hashlib.sha256(review_json.encode("utf-8")).hexdigest(),
        "original_chars": len(source_json),
        "review_chars": len(review_json),
        "facts_sampled": collection_mismatch or bool(unexpected_collection_mutations),
        "strings_truncated": bool(unexpected_string_mutations),
        "retained_subtrees_equal": not unexpected_mutations,
        "unexpected_mutations": unexpected_mutations,
        "unexpected_string_mutations": unexpected_string_mutations,
        "unexpected_collection_mutations": unexpected_collection_mutations,
        "removed_paths": removed_paths,
        "aliases": aliases,
        "collection_counts": collection_counts,
    }
    return review_data, manifest


def report_review_chart_layout_contract(
    report_data: dict[str, Any], required_chart_ids: list[str]
) -> dict[str, Any]:
    """Retain chart placement bindings without leaking prior generated prose."""

    contract = report_chart_layout_contract(report_data, required_chart_ids)
    contract["required_chart_bindings"] = [
        {
            "chart_ids": [
                str(chart_id)
                for chart_id in binding.get("chart_ids") or []
                if str(chart_id) in required_chart_ids
            ],
            "binding_role": "required_chart",
        }
        for binding in contract.get("required_chart_bindings") or []
        if isinstance(binding, dict)
        and any(
            str(chart_id) in required_chart_ids
            for chart_id in binding.get("chart_ids") or []
        )
    ]
    contract["binding_source"] = "insight_narrative_structure_only"
    return contract


def report_approval_request_payload(
    payload: dict[str, Any], report_data: dict[str, Any]
) -> dict[str, Any]:
    skill_markdown = str(payload.get("skillMarkdown") or "")
    review_report_data, pruning_manifest = build_review_report_data(report_data)
    required_chart_ids = [
        str(chart.get("id")) for chart in report_display_chart_specs(report_data)
    ]
    required_chart_id_set = set(required_chart_ids)
    chart_layout_contract = report_review_chart_layout_contract(
        report_data, required_chart_ids
    )
    return {
        "report_data": review_report_data,
        "report_data_pruning_manifest": pruning_manifest,
        "skill_analysis_contract": html_report_analysis_contract(skill_markdown),
        "skill_markdown_excerpt": compact_text(skill_markdown, 5200),
        "required_chart_ids": required_chart_ids,
        "summary_chart_ids": (
            [
                str(chart_id)
                for chart_id in report_data.get("summary_chart_ids") or []
                if str(chart_id) in required_chart_id_set
            ]
            if isinstance(report_data.get("summary_chart_ids"), list)
            else []
        ),
        "chart_layout_contract": chart_layout_contract,
        "output_contract": {
            "format": "raw_html_only",
            "complete_document": True,
            "inline_css_required": True,
            "javascript_forbidden": True,
            "chart_placeholders_required": bool(required_chart_ids),
            "server_managed_svg_injection": bool(required_chart_ids),
            "external_dependencies_forbidden": True,
            "insight_chart_interleaving_required": bool(required_chart_ids),
        },
    }


def review_html_report_node(payload: dict[str, Any]) -> dict[str, Any]:
    report_data = (
        payload.get("reportData")
        if isinstance(payload.get("reportData"), dict)
        else payload.get("marketReportData")
        if isinstance(payload.get("marketReportData"), dict)
        else {}
    )
    return review_html_report_with_llm(
        str(payload.get("html") or ""),
        review_round=max(1, int(payload.get("reviewRound") or 1)),
        request_payload=report_approval_request_payload(payload, report_data),
    )


def red_team_html_report_node(payload: dict[str, Any]) -> dict[str, Any]:
    report_data = (
        payload.get("reportData")
        if isinstance(payload.get("reportData"), dict)
        else payload.get("marketReportData")
        if isinstance(payload.get("marketReportData"), dict)
        else {}
    )
    return red_team_html_report_with_llm(
        str(payload.get("html") or ""),
        review_round=max(1, int(payload.get("reviewRound") or 1)),
        request_payload=report_approval_request_payload(payload, report_data),
    )


def revise_html_report_node(payload: dict[str, Any]) -> dict[str, Any]:
    report_data = (
        payload.get("reportData")
        if isinstance(payload.get("reportData"), dict)
        else payload.get("marketReportData")
        if isinstance(payload.get("marketReportData"), dict)
        else {}
    )
    request_payload = report_approval_request_payload(payload, report_data)
    revised_html, revision = revise_html_report_with_llm(
        str(payload.get("html") or ""),
        payload.get("review") if isinstance(payload.get("review"), dict) else {},
        revision_round=max(1, int(payload.get("revisionRound") or 1)),
        request_payload=request_payload,
        report_data=report_data,
        skill_html_template=str(payload.get("skillHtmlTemplate") or ""),
        required_chart_ids=[
            str(item) for item in request_payload.get("required_chart_ids") or [] if str(item)
        ],
        chart_render_bundle=(
            payload.get("chartRenderBundle")
            if isinstance(payload.get("chartRenderBundle"), dict)
            else {}
        ),
    )
    return {
        "html": revised_html,
        "revision": revision,
    }


# Backward-compatible aliases for persisted tests and callers from older runs.
weekly_market_review_is_approved = report_review_is_approved
review_weekly_market_html_with_llm = review_html_report_with_llm
revise_weekly_market_html_with_llm = revise_html_report_with_llm
weekly_market_approval_request_payload = report_approval_request_payload
review_weekly_market_html_node = review_html_report_node
revise_weekly_market_html_node = revise_html_report_node


def html_report_supported_data_context(report_data: dict[str, Any]) -> dict[str, Any]:
    context = dict(report_data)
    for key in (
        "analysis_sections",
        "swot",
        "decision_matrix",
        "data_gaps",
        "metric_gaps",
        "evidence_gaps",
        "report_quality",
        "source_notes",
        "warnings",
    ):
        context.pop(key, None)
    artifact = context.get("artifact")
    if isinstance(artifact, dict):
        context["artifact"] = {
            key: value
            for key, value in artifact.items()
            if key not in {"risks", "data_gaps", "warnings"}
        }
    return context


def compose_html_report_with_llm(
    payload: dict[str, Any],
    *,
    locale: str = "zh",
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    chart_render_bundle = (
        payload.get("chartRenderBundle")
        if isinstance(payload.get("chartRenderBundle"), dict)
        else {}
    )
    market_report_data = (
        payload.get("marketReportData") if isinstance(payload.get("marketReportData"), dict) else {}
    )
    tiktok_new_product_report_data = (
        payload.get("tiktokNewProductReportData")
        if isinstance(payload.get("tiktokNewProductReportData"), dict)
        else {}
    )
    tiktok_competitor_shop_report_data = (
        payload.get("tiktokCompetitorShopReportData")
        if isinstance(payload.get("tiktokCompetitorShopReportData"), dict)
        else {}
    )
    trend_report_data = (
        payload.get("trendReportData") if isinstance(payload.get("trendReportData"), dict) else {}
    )
    competitor_product_report_data = (
        payload.get("competitorProductReportData")
        if isinstance(payload.get("competitorProductReportData"), dict)
        else {}
    )
    hot_product_pain_report_data = (
        payload.get("hotProductPainReportData")
        if isinstance(payload.get("hotProductPainReportData"), dict)
        else {}
    )
    report_data = (
        competitor_product_report_data
        or hot_product_pain_report_data
        or tiktok_competitor_shop_report_data
        or tiktok_new_product_report_data
        or market_report_data
        or trend_report_data
    )
    tool_results = (
        []
        if report_data
        else (payload.get("toolResults") if isinstance(payload.get("toolResults"), list) else [])
    )
    style_reference = html_report_style_reference(payload.get("skillMarkdown"))
    analysis_contract = html_report_analysis_contract(payload.get("skillMarkdown"))
    skill_html_template = str(payload.get("skillHtmlTemplate") or "")
    skill_id = str(payload.get("skillId") or "")
    configured_skill = AGENT_SKILL_REGISTRY.get(skill_id)
    configured_evidence = (
        configured_skill.get("evidence_contract")
        if isinstance(configured_skill, dict)
        and isinstance(configured_skill.get("evidence_contract"), list)
        else []
    )
    requires_html_builder = bool(
        any(
            isinstance(rule, dict)
            and str(rule.get("tool") or "") == "render_html_report"
            and str(rule.get("severity") or "") == "block"
            for rule in configured_evidence
        )
        and any(
            isinstance(rule, dict)
            and str(rule.get("tool") or "").startswith("build_")
            and str(rule.get("tool") or "").endswith("report_data")
            and str(rule.get("severity") or "") == "block"
            for rule in configured_evidence
        )
    )
    if requires_html_builder and not report_data:
        return (
            "",
            {},
            {
                "enabled": False,
                "status": "missing_report_data",
                "message": (
                    f"{skill_id} requires versioned report data from its declared builder; "
                    "raw tool results cannot be rendered."
                ),
            },
        )
    required_product_image_urls: list[str] = []
    required_review_image_urls: list[str] = []
    review_image_evidence: list[dict[str, Any]] = []
    available_review_image_count = 0
    required_trend_visuals = [
        item
        for item in trend_report_data.get("visual_evidence") or []
        if isinstance(item, dict) and item.get("visual_id") and item.get("image_url")
    ][:TREND_MAX_REPORT_IMAGES]
    trend_visual_prompt_items = [
        {
            "visual_id": item.get("visual_id"),
            "image_url": item.get("image_url"),
            "platform_id": item.get("platform_id"),
            "source_page_title": item.get("source_page_title"),
            "source_page_url": item.get("source_page_url"),
            "published_at": item.get("published_at"),
            "alt_text": item.get("alt_text"),
            "query_dimensions": item.get("query_dimensions") or [],
        }
        for item in required_trend_visuals
    ]
    if skill_id == "hot_product_pain_analysis":
        required_product_image_urls = [
            str(item)
            for item in hot_product_pain_report_data.get("required_product_image_urls") or []
            if str(item)
        ]
        required_review_image_urls = [
            str(item)
            for item in hot_product_pain_report_data.get("required_review_image_urls") or []
            if str(item)
        ]
    elif skill_id == "competitor_product_deep_dive":
        review_image_evidence = [
            item
            for item in competitor_product_report_data.get("review_image_evidence") or []
            if isinstance(item, dict)
        ]
        coverage = (
            competitor_product_report_data.get("review_image_coverage")
            if isinstance(competitor_product_report_data.get("review_image_coverage"), dict)
            else {}
        )
        available_review_image_count = int(
            coverage.get("available_unique_image_count") or len(review_image_evidence)
        )
        required_review_image_urls = [
            str(item.get("image_url") or "") for item in review_image_evidence
        ]
    if not report_data and not tool_results:
        return (
            "",
            {},
            {
                "enabled": False,
                "status": "skipped",
                "message": "No report data or tool evidence was supplied.",
            },
        )
    report_context: dict[str, Any] = {
        "skill_id": payload.get("skillId"),
        "category": payload.get("category"),
        "brand": payload.get("brand"),
        "marketplace": payload.get("marketplace"),
        "time_range": payload.get("timeRange") or payload.get("time_range"),
        "generated_at": payload.get("generatedAt"),
        "mode": payload.get("mode"),
    }
    if competitor_product_report_data:
        report_context["competitor_product_report_data"] = html_report_supported_data_context(
            competitor_product_report_data
        )
        report_context["report_data_schema"] = (
            competitor_product_report_data.get("schema_version")
            or "competitor_product_report_data"
        )
    elif hot_product_pain_report_data:
        report_context["hot_product_pain_report_data"] = html_report_supported_data_context(
            hot_product_pain_report_data
        )
        report_context["report_data_schema"] = (
            hot_product_pain_report_data.get("schema_version")
            or "hot_product_pain_report_data"
        )
    elif tiktok_competitor_shop_report_data:
        report_context["tiktok_competitor_shop_report_data"] = (
            html_report_supported_data_context(tiktok_competitor_shop_report_data)
        )
        report_context["report_data_schema"] = (
            tiktok_competitor_shop_report_data.get("schema_version")
            or "tiktok_bra_competitor_shop_report_data"
        )
    elif tiktok_new_product_report_data:
        report_context["tiktok_new_product_report_data"] = html_report_supported_data_context(
            tiktok_new_product_report_data
        )
        report_context["report_data_schema"] = (
            tiktok_new_product_report_data.get("schema_version") or "tiktok_new_product_report_data"
        )
    elif market_report_data:
        report_context["market_report_data"] = market_report_llm_context(market_report_data)
        report_context["report_data_schema"] = (
            market_report_data.get("schema_version") or "market_report_data"
        )
    elif trend_report_data:
        report_context["trend_report_data"] = trend_report_llm_context(trend_report_data)
        report_context["report_data_schema"] = (
            trend_report_data.get("schema_version") or "trend_report_data"
        )
    else:
        report_context["tool_results"] = html_report_compact_tool_results(tool_results)
    if report_data:
        report_context["insight_narrative"] = html_report_insight_narrative_context(
            report_data.get("insight_narrative") or {}
        )
        report_context["secondary_metric_analysis"] = {
            "derived_metrics": html_report_compact_value(
                report_data.get("derived_metrics") or []
            ),
            "calculation_audit": html_report_compact_value(
                (report_data.get("metric_analysis") or {}).get("calculation_audit")
                if isinstance(report_data.get("metric_analysis"), dict)
                else {}
            ),
            "contract": (
                "Use only status=calculated derived_metrics as secondary metrics. "
                "Do not calculate replacements from raw fields. Silently omit unavailable metrics."
            ),
        }
    if skill_id == "competitor_product_deep_dive":
        report_context["review_image_evidence"] = review_image_evidence
        report_context["review_image_coverage"] = {
            "available_unique_image_count": available_review_image_count,
            "selected_image_count": len(review_image_evidence),
            "report_image_limit": competitor_review_image_limit(payload),
            "selection_method": "distinct_reviews_first_then_additional_images",
        }

    required_sections = html_template_required_sections(skill_html_template)
    required_chart_specs = report_display_chart_specs(report_data)
    required_chart_ids = [str(chart.get("id")) for chart in required_chart_specs]
    required_chart_id_set = set(required_chart_ids)
    precompiled_chart_ids = [
        str(item.get("chart_id"))
        for item in chart_render_bundle.get("charts") or []
        if isinstance(item, dict)
        and str(item.get("status") or "") == "rendered"
        and item.get("chart_id")
    ]
    chart_layout_contract = report_chart_layout_contract(report_data, required_chart_ids)
    request_payload = {
        "language": "Chinese" if locale == "zh" else "English",
        "user_prompt": payload.get("prompt") or "",
        "skill_markdown_excerpt": compact_text(str(payload.get("skillMarkdown") or ""), 5200),
        "skill_analysis_contract": analysis_contract,
        "style_reference_from_skill": style_reference,
        "skill_html_template": compact_text(skill_html_template, 18000),
        "required_template_sections": required_sections,
        "required_chart_ids": required_chart_ids,
        "precompiled_chart_ids": precompiled_chart_ids,
        "summary_chart_ids": (
            [
                str(chart_id)
                for chart_id in report_data.get("summary_chart_ids") or []
                if str(chart_id) in required_chart_id_set
            ]
            if isinstance(report_data.get("summary_chart_ids"), list)
            else []
        ),
        "chart_layout_contract": chart_layout_contract,
        "required_product_image_urls": required_product_image_urls,
        "required_review_image_urls": required_review_image_urls,
        "required_trend_visuals": trend_visual_prompt_items,
        **report_context,
        "output_contract": {
            "format": "raw_html_only",
            "complete_document": True,
            "inline_css_required": True,
            "javascript_forbidden": True,
            "chart_placeholders_required": bool(required_chart_ids),
            "server_managed_svg_injection": bool(required_chart_ids),
            "external_dependencies_forbidden": True,
            "insight_chart_interleaving_required": bool(required_chart_ids),
            "trend_visual_whitelist_required": bool(required_trend_visuals),
            "server_rendered_review_gallery_required": bool(review_image_evidence),
        },
    }
    if trend_report_data:
        system_content = (
            "You are a senior fashion-trend editor and visual design director for Hsia. "
            "Return only one complete HTML document beginning with <!doctype html> and ending with </html>. "
            "Do not return JSON, Markdown fences, commentary, or explanations outside the HTML. "
            "Use static HTML and inline CSS only; do not include JavaScript, canvas, external scripts, "
            "stylesheets, fonts, CSS imports, CDNs, or CSS image URLs. "
            "Create an editorial inspiration report for apparel designers, not an audit or data-analysis report. "
            "Open with a concise creative direction, then build 4–6 visually distinct trend stories. Each story "
            "must include a mood narrative, colour palette and suggested use, fabric/material/texture direction, "
            "silhouette or construction details, and 2–4 concrete prompts that can move into sketching or sourcing. "
            "Organize images inside the most relevant trend story instead of grouping them by WGSN, DICTION, or "
            "Pinterest. Aim for 6–10 relevant images per story when enough approved visuals exist; when there are "
            "fewer, use fewer and keep the layout intentional. Never duplicate an image or fill with an unrelated one. "
            "Use current-window source signals first and current/upcoming-season material as creative context. Do not "
            "turn publication status, source counts, query counts, access limitations, or platform coverage into a "
            "headline, KPI, warning panel, or standalone section. Forbidden sections include evidence boundaries, "
            "validation matrices, data-completeness or unfinished-task notices, coverage tables, and cross-source audit "
            "matrices. Do not display internal evidence ids, relevance labels, recency labels, or collection diagnostics. "
            "Keep attribution light: show platform, actual publication date when supplied, source-page title, and link "
            "in a small figcaption or a compact source index at the end. "
            "Use source_material text for trend interpretation and visual_inspiration for art direction; do not invent "
            "trend claims, dates, metrics, quotations, source URLs, or image URLs, and do not infer a trend from an image "
            "alone. Render every required_trend_visuals item exactly once as a semantic "
            '<figure data-visual-id="..."> containing an <img> with its exact approved image_url and a source link. '
            "Do not use any other image URL. The result should feel like a polished fashion moodbook: image-led, "
            "specific, generous in visual rhythm, and immediately useful to a design team."
        )
    elif tiktok_competitor_shop_report_data:
        system_content = (
            "You are a senior TikTok Shop US competitive-intelligence editor and HTML artifact "
            "designer for Hsia. Return only one complete HTML document beginning with <!doctype "
            "html> and ending with </html>. Do not return JSON, Markdown fences, commentary, or "
            "text outside the HTML. Use static HTML and inline CSS only; "
            "do not use JavaScript, canvas, external scripts, stylesheets, fonts, CSS imports, "
            "or CDNs. Use only tiktok_competitor_shop_report_data. Open with a compact reader-first "
            "summary naming the real scale threat, fastest-growing shop, shared playbook, and the "
            "most actionable Hsia response. Then render: competitor landscape, the 10-shop "
            "same-basis comparison table, product-portfolio and price-band comparison, channel and "
            "creator structures, shop-by-shop strengths and weak spots, and an Hsia learn/defend/"
            "attack/validate action matrix. Keep methodology and source scope concise; omit unavailable "
            "dimensions rather than writing data-gap, unfinished-task, evidence-matrix, or warning sections. "
            "Distinguish the completed-month L3 Bras ranking "
            "snapshot from trailing-28-day shop analyses. Treat ranking and product rows as Bras "
            "scoped, but never relabel whole-shop base, channel, trend, or creator metrics as "
            "bra-only metrics. Treat observed product and creator concentration as returned-sample "
            "concentration when that is the declared denominator. Do not invent ad spend, market "
            "size, demographics, causal attribution, missing shops, metrics, products, creators, or "
            "URLs. Use the supplied FastMoss URLs for shop and product links. The main comparison "
            "table must keep Shop and seller_id as separate visible columns and must show missing "
            "values as unknown. Every conclusion must land on a so-what: learnable playbook, threat "
            "to defend against, weak spot to attack, or evidence to validate. The result should feel "
            "like a concise competitor war-room brief, not a tool log."
        )
    elif tiktok_new_product_report_data:
        system_content = (
            "You are a senior TikTok Shop US product-planning editor and HTML artifact designer "
            "for Hsia. Return only one complete HTML document beginning with <!doctype html> and "
            "ending with </html>. Do not return JSON, Markdown fences, commentary, or text outside "
            "the HTML. Use static HTML and inline CSS only; do not use "
            "JavaScript, canvas, external scripts, stylesheets, fonts, CSS imports, or CDNs. "
            "Use only tiktok_new_product_report_data; do not infer market size, search demand, "
            "customer demographics, creator causality, or entry recommendations from this dataset. "
            "Open with a compact reader-first summary and KPI row, then present the new-product sales "
            "ranking, Top-product analysis cards, cross-product feature patterns and product-planning "
            "implications, followed by a compact source-and-method note. Omit unavailable dimensions "
            "instead of displaying data-gap, coverage, evidence-matrix, unfinished-task, execution-audit, "
            "or warning sections. Use total_units_sold only for the main rank; distinguish first-3-day "
            "performance, units_per_day_since_launch, and L7/P7 trend. Treat anomaly_flags as review "
            "cautions, not automatic exclusions. Render product images only from image_url and link "
            "product names only to the supplied fastmoss_url. Do not invent product features: use "
            "feature_tags and their evidence. Missing optional product fields and dependent claims must be omitted "
            "from prose rather than explained as gaps. When daily_trend is visualized, use the supplied complete "
            "dates and values exactly. The new-product ranking must render every field declared in "
            "output_contract.new_product_ranking_required_columns as a visible table column. Never merge, "
            "rename away, or omit the separate Shop Name and shop_id columns; show missing values as unknown. "
            "All candidate rows have already passed the inclusive USD 20–100 price filter; do not restore "
            "or discuss excluded products as candidates. The result should feel like a polished, concise product-planning "
            "weekly report rather than a system audit."
        )
    else:
        system_content = (
            "You are a senior product and R&D insight editor and HTML artifact designer for Hsia. "
            "Return only one complete HTML document beginning with <!doctype html> and ending with </html>. "
            "Do not return JSON, Markdown fences, commentary, or explanations outside the HTML. "
            "Use static HTML and inline CSS only. Do not include JavaScript or canvas; "
            "the report preview is sandboxed and scripts never execute. Do not load external scripts, stylesheets, "
            "fonts, CSS imports, or CDNs. External product/review images are allowed only when their URLs "
            "appear in the supplied evidence. Do not invent metrics, ranks, ASINs, market size, search volume, "
            "sales, review quotes, or image URLs. Every important claim must show a nearby evidence handle. "
            "Use insight_narrative as the reader-facing analytical spine: render its supported conclusion, "
            "observation, and interpretation near the relevant chart or table; render business implication and "
            "action only when those optional fields are present. "
            "Do not turn missing evidence, rejected metrics, unavailable dimensions, prior attempts, or omitted "
            "execution history into visible prose; silently omit the dependent conclusion instead. "
            "Treat tool_methodology and MCP descriptions only as instructions for how to analyze a tool's actual data; "
            "they are never evidence. Respect each analysis dimension's allowed_conclusion and limitation. "
            "Disclose only the actual market, period, sample, and deduplication scope used by visible conclusions; "
            "do not display P0 task coverage or missing-task status. When deduplication.scope is product_identity_only, "
            "only product family counts carrying family_id may be described as unique; never extend that claim to "
            "keywords, reviews, sellers, brands, or total market size. When deduplication.applied is false, never "
            "describe row counts as deduplicated unique keywords, products, listings, sellers, brands, or total market size."
            " A degraded internal evidence state must not create a visible data-completeness or unfinished-task "
            "section. Keep source scope concise, preserve supported analysis, and omit only the conclusions that "
            "depend on unavailable evidence. Never abandon the whole report because one market task or chart is "
            "unavailable."
            " Treat summary_chart_ids as ordering priorities, not as a separate chart gallery. Place each summary "
            "chart exactly once, inside its complete chart-backed insight block near the executive section when it "
            "explains an executive insight; otherwise keep it in the analysis section whose prose interprets it. "
            "Place every remaining required chart inside the analysis section whose prose interprets it; "
            "multiple charts may share a section only when each chart has its own "
            "observation and interpretation directly below it; business implication is optional. "
            "For hot-product pain reports, render every supplied required product image URL and required review image URL "
            "as an <img> near its matching product or review evidence. "
            "For competitor deep-dive reports, review_image_evidence and required_review_image_urls are rendered by the "
            "server as one exact buyer-image gallery inside the fit-voc section. Use their metadata for analysis, but do "
            "not create a second review-image gallery or alter those URLs."
        )
    system_content += (
        " For secondary metrics, use only entries in secondary_metric_analysis.derived_metrics "
        "whose status is calculated. Never recompute a rejected or absent metric from primary fields, "
        "and silently omit rejected or absent metrics. Expand each supported insight into readable prose "
        "instead of reducing the report to chart captions or KPI cards. Do not add a visible list of omitted "
        "dimensions, missing data, or unfinished tasks. Treat chart_layout_contract as mandatory for every "
        "report type. Do not group narrative first and charts later. For each chart-backed insight, create one "
        '<section class="insight-section" data-insight-section="..."> containing an '
        '<article class="insight-chart-block">. Put its conclusion in h3.insight-conclusion and its supported '
        "observation in p.insight-observation. Immediately after them, create div.insight-chart-layout containing "
        "the bound figure(s), followed by div.insight-explanation with the interpretation, business implication, "
        "and optional action when those fields are present. Add CSS that keeps "
        ".insight-chart-layout in one column at every viewport: each figure must use the full available content "
        "width and insight-explanation must sit underneath it. Add a responsive rule such as "
        ".compiled-chart-svg svg{display:block;width:100%;height:auto} so the validated SVG grows with the report "
        "column instead of staying at its intrinsic width. Text-only insights may use compact "
        "article.insight-text-block elements in the relevant analysis section. A multi-chart analysis "
        "section is allowed only when every chart is wrapped in its own insight-chart-block and followed by "
        "specific observation and interpretation; business implication and action appear only when supported. "
        "Never produce two consecutive chart-only blocks, "
        "a prose batch followed by a chart batch, or a detached caption that merely repeats the title."
        " Treat non_chart_presentations as mandatory non-chart presentation contracts. Render scope summaries as "
        "compact definition lists or scope cards, and sample audits as compact facts or a small table only when "
        "multiple sources exist. Never convert them into SVG charts. Never label a sample representative merely "
        "because it has a source count; use the supplied sample scope and deduplication wording."
    )
    if required_chart_ids:
        system_content += (
            " Only create analytical chart figures for ids listed in required_chart_ids. For every required "
            "id, place a semantic figure with the exact data-chart-id and an empty inline svg placeholder at "
            "the correct narrative location. Follow chart_layout_contract.required_chart_bindings exactly: "
            "place each bound chart in the same insight-chart-block as its supplied observation and interpretation, "
            "plus any supported conclusion, business implication, or action. If unbound_required_chart_ids is non-empty, "
            "keep those charts and derive a complete nearby block from the supplied chart_spec only: state a "
            "specific observation and bounded interpretation below the chart, with business implication only when "
            "supported. Never leave "
            "a chart with only its title, source, or generic methodology caption. "
            "When a chart_spec has placement.section_hint, use that business section unless a validated binding "
            "specifies a more precise insight section. Do not create a separate summary-chart gallery: a "
            "summary_chart_id is the same chart-backed insight, merely prioritized earlier in the report. "
            "Every data-chart-id must appear exactly once in the entire document. Never duplicate the same data-chart-id. "
            "Do not redraw, relabel, alter, or derive new chart data, and do not invent additional analytical SVG charts. "
            "The server will replace each placeholder with a validated MCP SVG or deterministic fallback "
            "before HTML validation and review."
        )
    else:
        system_content += (
            " No chart_specs were supplied. Do not invent analytical SVG charts from prose or raw fields; "
            "use compact tables, text, or ordinary KPI cards instead."
        )
    system_message: dict[str, Any] = {"role": "system", "content": system_content}
    messages: list[dict[str, Any]] = [
        system_message,
        {
            "role": "user",
            "content": json.dumps(request_payload, ensure_ascii=False, default=str),
        },
    ]
    input_profile = {
        "request_chars": sum(len(str(message.get("content") or "")) for message in messages),
        "max_tokens_requested": HTML_REPORT_MAX_OUTPUT_TOKENS,
        "market_report_chars": len(
            json.dumps(
                report_context.get("market_report_data") or {}, ensure_ascii=False, default=str
            )
        ),
        "trend_report_chars": len(
            json.dumps(
                report_context.get("trend_report_data") or {}, ensure_ascii=False, default=str
            )
        ),
        "tiktok_new_product_report_chars": len(
            json.dumps(
                report_context.get("tiktok_new_product_report_data") or {},
                ensure_ascii=False,
                default=str,
            )
        ),
        "tiktok_competitor_shop_report_chars": len(
            json.dumps(
                report_context.get("tiktok_competitor_shop_report_data") or {},
                ensure_ascii=False,
                default=str,
            )
        ),
        "tool_results_chars": len(
            json.dumps(report_context.get("tool_results") or [], ensure_ascii=False, default=str)
        ),
        "skill_excerpt_chars": len(str(request_payload.get("skill_markdown_excerpt") or "")),
        "skill_analysis_contract_chars": len(
            str(request_payload.get("skill_analysis_contract") or "")
        ),
        "template_chars": len(str(request_payload.get("skill_html_template") or "")),
    }
    attempts: list[dict[str, Any]] = []
    last_error = "LLM did not return a usable self-contained HTML report."
    last_meta: dict[str, Any] = {}
    for attempt_index in range(1, 3):
        attempt_started = time.perf_counter()
        attempt_request_chars = sum(len(str(message.get("content") or "")) for message in messages)
        try:
            response = call_openai_compatible_chat(
                messages,
                max_tokens=HTML_REPORT_MAX_OUTPUT_TOKENS,
            )
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
            return (
                "",
                {},
                {
                    "enabled": True,
                    "status": "unavailable",
                    "message": str(exc),
                    "input_profile": input_profile,
                    "attempt_count": len(attempts),
                    "attempts": attempts,
                },
            )
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
            return (
                "",
                {},
                {
                    "enabled": True,
                    "status": "error",
                    "message": str(exc),
                    "input_profile": input_profile,
                    "attempt_count": len(attempts),
                    "attempts": attempts,
                },
            )

        message = response.get("message") if isinstance(response.get("message"), dict) else {}
        raw_content = str(message.get("content") or "")
        html_content = normalize_llm_html_document(raw_content)
        server_rendered_chart_ids: list[str] = []
        if html_content and report_data:
            html_content, server_rendered_chart_ids = replace_server_rendered_chart_figures(
                html_content,
                required_chart_specs,
            )
        compiled_chart_ids: list[str] = []
        if html_content and report_data and chart_render_bundle:
            html_content, compiled_chart_ids = replace_compiled_chart_figures(
                html_content,
                required_chart_specs,
                chart_render_bundle,
            )
        degraded_chart_ids: list[str] = []
        if html_content and report_data and chart_render_bundle:
            html_content, degraded_chart_ids = replace_degraded_chart_figures(
                html_content,
                required_chart_specs,
                chart_render_bundle,
            )
        recovered_chart_ids: list[str] = []
        if html_content and report_data:
            html_content, recovered_chart_ids = repair_missing_or_empty_chart_figures(
                html_content,
                required_chart_specs,
            )
        html_content = enforce_summary_chart_single_column(html_content)
        recovered_visual_ids: list[str] = []
        if html_content and required_trend_visuals and attempt_index == 2:
            html_content, recovered_visual_ids = ensure_trend_visual_atlas(
                html_content,
                required_trend_visuals,
            )
        rendered_review_image_count = 0
        if html_content and skill_id == "competitor_product_deep_dive":
            html_content, rendered_review_image_count = ensure_competitor_review_image_gallery(
                html_content,
                review_image_evidence,
                available_count=available_review_image_count,
            )
        validation_error = validate_llm_html_document(
            html_content,
            skill_html_template,
            required_chart_ids,
            required_trend_visuals,
        )
        if not validation_error and tiktok_new_product_report_data:
            validation_error = validate_tiktok_new_product_table_markup(html_content)
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
        if (
            not validation_error
            and skill_id == "competitor_product_deep_dive"
            and review_image_evidence
        ):
            gallery_heading_count = len(re.findall(r"评论区\s*买家返图", html_content))
            duplicated_review_urls = [
                url for url in required_review_image_urls if html_content.count(url) > 1
            ]
            if gallery_heading_count != 1 or duplicated_review_urls:
                validation_error = (
                    "Competitor deep-dive HTML must contain exactly one server-rendered buyer-image gallery; "
                    "do not create review-image modules or repeat review image URLs in model-generated HTML."
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
            approval_analysis: dict[str, Any] = {
                "enabled": True,
                "policy": "two_parallel_review_rounds",
                "orchestrator": "langgraph_nodes",
                "status": "pending_langgraph_review",
                "approved": False,
                "published_without_approval": False,
                "review_count": 0,
                "red_team_count": 0,
                "revision_count": 0,
                "render_version_count": 1,
                "reviews": [],
                "red_teams": [],
                "revisions": [],
            }
            artifact = html_report_base_artifact(payload, report_data, tool_results)
            title_match = re.search(
                r"<title[^>]*>(.*?)</title>", html_content, flags=re.IGNORECASE | re.DOTALL
            )
            html_title = (
                html.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip()
                if title_match
                else ""
            )
            artifact.setdefault("title", report_data.get("title") or html_title or "HTML 报告")
            artifact.setdefault("executive_summary", report_data.get("executive_summary") or "")
            return (
                html_content,
                artifact,
                {
                    "enabled": True,
                    "status": "ok",
                    **last_meta,
                    "input_profile": input_profile,
                    "attempt_count": len(attempts),
                    "attempts": attempts,
                    "quality_notes": [
                        *(
                            [
                                f"Deterministically rendered chart(s): {', '.join(server_rendered_chart_ids)}."
                            ]
                            if server_rendered_chart_ids
                            else []
                        ),
                        *(
                            [
                                f"Injected Flint MCP chart(s): {', '.join(compiled_chart_ids)}."
                            ]
                            if compiled_chart_ids
                            else []
                        ),
                        *(
                            [
                                "Used deterministic fallback for chart(s): "
                                f"{', '.join(degraded_chart_ids)}."
                            ]
                            if degraded_chart_ids
                            else []
                        ),
                        *(
                            [
                                f"Recovered missing or empty chart(s): {', '.join(recovered_chart_ids)}."
                            ]
                            if recovered_chart_ids
                            else []
                        ),
                        *(
                            [
                                f"Recovered missing trend visual(s): {', '.join(recovered_visual_ids)}."
                            ]
                            if recovered_visual_ids
                            else []
                        ),
                        *(
                            [
                                "Deterministically rendered "
                                f"{rendered_review_image_count}/{available_review_image_count} unique review image(s)."
                            ]
                            if rendered_review_image_count
                            else []
                        ),
                    ],
                    "server_rendered_chart_ids": server_rendered_chart_ids,
                    "recovered_chart_ids": recovered_chart_ids,
                    "recovered_visual_ids": recovered_visual_ids,
                    "available_review_image_count": available_review_image_count,
                    "selected_review_image_count": len(review_image_evidence),
                    "server_rendered_review_image_count": rendered_review_image_count,
                    "approval": approval_analysis,
                },
            )
        if attempt_index == 1:
            retry_instruction = (
                "The previous trend moodbook failed HTML validation. Regenerate the complete report and place every "
                "approved visual exactly once inside the most relevant of 4–6 theme stories, using the required "
                "data-visual-id and exact image_url. Keep sources in compact captions; do not add an evidence atlas, "
                "coverage section, validation matrix, or data-gap section. Return raw HTML only."
                if trend_report_data
                else (
                    "The previous response failed HTML validation. Regenerate the complete report from the same "
                    "evidence and return raw HTML only, with no JSON, Markdown fence, preface, or trailing explanation."
                )
            )
            retry_payload = {
                **request_payload,
                "validation_feedback": {
                    "previous_error": validation_error,
                    "instruction": retry_instruction,
                },
            }
            messages = [
                system_message,
                {
                    "role": "user",
                    "content": json.dumps(retry_payload, ensure_ascii=False, default=str),
                },
            ]

    return (
        "",
        {},
        {
            "enabled": True,
            "status": "validation_failed",
            "message": last_error,
            **last_meta,
            "input_profile": input_profile,
            "attempt_count": len(attempts),
            "attempts": attempts,
        },
    )


def build_market_report_data(payload: dict[str, Any]) -> dict[str, Any]:
    tool_results = (
        payload.get("toolResults") if isinstance(payload.get("toolResults"), list) else []
    )
    if str(payload.get("skillId") or "") == "tiktok_us_market_insight" or any(
        isinstance(item, dict) and str(item.get("name") or "").startswith("mcp__fastmoss__")
        for item in tool_results
    ):
        return build_fastmoss_market_report_data(payload)
    category = str(payload.get("category") or "").strip()
    if not category:
        raise ValueError(
            "category is required for MarketReportData; do not default to an example category."
        )
    brand = str(payload.get("brand") or "Hsia")
    marketplace = str(payload.get("marketplace") or "US")
    time_range = str(payload.get("timeRange") or payload.get("time_range") or "90d")
    generated_at = str(payload.get("generatedAt") or now_iso())
    tool_results = [
        item
        for item in (
            payload.get("toolResults") if isinstance(payload.get("toolResults"), list) else []
        )
        if isinstance(item, dict)
        and str(item.get("name") or "")
        not in {"build_market_report_data", "build_market_report_charts", "render_html_report"}
    ]
    evidence_items = market_report_evidence_items(tool_results)
    successful = [tool for tool in tool_results if tool.get("status") in SUCCESS_TOOL_STATUSES]
    usable_evidence_items = [
        item for item in evidence_items if item.get("status") in SUCCESS_TOOL_STATUSES
    ]
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
    keyword_opportunities = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_keyword_research", "sellersprite_keyword_research_trends"),
        preferred_keys=("items", "keywords", "trends"),
        include_terms=("keyword", "search", "purchase", "demand", "trend", "ppc"),
        include_container=True,
        limit=32,
    )
    keyword_competition = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sif_market_get_keyword_competition",),
        preferred_keys=("top_competitors", "products", "items", "asins"),
        include_terms=("asin", "click", "traffic", "share", "title"),
        include_container=True,
        limit=30,
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
    node_demand_quality = list(demand_metrics)
    market_statistics = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_research_statistics",),
        preferred_keys=("items", "statistics"),
        include_terms=("sales", "revenue", "price", "profit", "new", "rating", "listing"),
        include_container=True,
        limit=24,
    )
    raw_top_products = market_report_first_available_rows(
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
    product_identity = resolve_market_product_identity(
        tool_results,
        marketplace=marketplace,
        category=category,
        detail_lookup_asins=(
            payload.get("productIdentityDetailLookupAsins")
            if isinstance(payload.get("productIdentityDetailLookupAsins"), list)
            else []
        ),
    )
    product_identity_applied = bool((product_identity.get("audit") or {}).get("applied"))
    top_products = (
        product_family_report_rows(
            product_identity,
            require_source_tool="sellersprite_market_product_concentration",
        )[:30]
        if product_identity_applied
        else raw_top_products
    )
    bra_attribute_distribution = (
        build_bra_attribute_distribution(
            tool_results,
            sample_limit=100,
            product_families=product_identity.get("families") if product_identity_applied else None,
        )
        if is_bra_category(category)
        else {}
    )
    brand_competition = market_report_first_available_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_brand_concentration", "sellersprite_market_research"),
        preferred_keys=("brands", "items"),
        include_terms=("brand", "seller", "merchant"),
        limit=24,
    )
    seller_competition = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_seller_concentration",),
        preferred_keys=("items", "sellers"),
        include_terms=("seller", "sales", "share", "concentration"),
        include_container=True,
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
    rating_distribution = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_rating_distribution",),
        preferred_keys=("items",),
        include_container=True,
        limit=16,
    )
    listing_date_distribution = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_listing_date_distribution",),
        preferred_keys=("items",),
        limit=16,
    )
    listing_trend_distribution = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_listing_trend_distribution",),
        preferred_keys=("items",),
        include_container=True,
        limit=20,
    )
    seller_type_distribution = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_seller_type_concentration",),
        preferred_keys=("items",),
        include_container=True,
        limit=16,
    )
    seller_country_distribution = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_seller_country_distribution",),
        preferred_keys=("items",),
        include_container=True,
        limit=16,
    )
    content_distribution = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_market_ebc_distribution",),
        preferred_keys=("items",),
        include_container=True,
        limit=16,
    )
    external_demand_trend = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=("sellersprite_google_trend",),
        preferred_keys=(
            "items",
            "trends",
            "timeline",
            "timelineData",
            "interestOverTime",
            "points",
            "values",
        ),
        include_terms=(
            "date",
            "month",
            "period",
            "week",
            "time",
            "value",
            "trend",
            "interest",
            "index",
        ),
        include_container=True,
        limit=20,
    )
    raw_product_universe = market_report_selected_rows(
        tool_results,
        evidence_items,
        tool_names=(
            "sellersprite_market_product_concentration",
            "sellersprite_product_research",
            "sellersprite_competitor_lookup",
        ),
        preferred_keys=("items", "products", "eligible_candidates"),
        include_terms=("asin", "parent", "variation", "brand", "title"),
        include_container=True,
        limit=100,
    )
    product_universe = (
        product_family_report_rows(product_identity)[:100]
        if product_identity_applied
        else raw_product_universe
    )
    review_pain_points = market_report_user_voice(tool_results, evidence_items)

    datasets: dict[str, tuple[list[dict[str, Any]], tuple[str, ...]]] = {
        "keyword_trends": (
            keyword_trends,
            (
                "sif_market_get_keyword_history",
                "sif_market_get_keyword_demand",
                "sif_market_get_keyword_root_trend",
                "sellersprite_aba_research_weekly",
                "sellersprite_keyword_research",
                "sellersprite_keyword_research_trends",
            ),
        ),
        "keyword_opportunities": (
            keyword_opportunities,
            ("sellersprite_keyword_research", "sellersprite_keyword_research_trends"),
        ),
        "keyword_competition": (
            keyword_competition,
            ("sif_market_get_keyword_competition",),
        ),
        "node_demand_quality": (
            node_demand_quality,
            ("sellersprite_market_product_demand_trend",),
        ),
        "category_benchmark": (
            category_benchmark,
            ("sellersprite_market_research", "sellersprite_market_product_demand_trend"),
        ),
        "market_statistics": (market_statistics, ("sellersprite_market_research_statistics",)),
        "top_products": (
            top_products,
            ("sellersprite_market_product_concentration",),
        ),
        "brand_competition": (
            brand_competition,
            ("sellersprite_market_brand_concentration", "sellersprite_market_research"),
        ),
        "seller_competition": (seller_competition, ("sellersprite_market_seller_concentration",)),
        "price_distribution": (
            price_distribution,
            ("sellersprite_market_price_distribution", "sellersprite_market_research"),
        ),
        "rating_distribution": (rating_distribution, ("sellersprite_market_rating_distribution",)),
        "ratings_count_distribution": (
            ratings_count_distribution,
            ("sellersprite_market_ratings_count_distribution",),
        ),
        "listing_date_distribution": (
            listing_date_distribution,
            ("sellersprite_market_listing_date_distribution",),
        ),
        "listing_trend_distribution": (
            listing_trend_distribution,
            ("sellersprite_market_listing_trend_distribution",),
        ),
        "seller_type_distribution": (
            seller_type_distribution,
            ("sellersprite_market_seller_type_concentration",),
        ),
        "seller_country_distribution": (
            seller_country_distribution,
            ("sellersprite_market_seller_country_distribution",),
        ),
        "content_distribution": (content_distribution, ("sellersprite_market_ebc_distribution",)),
        "external_demand_trend": (external_demand_trend, ("sellersprite_google_trend",)),
        "product_universe": (
            product_universe,
            (
                "sellersprite_market_product_concentration",
                "sellersprite_product_research",
                "sellersprite_competitor_lookup",
            ),
        ),
        "review_pain_points": (
            review_pain_points,
            ("sellersprite_review", "reddit_voc", "tiktok_social", "media_rankings"),
        ),
    }
    dedup_audits: list[dict[str, Any]] = []
    dedup_context = {
        "category": category,
        "marketplace": marketplace,
        "time_range": time_range,
    }
    deduplicated: dict[str, list[dict[str, Any]]] = {}
    for dataset_name, (records, source_tools) in datasets.items():
        result = run_market_data_dedup(
            dataset_name,
            records,
            source_tools=source_tools,
            context=dedup_context,
        )
        deduplicated[dataset_name] = list(result.records)
        dedup_audits.append(result.audit)

    keyword_trends = deduplicated["keyword_trends"]
    keyword_opportunities = deduplicated["keyword_opportunities"]
    keyword_competition = deduplicated["keyword_competition"]
    node_demand_quality = deduplicated["node_demand_quality"]
    category_benchmark = deduplicated["category_benchmark"]
    market_statistics = deduplicated["market_statistics"]
    top_products = deduplicated["top_products"]
    brand_competition = deduplicated["brand_competition"]
    seller_competition = deduplicated["seller_competition"]
    price_distribution = deduplicated["price_distribution"]
    rating_distribution = deduplicated["rating_distribution"]
    ratings_count_distribution = deduplicated["ratings_count_distribution"]
    listing_date_distribution = deduplicated["listing_date_distribution"]
    listing_trend_distribution = deduplicated["listing_trend_distribution"]
    seller_type_distribution = deduplicated["seller_type_distribution"]
    seller_country_distribution = deduplicated["seller_country_distribution"]
    content_distribution = deduplicated["content_distribution"]
    external_demand_trend = deduplicated["external_demand_trend"]
    product_universe = deduplicated["product_universe"]
    review_pain_points = deduplicated["review_pain_points"]
    data_gaps = [
        f"{tool.get('label') or tool.get('name')} 未成功：{tool.get('summary') or tool.get('outcome') or '未知原因'}"
        for tool in failed
    ]
    data_gaps.extend(
        str(gap.get("artifact_requirement") or f"缺少 {gap.get('tool')} 证据")
        for gap in payload.get("evidenceGaps", [])
        if isinstance(gap, dict)
    )
    attribute_family_count = int(bra_attribute_distribution.get("product_family_count") or 0)
    if is_bra_category(category) and attribute_family_count < 30:
        data_gaps.append(
            f"文胸属性占比仅覆盖 {attribute_family_count} 个去重商品家族，低于30个最低门槛，不得用于市场结构判断。"
        )
    low_coverage_axes = [
        str(axis.get("label") or axis.get("id") or "未知属性")
        for axis in bra_attribute_distribution.get("axes") or []
        if isinstance(axis, dict) and float(axis.get("classified_product_share") or 0) < 70
    ]
    if low_coverage_axes:
        data_gaps.append(
            "以下属性轴明确分类覆盖率低于70%，只能作为方向性样本：" + "、".join(low_coverage_axes)
        )
    if product_identity.get("status") == "not_applied" and any(
        str(tool.get("name") or "")
        in {
            "sellersprite_market_product_concentration",
            "sellersprite_product_research",
            "sellersprite_competitor_lookup",
        }
        and str(tool.get("status") or "") in SUCCESS_TOOL_STATUSES
        for tool in tool_results
    ):
        data_gaps.append("商品身份解析未成功，商品池已保留原始数据；不得声明唯一商品数。")
    unresolved_count = int((product_identity.get("audit") or {}).get("unresolved_count") or 0)
    if unresolved_count:
        data_gaps.append(f"仍有 {unresolved_count} 组疑似同款因证据或补查预算不足未归并。")
    if not keyword_trends:
        data_gaps.append(
            "关键词趋势结构化字段不足，需补充 Sif/SellerSprite 关键词历史或 ABA 数据。"
        )
    if not category_benchmark:
        data_gaps.append(
            "类目对标结构化字段不足，需补充 SellerSprite market research 或节点级数据。"
        )
    category_node_id = str(
        payload.get("categoryNodeId") or payload.get("category_node_id") or ""
    ).strip()
    analysis_coverage = evaluate_market_analysis_coverage(
        tool_results,
        category_node_id=category_node_id,
    )
    uncovered_p0 = [
        f"{item.get('dimension_id')} {item.get('name')}"
        for item in analysis_coverage.get("dimensions", [])
        if isinstance(item, dict)
        and item.get("priority") == "P0"
        and item.get("status") != "covered"
    ]
    if uncovered_p0:
        data_gaps.append("P0 分析维度未完整覆盖：" + "、".join(uncovered_p0))
    tool_catalog = {**get_sif_tool_catalog(), **get_sellersprite_tool_catalog()}
    tool_descriptions = {
        name: str(metadata.get("description") or "")
        for name, metadata in tool_catalog.items()
        if isinstance(metadata, dict)
    }
    tool_methodology = build_tool_methodology(tool_results, tool_descriptions)
    deduplication = {
        "schema_version": "market_data_dedup_layer.v1",
        "status": "partial" if product_identity_applied else "deferred",
        "implementation": "product_identity_v1+passthrough_v0"
        if product_identity_applied
        else "passthrough_v0",
        "applied": product_identity_applied,
        "scope": "product_identity_only"
        if product_identity_applied
        else "post_compilation_interface",
        "upstream_normalization_audited": product_identity_applied,
        "product_identity": product_identity.get("audit") or {},
        "datasets": dedup_audits,
    }
    signal_context = {
        "keyword_trends": keyword_trends,
        "category_benchmark": category_benchmark,
        "top_products": top_products,
        "bra_attribute_distribution": bra_attribute_distribution,
        "brand_competition": brand_competition,
        "price_distribution": price_distribution,
        "evidence_map": usable_evidence_items,
        "data_gaps": list(dict.fromkeys(data_gaps))[:16],
    }
    signals = market_report_core_signals(signal_context)
    verdict = market_report_verdict(signal_context)
    success_evidence_ids = (
        signals.get("evidence_ids") or [item["id"] for item in usable_evidence_items][:6]
    )
    demand_phrase = market_report_signal_phrase(signals.get("keyword"), "关键词需求锚点不足")
    category_phrase = market_report_signal_phrase(signals.get("category"), "类目基本盘字段不足")
    price_phrase = market_report_signal_phrase(signals.get("price"), "价格带证据不足")
    brand_phrase = market_report_signal_phrase(signals.get("brand"), "品牌集中度证据不足")
    product_phrase = market_report_signal_phrase(signals.get("product"), "Top 商品证据不足")
    keyword_label = str((signals.get("keyword") or {}).get("label") or category)
    price_label = str((signals.get("price") or {}).get("label") or "主力价格带")
    competitor_label = str(
        (signals.get("product") or signals.get("brand") or {}).get("label") or "头部竞品"
    )
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
            "evidence_ids": market_report_evidence_ids_from_rows(
                [*brand_competition[:2], *top_products[:2]], 4
            )
            or success_evidence_ids,
        },
        {
            "id": "insight_price",
            "title": "价格与边界",
            "summary": f"价格/利润相关记录 {len(price_distribution)} 条，当前价格锚点是 {price_phrase}；若缺少节点级分布，只能作为方向性假设。",
            "evidence_ids": market_report_evidence_ids_from_rows(price_distribution, 4)
            or success_evidence_ids,
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
            "evidence_ids": market_report_evidence_ids_from_rows(
                [*brand_competition[:2], *top_products[:2]], 4
            ),
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
        "category_node_id": category_node_id,
        "time_range": time_range,
        "generated_at": generated_at,
        "source_summary": {
            "tool_count": len(tool_results),
            "successful_tool_count": len(successful),
            "failed_tool_count": len(failed),
            "p0_dimension_total": analysis_coverage["summary"]["p0_total"],
            "p0_dimension_covered": analysis_coverage["summary"]["p0_covered"],
            "deduplication_status": deduplication["status"],
        },
        "market_kpis": kpis[:12],
        "keyword_trends": keyword_trends,
        "keyword_opportunities": keyword_opportunities,
        "keyword_competition": keyword_competition,
        "demand_trend": demand_trend,
        "node_demand_quality": node_demand_quality,
        "category_benchmark": category_benchmark,
        "market_statistics": market_statistics,
        "top_products": top_products,
        "bra_attribute_distribution": bra_attribute_distribution,
        "brand_competition": brand_competition,
        "seller_competition": seller_competition,
        "price_distribution": price_distribution,
        "rating_distribution": rating_distribution,
        "ratings_count_distribution": ratings_count_distribution,
        "listing_date_distribution": listing_date_distribution,
        "listing_trend_distribution": listing_trend_distribution,
        "seller_type_distribution": seller_type_distribution,
        "seller_country_distribution": seller_country_distribution,
        "content_distribution": content_distribution,
        "external_demand_trend": external_demand_trend,
        "product_universe": product_universe,
        "product_identity": product_identity,
        "review_pain_points": review_pain_points,
        "analysis_coverage": analysis_coverage,
        "tool_methodology": tool_methodology,
        "deduplication": deduplication,
        "insights": insights,
        "opportunity_pool": opportunity_pool,
        "evidence_map": usable_evidence_items,
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
    chart_payload = build_market_report_charts(report_data)
    report_data["chart_specs"] = chart_payload.get("chart_specs") or []
    report_data["summary_chart_ids"] = chart_payload.get("summary_chart_ids") or []
    report_data["chart_manifest"] = chart_payload.get("chart_manifest") or []
    report_data["non_chart_presentations"] = (
        chart_payload.get("non_chart_presentations") or []
    )
    report_data["dimension_results"] = build_market_dimension_results(
        analysis_coverage,
        report_data["chart_manifest"],
    )
    report_quality = weekly_market_report_quality(report_data)
    report_data["report_quality"] = report_quality
    report_data["data_gaps"] = list(
        dict.fromkeys(
            [
                *(
                    report_data.get("data_gaps")
                    if isinstance(report_data.get("data_gaps"), list)
                    else []
                ),
                *report_quality.get("gap_messages", []),
            ]
        )
    )[:24]
    report_signals = market_report_core_signals(report_data)
    report_verdict = market_report_verdict(report_data)
    report_data["executive_summary"] = (
        f"{report_verdict['label']}。本轮围绕 {marketplace} {category} 的核心判断是："
        f"先用 {market_report_signal_phrase(report_signals.get('keyword'), '关键词需求锚点')} 判断需求入口，"
        f"再用 {market_report_signal_phrase(report_signals.get('brand') or report_signals.get('product'), '竞争锚点')} 判断进入门槛，"
        f"最后用 {market_report_signal_phrase(report_signals.get('price'), '价格带锚点')} 验证 Hsia 的价格与结构假设。"
        f"报告已沉淀 {len(opportunity_pool)} 个有证据支持的研发机会，并将结论限定在本轮实际取得的市场、周期与样本范围内。"
    )
    report_data["artifact"] = market_report_data_to_artifact(report_data)
    return report_data


PRODUCT_DESIGN_REPORT_SECTIONS = [
    "研发课题与研究范围",
    "一句话研发方向",
    "市场边界与消费者真实搜索词",
    "趋势信号及其可信度",
    "Amazon 头部商品与价格/结构分布",
    "好评、差评和 3 星权衡点",
    "TikTok 卖点表达与消费者反馈",
    "品牌独立站对标",
    "痛点→原因→产品解法矩阵",
    "必须解决、值得探索、不建议照搬",
    "结构、面料、颜色、尺码和价格建议",
    "概念方向文字简报",
    "验证动作、证据链和数据缺口",
]

PRODUCT_DESIGN_KEYWORD_TOOLS = {
    "sif_market_get_keyword_root_trend",
    "sif_market_get_keyword_demand",
    "sif_market_get_keyword_history",
    "sif_market_get_keyword_competition",
    "sellersprite_aba_research_weekly",
}


def product_design_first_value(value: Any, keys: tuple[str, ...], depth: int = 0) -> Any:
    if depth > 4:
        return None
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if candidate not in (None, "", [], {}):
                return candidate
        for child in value.values():
            candidate = product_design_first_value(child, keys, depth + 1)
            if candidate not in (None, "", [], {}):
                return candidate
    elif isinstance(value, list):
        for child in value[:20]:
            candidate = product_design_first_value(child, keys, depth + 1)
            if candidate not in (None, "", [], {}):
                return candidate
    return None


def product_design_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    payload = data.get("data")
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [item for item in payload.get("items") or [] if isinstance(item, dict)]
    if isinstance(data.get("items"), list):
        return [item for item in data.get("items") or [] if isinstance(item, dict)]
    return []


def product_design_rating(review: dict[str, Any]) -> float | None:
    value = product_design_first_value(review, ("star", "rating", "rating_value", "score"))
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def product_design_review_group(rating: float | None) -> str:
    if rating is None:
        return "unknown"
    if rating <= 2:
        return "failure_1_2_star"
    if rating < 4:
        return "tradeoff_3_star"
    return "purchase_driver_4_5_star"


def product_design_stratified_reviews(
    items: list[dict[str, Any]], limit: int = 18
) -> list[dict[str, Any]]:
    buckets = {
        "failure_1_2_star": [],
        "tradeoff_3_star": [],
        "purchase_driver_4_5_star": [],
        "unknown": [],
    }
    for item in items:
        buckets[product_design_review_group(product_design_rating(item))].append(item)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    per_bucket = max(1, limit // 3)

    def append_unique(item: dict[str, Any]) -> None:
        identity = json.dumps(
            [
                item.get("id"),
                item.get("reviewId"),
                item.get("author"),
                item.get("title"),
                item.get("date"),
                item.get("content"),
                item.get("body"),
            ],
            ensure_ascii=False,
            default=str,
        )
        if identity in seen or len(selected) >= limit:
            return
        seen.add(identity)
        selected.append(item)

    for bucket_name in ("failure_1_2_star", "tradeoff_3_star", "purchase_driver_4_5_star"):
        for item in buckets[bucket_name][:per_bucket]:
            append_unique(item)
    for bucket_name in (
        "failure_1_2_star",
        "tradeoff_3_star",
        "purchase_driver_4_5_star",
        "unknown",
    ):
        for item in buckets[bucket_name]:
            append_unique(item)
    return selected


def product_design_amazon_url(asin: str, value: Any = "") -> str:
    candidate = html_report_first_http_url(value)
    if candidate:
        return candidate
    return f"https://www.amazon.com/dp/{asin}" if asin else ""


def product_design_evidence_item(
    evidence_id: str,
    *,
    source: str,
    kind: str,
    title: str,
    url: str = "",
    excerpt: str = "",
    reference: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": evidence_id,
        "source": source,
        "kind": kind,
        "title": compact_text(title, 220),
        "url": url,
        "excerpt": compact_text(excerpt, 900),
        "reference": compact_text(reference, 260),
        "metadata": metadata or {},
    }


def build_product_design_brief_data(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "").strip()
    design_goal = str(payload.get("designGoal") or payload.get("design_goal") or "").strip()
    if not category:
        raise ValueError("category is required for ProductDesignBriefData")
    if not design_goal:
        raise ValueError("design_goal is required for ProductDesignBriefData")

    brand = str(payload.get("brand") or "Hsia / 遐")
    marketplace = str(payload.get("marketplace") or "Amazon US")
    time_range = str(payload.get("timeRange") or payload.get("time_range") or "180d")
    generated_at = str(payload.get("generatedAt") or now_iso())
    target_user = str(payload.get("targetUser") or payload.get("target_user") or "由研究识别")
    trend_context = str(payload.get("trendContext") or payload.get("trend_context") or "").strip()
    brand_site_urls, brand_url_warnings = extract_article_urls(
        {"urls": payload.get("brandSiteUrls") or payload.get("brand_site_urls") or []}
    )
    tool_results = [tool for tool in payload.get("toolResults") or [] if isinstance(tool, dict)]
    successful = [
        tool for tool in tool_results if str(tool.get("status") or "") in SUCCESS_TOOL_STATUSES
    ]
    successful_names = {str(tool.get("name") or "") for tool in successful}
    evidence_map: list[dict[str, Any]] = []

    keyword_evidence: list[dict[str, Any]] = []
    keyword_index = 0
    for tool in successful:
        tool_name = str(tool.get("name") or "")
        if tool_name not in PRODUCT_DESIGN_KEYWORD_TOOLS:
            continue
        keyword_index += 1
        evidence_id = f"K{keyword_index:02d}"
        tool_input = tool.get("input") if isinstance(tool.get("input"), dict) else {}
        keyword = str(
            product_design_first_value(
                tool_input,
                ("keyword", "keywords", "query", "searchTerm", "includeKeywords", "category"),
            )
            or category
        )
        compacted_data = html_report_compact_value(tool.get("data"))
        excerpt = json.dumps(compacted_data, ensure_ascii=False, default=str)
        keyword_evidence.append(
            {
                "evidence_id": evidence_id,
                "tool": tool_name,
                "keyword": keyword,
                "summary": compact_text(str(tool.get("summary") or ""), 360),
                "data": compacted_data,
            }
        )
        evidence_map.append(
            product_design_evidence_item(
                evidence_id,
                source=str(tool.get("label") or tool_name),
                kind="keyword_or_market_boundary",
                title=f"{keyword} · {tool_name}",
                excerpt=excerpt,
                reference=f"{tool_name} · {keyword}",
                metadata={"tool": tool_name, "keyword": keyword},
            )
        )

    market_evidence: list[dict[str, Any]] = []
    market_index = 0
    for tool in successful:
        tool_name = str(tool.get("name") or "")
        if tool_name in PRODUCT_DESIGN_KEYWORD_TOOLS or tool_name in {
            "sellersprite_review",
            "sellersprite_market_product_concentration",
            "tiktok_social",
            "media_rankings",
            "reddit_voc",
        }:
            continue
        if not (tool_name.startswith("sellersprite_") or tool_name.startswith("sif_")):
            continue
        market_index += 1
        evidence_id = f"M{market_index:02d}"
        compacted_data = html_report_compact_value(tool.get("data"))
        market_evidence.append(
            {
                "evidence_id": evidence_id,
                "tool": tool_name,
                "summary": compact_text(str(tool.get("summary") or ""), 360),
                "data": compacted_data,
            }
        )
        evidence_map.append(
            product_design_evidence_item(
                evidence_id,
                source=str(tool.get("label") or tool_name),
                kind="amazon_market",
                title=str(tool.get("label") or tool_name),
                excerpt=json.dumps(compacted_data, ensure_ascii=False, default=str),
                reference=tool_name,
                metadata={"tool": tool_name},
            )
        )

    concentration = next(
        (
            tool
            for tool in reversed(successful)
            if str(tool.get("name") or "") == "sellersprite_market_product_concentration"
        ),
        None,
    )
    concentration_data = (
        concentration.get("data")
        if isinstance(concentration, dict) and isinstance(concentration.get("data"), dict)
        else {}
    )
    selection = (
        concentration_data.get("product_selection")
        if isinstance(concentration_data.get("product_selection"), dict)
        else {}
    )
    product_rows = selection.get("selected") if isinstance(selection.get("selected"), list) else []
    if not product_rows:
        product_rows = (
            selection.get("eligible_candidates")
            if isinstance(selection.get("eligible_candidates"), list)
            else []
        )
    if not product_rows:
        product_rows = product_design_items(concentration_data)
    head_count = max(
        5, min(int(payload.get("headListingCount") or payload.get("head_listing_count") or 10), 30)
    )
    products: list[dict[str, Any]] = []
    seen_product_families: set[str] = set()
    product_index = 0
    for row in product_rows:
        asin = str(row.get("asin") or "").strip().upper()
        if not asin:
            continue
        family_asin = (
            str(
                row.get("family_asin")
                or row.get("parentAsin")
                or row.get("parent_asin")
                or row.get("parent")
                or asin
            )
            .strip()
            .upper()
        )
        if family_asin in seen_product_families:
            continue
        seen_product_families.add(family_asin)
        product_index += 1
        evidence_id = f"P{product_index:02d}"
        url = product_design_amazon_url(asin, row.get("asinUrl") or row.get("url"))
        product = {
            "evidence_id": evidence_id,
            "asin": asin,
            "family_asin": family_asin,
            "rank": row.get("ranking") or row.get("rank") or row.get("candidate_order"),
            "title": row.get("title"),
            "brand": row.get("brand"),
            "price": row.get("price"),
            "rating": row.get("rating"),
            "review_count": row.get("ratings") or row.get("reviews") or row.get("review_count"),
            "image_url": html_report_first_http_url(
                row.get("imageUrl") or row.get("image_url") or row.get("image")
            ),
            "url": url,
            "matched_category_tokens": row.get("matched_category_tokens") or [],
        }
        products.append(product)
        evidence_map.append(
            product_design_evidence_item(
                evidence_id,
                source="SellerSprite",
                kind="amazon_product",
                title=str(product.get("title") or asin),
                url=url,
                excerpt=json.dumps(product, ensure_ascii=False, default=str),
                reference=f"ASIN {asin}",
                metadata={"asin": asin, "family_asin": family_asin},
            )
        )
        if len(products) >= head_count:
            break

    reviews: list[dict[str, Any]] = []
    actual_review_count = 0
    reviewed_products: set[str] = set()
    review_index = 0
    for tool in successful:
        if str(tool.get("name") or "") != "sellersprite_review":
            continue
        tool_input = tool.get("input") if isinstance(tool.get("input"), dict) else {}
        requested_asin = str(tool_input.get("asin") or "").strip().upper()
        data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
        items = product_design_items(data)
        actual_review_count += len(items)
        if items and requested_asin:
            reviewed_products.add(requested_asin)
        sampling = (
            data.get("review_sampling") if isinstance(data.get("review_sampling"), dict) else {}
        )
        review_asin = str(sampling.get("selected_review_asin") or requested_asin).strip().upper()
        for item in product_design_stratified_reviews(items, 18):
            review_index += 1
            evidence_id = f"R{review_index:02d}"
            rating = product_design_rating(item)
            title = str(item.get("title") or item.get("summary") or f"{rating or '?'} star review")
            body = str(
                item.get("content")
                or item.get("body")
                or item.get("text")
                or item.get("review")
                or ""
            )
            review_url = product_design_amazon_url(
                requested_asin,
                item.get("url") or item.get("reviewUrl") or item.get("review_url"),
            )
            review = {
                "evidence_id": evidence_id,
                "product_asin": requested_asin,
                "review_asin": review_asin,
                "sampling_scope": sampling.get("scope") or "exact_asin",
                "rating": rating,
                "group": product_design_review_group(rating),
                "title": compact_text(title, 220),
                "excerpt": compact_text(body, 900),
                "date": item.get("date") or item.get("reviewDate") or item.get("created_at"),
                "sku": item.get("skus") or item.get("sku") or item.get("variation"),
                "verified_purchase": item.get("verified") or item.get("verifiedPurchase"),
                "url": review_url,
            }
            reviews.append(review)
            evidence_map.append(
                product_design_evidence_item(
                    evidence_id,
                    source="SellerSprite review",
                    kind=review["group"],
                    title=review["title"],
                    url=review_url,
                    excerpt=review["excerpt"],
                    reference=f"ASIN {requested_asin} · {rating or '?'} star",
                    metadata={
                        "asin": requested_asin,
                        "review_asin": review_asin,
                        "rating": rating,
                        "sampling_scope": review["sampling_scope"],
                    },
                )
            )

    tiktok_videos: list[dict[str, Any]] = []
    actual_tiktok_videos = 0
    actual_tiktok_comments = 0
    tiktok_index = 0
    for tool in successful:
        if str(tool.get("name") or "") != "tiktok_social":
            continue
        data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
        videos = data.get("videos") if isinstance(data.get("videos"), list) else []
        actual_tiktok_videos += len(videos)
        for video in videos[:12]:
            if not isinstance(video, dict):
                continue
            comments = (
                video.get("comment_samples")
                if isinstance(video.get("comment_samples"), list)
                else []
            )
            actual_tiktok_comments += len(comments)
            tiktok_index += 1
            evidence_id = f"T{tiktok_index:02d}"
            record = {
                "evidence_id": evidence_id,
                "title": video.get("title"),
                "author": video.get("author"),
                "url": video.get("url"),
                "views": video.get("views"),
                "snippet": video.get("snippet"),
                "comment_samples": comments[:8],
            }
            tiktok_videos.append(record)
            evidence_map.append(
                product_design_evidence_item(
                    evidence_id,
                    source="TikTok",
                    kind="creator_video_and_comments",
                    title=str(record.get("title") or "TikTok video"),
                    url=str(record.get("url") or ""),
                    excerpt=json.dumps(record, ensure_ascii=False, default=str),
                    reference=f"TikTok · {record.get('author') or 'creator'}",
                    metadata={"views": record.get("views"), "comment_samples": len(comments)},
                )
            )

    web_pages: list[dict[str, Any]] = []
    actual_web_pages = 0
    web_index = 0
    for tool in successful:
        if str(tool.get("name") or "") != "media_rankings":
            continue
        data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
        articles = data.get("articles") if isinstance(data.get("articles"), list) else []
        actual_web_pages += len(articles)
        for article in articles[:12]:
            if not isinstance(article, dict):
                continue
            web_index += 1
            evidence_id = f"W{web_index:02d}"
            record = {
                "evidence_id": evidence_id,
                "title": article.get("title"),
                "domain": article.get("domain"),
                "url": article.get("url"),
                "source_type": article.get("source_type"),
                "authority_level": article.get("authority_level"),
                "product_signals": article.get("product_signals") or [],
                "evidence_snippets": article.get("evidence_snippets") or [],
                "cautions": article.get("cautions") or [],
            }
            web_pages.append(record)
            evidence_map.append(
                product_design_evidence_item(
                    evidence_id,
                    source=str(article.get("domain") or "Public web"),
                    kind=str(article.get("source_type") or "public_web_page"),
                    title=str(article.get("title") or article.get("domain") or "Public web page"),
                    url=str(article.get("url") or ""),
                    excerpt=json.dumps(record, ensure_ascii=False, default=str),
                    reference=f"{article.get('domain') or 'web'} · {article.get('authority_level') or 'unrated'}",
                )
            )

    reddit_evidence: list[dict[str, Any]] = []
    reddit_index = 0
    for tool in successful:
        if str(tool.get("name") or "") != "reddit_voc":
            continue
        data = tool.get("data") if isinstance(tool.get("data"), dict) else {}
        for post in data.get("posts") or []:
            if not isinstance(post, dict):
                continue
            reddit_index += 1
            evidence_id = f"D{reddit_index:02d}"
            record = {
                "evidence_id": evidence_id,
                "title": post.get("title"),
                "subreddit": post.get("subreddit"),
                "url": post.get("url"),
                "excerpt": post.get("excerpt"),
                "comment_items": (post.get("comment_items") or [])[:6],
            }
            reddit_evidence.append(record)
            evidence_map.append(
                product_design_evidence_item(
                    evidence_id,
                    source=f"Reddit r/{post.get('subreddit') or 'unknown'}",
                    kind="community_voc",
                    title=str(post.get("title") or "Reddit discussion"),
                    url=str(post.get("url") or ""),
                    excerpt=json.dumps(record, ensure_ascii=False, default=str),
                    reference=f"Reddit · {post.get('subreddit') or 'unknown'}",
                )
            )

    listing_target = max(
        10,
        min(
            int(payload.get("listingSampleSize") or payload.get("listing_sample_size") or 100), 200
        ),
    )
    review_target = max(
        10,
        min(int(payload.get("reviewSampleSize") or payload.get("review_sample_size") or 60), 100),
    )
    tiktok_video_target = max(1, min(int(payload.get("tiktokVideoLimit") or 12), 12))
    tiktok_comment_target = max(1, min(int(payload.get("tiktokCommentsPerVideo") or 20), 20))
    data_volume = {
        "planned": {
            "candidate_products": listing_target,
            "deep_dive_products": head_count,
            "reviews": head_count * review_target,
            "tiktok_videos": tiktok_video_target,
            "tiktok_comments": tiktok_video_target * tiktok_comment_target,
            "public_web_pages": len(brand_site_urls)
            or int(payload.get("articleCandidateLimit") or 12),
        },
        "actual": {
            "candidate_products": int(selection.get("candidate_count") or len(product_rows)),
            "eligible_products": int(selection.get("eligible_count") or len(product_rows)),
            "unique_products": len(products),
            "reviewed_products": len(reviewed_products),
            "reviews": actual_review_count,
            "tiktok_videos": actual_tiktok_videos,
            "tiktok_comments": actual_tiktok_comments,
            "public_web_pages": actual_web_pages,
        },
        "included_in_llm": {
            "keyword_evidence": len(keyword_evidence),
            "market_evidence": len(market_evidence),
            "products": len(products),
            "reviews": len(reviews),
            "tiktok_videos": len(tiktok_videos),
            "tiktok_comments": sum(
                len(item.get("comment_samples") or []) for item in tiktok_videos
            ),
            "public_web_pages": len(web_pages),
            "reddit_posts": len(reddit_evidence),
            "evidence_items": len(evidence_map),
        },
    }

    data_gaps = [
        str(gap.get("artifact_requirement") or gap.get("summary") or "")
        for gap in payload.get("evidenceGaps") or []
        if isinstance(gap, dict)
    ]
    failed_without_recovery = [
        tool
        for tool in tool_results
        if str(tool.get("status") or "") not in SUCCESS_TOOL_STATUSES
        and str(tool.get("name") or "") not in successful_names
    ]
    data_gaps.extend(
        f"{tool.get('label') or tool.get('name')} 未取得可用数据：{tool.get('summary') or tool.get('status')}"
        for tool in failed_without_recovery
    )
    if len(reviewed_products) < head_count:
        data_gaps.append(
            f"目标深拆 {head_count} 个商品，实际取得 {len(reviewed_products)} 个不同商品的评论样本。"
        )
    if not tiktok_videos:
        data_gaps.append("未取得 TikTok 达人视频和留言证据，不能判断内容卖点表达。")
    if not web_pages:
        data_gaps.append("未取得可读的品牌独立站或公开趋势网页。")
    if trend_context:
        data_gaps.append("趋势背景来自用户人工输入、未经数据工具验证，不能单独支持研发结论。")
    else:
        data_gaps.append("未接入 WGSN、蝶讯付费报告；趋势章节只能使用可公开验证的网页证据。")
    data_gaps.extend(
        [
            "品牌站动态评论未由公开网页工具验证。",
            "未接入 FastMoss，不能声称覆盖 TikTok Shop 买家评价或真实销量。",
            "Pinterest 视觉图片和情绪板未自动采集，只能输出后续人工搜索建议。",
            *brand_url_warnings,
        ]
    )
    data_gaps = [gap for gap in dict.fromkeys(gap.strip() for gap in data_gaps) if gap][:20]

    title = f"{brand} · {category} 产品研发调研任务书"
    result = {
        "schema_version": "product_design_brief_data.v1",
        "title": title,
        "research_scope": {
            "brand": brand,
            "marketplace": marketplace,
            "category": category,
            "design_goal": design_goal,
            "target_user": target_user,
            "time_range": time_range,
            "generated_at": generated_at,
        },
        "human_inputs": {
            "brand_site_urls": brand_site_urls,
            "trend_context": trend_context,
            "trend_context_status": "user_provided_unverified" if trend_context else "not_provided",
        },
        "data_volume": data_volume,
        "keyword_evidence": keyword_evidence,
        "market_evidence": market_evidence,
        "products": products,
        "reviews": reviews,
        "tiktok_evidence": tiktok_videos,
        "web_evidence": web_pages,
        "reddit_evidence": reddit_evidence,
        "evidence_map": evidence_map,
        "data_gaps": data_gaps,
        "report_contract": {
            "required_sections": PRODUCT_DESIGN_REPORT_SECTIONS,
            "recommendation_sections_require_evidence": [9, 10, 11, 12],
            "facts_vs_inference_required": True,
        },
        "source_summary": {
            "successful_tool_count": len(successful),
            "failed_tool_count": len(failed_without_recovery),
            "successful_tools": sorted(successful_names),
        },
        "artifact": {
            "title": title,
            "executive_summary": "多来源证据已编译，最终研发方向由 Markdown renderer 在证据约束下生成。",
            "key_findings": [],
            "opportunity_pool": [],
            "risks": data_gaps,
            "next_steps": ["由设计师审核证据、产品机制和概念方向后再进入出图。"],
        },
    }
    return result


def product_design_brief_llm_context(brief_data: dict[str, Any]) -> dict[str, Any]:
    evidence_map = [
        {
            "id": item.get("id"),
            "source": item.get("source"),
            "kind": item.get("kind"),
            "title": item.get("title"),
            "url": item.get("url"),
            "reference": item.get("reference"),
        }
        for item in brief_data.get("evidence_map") or []
        if isinstance(item, dict)
    ]
    return {
        "schema_version": brief_data.get("schema_version"),
        "title": brief_data.get("title"),
        "research_scope": brief_data.get("research_scope"),
        "human_inputs": brief_data.get("human_inputs"),
        "data_volume": brief_data.get("data_volume"),
        "keyword_evidence": brief_data.get("keyword_evidence"),
        "market_evidence": brief_data.get("market_evidence"),
        "products": brief_data.get("products"),
        "reviews": brief_data.get("reviews"),
        "tiktok_evidence": brief_data.get("tiktok_evidence"),
        "web_evidence": brief_data.get("web_evidence"),
        "reddit_evidence": brief_data.get("reddit_evidence"),
        "evidence_map": evidence_map,
        "data_gaps": brief_data.get("data_gaps"),
        "report_contract": brief_data.get("report_contract"),
    }


def normalize_llm_markdown_document(value: Any) -> str:
    content = str(value or "").strip()
    fence = re.match(
        r"^```(?:markdown|md)?\s*(.*?)\s*```$", content, flags=re.IGNORECASE | re.DOTALL
    )
    if fence:
        content = fence.group(1).strip()
    first_heading = re.search(r"(?m)^#\s+", content)
    if first_heading and first_heading.start() > 0:
        content = content[first_heading.start() :].strip()
    return content


def markdown_numbered_section(markdown: str, number: int) -> str:
    match = re.search(rf"(?m)^##\s+{number}\.\s+.+$", markdown)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"(?m)^##\s+\d+\.\s+", markdown[start:])
    end = start + next_match.start() if next_match else len(markdown)
    return markdown[start:end].strip()


def validate_product_design_markdown(markdown: str, brief_data: dict[str, Any]) -> str:
    if len(markdown) < 1800:
        return "Markdown report is too short to be a complete product R&D brief."
    if not re.search(r"(?m)^#\s+\S", markdown):
        return "Markdown report must begin with an H1 title."
    if "<html" in markdown.lower():
        return "Markdown renderer must not return HTML."
    for index, section in enumerate(PRODUCT_DESIGN_REPORT_SECTIONS, start=1):
        if not re.search(rf"(?m)^##\s+{index}\.\s+{re.escape(section)}\s*$", markdown):
            return f"Markdown report is missing required section {index}: {section}."
    for label in ("计划采集", "实际采集", "进入 LLM"):
        if label not in markdown:
            return f"Markdown report must disclose the `{label}` data-volume scope."
    valid_ids = {
        str(item.get("id") or "")
        for item in brief_data.get("evidence_map") or []
        if isinstance(item, dict) and item.get("id")
    }
    citation_pattern = r"\[[A-Z]+\d{2,3}\]"
    cited_ids = set(re.findall(r"\[([A-Z]+\d{2,3})\]", markdown))
    unknown_ids = sorted(cited_ids - valid_ids)
    if unknown_ids:
        return "Markdown report cites unknown evidence id(s): " + ", ".join(unknown_ids[:8])
    if len(cited_ids) < min(8, len(valid_ids)):
        return "Markdown report does not cite enough of the supplied evidence items."
    if not re.search(citation_pattern, markdown_numbered_section(markdown, 2)):
        return "The one-sentence R&D direction must cite nearby evidence."
    for section_number in (9, 10, 11, 12):
        section_body = markdown_numbered_section(markdown, section_number)
        if not re.search(citation_pattern, section_body):
            return f"Recommendation section {section_number} must include nearby evidence ids."
        actionable_lines = [
            line.strip()
            for line in section_body.splitlines()
            if line.strip().startswith("- ")
            or (
                line.strip().startswith("|")
                and "---" not in line
                and not any(label in line for label in ("痛点", "建议", "方向", "证据"))
            )
        ]
        if any(not re.search(citation_pattern, line) for line in actionable_lines):
            return f"Every recommendation row or bullet in section {section_number} must cite nearby evidence."
    return ""


def compose_markdown_report_with_llm(
    payload: dict[str, Any],
    *,
    locale: str = "zh",
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    brief_data = (
        payload.get("productDesignBriefData")
        if isinstance(payload.get("productDesignBriefData"), dict)
        else {}
    )
    if not brief_data:
        return (
            "",
            {},
            {
                "enabled": False,
                "status": "skipped",
                "message": "ProductDesignBriefData was not supplied.",
            },
        )
    context = product_design_brief_llm_context(brief_data)
    request_payload = {
        "language": "Chinese" if locale == "zh" else "English",
        "user_prompt": payload.get("prompt") or "",
        "skill_markdown_excerpt": compact_text(str(payload.get("skillMarkdown") or ""), 9000),
        "product_design_brief_data": context,
        "output_contract": {
            "format": "raw_markdown_only",
            "required_sections": [
                f"## {index}. {title}"
                for index, title in enumerate(PRODUCT_DESIGN_REPORT_SECTIONS, start=1)
            ],
            "recommendation_sections_require_nearby_evidence": [9, 10, 11, 12],
            "show_planned_actual_and_llm_included_counts": True,
            "no_html": True,
        },
    }
    system_message = {
        "role": "system",
        "content": (
            "You are Hsia's senior intimate-apparel product research and R&D brief editor. "
            "Return raw Markdown only, beginning with one H1 title. Do not return JSON, HTML, a Markdown fence, "
            "or commentary outside the report. Use only ProductDesignBriefData. Separate observed facts, analysis, "
            "and designer judgment. Every product mechanism, R&D direction, or design recommendation must have a "
            "nearby evidence id in square brackets. Never invent evidence ids, sales, search volume, market capacity, "
            "demographics, material performance, WGSN/Diexun findings, TikTok Shop reviews, or Pinterest research. "
            "Treat trend_context as unverified human input. Keep the report product-focused; exclude listing SEO, ads, "
            "creator commissions, inventory, and store operations. Include all 13 required headings verbatim."
        ),
    }
    messages: list[dict[str, Any]] = [
        system_message,
        {"role": "user", "content": json.dumps(request_payload, ensure_ascii=False, default=str)},
    ]
    input_profile = {
        "request_chars": sum(len(str(message.get("content") or "")) for message in messages),
        "brief_chars": len(json.dumps(context, ensure_ascii=False, default=str)),
        "evidence_items": len(context.get("evidence_map") or []),
    }
    attempts: list[dict[str, Any]] = []
    last_error = "LLM did not return a valid product R&D Markdown report."
    last_meta: dict[str, Any] = {}
    for attempt_index in range(1, 3):
        attempt_started = time.perf_counter()
        try:
            response = call_openai_compatible_chat(messages)
        except LLMUnavailable as exc:
            return (
                "",
                {},
                {
                    "enabled": True,
                    "status": "unavailable",
                    "message": str(exc),
                    "input_profile": input_profile,
                    "attempt_count": len(attempts),
                    "attempts": attempts,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return (
                "",
                {},
                {
                    "enabled": True,
                    "status": "error",
                    "message": str(exc),
                    "input_profile": input_profile,
                    "attempt_count": len(attempts),
                    "attempts": attempts,
                },
            )
        message = response.get("message") if isinstance(response.get("message"), dict) else {}
        raw_content = str(message.get("content") or "")
        markdown = normalize_llm_markdown_document(raw_content)
        validation_error = validate_product_design_markdown(markdown, brief_data)
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
                "response_chars": len(raw_content),
                "markdown_chars": len(markdown),
            }
        )
        if not validation_error:
            title_match = re.search(r"(?m)^#\s+(.+)$", markdown)
            section_two = markdown_numbered_section(markdown, 2)
            executive_summary = next(
                (line.strip(" -*") for line in section_two.splitlines() if line.strip()),
                "已生成带证据链的产品研发任务书。",
            )
            artifact = dict(brief_data.get("artifact") or {})
            artifact["title"] = (
                title_match.group(1).strip() if title_match else brief_data.get("title")
            )
            artifact["executive_summary"] = compact_text(executive_summary, 600)
            return (
                markdown,
                artifact,
                {
                    "enabled": True,
                    "status": "ok",
                    **last_meta,
                    "input_profile": input_profile,
                    "attempt_count": len(attempts),
                    "attempts": attempts,
                },
            )
        if attempt_index == 1:
            retry_payload = {
                **request_payload,
                "validation_feedback": {
                    "previous_error": validation_error,
                    "instruction": "Regenerate the complete report using the exact 13 headings and only supplied evidence ids.",
                },
            }
            messages = [
                system_message,
                {
                    "role": "user",
                    "content": json.dumps(retry_payload, ensure_ascii=False, default=str),
                },
            ]
    return (
        "",
        {},
        {
            "enabled": True,
            "status": "validation_failed",
            "message": last_error,
            **last_meta,
            "input_profile": input_profile,
            "attempt_count": len(attempts),
            "attempts": attempts,
        },
    )


def render_markdown_report_tool(payload: dict[str, Any]) -> dict[str, Any]:
    brief_data = (
        payload.get("productDesignBriefData")
        if isinstance(payload.get("productDesignBriefData"), dict)
        else {}
    )
    if not payload.get("useLlm"):
        raise RuntimeError(
            "render_markdown_report requires LLM-authored Markdown. Enable useLlm=true."
        )
    markdown, artifact, markdown_analysis = compose_markdown_report_with_llm(payload, locale="zh")
    if not markdown:
        status = markdown_analysis.get("status") or "error"
        detail = markdown_analysis.get("message") or "LLM did not return a valid Markdown report."
        raise MarkdownReportGenerationError(
            f"LLM Markdown generation failed ({status}): {detail}",
            markdown_analysis,
        )
    return {
        "format": "markdown",
        "title": brief_data.get("title") or artifact.get("title") or "产品研发任务书",
        "markdown": markdown,
        "product_design_brief_data": brief_data,
        "artifact": artifact,
        "renderer": "llm-markdown",
        "markdown_analysis": markdown_analysis,
    }


def weekly_market_report_readiness_issues(report_data: dict[str, Any]) -> list[str]:
    coverage = (
        report_data.get("analysis_coverage")
        if isinstance(report_data.get("analysis_coverage"), dict)
        else {}
    )
    dimensions = coverage.get("dimensions") if isinstance(coverage.get("dimensions"), list) else []
    if not dimensions:
        return ["MarketReportData is missing analysis_coverage dimensions."]
    uncovered_p0 = [
        str(item.get("dimension_id") or "")
        for item in dimensions
        if isinstance(item, dict)
        and item.get("priority") == "P0"
        and item.get("status") != "covered"
    ]
    manifest = (
        report_data.get("chart_manifest")
        if isinstance(report_data.get("chart_manifest"), list)
        else []
    )
    charts_by_dimension = {
        str(item.get("dimension_id") or ""): item
        for item in manifest
        if isinstance(item, dict) and item.get("dimension_id")
    }
    ready_chart_ids = {
        str(item.get("id") or "")
        for item in report_data.get("chart_specs", [])
        if isinstance(item, dict)
        and item.get("id")
        and str(item.get("quality_status") or "ready") == "ready"
    }
    missing_charts = [
        str(item.get("dimension_id") or "")
        for item in dimensions
        if isinstance(item, dict)
        and item.get("status") == "covered"
        and (
            (
                charts_by_dimension.get(str(item.get("dimension_id") or "")) or {}
            ).get("chart_status")
            not in {"ready", "text_only"}
            or (
                (
                    charts_by_dimension.get(str(item.get("dimension_id") or "")) or {}
                ).get("chart_status")
                == "ready"
                and str(
                    (
                        charts_by_dimension.get(str(item.get("dimension_id") or ""))
                        or {}
                    ).get("chart_id")
                    or ""
                )
                not in ready_chart_ids
            )
        )
    ]
    issues: list[str] = []
    if uncovered_p0:
        issues.append("P0 analysis dimensions not covered: " + ", ".join(uncovered_p0))
    if missing_charts:
        issues.append(
            "Covered analysis dimensions missing valid charts: " + ", ".join(missing_charts)
        )
    return issues


def weekly_market_report_quality(report_data: dict[str, Any]) -> dict[str, Any]:
    coverage = (
        report_data.get("analysis_coverage")
        if isinstance(report_data.get("analysis_coverage"), dict)
        else {}
    )
    dimensions = coverage.get("dimensions") if isinstance(coverage.get("dimensions"), list) else []
    manifest = (
        report_data.get("chart_manifest")
        if isinstance(report_data.get("chart_manifest"), list)
        else []
    )
    manifest_by_dimension = {
        str(item.get("dimension_id") or ""): item
        for item in manifest
        if isinstance(item, dict) and item.get("dimension_id")
    }
    ready_chart_ids = {
        str(item.get("id") or "")
        for item in report_data.get("chart_specs", [])
        if isinstance(item, dict)
        and item.get("id")
        and str(item.get("quality_status") or "ready") == "ready"
    }
    unavailable_dimensions: list[dict[str, Any]] = []
    for dimension in dimensions:
        if not isinstance(dimension, dict):
            continue
        dimension_id = str(dimension.get("dimension_id") or "")
        chart = manifest_by_dimension.get(dimension_id) or {}
        analysis_status = str(dimension.get("status") or "unknown")
        chart_status = str(chart.get("chart_status") or "missing")
        chart_id = str(chart.get("chart_id") or "")
        chart_is_ready = chart_status == "ready" and chart_id in ready_chart_ids
        presentation_is_ready = chart_is_ready or chart_status == "text_only"
        if chart_status == "ready" and not chart_is_ready:
            chart_status = "missing_spec"
        if analysis_status == "not_triggered" or (
            analysis_status == "covered" and presentation_is_ready
        ):
            continue
        unavailable_dimensions.append(
            {
                "dimension_id": dimension_id,
                "name": dimension.get("name"),
                "priority": dimension.get("priority"),
                "market_question": dimension.get("market_question"),
                "analysis_status": analysis_status,
                "chart_status": chart_status,
                "reason": (
                    "Chart manifest marked this dimension ready, but the chart spec is absent."
                    if chart_status == "missing_spec"
                    else chart.get("reason")
                    or dimension.get("limitation")
                    or "Required evidence is incomplete."
                ),
                "evidence_ids": chart.get("evidence_ids") or dimension.get("evidence_ids") or [],
            }
        )

    source_summary = (
        report_data.get("source_summary")
        if isinstance(report_data.get("source_summary"), dict)
        else {}
    )
    failed_tool_count = int(source_summary.get("failed_tool_count") or 0)
    evidence_gaps = (
        report_data.get("evidence_gaps")
        if isinstance(report_data.get("evidence_gaps"), list)
        else []
    )
    issues = weekly_market_report_readiness_issues(report_data)
    status = "degraded" if issues or failed_tool_count or evidence_gaps else "complete"
    gap_messages = [
        (
            f"分析维度 {item['dimension_id']} {item.get('name') or ''} 未完整产出"
            f"（分析状态 {item['analysis_status']}，图表状态 {item['chart_status']}）：{item['reason']}"
            "；对应结论已降级，其他有证据维度继续生成。"
        )
        for item in unavailable_dimensions
    ]
    return {
        "schema_version": "weekly_market_report_quality.v1",
        "status": status,
        "publishable": True,
        "policy": "Missing tasks suppress their dependent conclusions but do not suppress the report artifact.",
        "diagnostic_issues": issues,
        "failed_tool_count": failed_tool_count,
        "evidence_gap_count": len(evidence_gaps),
        "dimension_total": len(dimensions),
        "dimension_covered": sum(
            1 for item in dimensions if isinstance(item, dict) and item.get("status") == "covered"
        ),
        "p0_total": int((coverage.get("summary") or {}).get("p0_total") or 0)
        if isinstance(coverage.get("summary"), dict)
        else 0,
        "p0_covered": int((coverage.get("summary") or {}).get("p0_covered") or 0)
        if isinstance(coverage.get("summary"), dict)
        else 0,
        "ready_chart_count": sum(
            1
            for chart in report_data.get("chart_specs", [])
            if isinstance(chart, dict) and str(chart.get("quality_status") or "ready") == "ready"
        ),
        "unavailable_dimensions": unavailable_dimensions,
        "gap_messages": gap_messages,
    }


def build_workflow_evidence_report_data(
    payload: dict[str, Any],
    *,
    schema_version: str,
    workflow: str,
    title: str,
) -> dict[str, Any]:
    tool_results = [
        tool
        for tool in payload.get("toolResults") or []
        if isinstance(tool, dict)
        and not str(tool.get("name") or "").startswith("build_")
        and str(tool.get("name") or "")
        not in {
            "analyze_market_report",
            "synthesize_report_insights",
            "render_report_charts",
            "render_html_report",
            "render_markdown_report",
            "review_html_report",
            "red_team_html_report",
            "revise_html_report",
            "review_weekly_market_html",
            "revise_weekly_market_html",
        }
    ]
    successful = [
        tool for tool in tool_results if str(tool.get("status") or "") in SUCCESS_TOOL_STATUSES
    ]
    failed = [
        {
            "tool": str(tool.get("name") or ""),
            "status": str(tool.get("status") or ""),
            "summary": compact_text(str(tool.get("summary") or ""), 360),
        }
        for tool in tool_results
        if str(tool.get("status") or "") not in SUCCESS_TOOL_STATUSES
    ][:24]
    evidence_sources = html_report_compact_tool_results(tool_results, limit=48)
    evidence_gaps = [
        {
            "tool": gap.get("tool"),
            "severity": gap.get("severity"),
            "artifact_requirement": compact_text(
                str(gap.get("artifact_requirement") or gap.get("summary") or ""),
                420,
            ),
        }
        for gap in payload.get("evidenceGaps") or []
        if isinstance(gap, dict)
    ][:24]
    report_data: dict[str, Any] = {
        "schema_version": schema_version,
        "workflow": workflow,
        "title": title,
        "category": str(payload.get("category") or ""),
        "asin": str(payload.get("asin") or "").strip().upper(),
        "brand": str(payload.get("brand") or "Hsia / 遐"),
        "marketplace": str(payload.get("marketplace") or "Amazon US"),
        "time_range": str(payload.get("timeRange") or payload.get("time_range") or ""),
        "generated_at": str(payload.get("generatedAt") or now_iso()),
        "evidence_sources": evidence_sources,
        "evidence_gaps": evidence_gaps,
        "failed_sources": failed,
        "source_summary": {
            "attempted_tool_count": len(tool_results),
            "successful_tool_count": len(successful),
            "failed_tool_count": len(failed),
            "included_source_count": len(evidence_sources),
        },
        "bounds": {
            "max_source_results": 48,
            "max_fields_per_object": 24,
            "max_list_items": 12,
            "review_text_max_chars": 2000,
        },
        "output_contract": {
            "renderer_input": "this report-data object plus presentation instructions only",
            "raw_tool_results_forbidden": True,
            "evidence_handles_required": True,
            "missing_values": "unknown_or_data_gap",
        },
    }
    if workflow == "competitor_product_deep_dive":
        review_images, available_review_images = competitor_review_image_evidence(
            tool_results,
            limit=competitor_review_image_limit(payload),
        )
        report_data["review_image_evidence"] = review_images
        report_data["review_image_coverage"] = {
            "available_unique_image_count": available_review_images,
            "selected_image_count": len(review_images),
            "report_image_limit": competitor_review_image_limit(payload),
            "selection_method": "distinct_reviews_first_then_additional_images",
        }
    elif workflow == "hot_product_pain_analysis":
        product_urls, review_urls = hot_product_required_image_urls(tool_results)
        report_data["required_product_image_urls"] = product_urls
        report_data["required_review_image_urls"] = review_urls
    return report_data


def build_competitor_product_report_data(payload: dict[str, Any]) -> dict[str, Any]:
    asin = str(payload.get("asin") or "").strip().upper()
    return build_workflow_evidence_report_data(
        payload,
        schema_version="competitor_product_report_data.v1",
        workflow="competitor_product_deep_dive",
        title=f"{asin or '竞品'} 爆款深度拆解",
    )


def build_hot_product_pain_report_data(payload: dict[str, Any]) -> dict[str, Any]:
    category = str(payload.get("category") or "目标品类").strip()
    return build_workflow_evidence_report_data(
        payload,
        schema_version="hot_product_pain_report_data.v1",
        workflow="hot_product_pain_analysis",
        title=f"{category} 爆款痛点分析",
    )


def render_html_report_tool(payload: dict[str, Any]) -> dict[str, Any]:
    chart_render_bundle = (
        payload.get("chartRenderBundle")
        if isinstance(payload.get("chartRenderBundle"), dict)
        else {}
    )
    market_report_data = (
        payload.get("marketReportData") if isinstance(payload.get("marketReportData"), dict) else {}
    )
    tiktok_new_product_report_data = (
        payload.get("tiktokNewProductReportData")
        if isinstance(payload.get("tiktokNewProductReportData"), dict)
        else {}
    )
    tiktok_competitor_shop_report_data = (
        payload.get("tiktokCompetitorShopReportData")
        if isinstance(payload.get("tiktokCompetitorShopReportData"), dict)
        else {}
    )
    trend_report_data = (
        payload.get("trendReportData") if isinstance(payload.get("trendReportData"), dict) else {}
    )
    competitor_product_report_data = (
        payload.get("competitorProductReportData")
        if isinstance(payload.get("competitorProductReportData"), dict)
        else {}
    )
    hot_product_pain_report_data = (
        payload.get("hotProductPainReportData")
        if isinstance(payload.get("hotProductPainReportData"), dict)
        else {}
    )
    report_data = (
        competitor_product_report_data
        or hot_product_pain_report_data
        or tiktok_competitor_shop_report_data
        or tiktok_new_product_report_data
        or market_report_data
        or trend_report_data
    )
    if not payload.get("useLlm"):
        raise RuntimeError(
            "render_html_report requires LLM-authored HTML. Enable useLlm=true; no template renderer is available."
        )
    chart_specs = payload.get("chartSpecs") if isinstance(payload.get("chartSpecs"), list) else []
    if market_report_data and chart_specs:
        market_report_data = {**market_report_data, "chart_specs": chart_specs}
    elif (
        market_report_data
        and not str(market_report_data.get("schema_version") or "").startswith("fastmoss_")
        and (
            not isinstance(market_report_data.get("chart_specs"), list)
            or not market_report_data.get("chart_specs")
        )
    ):
        chart_payload = build_market_report_charts(market_report_data)
        generated_specs = (
            chart_payload.get("chart_specs") if isinstance(chart_payload, dict) else []
        )
        if isinstance(generated_specs, list):
            market_report_data = {
                **market_report_data,
                "chart_specs": generated_specs,
                "summary_chart_ids": chart_payload.get("summary_chart_ids") or [],
                "chart_manifest": chart_payload.get("chart_manifest") or [],
                "non_chart_presentations": (
                    chart_payload.get("non_chart_presentations") or []
                ),
            }
    if market_report_data and str(payload.get("skillId") or "") == "weekly_market_insight":
        evidence_gaps = (
            payload.get("evidenceGaps") if isinstance(payload.get("evidenceGaps"), list) else []
        )
        if evidence_gaps:
            market_report_data = {
                **market_report_data,
                "evidence_gaps": evidence_gaps,
                "data_gaps": list(
                    dict.fromkeys(
                        [
                            *(
                                market_report_data.get("data_gaps")
                                if isinstance(market_report_data.get("data_gaps"), list)
                                else []
                            ),
                            *(
                                str(
                                    gap.get("artifact_requirement")
                                    or f"缺少 {gap.get('tool')} 证据。"
                                )
                                for gap in evidence_gaps
                                if isinstance(gap, dict)
                            ),
                        ]
                    )
                )[:24],
            }
        chart_payload = build_market_report_charts(market_report_data)
        market_report_data = {
            **market_report_data,
            "chart_specs": chart_payload.get("chart_specs") or [],
            "summary_chart_ids": chart_payload.get("summary_chart_ids") or [],
            "chart_manifest": chart_payload.get("chart_manifest") or [],
            "non_chart_presentations": (
                chart_payload.get("non_chart_presentations") or []
            ),
        }
        market_report_data["dimension_results"] = build_market_dimension_results(
            market_report_data.get("analysis_coverage")
            if isinstance(market_report_data.get("analysis_coverage"), dict)
            else {},
            market_report_data["chart_manifest"],
        )
        report_quality = weekly_market_report_quality(market_report_data)
        market_report_data = {
            **market_report_data,
            "report_quality": report_quality,
            "data_gaps": list(
                dict.fromkeys(
                    [
                        *(
                            market_report_data.get("data_gaps")
                            if isinstance(market_report_data.get("data_gaps"), list)
                            else []
                        ),
                        *report_quality.get("gap_messages", []),
                    ]
                )
            )[:24],
        }
        market_report_data["artifact"] = market_report_data_to_artifact(market_report_data)
    report_data = (
        competitor_product_report_data
        or hot_product_pain_report_data
        or tiktok_competitor_shop_report_data
        or tiktok_new_product_report_data
        or market_report_data
        or trend_report_data
    )
    render_payload = dict(payload)
    if market_report_data:
        render_payload["marketReportData"] = market_report_data
    if tiktok_new_product_report_data:
        render_payload["tiktokNewProductReportData"] = tiktok_new_product_report_data
    if tiktok_competitor_shop_report_data:
        render_payload["tiktokCompetitorShopReportData"] = (
            tiktok_competitor_shop_report_data
        )
    if trend_report_data:
        render_payload["trendReportData"] = trend_report_data
    if competitor_product_report_data:
        render_payload["competitorProductReportData"] = competitor_product_report_data
    if hot_product_pain_report_data:
        render_payload["hotProductPainReportData"] = hot_product_pain_report_data
    html_content, artifact, html_analysis = compose_html_report_with_llm(
        render_payload,
        locale="zh",
    )
    if not html_content:
        status = html_analysis.get("status") or "error"
        detail = (
            html_analysis.get("message")
            or "LLM did not return a usable self-contained HTML report."
        )
        raise HtmlReportGenerationError(
            f"LLM HTML generation failed ({status}): {detail}",
            html_analysis,
        )
    if not artifact:
        artifact = html_report_base_artifact(payload, report_data, [])
    return {
        "format": "html",
        "title": report_data.get("title") or artifact.get("title") or "HTML 报告",
        "html": html_content,
        "market_report_data": market_report_data,
        "tiktok_new_product_report_data": tiktok_new_product_report_data,
        "tiktok_competitor_shop_report_data": tiktok_competitor_shop_report_data,
        "trend_report_data": trend_report_data,
        "competitor_product_report_data": competitor_product_report_data,
        "hot_product_pain_report_data": hot_product_pain_report_data,
        "chart_render_bundle": chart_render_bundle,
        "artifact": artifact,
        "renderer": "llm-html",
        "html_analysis": html_analysis,
        "report_quality": report_data.get("report_quality")
        if isinstance(report_data.get("report_quality"), dict)
        else {},
    }


def write_agent_run_json(run_id: str, filename: str, payload: Any) -> str:
    run_dir = CACHE_DIR / "agent-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / filename
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
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


def agent_run_is_active(run_id: str) -> bool:
    with ACTIVE_AGENT_RUN_LOCK:
        return run_id in ACTIVE_AGENT_RUN_IDS


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
    progress_status = str(progress.get("status") or "running")
    if progress_status == "running" and not agent_run_is_active(run_id):
        progress_status = "error"
        progress["status"] = "error"
        progress["error"] = (
            "Agent run was interrupted before a final result was written. "
            "The backend may have restarted during a long-running tool call; rerun the task."
        )
    return {
        "run_id": run_id,
        "status": progress_status,
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
    labels = [AGENT_PARAM_LABELS.get(param, {}).get(language, param) for param in missing_params]
    if language == "en":
        message = (
            f"I loaded {skill.get('name')}, but need these inputs before running tools: "
            f"{', '.join(labels)}."
        )
        question_prefix = "Please confirm"
    else:
        message = f"我已加载「{skill.get('name')}」，但执行工具前还需要确认：{'、'.join(labels)}。"
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
            "key_findings": [
                f"Missing input: {question['label']}"
                for question in clarification.get("questions", [])
            ],
            "opportunities": [
                "After the user confirms the missing inputs, continue the same selected skill."
            ],
            "risks": ["No data tools were run yet, so no market conclusion has been generated."],
            "next_steps": ["Reply with the missing inputs in one sentence."],
            "prompt": prompt,
            "mode": mode,
            "category": category,
        }
    return {
        "title": "需要补齐参数",
        "executive_summary": clarification["message"],
        "key_findings": [
            f"缺少参数：{question['label']}" for question in clarification.get("questions", [])
        ],
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
        comments_per_post=int(reddit_comments_per_post)
        if reddit_comments_per_post is not None
        else None,
    )
    result = summarize_posts(category, posts, source_mode, warnings)
    result["data_volume"] = build_data_volume_stats(
        limit,
        posts,
        source_mode,
        use_llm,
        detail_limit_override=int(reddit_detail_limit) if reddit_detail_limit is not None else None,
        comments_per_post_override=int(reddit_comments_per_post)
        if reddit_comments_per_post is not None
        else None,
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

    requested_run_id = str(payload.get("runId") or "").strip()
    tracked_run_id = requested_run_id if re.fullmatch(r"[a-f0-9]{12}", requested_run_id) else ""
    if tracked_run_id:
        with ACTIVE_AGENT_RUN_LOCK:
            ACTIVE_AGENT_RUN_IDS.add(tracked_run_id)
    try:
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
                analyze_market_report=analyze_market_report_node,
                synthesize_report_insights=synthesize_report_insights_node,
                render_report_charts=render_report_charts_via_flint,
                available_report_metrics=available_metric_catalog_for_skill,
                review_html_report=review_html_report_node,
                red_team_html_report=red_team_html_report_node,
                revise_html_report=revise_html_report_node,
            )
        )
        return runtime.run(payload, emit_event=emit_event)
    finally:
        if tracked_run_id:
            with ACTIVE_AGENT_RUN_LOCK:
                ACTIVE_AGENT_RUN_IDS.discard(tracked_run_id)


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
            self.send_json(
                {"error": f"Analysis failed: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR
            )

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
            f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
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
        stream_queue: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()

        def safe_send(event_name: str, event_payload: dict[str, Any]) -> None:
            nonlocal connected
            if not connected:
                return
            try:
                self.send_sse(event_name, event_payload)
            except (BrokenPipeError, ConnectionResetError, OSError):
                connected = False

        def execute_run() -> None:
            try:
                result = run_agent(
                    payload, emit_event=lambda event: stream_queue.put(("event", event))
                )
                stream_queue.put(("result", result))
            except ValueError as exc:
                stream_queue.put(("error", {"error": str(exc)}))
            except Exception as exc:  # noqa: BLE001
                stream_queue.put(("error", {"error": f"Analysis failed: {exc}"}))
            finally:
                stream_queue.put(None)

        worker = threading.Thread(
            target=execute_run,
            name=f"agent-run-{str(payload.get('runId') or 'stream')}",
            daemon=True,
        )
        worker.start()
        while connected:
            try:
                item = stream_queue.get(timeout=AGENT_STREAM_HEARTBEAT_SECONDS)
            except queue.Empty:
                safe_send(
                    "heartbeat",
                    {
                        "run_id": payload.get("runId"),
                        "timestamp": now_iso(),
                    },
                )
                continue
            if item is None:
                break
            event_name, event_payload = item
            safe_send(event_name, event_payload)


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

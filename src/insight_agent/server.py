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

from .ingestion.agent_reach import agent_reach_health, fetch_reddit_agent_reach, reconnect_opencli_extension
from .llm import LLMUnavailable, enhance_report_with_llm
from .settings import (
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
        "trend": [{"month": month, "count": count} for month, count in sorted(month_counts.items())],
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
    posts, warnings, source_mode = collect_reddit(category, limit, time_range, mode, bypass_cache=bypass_cache)
    result = summarize_posts(category, posts, source_mode, warnings)
    result["data_volume"] = build_data_volume_stats(limit, posts, source_mode, bool(payload.get("useLlm")))
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
    if bool(payload.get("useLlm")):
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
            elif parsed.path == "/api/settings/llm":
                result = update_llm_settings(payload)
            elif parsed.path == "/api/settings/reddit":
                result = update_reddit_settings(payload)
            elif parsed.path == "/api/settings/research":
                result = update_research_settings(payload)
            elif parsed.path == "/api/settings/agent-reach":
                result = update_agent_reach_settings(payload)
            else:
                result = analyze_category(payload)
            self.send_json(result)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": f"Analysis failed: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

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

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TikTokResult:
    videos: list[dict[str, Any]]
    warnings: list[str]
    source_mode: str


def compact_text(value: Any, limit: int = 1200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def int_or_none(value: Any) -> int | None:
    if value in {None, ""} or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    text = str(value).strip().lower().replace(",", "")
    multiplier = 1
    if text.endswith("k"):
        multiplier = 1_000
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1_000_000
        text = text[:-1]
    elif text.endswith("b"):
        multiplier = 1_000_000_000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def normalize_video_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if url.startswith("/"):
        url = f"https://www.tiktok.com{url}"
    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    if "/video/" not in path:
        return ""
    return urllib.parse.urlunparse((parsed.scheme or "https", parsed.netloc, path, "", "", ""))


def tiktok_video_id(url: str) -> str:
    match = re.search(r"/video/(\d+)", url)
    return match.group(1) if match else url


def hashtag_terms(*values: Any) -> list[str]:
    tags: list[str] = []
    for value in values:
        for tag in re.findall(r"#([\w.-]+)", str(value or "")):
            clean = tag.strip(".,;:!?)]}")
            if clean:
                tags.append(clean)
    seen: set[str] = set()
    unique: list[str] = []
    for tag in tags:
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(tag)
    return unique[:30]


def tiktok_profile_dir() -> Path:
    configured = os.getenv("TIKTOK_BROWSER_PROFILE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".insight-agent" / "tiktok-chrome-profile"


def find_chrome_executable() -> Path | None:
    configured = os.getenv("TIKTOK_CHROME_PATH", "").strip()
    if configured:
        configured_path = Path(configured).expanduser()
        return configured_path if configured_path.is_file() else None

    for command in ("chrome", "chrome.exe", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        resolved = shutil.which(command)
        if resolved:
            return Path(resolved)

    candidates: list[Path] = []
    if os.name == "nt":
        for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.getenv(env_key, "").strip()
            if root:
                candidates.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        candidates.extend(
            [
                Path("/usr/bin/google-chrome"),
                Path("/usr/bin/google-chrome-stable"),
                Path("/usr/bin/chromium"),
                Path("/usr/bin/chromium-browser"),
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def open_tiktok_login_browser() -> dict[str, Any]:
    profile_dir = tiktok_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    chrome_path = find_chrome_executable()
    if not chrome_path:
        return {
            "ok": False,
            "status": "chrome_not_found",
            "profile_dir": str(profile_dir),
            "chrome_path": "",
            "message": "Google Chrome was not found. Set TIKTOK_CHROME_PATH to chrome.exe and retry.",
        }

    login_url = os.getenv("TIKTOK_LOGIN_URL", "https://www.tiktok.com/login").strip() or "https://www.tiktok.com/login"
    args = [
        str(chrome_path),
        f"--user-data-dir={profile_dir}",
        "--profile-directory=Default",
        "--no-first-run",
        "--new-window",
        login_url,
    ]
    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    try:
        subprocess.Popen(args, **popen_kwargs)  # noqa: S603
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "launch_failed",
            "profile_dir": str(profile_dir),
            "chrome_path": str(chrome_path),
            "message": f"Could not open Chrome for TikTok login: {exc}",
        }
    return {
        "ok": True,
        "status": "opened",
        "profile_dir": str(profile_dir),
        "chrome_path": str(chrome_path),
        "url": login_url,
        "message": "Opened a dedicated Chrome profile for TikTok login. Close that window after login, then run TikTok collection.",
    }


def tiktok_headless() -> bool:
    return os.getenv("TIKTOK_HEADLESS", "0").strip().lower() in {"1", "true", "yes"}


def tiktok_login_wait_seconds() -> int:
    raw = os.getenv("TIKTOK_LOGIN_WAIT_SECONDS", "240").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 240
    return max(0, min(value, 600))


def playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def build_search_url(query: str) -> str:
    stripped = query.strip()
    if stripped.startswith("#") and len(stripped) > 1:
        return f"https://www.tiktok.com/tag/{urllib.parse.quote(stripped[1:])}"
    return f"https://www.tiktok.com/search?q={urllib.parse.quote(stripped)}"


def normalize_video(base: dict[str, Any], detail: dict[str, Any], comments: list[dict[str, Any]]) -> dict[str, Any]:
    url = normalize_video_url(detail.get("url") or base.get("url"))
    caption = compact_text(detail.get("caption") or detail.get("title") or base.get("caption") or base.get("title"), 2000)
    author = str(detail.get("author") or base.get("author") or "").strip()
    return {
        "id": str(detail.get("id") or tiktok_video_id(url)),
        "url": url,
        "title": compact_text(detail.get("title") or caption or "Untitled TikTok video", 220),
        "caption": caption,
        "author": author,
        "author_url": str(detail.get("author_url") or base.get("author_url") or "").strip(),
        "cover_url": str(detail.get("cover_url") or base.get("cover_url") or "").strip(),
        "hashtags": hashtag_terms(caption, *(detail.get("hashtags") or []), *(base.get("hashtags") or [])),
        "view_count": int_or_none(detail.get("view_count") or base.get("view_count")),
        "like_count": int_or_none(detail.get("like_count") or base.get("like_count")),
        "comment_count": int_or_none(detail.get("comment_count") or base.get("comment_count")),
        "share_count": int_or_none(detail.get("share_count") or base.get("share_count")),
        "save_count": int_or_none(detail.get("save_count") or base.get("save_count")),
        "published_at": str(detail.get("published_at") or base.get("published_at") or "").strip(),
        "comment_samples": comments,
        "fetched_at": "",
    }


def collect_search_cards(page: Any, query: str, limit: int, max_scrolls: int = 8) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    search_url = build_search_url(query)
    page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_timeout(2_500)
    seen: set[str] = set()
    cards: list[dict[str, Any]] = []
    for _ in range(max_scrolls + 1):
        raw_cards = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('a[href*="/video/"]'))
              .map((anchor) => {
                const href = anchor.href || anchor.getAttribute('href') || '';
                const container = anchor.closest('article, [data-e2e*="search"], [data-e2e*="video"], div') || anchor;
                const text = (container.innerText || anchor.innerText || '').trim();
                const image = anchor.querySelector('img') || container.querySelector('img');
                const author = container.querySelector('a[href^="/@"]');
                return {
                  url: href,
                  title: (anchor.getAttribute('title') || '').trim(),
                  caption: text,
                  cover_url: image ? image.src : '',
                  author: author ? author.textContent.trim() : '',
                  author_url: author ? author.href : '',
                };
              })
            """
        )
        for item in raw_cards if isinstance(raw_cards, list) else []:
            if not isinstance(item, dict):
                continue
            url = normalize_video_url(item.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            cards.append({**item, "url": url, "hashtags": hashtag_terms(item.get("caption"), item.get("title"))})
            if len(cards) >= limit:
                break
        if len(cards) >= limit:
            break
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(1_100)
    if not cards:
        warnings.append(
            "TikTok search returned no readable video links. Log in in the opened browser, solve any challenge, then rerun with bypass cache."
        )
    return cards[:limit], warnings


def extract_video_detail(page: Any, url: str, comments_per_video: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_timeout(2_500)
    for _ in range(3):
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(700)
    detail = page.evaluate(
        """
        () => {
          const meta = (name) =>
            document.querySelector(`meta[property="${name}"]`)?.content ||
            document.querySelector(`meta[name="${name}"]`)?.content ||
            '';
          const textOf = (...selectors) => {
            for (const selector of selectors) {
              const element = document.querySelector(selector);
              const text = element ? (element.textContent || '').trim() : '';
              if (text) return text;
            }
            return '';
          };
          const authorLink = document.querySelector('a[href^="/@"]');
          const caption = textOf('[data-e2e="browse-video-desc"]', '[data-e2e="video-desc"]', 'h1[data-e2e]', 'h1');
          const count = (...selectors) => textOf(...selectors);
          const tagLinks = Array.from(document.querySelectorAll('a[href*="/tag/"]')).map((item) => item.textContent.trim()).filter(Boolean);
          return {
            url: location.href,
            title: meta('og:title') || document.title || caption,
            caption: caption || meta('description') || meta('og:description'),
            author: authorLink ? authorLink.textContent.trim() : '',
            author_url: authorLink ? authorLink.href : '',
            cover_url: meta('og:image'),
            hashtags: tagLinks,
            like_count: count('[data-e2e="like-count"]', '[data-e2e="browse-like-count"]'),
            comment_count: count('[data-e2e="comment-count"]', '[data-e2e="browse-comment-count"]'),
            share_count: count('[data-e2e="share-count"]', '[data-e2e="browse-share-count"]'),
            save_count: count('[data-e2e="undefined-count"]', '[data-e2e="favorite-count"]'),
          };
        }
        """
    )
    comments = page.evaluate(
        """
        (limit) => {
          const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim();
          const nodes = Array.from(document.querySelectorAll(
            '[data-e2e="comment-level-1"], [data-e2e="comment-item"], [class*="CommentItem"], [class*="DivCommentItem"]'
          ));
          const candidates = nodes.length ? nodes : Array.from(document.querySelectorAll('[data-e2e*="comment"]')).slice(0, limit * 3);
          const comments = [];
          const seen = new Set();
          for (const node of candidates) {
            const authorLink = node.querySelector('a[href^="/@"]');
            const author = normalize(authorLink ? authorLink.textContent : '');
            let text = normalize(node.innerText || node.textContent || '');
            if (!text || text.length < 2) continue;
            if (author && text.startsWith(author)) text = normalize(text.slice(author.length));
            text = text.replace(/\\bReply\\b.*$/i, '').replace(/\\bLike\\b.*$/i, '').trim();
            if (!text || seen.has(text)) continue;
            seen.add(text);
            comments.push({ id: '', author, text, like_count: null, created_at: '' });
            if (comments.length >= limit) break;
          }
          return comments;
        }
        """,
        comments_per_video,
    )
    raw_comments = comments if isinstance(comments, list) else []
    normalized_comments = [
        {
            "id": str(comment.get("id") or "").strip(),
            "author": str(comment.get("author") or "").strip(),
            "text": compact_text(comment.get("text"), 900),
            "like_count": int_or_none(comment.get("like_count")),
            "created_at": str(comment.get("created_at") or "").strip(),
        }
        for comment in raw_comments
        if isinstance(comment, dict) and str(comment.get("text") or "").strip()
    ][:comments_per_video]
    if comments_per_video > 0 and not normalized_comments:
        warnings.append(f"No readable TikTok comments were collected from detail page {url}.")
    return detail if isinstance(detail, dict) else {"url": url}, normalized_comments, warnings


def fetch_tiktok_playwright(
    query: str,
    limit: int,
    comments_per_video: int = 10,
    timeout_seconds: int = 180,
) -> TikTokResult:
    if not playwright_available():
        return TikTokResult(
            [],
            [
                "Playwright is not installed. Install project dependencies, then run `python -m playwright install chromium` before TikTok collection.",
            ],
            "tiktok_unavailable",
        )

    from playwright.sync_api import (  # type: ignore[import-not-found]
        TimeoutError as PlaywrightTimeoutError,
    )
    from playwright.sync_api import sync_playwright

    limit = max(1, min(int(limit), 30))
    comments_per_video = max(1, min(int(comments_per_video), 50))
    warnings: list[str] = []
    profile_dir = tiktok_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    headless = tiktok_headless()
    login_wait_seconds = tiktok_login_wait_seconds()
    chrome_path = find_chrome_executable()
    try:
        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {
                "headless": headless,
                "viewport": {"width": 1280, "height": 900},
                "locale": "en-US",
                "timeout": timeout_seconds * 1000,
            }
            if chrome_path:
                launch_options["executable_path"] = str(chrome_path)
            context = playwright.chromium.launch_persistent_context(
                str(profile_dir),
                **launch_options,
            )
            page = context.pages[0] if context.pages else context.new_page()
            try:
                cards, search_warnings = collect_search_cards(page, query, limit)
                if not cards and not headless and login_wait_seconds > 0:
                    warnings.append(
                        "TikTok returned no readable video links. "
                        f"Kept the browser open for {login_wait_seconds} seconds so you could log in or solve a challenge, then retried search."
                    )
                    page.wait_for_timeout(login_wait_seconds * 1000)
                    cards, retry_warnings = collect_search_cards(page, query, limit)
                    warnings.extend(retry_warnings)
                else:
                    warnings.extend(search_warnings)
                videos: list[dict[str, Any]] = []
                for card in cards:
                    detail, comments, detail_warnings = extract_video_detail(
                        page,
                        str(card.get("url") or ""),
                        comments_per_video,
                    )
                    warnings.extend(detail_warnings)
                    video = normalize_video(card, detail, comments)
                    if video["url"]:
                        videos.append(video)
                context.close()
                return TikTokResult(videos, warnings, "tiktok_playwright")
            except PlaywrightTimeoutError as exc:
                context.close()
                return TikTokResult([], [f"TikTok browser collection timed out: {exc}"], "tiktok_playwright")
            except Exception as exc:  # noqa: BLE001
                context.close()
                return TikTokResult([], [f"TikTok browser collection failed: {exc}"], "tiktok_playwright")
    except Exception as exc:  # noqa: BLE001
        return TikTokResult(
            [],
            [
                "TikTok browser could not start. If the dedicated TikTok login Chrome window is still open, close it and rerun collection. "
                "You can also run `python -m playwright install chromium`, then rerun. "
                f"Details: {exc}"
            ],
            "tiktok_unavailable",
        )

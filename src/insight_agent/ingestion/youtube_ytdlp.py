from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent_reach import resolve_command, run_command


@dataclass(frozen=True)
class YouTubeResult:
    videos: list[dict[str, Any]]
    warnings: list[str]
    source_mode: str


def yt_dlp_command() -> list[str]:
    if resolve_command("yt-dlp"):
        return ["yt-dlp"]
    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    return []


def parse_json_lines(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            items.append(payload)
    return items


def int_or_none(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    try:
        return int(str(value).replace(",", "").strip())
    except ValueError:
        return None


def upload_date_to_iso(value: Any) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{8}", text):
        return ""
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def compact_text(value: Any, limit: int = 1200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def normalize_video(payload: dict[str, Any]) -> dict[str, Any]:
    video_id = str(payload.get("id") or "").strip()
    url = str(payload.get("webpage_url") or payload.get("url") or "").strip()
    if video_id and not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={video_id}"
    return {
        "id": video_id,
        "title": str(payload.get("title") or "Untitled YouTube video").strip(),
        "url": url,
        "channel": str(payload.get("channel") or payload.get("uploader") or "").strip(),
        "channel_url": str(payload.get("channel_url") or payload.get("uploader_url") or "").strip(),
        "duration_seconds": int_or_none(payload.get("duration")),
        "view_count": int_or_none(payload.get("view_count")),
        "like_count": int_or_none(payload.get("like_count")),
        "comment_count": int_or_none(payload.get("comment_count")),
        "upload_date": upload_date_to_iso(payload.get("upload_date")),
        "description": compact_text(payload.get("description"), 1800),
        "thumbnail": str(payload.get("thumbnail") or "").strip(),
        "tags": [str(tag) for tag in payload.get("tags") or [] if str(tag).strip()][:20],
        "transcript": "",
        "transcript_chars": 0,
        "comment_samples": [],
        "fetched_at": "",
    }


def search_warning_from_error(stderr: str, stdout: str) -> str:
    message = compact_text((stderr or stdout).strip(), 360)
    if not message:
        return "yt-dlp skipped one or more YouTube search results."
    return f"yt-dlp skipped one or more YouTube search results: {message}"


def search_youtube_videos(
    command: list[str],
    query: str,
    limit: int,
    timeout_seconds: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    search_limit = max(limit, min(limit * 3, 50))
    warnings: list[str] = []
    args = [
        *command,
        "--dump-json",
        "--skip-download",
        "--ignore-errors",
        "--no-warnings",
        f"ytsearch{search_limit}:{query}",
    ]
    code, stdout, stderr = run_command(args, timeout_seconds)
    items = parse_json_lines(stdout)
    if items:
        if code != 0:
            warnings.append(search_warning_from_error(stderr, stdout))
        return items, warnings

    if code != 0:
        warnings.append(search_warning_from_error(stderr, stdout))

    flat_args = [
        *command,
        "--dump-json",
        "--skip-download",
        "--flat-playlist",
        "--ignore-errors",
        "--no-warnings",
        f"ytsearch{search_limit}:{query}",
    ]
    flat_code, flat_stdout, flat_stderr = run_command(flat_args, timeout_seconds)
    flat_items = parse_json_lines(flat_stdout)
    if flat_items:
        if flat_code != 0:
            warnings.append(search_warning_from_error(flat_stderr, flat_stdout))
        warnings.append(
            "Used yt-dlp flat YouTube search fallback after full metadata search returned no usable videos."
        )
        return flat_items, warnings

    if flat_code != 0:
        warnings.append(f"yt-dlp YouTube search failed: {(flat_stderr or flat_stdout or stderr or stdout).strip()[:400]}")
    elif not warnings:
        warnings.append("yt-dlp YouTube search returned no usable videos.")
    return [], warnings


def vtt_to_text(content: str, limit: int = 8000) -> str:
    lines: list[str] = []
    previous = ""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT" or "-->" in line:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line or line == previous:
            continue
        previous = line
        lines.append(line)
    text = " ".join(lines)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def collect_transcript(video: dict[str, Any], command: list[str], timeout_seconds: int) -> tuple[str, str]:
    url = video.get("url")
    video_id = video.get("id") or "youtube-video"
    if not url:
        return "", "Missing video URL for transcript fetch."
    with tempfile.TemporaryDirectory(prefix="insight-youtube-") as tmp_dir:
        output_template = str(Path(tmp_dir) / "%(id)s")
        args = [
            *command,
            "--write-sub",
            "--write-auto-sub",
            "--sub-langs",
            "en.*,en,zh-Hans,zh",
            "--sub-format",
            "vtt",
            "--skip-download",
            "--no-warnings",
            "-o",
            output_template,
            str(url),
        ]
        code, stdout, stderr = run_command(args, timeout_seconds)
        if code != 0:
            return "", f"yt-dlp subtitle fetch failed for {video_id}: {(stderr or stdout).strip()[:260]}"
        texts = []
        for path in Path(tmp_dir).glob("*.vtt"):
            try:
                text = vtt_to_text(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
            if text:
                texts.append(text)
        if not texts:
            return "", f"No readable YouTube transcript found for {video_id}."
        return compact_text(" ".join(texts), 8000), ""


def normalize_comment(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(comment.get("id") or "").strip(),
        "author": str(comment.get("author") or "").strip(),
        "text": compact_text(comment.get("text"), 900),
        "like_count": int_or_none(comment.get("like_count")),
        "timestamp": int_or_none(comment.get("timestamp")),
    }


def collect_comments(
    video: dict[str, Any],
    command: list[str],
    comments_per_video: int,
    timeout_seconds: int,
) -> tuple[list[dict[str, Any]], str]:
    url = video.get("url")
    video_id = video.get("id") or "youtube-video"
    if not url or comments_per_video <= 0:
        return [], ""
    with tempfile.TemporaryDirectory(prefix="insight-youtube-") as tmp_dir:
        output_template = str(Path(tmp_dir) / "%(id)s")
        args = [
            *command,
            "--write-comments",
            "--skip-download",
            "--write-info-json",
            "--extractor-args",
            f"youtube:max_comments={comments_per_video}",
            "--no-warnings",
            "-o",
            output_template,
            str(url),
        ]
        code, stdout, stderr = run_command(args, timeout_seconds)
        if code != 0:
            return [], f"yt-dlp comment fetch failed for {video_id}: {(stderr or stdout).strip()[:260]}"
        for path in Path(tmp_dir).glob("*.info.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            raw_comments = payload.get("comments") if isinstance(payload, dict) else []
            if isinstance(raw_comments, list):
                comments = [
                    normalize_comment(comment)
                    for comment in raw_comments
                    if isinstance(comment, dict) and str(comment.get("text") or "").strip()
                ]
                return comments[:comments_per_video], ""
        return [], f"No readable YouTube comments found for {video_id}."


def fetch_youtube_ytdlp(
    query: str,
    limit: int,
    transcript_video_limit: int = 5,
    comment_video_limit: int = 3,
    comments_per_video: int = 10,
    timeout_seconds: int = 120,
) -> YouTubeResult:
    command = yt_dlp_command()
    if not command:
        return YouTubeResult(
            [],
            [
                "yt-dlp is not installed. Install it with `python -m pip install yt-dlp` or reinstall project dependencies.",
            ],
            "youtube_unavailable",
        )

    limit = max(1, min(int(limit), 50))
    transcript_video_limit = max(0, min(int(transcript_video_limit), limit))
    comment_video_limit = max(0, min(int(comment_video_limit), limit))
    comments_per_video = max(0, min(int(comments_per_video), 50))
    search_items, warnings = search_youtube_videos(command, query, limit, timeout_seconds)
    if not search_items:
        return YouTubeResult([], warnings, "youtube_ytdlp")

    videos = [normalize_video(item) for item in search_items]
    videos = [video for video in videos if video.get("url")][:limit]
    for index, video in enumerate(videos):
        video["fetched_at"] = ""
        if index < transcript_video_limit:
            transcript, warning = collect_transcript(video, command, timeout_seconds)
            if transcript:
                video["transcript"] = transcript
                video["transcript_chars"] = len(transcript)
            if warning:
                warnings.append(warning)
        if index < comment_video_limit:
            comments, warning = collect_comments(video, command, comments_per_video, timeout_seconds)
            video["comment_samples"] = comments
            if warning:
                warnings.append(warning)
    return YouTubeResult(videos, warnings, "youtube_ytdlp")

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from .schema import EvidenceItem, ProviderResult


@dataclass(frozen=True)
class AgentReachConfig:
    enabled: bool = True
    timeout_seconds: int = 90
    detail_limit: int = 8
    comments_per_post: int = 20
    preferred_backend: str = "opencli"


def agent_reach_config_from_env() -> AgentReachConfig:
    return AgentReachConfig(
        enabled=os.getenv("AGENT_REACH_ENABLED", "1").strip().lower() not in {"0", "false", "no"},
        timeout_seconds=int(os.getenv("AGENT_REACH_TIMEOUT", "90") or 90),
        detail_limit=int(os.getenv("AGENT_REACH_DETAIL_LIMIT", "8") or 8),
        comments_per_post=int(os.getenv("AGENT_REACH_COMMENTS_PER_POST", "20") or 20),
        preferred_backend=os.getenv("AGENT_REACH_BACKEND", "opencli").strip().lower() or "opencli",
    )


def command_search_path() -> str:
    paths = [os.environ.get("PATH", "")]
    for key in ("AGENT_REACH_BIN_DIR",):
        value = os.environ.get(key)
        if value:
            paths.insert(0, value)
    venv = os.environ.get("AGENT_REACH_VENV")
    if venv:
        paths.insert(0, os.path.join(venv, "Scripts"))
        paths.insert(0, os.path.join(venv, "bin"))
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", "")
    program_files = os.environ.get("ProgramFiles", "")
    codex_deps = os.path.join(home, ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies")
    paths.insert(0, os.path.join(codex_deps, "node", "bin"))
    paths.insert(0, os.path.join(codex_deps, "bin"))
    paths.insert(0, os.path.join(home, ".agent-reach-venv", "Scripts"))
    paths.insert(0, os.path.join(home, ".agent-reach-venv", "bin"))
    paths.insert(0, os.path.join(home, ".agent-reach", "bin"))
    if appdata:
        paths.insert(0, os.path.join(appdata, "npm"))
    if program_files:
        paths.insert(0, os.path.join(program_files, "nodejs"))
    paths.insert(0, os.path.join(home, ".local", "bin"))
    return os.pathsep.join(dict.fromkeys(path for path in paths if path))


def resolve_command(name: str) -> str | None:
    return shutil.which(name, path=command_search_path())


def agent_reach_health() -> dict[str, Any]:
    opencli = resolve_command("opencli")
    rdt = resolve_command("rdt")
    agent_reach = resolve_command("agent-reach")
    opencli_connected = opencli_daemon_connected() if opencli else False
    ready = opencli_connected or bool(rdt)
    return {
        "agent_reach_installed": bool(agent_reach),
        "opencli_installed": bool(opencli),
        "opencli_connected": opencli_connected,
        "rdt_installed": bool(rdt),
        "agent_reach_path": agent_reach or "",
        "opencli_path": opencli or "",
        "rdt_path": rdt or "",
        "ready": ready,
        "recommended_backend": "opencli" if opencli_connected else "rdt" if rdt else "",
    }


def run_command(args: list[str], timeout_seconds: int) -> tuple[int, str, str]:
    resolved = resolve_command(args[0])
    final_args = [resolved or args[0], *args[1:]]
    env = os.environ.copy()
    env["PATH"] = command_search_path()
    completed = subprocess.run(
        final_args,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout_seconds,
    )
    return completed.returncode, completed.stdout, completed.stderr


def opencli_daemon_connected() -> bool:
    try:
        code, stdout, stderr = run_command(["opencli", "daemon", "status"], 8)
    except Exception:  # noqa: BLE001 - health check should not break API.
        return False
    if code != 0:
        return False
    output = f"{stdout}\n{stderr}".lower()
    return "extension: connected" in output


def trim_command_output(text: str, limit: int = 1200) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[-limit:]


def reconnect_opencli_extension(timeout_seconds: int = 20) -> dict[str, Any]:
    before = agent_reach_health()
    if not before.get("opencli_installed"):
        return {
            "ok": False,
            "message": "OpenCLI is not installed. Install OpenCLI before connecting the Chrome extension.",
            "health": before,
            "restart": {"code": None, "stdout": "", "stderr": "opencli not found"},
            "profiles": {"code": None, "stdout": "", "stderr": ""},
        }

    try:
        code, stdout, stderr = run_command(["opencli", "daemon", "restart"], max(10, min(timeout_seconds, 60)))
    except Exception as exc:  # noqa: BLE001 - return diagnostics to the settings UI.
        after = agent_reach_health()
        return {
            "ok": False,
            "message": f"OpenCLI daemon restart failed: {exc}",
            "health": after,
            "restart": {"code": None, "stdout": "", "stderr": str(exc)},
            "profiles": {"code": None, "stdout": "", "stderr": ""},
        }

    after = agent_reach_health()
    for _ in range(6):
        if after.get("opencli_connected"):
            break
        time.sleep(1)
        after = agent_reach_health()

    profile_code: int | None = None
    profile_stdout = ""
    profile_stderr = ""
    try:
        profile_code, profile_stdout, profile_stderr = run_command(["opencli", "profile", "list"], 8)
    except Exception as exc:  # noqa: BLE001
        profile_stderr = str(exc)

    connected = bool(after.get("opencli_connected"))
    if connected:
        message = "OpenCLI daemon restarted and the Chrome extension is connected."
    elif code == 0:
        message = (
            "OpenCLI daemon restarted, but the Chrome extension is still not connected. "
            "Open Chrome with the OpenCLI extension enabled, then click reconnect again."
        )
    else:
        message = f"OpenCLI daemon restart failed: {stderr.strip() or stdout.strip() or f'exit code {code}'}"

    return {
        "ok": connected,
        "message": message,
        "health": after,
        "restart": {
            "code": code,
            "stdout": trim_command_output(stdout),
            "stderr": trim_command_output(stderr),
        },
        "profiles": {
            "code": profile_code,
            "stdout": trim_command_output(profile_stdout),
            "stderr": trim_command_output(profile_stderr),
        },
    }


def parse_structured_output(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    return parse_simple_yaml(stripped)


def parse_simple_yaml(text: str) -> Any:
    try:
        import yaml  # type: ignore[import-untyped]

        return yaml.safe_load(text)
    except Exception:  # noqa: BLE001 - keep provider optional without PyYAML.
        return parse_yaml_like_list(text)


def parse_yaml_like_list(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- "):
            if current:
                items.append(current)
            current = {}
            line = line.lstrip()[2:]
            if ":" in line:
                key, value = line.split(":", 1)
                current[key.strip()] = value.strip().strip('"').strip("'")
            continue
        if current is not None and ":" in line:
            key, value = line.strip().split(":", 1)
            current[key.strip()] = value.strip().strip('"').strip("'")
    if current:
        items.append(current)
    return items


def coerce_items(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "results", "posts", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def first_value(item: dict[str, Any], keys: tuple[str, ...], default: Any = "") -> Any:
    for key in keys:
        value = item.get(key)
        if value not in {None, ""}:
            return value
    return default


def normalize_reddit_item(item: dict[str, Any], provider: str) -> EvidenceItem:
    url = str(first_value(item, ("url", "link", "permalink", "href"), ""))
    if url.startswith("/"):
        url = "https://www.reddit.com" + url
    external_id = str(first_value(item, ("id", "post_id", "name"), "")) or post_id_from_url(url)
    title = str(first_value(item, ("title", "name"), ""))
    text = str(first_value(item, ("text", "selftext", "body", "snippet", "excerpt", "content"), ""))
    community = str(first_value(item, ("subreddit", "community", "subreddit_name"), "")) or subreddit_from_url(url)
    created_at = str(first_value(item, ("created_utc", "created_at", "created", "date", "time"), ""))
    score = numeric_or_none(first_value(item, ("score", "ups", "upvotes"), None))
    comment_count = numeric_or_none(first_value(item, ("comments", "num_comments", "comment_count"), None))
    comments = normalize_comments(first_value(item, ("comments_data", "comment_items", "replies"), []))
    return EvidenceItem(
        source="reddit",
        provider=provider,
        content_type="post",
        external_id=external_id,
        title=title,
        text=text,
        url=url,
        author=first_value(item, ("author", "user"), None),
        community=community,
        created_at=created_at,
        metrics={"score": score, "comments": comment_count},
        comments=comments,
        raw=item,
    )


def normalize_opencli_read_items(
    payload: Any,
    url: str,
    provider: str,
    external_id_hint: str = "",
) -> list[EvidenceItem]:
    rows = coerce_items(payload)
    if not rows:
        return []
    post_row = next(
        (row for row in rows if str(row.get("type", "")).strip().upper() == "POST"),
        rows[0],
    )
    post_text = str(post_row.get("text") or "")
    title = str(first_value(post_row, ("title", "name"), "")).strip()
    if not title:
        title = post_text.splitlines()[0].strip() if post_text.strip() else ""
    normalized_url = url if url.startswith("http") else str(first_value(post_row, ("url", "permalink"), ""))
    if normalized_url.startswith("/"):
        normalized_url = "https://www.reddit.com" + normalized_url
    external_id = external_id_hint or post_id_from_url(normalized_url) or str(
        first_value(post_row, ("id", "post_id", "name"), "")
    )
    comments = []
    for row in rows:
        row_type = str(row.get("type", "")).strip().upper()
        text = str(row.get("text") or "").strip()
        if row is post_row or row_type == "POST" or not text or text.startswith("[+"):
            continue
        comments.append(
            {
                "id": row.get("id") or "",
                "author": row.get("author") or None,
                "text": text,
                "score": numeric_or_none(row.get("score")),
                "created_at": row.get("created_at") or "",
                "url": "",
            }
        )
    return [
        EvidenceItem(
            source="reddit",
            provider=provider,
            content_type="post",
            external_id=external_id,
            title=title,
            text=post_text,
            url=normalized_url,
            author=post_row.get("author") or None,
            community=subreddit_from_url(normalized_url),
            metrics={"score": numeric_or_none(post_row.get("score")), "comments": len(comments)},
            comments=comments,
            raw={"rows": rows},
        )
    ]


def normalize_comments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    comments: list[dict[str, Any]] = []
    for raw in value:
        if isinstance(raw, str):
            comments.append({"text": raw})
        elif isinstance(raw, dict):
            comments.append(
                {
                    "id": raw.get("id") or raw.get("comment_id") or "",
                    "author": raw.get("author") or raw.get("user"),
                    "text": raw.get("text") or raw.get("body") or raw.get("content") or "",
                    "score": numeric_or_none(raw.get("score") if raw.get("score") is not None else raw.get("ups")),
                    "created_at": raw.get("created_at") or raw.get("created_utc") or "",
                    "url": raw.get("url") or raw.get("permalink") or "",
                }
            )
    return comments


def numeric_or_none(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return value
    text = str(value).replace(",", "").strip()
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return None


def post_id_from_url(url: str) -> str:
    match = re.search(r"/comments/([^/]+)/", url)
    return match.group(1) if match else ""


def subreddit_from_url(url: str) -> str:
    match = re.search(r"/r/([^/]+)/", url, flags=re.I)
    return match.group(1) if match else ""


def fetch_reddit_agent_reach(query: str, limit: int, time_range: str) -> ProviderResult:
    config = agent_reach_config_from_env()
    if not config.enabled:
        return ProviderResult([], ["Agent Reach provider is disabled."], "agent_reach")

    health = agent_reach_health()
    warnings: list[str] = []
    if not health["ready"]:
        if health["opencli_installed"] and not health.get("opencli_connected"):
            return ProviderResult(
                [],
                ["OpenCLI is installed, but the Chrome extension is not connected. Install/connect the extension and log in to Reddit."],
                "agent_reach",
            )
        return ProviderResult(
            [],
            ["Agent Reach is not ready. Install OpenCLI or rdt-cli, then log in to Reddit."],
            "agent_reach",
        )

    backend = config.preferred_backend
    if backend == "auto":
        backend = health["recommended_backend"]
    if backend == "opencli" and not health["opencli_installed"]:
        warnings.append("OpenCLI is not installed; trying rdt-cli.")
        backend = "rdt"
    if backend == "rdt" and not health["rdt_installed"]:
        warnings.append("rdt-cli is not installed; trying OpenCLI.")
        backend = "opencli"

    if backend == "opencli" and health["opencli_installed"]:
        result = search_reddit_opencli(query, limit, time_range, config.timeout_seconds)
    elif backend == "rdt" and health["rdt_installed"]:
        result = search_reddit_rdt(query, limit, config.timeout_seconds)
    else:
        return ProviderResult([], warnings + ["No usable Agent Reach Reddit backend found."], "agent_reach")

    warnings.extend(result.warnings)
    detail_limit = max(0, min(config.detail_limit, len(result.items)))
    if detail_limit:
        enriched, detail_warnings = enrich_reddit_details(result.items, detail_limit, config)
        warnings.extend(detail_warnings)
        result.items = enriched
    return ProviderResult(result.items[:limit], warnings, result.source_mode)


def search_reddit_opencli(query: str, limit: int, time_range: str, timeout_seconds: int) -> ProviderResult:
    args = ["opencli", "reddit", "search", query, "--limit", str(limit), "--time", time_range, "-f", "json"]
    code, stdout, stderr = run_command(args, timeout_seconds)
    if code != 0 or not stdout.strip():
        args = ["opencli", "reddit", "search", query, "--limit", str(limit), "--time", time_range, "-f", "yaml"]
        code, stdout, stderr = run_command(args, timeout_seconds)
    if code != 0:
        return ProviderResult([], [f"OpenCLI Reddit search failed: {stderr.strip() or stdout.strip()}"], "agent_reach")
    payload = parse_structured_output(stdout)
    items = [normalize_reddit_item(item, "agent_reach_opencli") for item in coerce_items(payload)]
    return ProviderResult(items[:limit], [], "agent_reach")


def search_reddit_rdt(query: str, limit: int, timeout_seconds: int) -> ProviderResult:
    command_variants = [
        ["rdt", "search", query, "-n", str(limit), "--json"],
        ["rdt", "search", query, "--limit", str(limit), "--json"],
        ["rdt", "search", query, "-n", str(limit)],
    ]
    stderr = ""
    stdout = ""
    for args in command_variants:
        code, stdout, stderr = run_command(args, timeout_seconds)
        if code == 0 and stdout.strip():
            payload = parse_structured_output(stdout)
            items = [normalize_reddit_item(item, "agent_reach_rdt") for item in coerce_items(payload)]
            return ProviderResult(items[:limit], [], "agent_reach")
    return ProviderResult([], [f"rdt-cli Reddit search failed: {stderr.strip() or stdout.strip()}"], "agent_reach")


def enrich_reddit_details(
    items: list[EvidenceItem],
    detail_limit: int,
    config: AgentReachConfig,
) -> tuple[list[EvidenceItem], list[str]]:
    warnings: list[str] = []
    enriched = list(items)
    health = agent_reach_health()
    preferred_backend = config.preferred_backend
    if preferred_backend == "auto":
        preferred_backend = health.get("recommended_backend") or "opencli"
    backend_order = (
        ["rdt", "opencli"] if preferred_backend == "rdt" else ["opencli", "rdt"]
    )
    for index, item in enumerate(enriched[:detail_limit]):
        detail_result = None
        for backend in backend_order:
            if backend == "opencli" and health["opencli_installed"] and (item.external_id or item.url):
                detail_result = read_reddit_opencli(
                    item.external_id or item.url,
                    config.comments_per_post,
                    config.timeout_seconds,
                    url=item.url,
                )
            elif backend == "rdt" and health["rdt_installed"] and item.external_id:
                detail_result = read_reddit_rdt(item.external_id, config.timeout_seconds)
            else:
                continue
            warnings.extend(detail_result.warnings)
            if detail_result.items:
                break
        if detail_result and detail_result.items:
            detailed = detail_result.items[0]
            if not item.text and detailed.text:
                item.text = detailed.text
            if detailed.comments:
                item.comments = detailed.comments[: config.comments_per_post]
            if detailed.metrics:
                item.metrics.update({key: value for key, value in detailed.metrics.items() if value is not None})
            enriched[index] = item
    return enriched, warnings


def read_reddit_rdt(post_id: str, timeout_seconds: int) -> ProviderResult:
    for args in (["rdt", "read", post_id, "--json"], ["rdt", "read", post_id]):
        code, stdout, stderr = run_command(args, timeout_seconds)
        if code == 0 and stdout.strip():
            payload = parse_structured_output(stdout)
            items = [normalize_reddit_item(item, "agent_reach_rdt") for item in coerce_items(payload)]
            return ProviderResult(items[:1], [], "agent_reach")
    return ProviderResult([], [f"rdt-cli read failed for {post_id}: {stderr.strip() or stdout.strip()}"], "agent_reach")


def read_reddit_opencli(
    identifier: str,
    comment_limit: int,
    timeout_seconds: int,
    url: str = "",
) -> ProviderResult:
    candidates = [identifier]
    if url and url not in candidates:
        candidates.append(url)
    stderr = ""
    stdout = ""
    for candidate in candidates:
        for output_format in ("json", "yaml"):
            args = ["opencli", "reddit", "read", candidate, "--limit", str(comment_limit), "-f", output_format]
            code, stdout, stderr = run_command(args, timeout_seconds)
            if code == 0 and stdout.strip():
                payload = parse_structured_output(stdout)
                items = normalize_opencli_read_items(
                    payload,
                    url or candidate,
                    "agent_reach_opencli",
                    external_id_hint=identifier if not identifier.startswith("http") else "",
                )
                return ProviderResult(items[:1], [], "agent_reach")
    target = url or identifier
    return ProviderResult([], [f"OpenCLI read failed for {target}: {stderr.strip() or stdout.strip()}"], "agent_reach")

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from .opencli_client import OpenCLIClient, OpenCLIError

MARKETSCOPE_HOST = "marketscope.tiktok.com"
MARKETSCOPE_API_PREFIX = "/wormhole/"
ALLOWED_PAGE_PREFIXES = ("/brand/",)
BLOCKED_API_PATHS = {"/wormhole/people/api/v1/user/logout"}
SCHEMA_VERSION = 1
DEFAULT_MAX_BODY_CHARS = 1_048_576
DEFAULT_MAX_ENTRIES = 100
READ_ONLY_PROBE_PATHS = (
    "/wormhole/account/api/v1/account/get-info",
    "/wormhole/account/api/v1/account/get-brand-info",
    "/wormhole/homepage/api/v1/todoList",
)

ALLOWED_QUERY_KEYS = {
    "accountid",
    "cursor",
    "enddate",
    "limit",
    "metrictype",
    "offset",
    "page",
    "pageno",
    "pagesize",
    "region",
    "startdate",
}
SENSITIVE_BODY_KEYS = {
    "access_token",
    "auth_token",
    "authorization",
    "cookie",
    "csrf_token",
    "password",
    "passwd",
    "refresh_token",
    "session_id",
    "session_key",
    "session_token",
    "set_cookie",
    "xsrf_token",
}
LOGIN_MARKERS = (
    "tiktok ads: log in",
    "don't have an account yet?",
    "forgot password",
    "enter your password",
    "请输入你的手机号",
)


class MarketScopeCaptureError(RuntimeError):
    """MarketScope collection failed."""


class MarketScopeAuthenticationRequired(MarketScopeCaptureError):
    """The connected Chrome profile is not authenticated for MarketScope."""


@dataclass(frozen=True)
class MarketScopeTarget:
    url: str
    account_id: str


@dataclass(frozen=True)
class CaptureResult:
    output_path: Path
    source_mode: str
    page_count: int
    api_entry_count: int
    warnings: list[str]


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


def validate_marketscope_url(value: str) -> MarketScopeTarget:
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme != "https":
        raise ValueError("MarketScope URLs must use https://.")
    if parsed.hostname != MARKETSCOPE_HOST:
        raise ValueError(f"Only https://{MARKETSCOPE_HOST}/ URLs are allowed.")
    if parsed.username or parsed.password:
        raise ValueError("MarketScope URLs must not contain credentials.")
    if not parsed.path.startswith("/"):
        raise ValueError("MarketScope URL path is invalid.")
    if "%" in parsed.path or "\\" in parsed.path:
        raise ValueError("Encoded or backslash path segments are not allowed.")
    if not any(parsed.path.startswith(prefix) for prefix in ALLOWED_PAGE_PREFIXES):
        raise ValueError("Only MarketScope /brand/ page URLs may be opened by this crawler.")

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    unknown_query_keys = sorted(
        {key for key, _item in query_pairs if key.lower() not in ALLOWED_QUERY_KEYS}
    )
    if unknown_query_keys:
        raise ValueError(
            "Unsupported MarketScope page query parameters: " + ", ".join(unknown_query_keys)
        )
    query = dict(query_pairs)
    account_id = str(query.get("accountId") or query.get("accountid") or "").strip()
    if account_id and not re.fullmatch(r"\d{5,30}", account_id):
        raise ValueError("accountId must contain 5 to 30 digits.")

    normalized = urlunsplit(
        ("https", MARKETSCOPE_HOST, parsed.path or "/", urlencode(query_pairs), "")
    )
    return MarketScopeTarget(url=normalized, account_id=account_id)


def is_marketscope_api_url(value: str, base_url: str) -> bool:
    absolute = urljoin(base_url, value)
    parsed = urlsplit(absolute)
    return (
        parsed.scheme == "https"
        and parsed.hostname == MARKETSCOPE_HOST
        and parsed.path.startswith(MARKETSCOPE_API_PREFIX)
        and parsed.path not in BLOCKED_API_PATHS
    )


def safe_endpoint(value: str, base_url: str) -> dict[str, Any]:
    absolute = urljoin(base_url, value)
    parsed = urlsplit(absolute)
    kept: dict[str, str | list[str]] = {}
    dropped: list[str] = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() not in ALLOWED_QUERY_KEYS:
            dropped.append(key)
            continue
        existing = kept.get(key)
        if existing is None:
            kept[key] = item
        elif isinstance(existing, list):
            existing.append(item)
        else:
            kept[key] = [existing, item]
    endpoint: dict[str, Any] = {"path": parsed.path}
    if kept:
        endpoint["query"] = kept
    if dropped:
        endpoint["dropped_query_keys"] = sorted(set(dropped))
    return endpoint


def _normalized_sensitive_key(value: str) -> str:
    snake_case = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value.strip())
    return re.sub(r"[^a-z0-9]+", "_", snake_case.lower()).strip("_")


def _sanitized_url(value: str, base_url: str) -> str:
    absolute = urljoin(base_url, value)
    parsed = urlsplit(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return value
    if parsed.hostname != MARKETSCOPE_HOST:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    kept = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() in ALLOWED_QUERY_KEYS
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(kept), ""))


def sanitize_page_markdown(value: str, base_url: str) -> str:
    """Remove signed CDN queries and unknown MarketScope query parameters."""

    return re.sub(
        r"https?://[^\s)\]>]+",
        lambda match: _sanitized_url(match.group(0), base_url),
        value,
    )


def redact_auth_secrets(
    value: Any,
    base_url: str = f"https://{MARKETSCOPE_HOST}/",
) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if _normalized_sensitive_key(text_key) in SENSITIVE_BODY_KEYS:
                redacted[text_key] = "[REDACTED]"
            else:
                redacted[text_key] = redact_auth_secrets(item, base_url)
        return redacted
    if isinstance(value, list):
        return [redact_auth_secrets(item, base_url) for item in value]
    if isinstance(value, str) and re.fullmatch(r"https?://[^\s]+", value.strip()):
        return _sanitized_url(value.strip(), base_url)
    return value


def parse_json_body(value: Any) -> Any | None:
    if isinstance(value, dict | list):
        return value
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict | list) else None


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def select_market_scope_previews(
    network_payload: Any,
    *,
    base_url: str,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if not isinstance(network_payload, dict):
        raise MarketScopeCaptureError("OpenCLI network output was not a JSON object.")
    if isinstance(network_payload.get("error"), dict):
        error = network_payload["error"]
        raise MarketScopeCaptureError(str(error.get("message") or error.get("code") or error))

    raw_entries = network_payload.get("entries")
    if not isinstance(raw_entries, list):
        raise MarketScopeCaptureError("OpenCLI network output did not contain an entries list.")

    selected: list[dict[str, Any]] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "")
        if not is_marketscope_api_url(url, base_url):
            continue
        status = int(raw.get("status") or 0)
        if status in {401, 403}:
            raise MarketScopeAuthenticationRequired(
                f"MarketScope returned HTTP {status}; sign in or request account permission, then retry."
            )
        if status == 429:
            raise MarketScopeCaptureError("MarketScope returned HTTP 429. Collection stopped without retrying.")
        key = str(raw.get("key") or "").strip()
        if not key:
            warnings.append(f"Skipped an API response without a network key: {safe_endpoint(url, base_url)}")
            continue
        selected.append(raw)
        if len(selected) >= max(1, min(max_entries, 200)):
            warnings.append(f"Stopped after the configured maximum of {len(selected)} API responses.")
            break
    return selected, warnings


def normalize_detail_entry(
    detail: Any,
    *,
    base_url: str,
    max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
) -> dict[str, Any] | None:
    if not isinstance(detail, dict) or isinstance(detail.get("error"), dict):
        return None
    url = str(detail.get("url") or "")
    if not is_marketscope_api_url(url, base_url):
        return None
    status = int(detail.get("status") or 0)
    if status in {401, 403}:
        raise MarketScopeAuthenticationRequired(
            f"MarketScope returned HTTP {status}; sign in or request account permission, then retry."
        )
    if status == 429:
        raise MarketScopeCaptureError("MarketScope returned HTTP 429. Collection stopped without retrying.")

    body = parse_json_body(detail.get("body"))
    if body is None:
        return None
    body = redact_auth_secrets(body, base_url)
    body_size = len(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    if body_size > max(10_000, min(int(max_body_chars), 2_000_000)):
        return None
    endpoint = safe_endpoint(url, base_url)
    result: dict[str, Any] = {
        "key": str(detail.get("key") or ""),
        "method": str(detail.get("method") or "GET").upper(),
        "status": status,
        "endpoint": endpoint,
        "content_type": str(detail.get("ct") or ""),
        "size": int(detail.get("size") or 0),
        "body_sha256": canonical_sha256(body),
        "body": body,
    }
    if detail.get("timestamp"):
        result["captured_at"] = str(detail["timestamp"])
    if detail.get("body_truncated"):
        result["body_truncated"] = True
        result["body_full_size"] = int(detail.get("body_full_size") or result["size"])
    return result


def deduplicate_entries(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int, str]] = set()
    unique: list[dict[str, Any]] = []
    for entry in entries:
        endpoint = entry.get("endpoint") if isinstance(entry.get("endpoint"), dict) else {}
        endpoint_marker = json.dumps(
            {
                "path": endpoint.get("path"),
                "query": endpoint.get("query", {}),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        marker = (
            str(entry.get("method") or ""),
            endpoint_marker,
            int(entry.get("status") or 0),
            str(entry.get("body_sha256") or ""),
        )
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(entry)
    return unique


def build_read_only_probe_script(account_id: str, max_body_chars: int) -> str:
    """Build a same-origin script for the small, audited GET-only fallback."""

    config = json.dumps(
        {
            "accountId": account_id,
            "paths": READ_ONLY_PROBE_PATHS,
            "maxBodyChars": max_body_chars,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"""
    (async () => {{
      const config = {config};
      const accountId = config.accountId || new URL(location.href).searchParams.get('accountId') || '';
      const entries = [];
      for (const path of config.paths) {{
        const url = new URL(path, location.origin);
        if (accountId) url.searchParams.set('accountId', accountId);
        try {{
          const response = await fetch(url.toString(), {{
            method: 'GET',
            credentials: 'include',
            headers: {{ accept: 'application/json' }},
          }});
          const text = await response.text();
          let body = null;
          let parseError = '';
          if (text.length <= config.maxBodyChars) {{
            try {{ body = JSON.parse(text); }} catch (error) {{ parseError = String(error); }}
          }}
          entries.push({{
            key: `GET ${{url.host}}${{url.pathname}}`,
            url: url.toString(),
            method: 'GET',
            status: response.status,
            ct: response.headers.get('content-type') || '',
            size: text.length,
            timestamp: new Date().toISOString(),
            body,
            body_truncated: text.length > config.maxBodyChars,
            body_full_size: text.length,
            parse_error: parseError,
          }});
        }} catch (error) {{
          entries.push({{
            key: `GET ${{url.host}}${{url.pathname}}`,
            url: url.toString(),
            method: 'GET',
            status: 0,
            ct: '',
            size: 0,
            timestamp: new Date().toISOString(),
            body: null,
            error: String(error),
          }});
        }}
      }}
      return {{ entries }};
    }})()
    """.strip()


def normalize_probe_entries(
    payload: Any,
    *,
    base_url: str,
    max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise MarketScopeCaptureError("The read-only MarketScope probe returned invalid output.")
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    for raw in payload["entries"]:
        if not isinstance(raw, dict):
            continue
        if int(raw.get("status") or 0) == 0:
            warnings.append(
                f"Read-only probe failed for {safe_endpoint(str(raw.get('url') or ''), base_url)}: "
                f"{str(raw.get('error') or 'network error')}"
            )
            continue
        normalized = normalize_detail_entry(
            raw,
            base_url=base_url,
            max_body_chars=max_body_chars,
        )
        if normalized is None:
            warnings.append(
                f"Read-only probe returned a non-JSON or truncated body: "
                f"{safe_endpoint(str(raw.get('url') or ''), base_url)}"
            )
            continue
        normalized["capture_method"] = "allowlisted_get_probe"
        entries.append(normalized)
    return entries, warnings


def default_output_path() -> Path:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return Path.cwd() / ".cache" / "marketscope" / f"capture_{timestamp}.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _login_page(extract_payload: Any, final_url: str) -> bool:
    if isinstance(extract_payload, dict):
        text = "\n".join(
            str(extract_payload.get(key) or "") for key in ("title", "content")
        ).lower()
        if any(marker in text for marker in LOGIN_MARKERS):
            return True
    parsed = urlsplit(final_url)
    return parsed.hostname != MARKETSCOPE_HOST or "/login" in parsed.path.lower()


def _tab_options(page_id: str) -> tuple[str, ...]:
    return ("--tab", page_id) if page_id else ()


def _safe_cleanup(client: OpenCLIClient, session: str, page_id: str) -> str | None:
    try:
        if page_id:
            result = client.browser_text(
                session,
                "tab",
                "close",
                page_id,
                allow_nonzero=True,
            )
            if result.returncode == 0:
                return None
        result = client.browser_text(session, "unbind", allow_nonzero=True)
        if result.returncode != 0:
            return "Could not release the OpenCLI browser session cleanly."
    except OpenCLIError:
        return "Could not release the OpenCLI browser session cleanly."
    return None


def capture_marketscope(
    client: OpenCLIClient,
    urls: Sequence[str],
    *,
    output_path: str | Path | None = None,
    session_prefix: str = "marketscope",
    settle_seconds: int = 5,
    chunk_size: int = 40_000,
    max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    probe_readonly: bool = True,
    keep_tab: bool = False,
) -> CaptureResult:
    if not urls:
        raise ValueError("At least one MarketScope URL is required.")
    targets = [validate_marketscope_url(url) for url in urls]
    settle = max(1, min(int(settle_seconds), 30))
    chunk = max(1_000, min(int(chunk_size), 200_000))
    body_limit = max(10_000, min(int(max_body_chars), 2_000_000))
    entry_limit = max(1, min(int(max_entries), 200))

    health = client.bridge_health()
    if not health.get("bridge_connected"):
        raise MarketScopeCaptureError(
            "OpenCLI Browser Bridge is not connected. Enable its Chrome extension and retry."
        )

    started_at = utc_now()
    run_suffix = secrets.token_hex(4)
    page_records: list[dict[str, Any]] = []
    api_entries: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, target in enumerate(targets, start=1):
        session = OpenCLIClient.validate_session(
            f"{session_prefix}_{started_at.strftime('%Y%m%d%H%M%S')}_{run_suffix}_{index}"
        )
        page_id = ""
        cleanup_needed = True
        try:
            opened = client.browser_json(
                session,
                "open",
                target.url,
                "--window",
                "background",
                timeout_seconds=max(client.timeout_seconds, 45),
            )
            if not isinstance(opened, dict):
                raise MarketScopeCaptureError("OpenCLI browser open returned an invalid response.")
            page_id = str(opened.get("page") or "").strip()
            final_url = str(opened.get("url") or target.url)
            tab_options = _tab_options(page_id)

            wait_result = client.browser_json(
                session,
                "wait",
                "xhr",
                r"/wormhole/",
                "--timeout",
                str(settle * 1000),
                *tab_options,
                timeout_seconds=max(client.timeout_seconds, settle + 10),
                allow_nonzero=True,
            )
            if isinstance(wait_result, dict) and isinstance(wait_result.get("error"), dict):
                warnings.append(str(wait_result["error"].get("message") or wait_result["error"]))

            extract_payload = client.browser_json(
                session,
                "extract",
                "--chunk-size",
                str(chunk),
                *tab_options,
            )
            if _login_page(extract_payload, final_url):
                raise MarketScopeAuthenticationRequired(
                    "The connected Chrome profile reached the TikTok Ads login page. "
                    "Sign in to MarketScope in that OpenCLI-connected profile, then retry."
                )

            window_seconds = max(30, settle + 15)
            network_payload = client.browser_json(
                session,
                "network",
                "--since",
                f"{window_seconds}s",
                *tab_options,
            )
            previews, preview_warnings = select_market_scope_previews(
                network_payload,
                base_url=final_url,
                max_entries=entry_limit,
            )
            warnings.extend(preview_warnings)

            page_entries: list[dict[str, Any]] = []
            for preview in previews:
                key = str(preview.get("key") or "")
                detail = client.browser_json(
                    session,
                    "network",
                    "--detail",
                    key,
                    "--max-body",
                    str(body_limit),
                    *tab_options,
                )
                normalized = normalize_detail_entry(
                    detail,
                    base_url=final_url,
                    max_body_chars=body_limit,
                )
                if normalized is None:
                    endpoint = safe_endpoint(str(preview.get("url") or ""), final_url)
                    warnings.append(f"Skipped a non-JSON or incomplete API body: {endpoint}")
                    continue
                page_entries.append(normalized)

            if probe_readonly:
                probe_payload = client.browser_json(
                    session,
                    "eval",
                    build_read_only_probe_script(target.account_id, body_limit),
                    *tab_options,
                )
                probe_entries, probe_warnings = normalize_probe_entries(
                    probe_payload,
                    base_url=final_url,
                    max_body_chars=body_limit,
                )
                page_entries.extend(probe_entries)
                warnings.extend(probe_warnings)
            api_entries.extend(page_entries)

            page_record: dict[str, Any] = {
                "source_url": target.url,
                "final_url": _sanitized_url(final_url, target.url),
                "account_id": target.account_id or None,
                "session": session,
                "api_entry_count": len(page_entries),
            }
            if isinstance(extract_payload, dict):
                page_record["page"] = {
                    key: extract_payload.get(key)
                    for key in (
                        "title",
                        "total_chars",
                        "start",
                        "end",
                        "next_start_char",
                    )
                    if key in extract_payload
                }
                if "content" in extract_payload:
                    page_record["page"]["content"] = sanitize_page_markdown(
                        str(extract_payload.get("content") or ""),
                        final_url,
                    )
            page_records.append(page_record)
        finally:
            try:
                client.delete_network_cache(session)
            except OpenCLIError:
                warnings.append("Could not delete the temporary OpenCLI network cache for this run.")
            if keep_tab:
                cleanup_needed = False
            if cleanup_needed:
                cleanup_warning = _safe_cleanup(client, session, page_id)
                if cleanup_warning:
                    warnings.append(cleanup_warning)

    unique_entries = deduplicate_entries(api_entries)
    if not unique_entries:
        warnings.append(
            "No JSON responses under /wormhole/ were captured. The page may be cached, unavailable, or missing account permission."
        )

    finished_at = utc_now()
    destination = Path(output_path).expanduser() if output_path else default_output_path()
    bundle: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_mode": "marketscope_opencli",
        "started_at": iso_utc(started_at),
        "finished_at": iso_utc(finished_at),
        "coverage": {
            "scope": "Only UI text and API responses loaded by the supplied pages during this run.",
            "page_count": len(page_records),
            "captured_api_entries": len(unique_entries),
            "deduplicated_api_entries": len(api_entries) - len(unique_entries),
            "max_entries_per_page": entry_limit,
            "max_body_chars": body_limit,
            "read_only_probe_paths": list(READ_ONLY_PROBE_PATHS) if probe_readonly else [],
        },
        "browser_bridge": {
            "provider": "opencli",
            "selected_profile": health.get("selected_profile"),
        },
        "pages": page_records,
        "api_responses": unique_entries,
        "warnings": warnings,
    }
    _write_json_atomic(destination, bundle)
    return CaptureResult(
        output_path=destination.resolve(),
        source_mode="marketscope_opencli",
        page_count=len(page_records),
        api_entry_count=len(unique_entries),
        warnings=warnings,
    )

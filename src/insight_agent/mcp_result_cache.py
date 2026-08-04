from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(os.getenv("INSIGHT_AGENT_HOME", Path(__file__).resolve().parents[2])).resolve()
DEFAULT_MCP_RESULT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
MCP_RESULT_CACHE_SCHEMA_VERSION = "mcp_result_cache.v1"
CACHEABLE_MCP_STATUSES = {"ok", "partial_ok"}

_LOCKS_GUARD = threading.Lock()
_KEY_LOCKS: dict[str, threading.Lock] = {}


@dataclass(frozen=True)
class McpCacheEntry:
    result: dict[str, Any]
    metadata: dict[str, Any]


def mcp_result_cache_ttl_seconds() -> int:
    raw = os.getenv("MCP_RESULT_CACHE_TTL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_MCP_RESULT_CACHE_TTL_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_MCP_RESULT_CACHE_TTL_SECONDS


def mcp_result_cache_root() -> Path:
    configured = os.getenv("MCP_RESULT_CACHE_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else PROJECT_ROOT / ".cache" / "mcp-results"


def canonical_mcp_params(params: dict[str, Any]) -> str:
    return json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def mcp_result_cache_identity(provider: str, tool_name: str, params: dict[str, Any]) -> str:
    payload = canonical_mcp_params(
        {
            "schema_version": MCP_RESULT_CACHE_SCHEMA_VERSION,
            "provider": provider,
            "tool": tool_name,
            "params": params,
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("._")
    return cleaned or "unknown"


def mcp_result_cache_path(provider: str, tool_name: str, params: dict[str, Any]) -> Path:
    identity = mcp_result_cache_identity(provider, tool_name, params)
    return (
        mcp_result_cache_root()
        / _safe_segment(provider)
        / _safe_segment(tool_name)
        / f"{identity}.json"
    )


def _iso_timestamp(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).isoformat()


def _remove_invalid_cache_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def read_mcp_result_cache(
    provider: str,
    tool_name: str,
    params: dict[str, Any],
    *,
    ttl_seconds: int | None = None,
) -> McpCacheEntry | None:
    ttl = mcp_result_cache_ttl_seconds() if ttl_seconds is None else max(0, ttl_seconds)
    if ttl <= 0:
        return None
    path = mcp_result_cache_path(provider, tool_name, params)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _remove_invalid_cache_file(path)
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != MCP_RESULT_CACHE_SCHEMA_VERSION:
        _remove_invalid_cache_file(path)
        return None
    result = payload.get("result")
    created_at = payload.get("created_at")
    if not isinstance(result, dict) or not isinstance(created_at, int | float):
        _remove_invalid_cache_file(path)
        return None
    # Empty market responses are observations, not durable facts. Keeping them
    # for the normal seven-day TTL can hide newly available data after the
    # upstream provider refreshes a ranking or the user recharges an account.
    if str(result.get("status") or "") == "empty":
        _remove_invalid_cache_file(path)
        return None
    age_seconds = max(0.0, time.time() - float(created_at))
    if age_seconds > ttl:
        _remove_invalid_cache_file(path)
        return None
    expires_at = float(created_at) + ttl
    return McpCacheEntry(
        result=result,
        metadata={
            "hit": True,
            "provider": provider,
            "tool": tool_name,
            "key": mcp_result_cache_identity(provider, tool_name, params)[:16],
            "age_seconds": round(age_seconds, 3),
            "ttl_seconds": ttl,
            "created_at": _iso_timestamp(float(created_at)),
            "expires_at": _iso_timestamp(expires_at),
            "path": str(path),
        },
    )


def write_mcp_result_cache(
    provider: str,
    tool_name: str,
    params: dict[str, Any],
    result: dict[str, Any],
    *,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    ttl = mcp_result_cache_ttl_seconds() if ttl_seconds is None else max(0, ttl_seconds)
    identity = mcp_result_cache_identity(provider, tool_name, params)
    path = mcp_result_cache_path(provider, tool_name, params)
    metadata = {
        "hit": False,
        "stored": False,
        "provider": provider,
        "tool": tool_name,
        "key": identity[:16],
        "ttl_seconds": ttl,
        "path": str(path),
    }
    if ttl <= 0:
        metadata["disabled"] = True
        return metadata
    created_at = time.time()
    payload = {
        "schema_version": MCP_RESULT_CACHE_SCHEMA_VERSION,
        "provider": provider,
        "tool": tool_name,
        "cache_key": identity,
        "created_at": created_at,
        "expires_at": created_at + ttl,
        "params": params,
        "result": result,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temp_path.replace(path)
    except OSError:
        return metadata
    metadata.update(
        {
            "stored": True,
            "created_at": _iso_timestamp(created_at),
            "expires_at": _iso_timestamp(created_at + ttl),
        }
    )
    return metadata


def cacheable_mcp_result(result: dict[str, Any]) -> bool:
    return str(result.get("status") or "") in CACHEABLE_MCP_STATUSES


def with_mcp_cache_metadata(
    result: dict[str, Any],
    metadata: dict[str, Any],
    *,
    duration_ms: int,
) -> dict[str, Any]:
    enriched = dict(result)
    enriched["duration_ms"] = duration_ms
    enriched["cache"] = metadata
    if metadata.get("hit"):
        original_summary = str(enriched.get("summary") or "MCP tool completed.")
        enriched["summary"] = f"MCP cache hit. {original_summary}"
    return enriched


def execute_with_mcp_result_cache(
    provider: str,
    tool_name: str,
    params: dict[str, Any],
    execute: Callable[[], dict[str, Any]],
    *,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    identity = mcp_result_cache_identity(provider, tool_name, params)
    path = mcp_result_cache_path(provider, tool_name, params)
    with mcp_result_cache_lock(provider, tool_name, params):
        if not bypass_cache:
            cached = read_mcp_result_cache(provider, tool_name, params)
            if cached is not None:
                return with_mcp_cache_metadata(
                    cached.result,
                    cached.metadata,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
        result = execute()
        if cacheable_mcp_result(result):
            metadata = write_mcp_result_cache(provider, tool_name, params, result)
        else:
            metadata = {
                "hit": False,
                "stored": False,
                "provider": provider,
                "tool": tool_name,
                "key": identity[:16],
                "ttl_seconds": mcp_result_cache_ttl_seconds(),
                "path": str(path),
                "reason": "result_status_not_cacheable",
            }
        if bypass_cache:
            metadata["bypassed"] = True
            metadata["refreshed"] = bool(metadata.get("stored"))
        return with_mcp_cache_metadata(
            result,
            metadata,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


@contextmanager
def mcp_result_cache_lock(provider: str, tool_name: str, params: dict[str, Any]) -> Iterator[None]:
    identity = mcp_result_cache_identity(provider, tool_name, params)
    with _LOCKS_GUARD:
        lock = _KEY_LOCKS.setdefault(identity, threading.Lock())
    lock.acquire()
    try:
        yield
    finally:
        lock.release()

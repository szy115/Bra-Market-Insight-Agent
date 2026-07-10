from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from insight_agent.ingestion.marketscope.crawler import (
    MarketScopeAuthenticationRequired,
    build_read_only_probe_script,
    capture_marketscope,
    deduplicate_entries,
    is_marketscope_api_url,
    normalize_detail_entry,
    safe_endpoint,
    sanitize_page_markdown,
    select_market_scope_previews,
    validate_marketscope_url,
)
from insight_agent.ingestion.marketscope.opencli_client import (
    CommandOutput,
    OpenCLIError,
    OpenCLIUnavailableError,
    build_opencli_command_prefix,
    parse_json_document,
)

TARGET_URL = (
    "https://marketscope.tiktok.com/brand/homepage?accountId=7433364033920663559"
)


class FakeOpenCLIClient:
    timeout_seconds = 60

    def __init__(self, *, login_page: bool = False, unauthorized: bool = False) -> None:
        self.login_page = login_page
        self.unauthorized = unauthorized
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def bridge_health(self) -> dict[str, Any]:
        return {
            "bridge_connected": True,
            "selected_profile": "test-profile",
        }

    def browser_json(
        self,
        session: str,
        *args: str,
        timeout_seconds: int | None = None,
        allow_nonzero: bool = False,
    ) -> Any:
        del timeout_seconds, allow_nonzero
        self.calls.append((session, args))
        command = args[0]
        if command == "open":
            return {"url": TARGET_URL, "page": "tab-created-by-crawler"}
        if command == "wait":
            return {
                "matched": {
                    "url": "https://marketscope.tiktok.com/wormhole/homepage/api/v1/todoList",
                    "status": 200,
                }
            }
        if command == "extract":
            if self.login_page:
                return {
                    "url": TARGET_URL,
                    "title": "TikTok Ads: Log In",
                    "content": "Enter your password",
                    "total_chars": 20,
                }
            return {
                "url": TARGET_URL,
                "title": "TikTok Market Scope",
                "content": "Audience overview\nBrand perception",
                "total_chars": 35,
                "start": 0,
                "end": 35,
                "next_start_char": None,
            }
        if command == "network" and "--detail" not in args:
            status = 401 if self.unauthorized else 200
            return {
                "session": session,
                "entries": [
                    {
                        "key": "GET marketscope.tiktok.com/wormhole/account/get-brand-info",
                        "method": "GET",
                        "status": status,
                        "url": (
                            "https://marketscope.tiktok.com/wormhole/account/api/v1/"
                            "account/get-brand-info?accountId=7433364033920663559&signature=drop"
                        ),
                        "ct": "application/json",
                        "size": 180,
                    },
                    {
                        "key": "GET marketscope.tiktok.com/static/app.js",
                        "method": "GET",
                        "status": 200,
                        "url": "https://marketscope.tiktok.com/static/app.js",
                        "ct": "application/javascript",
                        "size": 100,
                    },
                ],
            }
        if command == "network" and "--detail" in args:
            return {
                "key": "GET marketscope.tiktok.com/wormhole/account/get-brand-info",
                "url": (
                    "https://marketscope.tiktok.com/wormhole/account/api/v1/"
                    "account/get-brand-info?accountId=7433364033920663559&signature=drop"
                ),
                "method": "GET",
                "status": 200,
                "ct": "application/json",
                "size": 180,
                "body": {
                    "code": 0,
                    "data": {
                        "name": "Example Brand",
                        "accessToken": "must-not-be-written",
                    },
                },
            }
        if command == "eval":
            return {
                "entries": [
                    {
                        "key": "GET marketscope.tiktok.com/wormhole/account/get-brand-info",
                        "url": (
                            "https://marketscope.tiktok.com/wormhole/account/api/v1/"
                            "account/get-brand-info?accountId=7433364033920663559"
                        ),
                        "method": "GET",
                        "status": 200,
                        "ct": "application/json",
                        "size": 180,
                        "body": {
                            "code": 0,
                            "data": {
                                "name": "Example Brand",
                                "accessToken": "must-not-be-written",
                            },
                        },
                    },
                    {
                        "key": "GET marketscope.tiktok.com/wormhole/account/get-info",
                        "url": (
                            "https://marketscope.tiktok.com/wormhole/account/api/v1/"
                            "account/get-info?accountId=7433364033920663559"
                        ),
                        "method": "GET",
                        "status": 200,
                        "ct": "application/json",
                        "size": 80,
                        "body": {"code": 0, "data": {"roles": ["analyst"]}},
                    },
                    {
                        "key": "GET marketscope.tiktok.com/wormhole/homepage/todoList",
                        "url": (
                            "https://marketscope.tiktok.com/wormhole/homepage/api/v1/"
                            "todoList?accountId=7433364033920663559"
                        ),
                        "method": "GET",
                        "status": 200,
                        "ct": "application/json",
                        "size": 60,
                        "body": {"code": 0, "data": {"todoList": []}},
                    },
                ]
            }
        raise AssertionError(f"Unexpected OpenCLI call: {args}")

    def browser_text(
        self,
        session: str,
        *args: str,
        timeout_seconds: int | None = None,
        allow_nonzero: bool = False,
    ) -> CommandOutput:
        del timeout_seconds, allow_nonzero
        self.calls.append((session, args))
        return CommandOutput(("opencli", *args), 0, "", "")

    def delete_network_cache(self, session: str) -> bool:
        self.calls.append((session, ("delete-network-cache",)))
        return True


def test_validate_marketscope_url_accepts_expected_target() -> None:
    target = validate_marketscope_url(TARGET_URL)

    assert target.account_id == "7433364033920663559"
    assert target.url == TARGET_URL


@pytest.mark.parametrize(
    "url",
    [
        "http://marketscope.tiktok.com/brand/homepage",
        "https://evil.example/brand/homepage?accountId=7433364033920663559",
        "https://marketscope.tiktok.com/brand/homepage?accountId=abc",
        "https://user:password@marketscope.tiktok.com/brand/homepage",
        "https://marketscope.tiktok.com/wormhole/people/api/v1/user/logout",
        "https://marketscope.tiktok.com/account/settings",
        "https://marketscope.tiktok.com/brand/%2e%2e/wormhole/people/api/v1/user/logout",
        "https://marketscope.tiktok.com/brand/homepage?accountId=12345&redirect=https://evil.example",
    ],
)
def test_validate_marketscope_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        validate_marketscope_url(url)


def test_api_filter_requires_exact_host_and_wormhole_prefix() -> None:
    assert is_marketscope_api_url(
        "/wormhole/homepage/api/v1/todoList",
        TARGET_URL,
    )
    assert not is_marketscope_api_url(
        "https://evil.example/wormhole/homepage/api/v1/todoList",
        TARGET_URL,
    )
    assert not is_marketscope_api_url(
        "https://marketscope.tiktok.com/wormhole-evil/homepage",
        TARGET_URL,
    )


def test_safe_endpoint_keeps_allowlisted_query_only() -> None:
    endpoint = safe_endpoint(
        "/wormhole/a?accountId=12345&page=2&signature=secret&token=secret",
        TARGET_URL,
    )

    assert endpoint["query"] == {"accountId": "12345", "page": "2"}
    assert endpoint["dropped_query_keys"] == ["signature", "token"]


def test_page_markdown_strips_signed_queries_but_keeps_account_id() -> None:
    content = (
        "![logo](https://cdn.example/logo.png?signature=secret&expires=1) "
        "[home](https://marketscope.tiktok.com/brand/homepage?accountId=12345&token=drop)"
    )

    sanitized = sanitize_page_markdown(content, TARGET_URL)

    assert "signature=" not in sanitized
    assert "expires=" not in sanitized
    assert "token=" not in sanitized
    assert "accountId=12345" in sanitized


def test_normalize_detail_redacts_auth_secrets_and_hashes_body() -> None:
    entry = normalize_detail_entry(
        {
            "key": "GET marketscope.tiktok.com/wormhole/test",
            "url": "https://marketscope.tiktok.com/wormhole/test?accountId=12345",
            "method": "GET",
            "status": 200,
            "ct": "application/json",
            "size": 120,
            "body": {
                "data": {
                    "name": "Example",
                    "access_token": "secret",
                    "sessionKey": "secret-two",
                    "logo": "https://cdn.example/logo.png?x-signature=secret&x-expires=999",
                }
            },
        },
        base_url=TARGET_URL,
    )

    assert entry is not None
    assert entry["body"]["data"]["name"] == "Example"
    assert entry["body"]["data"]["access_token"] == "[REDACTED]"
    assert entry["body"]["data"]["sessionKey"] == "[REDACTED]"
    assert entry["body"]["data"]["logo"] == "https://cdn.example/logo.png"
    assert len(entry["body_sha256"]) == 64


def test_normalize_detail_rejects_object_larger_than_body_limit() -> None:
    entry = normalize_detail_entry(
        {
            "key": "GET marketscope.tiktok.com/wormhole/test",
            "url": "https://marketscope.tiktok.com/wormhole/test?accountId=12345",
            "method": "GET",
            "status": 200,
            "ct": "application/json",
            "size": 20_000,
            "body": {"data": "x" * 15_000},
        },
        base_url=TARGET_URL,
        max_body_chars=10_000,
    )

    assert entry is None


def test_preview_selection_rejects_unauthorized_response() -> None:
    payload = {
        "entries": [
            {
                "key": "GET marketscope.tiktok.com/wormhole/test",
                "url": "https://marketscope.tiktok.com/wormhole/test",
                "status": 401,
            }
        ]
    }

    with pytest.raises(MarketScopeAuthenticationRequired):
        select_market_scope_previews(payload, base_url=TARGET_URL)


def test_deduplicate_entries_uses_body_hash() -> None:
    entry = {
        "method": "GET",
        "status": 200,
        "endpoint": {"path": "/wormhole/test"},
        "body_sha256": "same",
    }

    assert deduplicate_entries([entry, dict(entry)]) == [entry]


def test_deduplicate_entries_keeps_different_account_queries() -> None:
    first = {
        "method": "GET",
        "status": 200,
        "endpoint": {"path": "/wormhole/test", "query": {"accountId": "11111"}},
        "body_sha256": "same",
    }
    second = {
        **first,
        "endpoint": {"path": "/wormhole/test", "query": {"accountId": "22222"}},
    }

    assert deduplicate_entries([first, second]) == [first, second]


def test_capture_writes_local_bundle_and_closes_created_tab(tmp_path: Path) -> None:
    client = FakeOpenCLIClient()
    output = tmp_path / "capture.json"

    result = capture_marketscope(client, [TARGET_URL], output_path=output)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert result.api_entry_count == 3
    assert payload["source_mode"] == "marketscope_opencli"
    assert payload["coverage"]["captured_api_entries"] == 3
    assert payload["api_responses"][0]["body"]["data"]["name"] == "Example Brand"
    assert payload["api_responses"][0]["body"]["data"]["accessToken"] == "[REDACTED]"
    assert payload["api_responses"][0]["endpoint"]["query"] == {
        "accountId": "7433364033920663559"
    }
    assert any(call[1][:2] == ("tab", "close") for call in client.calls)
    assert any(call[1] == ("delete-network-cache",) for call in client.calls)
    assert "must-not-be-written" not in output.read_text(encoding="utf-8")


def test_read_only_probe_script_contains_only_audited_get_requests() -> None:
    script = build_read_only_probe_script("7433364033920663559", 100_000)

    assert "get-info" in script
    assert "get-brand-info" in script
    assert "todoList" in script
    assert "method: 'GET'" in script
    assert "method: 'POST'" not in script


def test_capture_fails_on_login_page_and_still_cleans_up(tmp_path: Path) -> None:
    client = FakeOpenCLIClient(login_page=True)

    with pytest.raises(MarketScopeAuthenticationRequired):
        capture_marketscope(client, [TARGET_URL], output_path=tmp_path / "capture.json")

    assert any(call[1][:2] == ("tab", "close") for call in client.calls)


def test_capture_fails_on_unauthorized_api(tmp_path: Path) -> None:
    client = FakeOpenCLIClient(unauthorized=True)

    with pytest.raises(MarketScopeAuthenticationRequired):
        capture_marketscope(client, [TARGET_URL], output_path=tmp_path / "capture.json")


def test_parse_json_document_ignores_banner_and_trailing_update_notice() -> None:
    payload = parse_json_document('notice\n{"ok": true}\nUpdate available')

    assert payload == {"ok": True}


def test_parse_json_document_rejects_non_json_output() -> None:
    with pytest.raises(OpenCLIError, match="OPENCLI_OUTPUT_INVALID"):
        parse_json_document("plain text only")


@pytest.mark.skipif(os.name != "nt", reason="Windows npm shim safety check")
def test_windows_batch_shim_is_rejected_without_safe_node_entry(tmp_path: Path) -> None:
    shim = tmp_path / "opencli.cmd"
    shim.write_text("@echo off\n", encoding="utf-8")

    with pytest.raises(OpenCLIUnavailableError, match="Refusing to execute"):
        build_opencli_command_prefix(shim)

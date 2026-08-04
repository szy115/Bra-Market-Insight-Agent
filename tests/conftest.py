from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_mcp_result_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MCP_RESULT_CACHE_DIR", str(tmp_path / "mcp-results"))
    monkeypatch.delenv("MCP_RESULT_CACHE_TTL_SECONDS", raising=False)

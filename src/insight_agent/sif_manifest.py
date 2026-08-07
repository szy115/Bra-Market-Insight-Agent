from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SIF_SPEC_PATH = Path(__file__).resolve().parent / "data" / "sif_tools.json"


def load_sif_manifest() -> tuple[dict[str, Any], ...]:
    payload = json.loads(SIF_SPEC_PATH.read_text(encoding="utf-8"))
    specs = tuple(dict(item) for item in payload if isinstance(item, dict))
    names = tuple(str(item.get("name") or "").strip() for item in specs)
    if not specs or any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("Sif capability manifest must contain unique named tools")
    return specs


SIF_MCP_TOOL_NAMES = tuple(str(item["name"]) for item in load_sif_manifest())

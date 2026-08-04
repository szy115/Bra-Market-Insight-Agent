from __future__ import annotations

import asyncio
import html
import json
import math
import os
import re
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any, TypeVar

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CHART_RENDER_BUNDLE_SCHEMA_VERSION = "chart_render_bundle.v1"
FLINT_MCP_PACKAGE_VERSION = "0.3.0"
MAX_ROWS_PER_CHART = 30
MAX_SVG_CHARS = 5_000_000
DEFAULT_CHART_TIMEOUT_SECONDS = 20
DEFAULT_TOTAL_TIMEOUT_SECONDS = 120

_T = TypeVar("_T")
_SAFE_CHART_ID_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")
_SVG_PATH_TAG_PATTERN = re.compile(r"<path\b[^>]*>", flags=re.IGNORECASE)
_SVG_FILL_ATTRIBUTE_PATTERN = re.compile(
    r"\bfill=(?P<quote>[\"'])[^\"']*(?P=quote)",
    flags=re.IGNORECASE,
)
_SVG_WIDTH_PATTERN = re.compile(r'\bwidth="(?P<value>\d+(?:\.\d+)?)"')
_SVG_VIEWBOX_PATTERN = re.compile(
    r'\bviewBox="(?P<x>-?\d+(?:\.\d+)?) (?P<y>-?\d+(?:\.\d+)?) '
    r'(?P<width>\d+(?:\.\d+)?) (?P<height>\d+(?:\.\d+)?)"'
)
_DANGEROUS_SVG_PATTERN = re.compile(
    r"<\s*(?:script|foreignObject|iframe|object|embed|image)\b"
    r"|(?:href|xlink:href)\s*=\s*[\"']\s*(?!#|data:)[^\"']+"
    r"|\bon[a-z]+\s*="
    r"|javascript:"
    r"|url\s*\(\s*[\"']?\s*(?!#|data:)[^)]+",
    flags=re.IGNORECASE,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def flint_mcp_cli_path() -> Path:
    override = str(os.getenv("FLINT_CHART_MCP_CLI") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (
        _repo_root()
        / "chart-runtime"
        / "node_modules"
        / "flint-chart-mcp"
        / "dist"
        / "cli.js"
    )


def _bounded_timeout(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.getenv(name) or default))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _label(value: Any, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _value_semantic_type(chart: dict[str, Any]) -> str:
    unit = str(chart.get("unit") or "").strip().lower()
    value_format = str(chart.get("value_format") or "").strip().lower()
    if "%" in unit or value_format in {"percent", "percentage", "ratio"}:
        return "Percentage"
    if "$" in unit or value_format in {"currency", "usd", "price"}:
        return "Price"
    return "Quantity"


def _label_semantic_type(rows: list[dict[str, Any]], field: str = "label") -> str:
    values = [_label(row.get(field)) for row in rows if _label(row.get(field))]
    if values and all(_DATE_PATTERN.fullmatch(value) for value in values):
        return "Date"
    return "Category"


def _chart_size(chart_type: str, row_count: int, orientation: str) -> tuple[int, int]:
    if chart_type in {"bar", "bar_table", "diverging_bar", "grouped_bar"} and orientation == "horizontal":
        return 720, max(260, min(640, 92 + row_count * 38))
    if chart_type == "bullet":
        return 760, max(260, min(520, 150 + row_count * 62))
    if chart_type == "donut":
        return 640, 400
    if chart_type in {"bubble", "scatter"}:
        return 760, 420
    return 760, 380


def _bar_arguments(chart: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    chart_type = str(chart.get("type") or "bar").strip().lower()
    diverging = chart_type == "diverging_bar"
    values: list[dict[str, Any]] = []
    for row in rows:
        label = _label(row.get("label"))
        value = _finite_number(row.get("value"))
        if label and value is not None:
            item: dict[str, Any] = {"label": label, "value": value}
            if diverging:
                item["direction"] = "上升" if value >= 0 else "下降"
            values.append(item)
    if not values:
        return None
    orientation = str(chart.get("orientation") or "vertical").lower()
    horizontal = orientation == "horizontal"
    width, height = _chart_size(chart_type, len(values), orientation)
    encodings: dict[str, Any] = (
        {"x": {"field": "value"}, "y": {"field": "label"}}
        if horizontal
        else {"x": {"field": "label"}, "y": {"field": "value"}}
    )
    if diverging:
        encodings["color"] = {"field": "direction"}
    else:
        # A bar chart without a color channel is interpreted as one series and
        # Flint deliberately assigns every bar the same theme color.  Category
        # coloring makes distinct market objects easier to scan while keeping
        # the palette deterministic across repeated renders.
        encodings["color"] = {"field": "label", "scheme": "tableau10"}
    return {
        "data": {"values": values},
        "semantic_types": {
            "label": _label_semantic_type(values),
            "value": _value_semantic_type(chart),
            **({"direction": "Direction"} if diverging else {}),
        },
        "field_display_names": {
            "label": str(
                (chart.get("y_label") if horizontal else chart.get("x_label")) or "分类"
            ),
            "value": str(
                (chart.get("x_label") if horizontal else chart.get("y_label"))
                or chart.get("unit")
                or "数值"
            ),
            **({"direction": "变化方向"} if diverging else {}),
        },
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": encodings,
            "baseSize": {"width": width, "height": height},
            "canvasSize": {"width": width, "height": height},
            "chartProperties": {"cornerRadius": 3},
        },
        "options": {"addTooltips": True},
        "backend": "vegalite",
        "format": "svg",
        "background": "#ffffff",
    }


def _bar_table_arguments(
    chart: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    label_field = str(chart.get("y_label") or "商品")
    value_field = str(chart.get("x_label") or chart.get("unit") or "数值")
    if label_field == value_field:
        value_field = f"{value_field}数值"
    values: list[dict[str, Any]] = []
    for row in rows:
        label = _label(row.get("label"))
        value = _finite_number(row.get("value"))
        if label and value is not None and value >= 0:
            # Flint estimates label width from character count. A few
            # zero-width spaces prevent wider ASCII identifiers (notably ASINs)
            # from being clipped without changing what the reader sees.
            values.append({label_field: f"{label}\u200b\u200b\u200b", value_field: value})
    if not values:
        return None
    width, height = _chart_size("bar_table", len(values), "horizontal")
    return {
        "data": {"values": values},
        "semantic_types": {
            label_field: _label_semantic_type(values, label_field),
            value_field: _value_semantic_type(chart),
        },
        "field_display_names": {
            label_field: label_field,
            value_field: value_field,
        },
        "chart_spec": {
            "chartType": "Bar Table",
            "encodings": {
                "x": {"field": value_field},
                "y": {"field": label_field},
                "color": {"field": label_field, "scheme": "tableau10"},
            },
            "baseSize": {"width": width, "height": height},
            "canvasSize": {"width": width, "height": height},
        },
        "options": {"addTooltips": True},
        "backend": "vegalite",
        "format": "svg",
        "background": "#ffffff",
    }


def _grouped_bar_arguments(
    chart: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    values: list[dict[str, Any]] = []
    categories: set[str] = set()
    groups: set[str] = set()
    for row in rows:
        label = _label(row.get("label"))
        group = _label(row.get("group"))
        value = _finite_number(row.get("value"))
        if label and group and value is not None and value >= 0:
            values.append({"label": label, "group": group, "value": value})
            categories.add(label)
            groups.add(group)
    if len(categories) < 2 or len(groups) < 2:
        return None
    orientation = str(chart.get("orientation") or "vertical").lower()
    horizontal = orientation == "horizontal"
    width, height = _chart_size("grouped_bar", len(categories), orientation)
    return {
        "data": {"values": values},
        "semantic_types": {
            "label": "Category",
            "group": "Category",
            "value": _value_semantic_type(chart),
        },
        "field_display_names": {
            "label": str(
                (chart.get("y_label") if horizontal else chart.get("x_label"))
                or "分类"
            ),
            "group": "对比口径",
            "value": str(
                (chart.get("x_label") if horizontal else chart.get("y_label"))
                or chart.get("unit")
                or "数值"
            ),
        },
        "chart_spec": {
            "chartType": "Grouped Bar Chart",
            "encodings": (
                {
                    "x": {"field": "value"},
                    "y": {"field": "label"},
                    "group": {"field": "group"},
                }
                if horizontal
                else {
                    "x": {"field": "label"},
                    "y": {"field": "value"},
                    "group": {"field": "group"},
                }
            ),
            "baseSize": {"width": width, "height": height},
            "canvasSize": {"width": width, "height": height},
            "chartProperties": {"dodge": "global"},
        },
        "options": {"addTooltips": True},
        "backend": "vegalite",
        "format": "svg",
        "background": "#ffffff",
    }


def _scatter_arguments(
    chart: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    values: list[dict[str, Any]] = []
    has_group = False
    for row in rows:
        label = _label(row.get("label"))
        x = _finite_number(row.get("x"))
        y = _finite_number(row.get("y"))
        group = _label(row.get("group"))
        if label and x is not None and y is not None:
            item: dict[str, Any] = {"label": label, "x": x, "y": y}
            if group:
                item["group"] = group
                has_group = True
            values.append(item)
    if len(values) < 2:
        return None
    field_semantics = (
        chart.get("field_semantics")
        if isinstance(chart.get("field_semantics"), dict)
        else {}
    )
    width, height = _chart_size("scatter", len(values), "vertical")
    encodings: dict[str, Any] = {
        "x": {"field": "x"},
        "y": {"field": "y"},
    }
    if has_group:
        encodings["color"] = {"field": "group", "scheme": "tableau10"}
    return {
        "data": {"values": values},
        "semantic_types": {
            "label": "Category",
            "x": str(field_semantics.get("x") or "Quantity"),
            "y": str(field_semantics.get("y") or "Quantity"),
            **({"group": "Category"} if has_group else {}),
        },
        "field_display_names": {
            "label": "商品",
            "x": str(chart.get("x_label") or "横轴"),
            "y": str(chart.get("y_label") or "纵轴"),
            **({"group": "品牌组"} if has_group else {}),
        },
        "chart_spec": {
            "chartType": "Scatter Plot",
            "encodings": encodings,
            "baseSize": {"width": width, "height": height},
            "canvasSize": {"width": width, "height": height},
            "chartProperties": {"opacity": 0.78},
        },
        "options": {"addTooltips": True},
        "backend": "vegalite",
        "format": "svg",
        "background": "#ffffff",
    }


def _bullet_arguments(
    chart: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    values: list[dict[str, Any]] = []
    for row in rows:
        label = _label(row.get("label"))
        value = _finite_number(row.get("value"))
        goal = _finite_number(row.get("goal"))
        if label and value is not None and goal is not None and value >= 0 and goal >= 0:
            comparison_direction = str(
                row.get("comparison_direction") or "higher_is_better"
            ).strip()
            meets_benchmark = (
                value <= goal
                if comparison_direction == "lower_is_better"
                else value >= goal
            )
            values.append(
                {
                    "metric": f"{label}\u200b\u200b\u200b",
                    "value": value,
                    "goal": goal,
                    "status": "优于同级" if meets_benchmark else "弱于同级",
                    "comparison_direction": comparison_direction,
                }
            )
    if not values:
        return None
    value_type = _value_semantic_type(chart)
    unit = str(chart.get("unit") or "").strip()
    unit_suffix = f"（{unit}）" if unit else ""
    width, height = _chart_size("bullet", len(values), "horizontal")
    return {
        "data": {"values": values},
        "semantic_types": {
            "metric": "Category",
            "value": value_type,
            "goal": value_type,
        },
        "field_display_names": {
            "metric": "指标",
            "value": f"当前值{unit_suffix}",
            "goal": f"同级基准{unit_suffix}",
        },
        "chart_spec": {
            "chartType": "Bullet Chart",
            "encodings": {
                "y": {"field": "metric"},
                "x": {"field": "value"},
                "goal": {"field": "goal"},
            },
            "baseSize": {"width": width, "height": height},
            "canvasSize": {"width": width, "height": height},
        },
        "options": {"addTooltips": True},
        "backend": "vegalite",
        "format": "svg",
        "background": "#ffffff",
    }


def _line_arguments(chart: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    values: list[dict[str, Any]] = []
    for row in rows:
        label = _label(row.get("label"))
        value = _finite_number(row.get("value"))
        if label and value is not None:
            values.append({"label": label, "value": value})
    if len(values) < 2:
        return None
    width, height = _chart_size("line", len(values), "vertical")
    return {
        "data": {"values": values},
        "semantic_types": {
            "label": _label_semantic_type(values),
            "value": _value_semantic_type(chart),
        },
        "field_display_names": {
            "label": str(chart.get("x_label") or "周期"),
            "value": str(chart.get("y_label") or chart.get("unit") or "数值"),
        },
        "chart_spec": {
            "chartType": "Line Chart",
            "encodings": {
                "x": {"field": "label"},
                "y": {"field": "value"},
            },
            "baseSize": {"width": width, "height": height},
            "canvasSize": {"width": width, "height": height},
            "chartProperties": {"interpolate": "monotone", "showPoints": True},
        },
        "options": {"addTooltips": True},
        "backend": "vegalite",
        "format": "svg",
        "background": "#ffffff",
    }


def _bubble_arguments(chart: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    values: list[dict[str, Any]] = []
    for row in rows:
        label = _label(row.get("label"))
        x = _finite_number(row.get("x"))
        y = _finite_number(row.get("y"))
        size = _finite_number(row.get("size"))
        if label and x is not None and y is not None and size is not None and size >= 0:
            values.append({"label": label, "x": x, "y": y, "size": size})
    if len(values) < 2:
        return None
    width, height = _chart_size("bubble", len(values), "vertical")
    return {
        "data": {"values": values},
        "semantic_types": {
            "label": "Category",
            "x": "Quantity",
            "y": _value_semantic_type(chart),
            "size": "Quantity",
        },
        "field_display_names": {
            "label": "关键词",
            "x": str(chart.get("x_label") or "横轴"),
            "y": str(chart.get("y_label") or "纵轴"),
            "size": "规模",
        },
        "chart_spec": {
            "chartType": "Scatter Plot",
            "encodings": {
                "x": {"field": "x"},
                "y": {"field": "y"},
                "size": {"field": "size"},
                "color": {"field": "label"},
            },
            "baseSize": {"width": width, "height": height},
            "canvasSize": {"width": width, "height": height},
        },
        "options": {"addTooltips": True},
        "backend": "vegalite",
        "format": "svg",
        "background": "#ffffff",
    }


def _donut_arguments(chart: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    values: list[dict[str, Any]] = []
    for row in rows:
        label = _label(row.get("label"))
        value = _finite_number(row.get("value"))
        if label and value is not None and value >= 0:
            values.append({"label": label, "value": value})
    if len(values) < 2 or sum(row["value"] for row in values) <= 0:
        return None
    width, height = _chart_size("donut", len(values), "vertical")
    return {
        "data": {"values": values},
        "semantic_types": {
            "label": "Category",
            "value": _value_semantic_type(chart),
        },
        "field_display_names": {
            "label": "分类",
            "value": str(chart.get("unit") or "占比"),
        },
        "chart_spec": {
            "chartType": "Pie Chart",
            "encodings": {
                "size": {"field": "value"},
                "color": {"field": "label"},
            },
            "baseSize": {"width": width, "height": height},
            "canvasSize": {"width": width, "height": height},
            "chartProperties": {"innerRadius": 58, "sortSlices": "descending"},
        },
        "options": {"addTooltips": True},
        "backend": "vegalite",
        "format": "svg",
        "background": "#ffffff",
    }


def _relationship_arguments(
    chart: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    labelled_rows = [
        row
        for row in rows
        if _label(row.get("label"))
    ]
    if len(labelled_rows) < 2:
        return None
    root_row = next(
        (
            row
            for row in labelled_rows
            if str(row.get("kind") or "").strip().lower() == "input_category"
        ),
        labelled_rows[0],
    )
    root_label = _label(root_row.get("label"))
    values: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for row in labelled_rows:
        item = _label(row.get("label"))
        if not item or item == root_label or item in seen_targets:
            continue
        weight = _finite_number(row.get("value"))
        kind = str(row.get("kind") or "").strip().lower()
        group = (
            "Amazon正式节点"
            if kind == "amazon_node"
            else "消费者搜索词"
            if kind == "search_term"
            else "其他边界对象"
        )
        values.append(
            {
                "group": group,
                "item": item,
                "weight": weight if weight is not None and weight > 0 else 1,
            }
        )
        seen_targets.add(item)
    if not values:
        return None
    return {
        "data": {"values": values},
        "semantic_types": {
            "group": "Category",
            "item": "Category",
            "weight": "Quantity",
        },
        "field_display_names": {
            "group": "边界层级",
            "item": "市场边界对象",
            "weight": "关联权重",
        },
        "chart_spec": {
            "chartType": "Tree",
            "encodings": {
                "color": {"field": "group"},
                "detail": {"field": "item"},
                "size": {"field": "weight"},
            },
            "baseSize": {"width": 860, "height": 420},
            "canvasSize": {"width": 860, "height": 420},
            "chartProperties": {"orient": "TB", "rootLabel": root_label},
        },
        "options": {"addTooltips": True},
        "backend": "echarts",
        "format": "svg",
        "background": "#ffffff",
    }


def _normalized_stacked_bar_arguments(
    chart: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    values: list[dict[str, Any]] = []
    axis_count = 0
    for row in rows:
        axis = _label(row.get("label"))
        segments = (
            row.get("segments")
            if isinstance(row.get("segments"), list)
            else []
        )
        if not axis or not segments:
            continue
        axis_values: list[dict[str, Any]] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            segment_label = _label(segment.get("label"))
            value = _finite_number(segment.get("value"))
            if not segment_label or value is None or value < 0:
                continue
            axis_values.append(
                {
                    "axis": axis,
                    "segment": segment_label,
                    "value": value,
                }
            )
        if not axis_values or sum(item["value"] for item in axis_values) <= 0:
            continue
        values.extend(axis_values)
        axis_count += 1
        if len(values) >= MAX_ROWS_PER_CHART:
            values = values[:MAX_ROWS_PER_CHART]
            break
    if axis_count < 1 or len(values) < 2:
        return None
    height = max(380, min(680, 180 + axis_count * 48))
    return {
        "data": {"values": values},
        "semantic_types": {
            "axis": "Category",
            "segment": "Category",
            "value": "Quantity",
        },
        "field_display_names": {
            "axis": str(chart.get("y_label") or "属性轴"),
            "segment": "属性值",
            "value": f"{str(chart.get('x_label') or '占比')} (%)",
        },
        "chart_spec": {
            "chartType": "Stacked Bar Chart",
            "encodings": {
                "x": {"field": "value"},
                "y": {"field": "axis"},
                "color": {"field": "segment"},
            },
            "baseSize": {"width": 860, "height": height},
            "canvasSize": {"width": 860, "height": height},
            "chartProperties": {"stackMode": "normalize"},
        },
        "options": {"addTooltips": True},
        "backend": "vegalite",
        "format": "svg",
        "background": "#ffffff",
    }


def _metric_group_arguments(
    chart: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    values: list[dict[str, Any]] = []
    row_units: list[str] = []
    for row in rows:
        label = _label(row.get("label"))
        value = _finite_number(row.get("value"))
        unit = _label(row.get("unit") or chart.get("unit"), limit=18)
        if label and value is not None:
            values.append(
                {
                    "metric": f"{label} ({unit})" if unit else label,
                    "value": value,
                }
            )
            row_units.append(unit.lower())
    if not values:
        return None
    if row_units and all("%" in unit for unit in row_units):
        value_type = "Percentage"
    elif row_units and all("$" in unit or "usd" in unit for unit in row_units):
        value_type = "Price"
    else:
        value_type = "Quantity"
    return {
        "data": {"values": values},
        "semantic_types": {"metric": "Category", "value": value_type},
        "field_display_names": {"metric": "指标", "value": "数值"},
        "chart_spec": {
            "chartType": "KPI Card",
            "encodings": {
                "metric": {"field": "metric"},
                "value": {"field": "value"},
            },
            "baseSize": {"width": 720, "height": 300},
            "canvasSize": {"width": 780, "height": 680},
        },
        "options": {"addTooltips": True},
        "backend": "vegalite",
        "format": "svg",
        "background": "#ffffff",
    }


def build_flint_render_arguments(chart: dict[str, Any]) -> dict[str, Any] | None:
    """Translate one bounded ReportData chart spec into Flint MCP arguments."""

    if str(chart.get("quality_status") or "ready") != "ready":
        return None
    rendering_contract = (
        chart.get("rendering_contract")
        if isinstance(chart.get("rendering_contract"), dict)
        else {}
    )
    if str(rendering_contract.get("renderer") or "") == "server":
        return None
    rows = [
        row
        for row in chart.get("data") or []
        if isinstance(row, dict)
    ][:MAX_ROWS_PER_CHART]
    chart_type = str(chart.get("type") or "").strip().lower()
    if chart_type in {"bar", "diverging_bar"}:
        return _bar_arguments(chart, rows)
    if chart_type == "bar_table":
        return _bar_table_arguments(chart, rows)
    if chart_type == "grouped_bar":
        return _grouped_bar_arguments(chart, rows)
    if chart_type == "scatter":
        return _scatter_arguments(chart, rows)
    if chart_type == "bullet":
        return _bullet_arguments(chart, rows)
    if chart_type == "line":
        return _line_arguments(chart, rows)
    if chart_type == "bubble":
        return _bubble_arguments(chart, rows)
    if chart_type in {"donut", "pie"}:
        return _donut_arguments(chart, rows)
    if chart_type == "relationship_map":
        return _relationship_arguments(chart, rows)
    if chart_type == "stacked_bar_100":
        return _normalized_stacked_bar_arguments(chart, rows)
    if chart_type == "metric_group":
        return _metric_group_arguments(chart, rows)
    return None


def build_flint_validate_arguments(
    render_arguments: dict[str, Any],
) -> dict[str, Any]:
    """Reuse one render request as a Flint validation request."""

    return {
        key: value
        for key, value in render_arguments.items()
        if key not in {"format", "scale", "background"}
    }


def parse_flint_validation(text: str) -> dict[str, Any]:
    """Normalize Flint validate_chart JSON for the chart-render audit bundle."""

    try:
        payload = json.loads(str(text or ""))
    except json.JSONDecodeError as exc:
        raise ValueError("Flint MCP validate_chart returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Flint MCP validate_chart returned a non-object result")
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    computed_size = (
        payload.get("computedSize")
        if isinstance(payload.get("computedSize"), dict)
        else {}
    )
    return {
        "status": "valid" if payload.get("valid") is True else "invalid",
        "valid": payload.get("valid") is True,
        "warnings": warnings[:20],
        "errors": errors[:20],
        "computed_size": {
            "width": computed_size.get("width"),
            "height": computed_size.get("height"),
        }
        if computed_size
        else {},
    }


def _flint_text_content(response: Any) -> str:
    return "\n".join(
        str(getattr(item, "text", "") or "")
        for item in response.content
        if getattr(item, "type", "") == "text"
    ).strip()


def _validation_error_message(validation: dict[str, Any]) -> str:
    messages: list[str] = []
    for item in validation.get("errors") or []:
        if isinstance(item, dict):
            message = str(item.get("message") or item.get("code") or "").strip()
        else:
            message = str(item or "").strip()
        if message:
            messages.append(message)
    return "; ".join(messages[:5]) or "Flint MCP rejected the chart specification"


def extract_safe_svg(text: str) -> str:
    match = re.search(r"<svg\b[\s\S]*?</svg\s*>", str(text or ""), flags=re.IGNORECASE)
    if not match:
        raise ValueError("Flint MCP did not return an SVG document")
    svg = match.group(0).strip()
    if len(svg) > MAX_SVG_CHARS:
        raise ValueError("Flint MCP SVG exceeded the configured size limit")
    if _DANGEROUS_SVG_PATTERN.search(svg):
        raise ValueError("Flint MCP SVG contained forbidden active or external content")
    return svg


def apply_business_semantics_to_svg(
    svg: str,
    chart: dict[str, Any],
    arguments: dict[str, Any],
) -> str:
    """Correct business-direction semantics Flint cannot encode in a Bullet Chart."""

    if str(chart.get("type") or "").strip().lower() != "bullet":
        return svg
    values = (
        arguments.get("data", {}).get("values", [])
        if isinstance(arguments.get("data"), dict)
        else []
    )
    status_by_metric = {
        str(row.get("metric") or ""): str(row.get("status") or "")
        for row in values
        if isinstance(row, dict)
        and str(row.get("metric") or "")
        and str(row.get("status") or "") in {"弱于同级", "优于同级"}
    }
    if not status_by_metric:
        return svg

    status_colors = {"弱于同级": "#c44e52", "优于同级": "#2f855a"}

    def replace_bar_fill(match: re.Match[str]) -> str:
        tag = match.group(0)
        if 'aria-roledescription="bar"' not in tag:
            return tag
        for metric, status in status_by_metric.items():
            if html.escape(metric, quote=True) not in tag:
                continue
            color = status_colors[status]
            if _SVG_FILL_ATTRIBUTE_PATTERN.search(tag):
                return _SVG_FILL_ATTRIBUTE_PATTERN.sub(
                    f'fill="{color}"',
                    tag,
                    count=1,
                )
            return tag[:-1] + f' fill="{color}">'
        return tag

    corrected = _SVG_PATH_TAG_PATTERN.sub(replace_bar_fill, svg)
    corrected = corrected.replace("Below target", "弱于同级")
    corrected = corrected.replace("Meets target", "优于同级")
    svg_open_end = corrected.find(">")
    if svg_open_end < 0:
        return corrected
    svg_open = corrected[: svg_open_end + 1]
    width_match = _SVG_WIDTH_PATTERN.search(svg_open)
    viewbox_match = _SVG_VIEWBOX_PATTERN.search(svg_open)
    if not width_match or not viewbox_match:
        return corrected
    padding = 36.0
    width = float(width_match.group("value"))
    viewbox_x = float(viewbox_match.group("x"))
    viewbox_y = float(viewbox_match.group("y"))
    viewbox_width = float(viewbox_match.group("width"))
    viewbox_height = float(viewbox_match.group("height"))
    padded_open = _SVG_WIDTH_PATTERN.sub(
        f'width="{width + padding:g}"',
        svg_open,
        count=1,
    )
    padded_open = _SVG_VIEWBOX_PATTERN.sub(
        f'viewBox="{viewbox_x - padding:g} {viewbox_y:g} '
        f'{viewbox_width + padding:g} {viewbox_height:g}"',
        padded_open,
        count=1,
    )
    return padded_open + corrected[svg_open_end + 1 :]


def _safe_chart_filename(chart_id: str, index: int) -> str:
    safe_id = _SAFE_CHART_ID_PATTERN.sub("-", chart_id).strip("-_")[:80]
    return f"{index:02d}-{safe_id or 'chart'}.svg"


async def _render_report_charts_async(
    charts: list[tuple[dict[str, Any], dict[str, Any]]],
    output_dir: Path,
) -> list[dict[str, Any]]:
    cli_path = flint_mcp_cli_path()
    if not cli_path.is_file():
        raise FileNotFoundError(
            f"Flint MCP runtime is not installed at {cli_path}. Run pnpm install in chart-runtime."
        )
    node_command = str(os.getenv("FLINT_CHART_NODE_COMMAND") or "node").strip() or "node"
    timeout_seconds = _bounded_timeout(
        "FLINT_CHART_TIMEOUT_SECONDS",
        DEFAULT_CHART_TIMEOUT_SECONDS,
        5,
        120,
    )
    server_params = StdioServerParameters(
        command=node_command,
        args=[
            str(cli_path),
            "--backends",
            "vegalite,echarts",
            "--disable-file-reference",
        ],
        cwd=str(_repo_root()),
    )
    rendered: list[dict[str, Any]] = []
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            server_version = str(
                getattr(getattr(initialized, "serverInfo", None), "version", "")
                or FLINT_MCP_PACKAGE_VERSION
            )
            for index, (chart, arguments) in enumerate(charts, start=1):
                chart_id = str(chart.get("id") or f"chart-{index}")
                validation: dict[str, Any] = {"status": "not_run", "valid": False}
                failure_stage = "validate_chart"
                try:
                    validation_response = await session.call_tool(
                        "validate_chart",
                        arguments=build_flint_validate_arguments(arguments),
                        read_timeout_seconds=timedelta(seconds=timeout_seconds),
                    )
                    validation_text = _flint_text_content(validation_response)
                    if validation_response.isError:
                        raise RuntimeError(
                            validation_text
                            or "Flint MCP validate_chart returned an error"
                        )
                    validation = parse_flint_validation(validation_text)
                    if not validation["valid"]:
                        raise ValueError(_validation_error_message(validation))

                    failure_stage = "render_chart"
                    response = await session.call_tool(
                        "render_chart",
                        arguments=arguments,
                        read_timeout_seconds=timedelta(seconds=timeout_seconds),
                    )
                    if response.isError:
                        message = " ".join(
                            str(getattr(item, "text", "") or "")
                            for item in response.content
                            if getattr(item, "type", "") == "text"
                        ).strip()
                        raise RuntimeError(message or "Flint MCP render_chart returned an error")
                    svg_text = next(
                        (
                            str(getattr(item, "text", "") or "")
                            for item in response.content
                            if getattr(item, "type", "") == "text"
                            and "<svg" in str(getattr(item, "text", "") or "").lower()
                        ),
                        "",
                    )
                    svg = extract_safe_svg(svg_text)
                    svg = apply_business_semantics_to_svg(svg, chart, arguments)
                    svg = extract_safe_svg(svg)
                    svg_path = output_dir / _safe_chart_filename(chart_id, index)
                    svg_path.write_text(svg, encoding="utf-8")
                    rendered.append(
                        {
                            "chart_id": chart_id,
                            "status": "rendered",
                            "backend": str(arguments.get("backend") or "vegalite"),
                            "native_tool": "render_chart",
                            "chart_type": str(
                                (arguments.get("chart_spec") or {}).get("chartType") or ""
                            ),
                            "svg_path": str(svg_path),
                            "svg_chars": len(svg),
                            "server_version": server_version,
                            "validation": validation,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    rendered.append(
                        {
                            "chart_id": chart_id,
                            "status": "failed",
                            "backend": str(arguments.get("backend") or "vegalite"),
                            "native_tool": "render_chart",
                            "error": str(exc),
                            "server_version": server_version,
                            "failure_stage": failure_stage,
                            "validation": validation,
                        }
                    )
    return rendered


def _run_coroutine(coroutine: Coroutine[Any, Any, _T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="flint-mcp") as executor:
        return executor.submit(asyncio.run, coroutine).result()


def render_report_charts_via_flint(payload: dict[str, Any]) -> dict[str, Any]:
    """Render supported ReportData charts through the pinned local Flint MCP server."""

    report_data = (
        payload.get("reportData") if isinstance(payload.get("reportData"), dict) else {}
    )
    chart_specs = [
        chart
        for chart in report_data.get("chart_specs") or []
        if isinstance(chart, dict)
    ]
    output_dir_value = str(payload.get("outputDir") or "").strip()
    if not output_dir_value:
        raise ValueError("outputDir is required for chart rendering")
    output_dir = Path(output_dir_value).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    render_inputs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    skipped: list[dict[str, Any]] = []
    for chart in chart_specs:
        chart_id = str(chart.get("id") or "").strip()
        arguments = build_flint_render_arguments(chart)
        if arguments is None:
            skipped.append(
                {
                    "chart_id": chart_id,
                    "status": "skipped",
                    "reason": "unsupported_or_deterministic_server_chart",
                }
            )
            continue
        render_inputs.append((chart, arguments))

    total_timeout = _bounded_timeout(
        "FLINT_CHART_TOTAL_TIMEOUT_SECONDS",
        DEFAULT_TOTAL_TIMEOUT_SECONDS,
        15,
        600,
    )
    rendered = (
        _run_coroutine(
            asyncio.wait_for(
                _render_report_charts_async(render_inputs, output_dir),
                timeout=total_timeout,
            )
        )
        if render_inputs
        else []
    )
    failures = [item for item in rendered if item.get("status") == "failed"]
    successes = [item for item in rendered if item.get("status") == "rendered"]
    return {
        "schema_version": CHART_RENDER_BUNDLE_SCHEMA_VERSION,
        "renderer": "flint-mcp",
        "native_tool": "render_chart",
        "mcp_package_version": FLINT_MCP_PACKAGE_VERSION,
        "status": (
            "ok"
            if successes and not failures
            else "partial_ok"
            if successes or skipped
            else "empty"
        ),
        "summary": {
            "chart_spec_count": len(chart_specs),
            "requested_count": len(render_inputs),
            "rendered_count": len(successes),
            "failed_count": len(failures),
            "skipped_count": len(skipped),
        },
        "charts": rendered,
        "skipped_charts": skipped,
        "fallback_policy": "existing deterministic server chart renderer",
    }

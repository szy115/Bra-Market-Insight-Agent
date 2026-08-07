from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .registry import (
    InvocationScope,
    RecoveryTraits,
    ResultContract,
    ToolCapability,
    ToolInvocation,
)

BoundedInt = Callable[[Any, int, int, int], int]
ResolveParams = Callable[[dict[str, Any]], Mapping[str, Any]]
CapabilityAdapter = Callable[[ToolInvocation], dict[str, Any]]


def input_schema(
    properties: dict[str, Any], *, required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": True,
    }


def planner_capability(
    *,
    capability_id: str,
    label: str,
    description: str,
    schema: Mapping[str, Any],
    normalize_input: Callable[[str, dict[str, Any]], dict[str, Any]],
    adapter: CapabilityAdapter,
    shape_result: Callable[[dict[str, Any]], dict[str, Any]],
    summarize: Callable[[dict[str, Any]], str],
    validate_result: Callable[[Mapping[str, Any]], None],
    catalog_metadata: Mapping[str, Any] | None = None,
) -> ToolCapability:
    return ToolCapability(
        capability_id=capability_id,
        label=label,
        description=description,
        input_schema=schema,
        invocation_scope=InvocationScope.PLANNER,
        normalize_input=normalize_input,
        adapter=adapter,
        shape_result=shape_result,
        shape_error=lambda _exc: {},
        summarize=summarize,
        result_contract=ResultContract(
            contract_id=f"{capability_id}_result.v1",
            validate=validate_result,
        ),
        recovery=RecoveryTraits(
            retryable=True,
            default_timeout_seconds=600,
            default_retry_attempts=2,
        ),
        output_kind=capability_id,
        catalog_metadata=catalog_metadata or {},
    )


def require_list(result: Mapping[str, Any], field_name: str) -> None:
    if not isinstance(result.get(field_name), list):
        raise ValueError(f"{field_name} must be a list")


def require_mapping_or_none(result: Mapping[str, Any], field_name: str) -> None:
    value = result.get(field_name)
    if value is not None and not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping or null")

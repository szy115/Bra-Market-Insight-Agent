from __future__ import annotations

import copy
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class InvocationScope(StrEnum):
    PLANNER = "planner"
    RUNTIME_INTERNAL = "runtime_internal"


@dataclass(frozen=True)
class RecoveryTraits:
    retryable: bool
    default_timeout_seconds: int
    default_retry_attempts: int


@dataclass(frozen=True)
class ResultContract:
    contract_id: str
    validate: Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True)
class ToolInvocation:
    requested_category: str
    tool_input: dict[str, Any]


@dataclass(frozen=True)
class ToolCapability:
    capability_id: str
    label: str
    description: str
    input_schema: Mapping[str, Any]
    invocation_scope: InvocationScope
    normalize_input: Callable[[str, dict[str, Any]], dict[str, Any]]
    adapter: Callable[[ToolInvocation], dict[str, Any]]
    shape_result: Callable[[dict[str, Any]], dict[str, Any]]
    shape_error: Callable[[Exception], dict[str, Any]]
    summarize: Callable[[dict[str, Any]], str]
    result_contract: ResultContract
    recovery: RecoveryTraits
    output_kind: str
    catalog_metadata: Mapping[str, Any] = field(default_factory=dict)


class InvalidToolCapability(ValueError):
    pass


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return copy.deepcopy(value)


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return copy.deepcopy(value)


class ToolCapabilityRegistry:
    def __init__(
        self,
        capabilities: Iterable[ToolCapability],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        registered: dict[str, ToolCapability] = {}
        for capability in capabilities:
            self._validate(capability)
            if capability.capability_id in registered:
                raise InvalidToolCapability(
                    f"Duplicate Tool Capability id: {capability.capability_id}"
                )
            registered[capability.capability_id] = replace(
                capability,
                input_schema=_freeze_json(capability.input_schema),
                catalog_metadata=_freeze_json(capability.catalog_metadata),
            )
        self._capabilities = MappingProxyType(registered)
        self._clock = clock

    @property
    def capabilities(self) -> Mapping[str, ToolCapability]:
        return self._capabilities

    def get(self, capability_id: str) -> ToolCapability:
        return self._capabilities[capability_id]

    def __contains__(self, capability_id: object) -> bool:
        return capability_id in self._capabilities

    def execute(
        self,
        capability_id: str,
        category: str,
        payload: dict[str, Any],
        *,
        runtime_adapter: Callable[[ToolInvocation], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        capability = self.get(capability_id)
        started = self._clock()
        tool_input = capability.normalize_input(category, payload)
        try:
            adapter = runtime_adapter or capability.adapter
            raw_result = adapter(
                ToolInvocation(requested_category=category, tool_input=tool_input)
            )
            shaped_result = capability.shape_result(raw_result)
            try:
                capability.result_contract.validate(shaped_result)
            except Exception as exc:  # noqa: BLE001 - contract validators explain mismatches
                raise ValueError(
                    f"{capability.result_contract.contract_id} contract violation: {exc}"
                ) from exc
            return self._result_envelope(
                capability,
                started,
                tool_input,
                status="ok",
                summary=capability.summarize(raw_result),
                data=shaped_result,
            )
        except Exception as exc:  # noqa: BLE001 - adapters report failures in the result contract
            return self._result_envelope(
                capability,
                started,
                tool_input,
                status="error",
                summary=str(exc),
                data=capability.shape_error(exc),
            )

    def _result_envelope(
        self,
        capability: ToolCapability,
        started: float,
        tool_input: dict[str, Any],
        *,
        status: str,
        summary: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "name": capability.capability_id,
            "label": capability.label,
            "status": status,
            "summary": summary,
            "duration_ms": int((self._clock() - started) * 1000),
            "input": tool_input,
            "data": data,
        }

    def catalog(self, invocation_scope: InvocationScope | None = None) -> dict[str, dict[str, Any]]:
        return {
            capability_id: self._catalog_entry(capability)
            for capability_id, capability in self._capabilities.items()
            if invocation_scope is None or capability.invocation_scope == invocation_scope
        }

    @staticmethod
    def _catalog_entry(capability: ToolCapability) -> dict[str, Any]:
        return {
            "label": capability.label,
            "description": capability.description,
            "input_schema": _thaw_json(capability.input_schema),
            "invocation_scope": capability.invocation_scope.value,
            "result_contract": capability.result_contract.contract_id,
            "recovery": {
                "retryable": capability.recovery.retryable,
                "default_timeout_seconds": capability.recovery.default_timeout_seconds,
                "default_retry_attempts": capability.recovery.default_retry_attempts,
            },
            "output_kind": capability.output_kind,
            **_thaw_json(capability.catalog_metadata),
        }

    @staticmethod
    def _validate(capability: ToolCapability) -> None:
        text_fields = {
            "capability_id": capability.capability_id,
            "label": capability.label,
            "description": capability.description,
            "output_kind": capability.output_kind,
        }
        for field_name, value in text_fields.items():
            if not isinstance(value, str) or not value.strip():
                raise InvalidToolCapability(f"{field_name} must be a non-empty string")
        if not isinstance(capability.result_contract, ResultContract):
            raise InvalidToolCapability("result_contract must be a ResultContract")
        if (
            not isinstance(capability.result_contract.contract_id, str)
            or not capability.result_contract.contract_id.strip()
        ):
            raise InvalidToolCapability("result_contract.contract_id must be a non-empty string")
        if not callable(capability.result_contract.validate):
            raise InvalidToolCapability("result_contract.validate must be callable")
        if not isinstance(capability.invocation_scope, InvocationScope):
            raise InvalidToolCapability("invocation_scope must be an InvocationScope")
        if not isinstance(capability.input_schema, Mapping):
            raise InvalidToolCapability("input_schema must be a mapping")
        if capability.input_schema.get("type") != "object":
            raise InvalidToolCapability("input_schema.type must be object")
        if not isinstance(capability.input_schema.get("properties"), Mapping):
            raise InvalidToolCapability("input_schema.properties must be a mapping")
        if not isinstance(capability.input_schema.get("required"), list | tuple):
            raise InvalidToolCapability("input_schema.required must be a list")
        if not isinstance(capability.catalog_metadata, Mapping):
            raise InvalidToolCapability("catalog_metadata must be a mapping")
        reserved_metadata = {
            "label",
            "description",
            "input_schema",
            "invocation_scope",
            "result_contract",
            "recovery",
            "output_kind",
        }
        if reserved_metadata.intersection(capability.catalog_metadata):
            raise InvalidToolCapability("catalog_metadata cannot override registry fields")
        callables = {
            "normalize_input": capability.normalize_input,
            "adapter": capability.adapter,
            "shape_result": capability.shape_result,
            "shape_error": capability.shape_error,
            "summarize": capability.summarize,
        }
        for field_name, value in callables.items():
            if not callable(value):
                raise InvalidToolCapability(f"{field_name} must be callable")
        if not isinstance(capability.recovery, RecoveryTraits):
            raise InvalidToolCapability("recovery must be RecoveryTraits")
        if capability.recovery.default_timeout_seconds <= 0:
            raise InvalidToolCapability("default_timeout_seconds must be positive")
        if capability.recovery.default_retry_attempts < 0:
            raise InvalidToolCapability("default_retry_attempts must be non-negative")

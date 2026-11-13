# -*- coding: utf-8 -*-
"""Provider-neutral canonical tool definitions.

``ToolDefinition`` is immutable metadata.  Execution callables are carried only
as a compatibility convenience for the existing factory/tests; the registry
extracts them into entries and catalog snapshots expose definitions without a
handler.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from ..core.tooling import ToolArguments
from .schema import (
	ToolSchemaError,
	clone_schema,
	freeze_json,
	normalize_input_schema,
	normalize_output_schema,
	schema_fingerprint,
	serialize_schema,
)

ToolExecutorCallable = Callable[[ToolArguments], object]


@dataclass(frozen=True, slots=True)
class ToolAnnotations:
	"""Behavioural hints.  Hints are untrusted for external providers."""

	title: str | None = None
	read_only_hint: bool | None = None
	destructive_hint: bool | None = None
	idempotent_hint: bool | None = None
	open_world_hint: bool | None = None
	raw: Mapping[str, Any] = field(default_factory=dict, compare=False)

	def __post_init__(self) -> None:
		object.__setattr__(self, "raw", freeze_json(dict(self.raw or {})))

	def to_dict(self) -> dict[str, Any]:
		payload: dict[str, Any] = {}
		if self.title is not None:
			payload["title"] = self.title
		if self.read_only_hint is not None:
			payload["readOnlyHint"] = self.read_only_hint
		if self.destructive_hint is not None:
			payload["destructiveHint"] = self.destructive_hint
		if self.idempotent_hint is not None:
			payload["idempotentHint"] = self.idempotent_hint
		if self.open_world_hint is not None:
			payload["openWorldHint"] = self.open_world_hint
		return payload

	@classmethod
	def from_payload(cls, payload: Mapping[str, Any] | None) -> "ToolAnnotations | None":
		if not isinstance(payload, Mapping):
			return None
		title = payload.get("title")
		return cls(
			title=title if isinstance(title, str) else None,
			read_only_hint=_optional_bool(payload.get("readOnlyHint")),
			destructive_hint=_optional_bool(payload.get("destructiveHint")),
			idempotent_hint=_optional_bool(payload.get("idempotentHint")),
			open_world_hint=_optional_bool(payload.get("openWorldHint")),
			raw=dict(payload),
		)


@dataclass(frozen=True, slots=True)
class ToolDefinition:
	"""Canonical, provider-neutral tool metadata.

	Compatibility: ``parameters``/``required`` remain accepted and are folded
	into ``input_schema`` when no explicit schema is supplied.  Prefer
	``input_schema`` for new tools.
	"""

	name: str
	description: str
	parameters: Mapping[str, Any] = field(default_factory=dict)
	required: list[str] = field(default_factory=list)
	executor: ToolExecutorCallable | None = field(default=None, compare=False, repr=False)
	input_schema: Mapping[str, Any] | None = None
	output_schema: Mapping[str, Any] | bool | None = None
	tool_id: str | None = None
	provider_tool_name: str | None = None
	provider_id: str = "native"
	source: str = "native"
	display_title: str | None = None
	annotations: ToolAnnotations | None = None
	metadata: Mapping[str, Any] = field(default_factory=dict, compare=False)
	available: bool = True

	def __post_init__(self) -> None:
		declared_name = str(self.name or "").strip()
		if not declared_name:
			raise ValueError("Tool name is required")
		if self.source not in ("native", "mcp"):
			raise ValueError(f"Unsupported tool source: {self.source!r}")
		provider_id = str(self.provider_id or "native").strip() or "native"
		provider_tool_name = str(self.provider_tool_name or declared_name)

		explicit_schema = self.input_schema is not None
		if explicit_schema:
			schema = normalize_input_schema(self.input_schema)
		else:
			schema = {
				"type": "object",
				"properties": clone_schema(dict(self.parameters)),
				"required": [str(item) for item in self.required],
			}
			if not schema["required"]:
				schema.pop("required")
			schema = normalize_input_schema(schema)
		output_schema = normalize_output_schema(self.output_schema)

		annotations = self.annotations
		if annotations is not None and not isinstance(annotations, ToolAnnotations):
			annotations = ToolAnnotations.from_payload(annotations)  # type: ignore[arg-type]

		tool_id = self.tool_id or (
			f"native:{declared_name}"
			if self.source == "native"
			else f"mcp:{provider_id}:{provider_tool_name}"
		)
		metadata = dict(self.metadata or {})
		derived_required = schema.get("required")
		required_list = (
			[str(item) for item in derived_required]
			if isinstance(derived_required, list)
			else [str(item) for item in self.required]
		)
		parameters = schema.get("properties")
		parameters = clone_schema(parameters) if isinstance(parameters, Mapping) else {}

		object.__setattr__(self, "name", declared_name)
		object.__setattr__(self, "provider_id", provider_id)
		object.__setattr__(self, "provider_tool_name", provider_tool_name)
		object.__setattr__(self, "input_schema", freeze_json(schema))
		object.__setattr__(self, "output_schema", freeze_json(output_schema) if output_schema is not None else None)
		object.__setattr__(self, "tool_id", tool_id)
		object.__setattr__(self, "annotations", annotations)
		object.__setattr__(self, "metadata", freeze_json(metadata))
		object.__setattr__(self, "parameters", freeze_json(parameters))
		object.__setattr__(self, "required", freeze_json(required_list))

	@property
	def schema_fingerprint(self) -> str:
		return schema_fingerprint(self.input_schema or {})

	def to_dict(self) -> dict[str, Any]:
		"""Provider-neutral function declaration (OpenAI-style envelope)."""
		return {
			"type": "function",
			"function": {
				"name": self.name,
				"description": self.description,
				"parameters": clone_schema(self.input_schema or {"type": "object", "properties": {}}),
			},
		}

	def to_wire_dict(self) -> dict[str, Any]:
		return self.to_dict()

	def to_schema_json(self) -> str:
		return serialize_schema(self.input_schema or {})

	def with_model_name(self, model_name: str) -> "ToolDefinition":
		return replace(self, name=model_name)

	def without_executor(self) -> "ToolDefinition":
		if self.executor is None:
			return self
		return replace(self, executor=None)

	def with_availability(self, available: bool) -> "ToolDefinition":
		return replace(self, available=available)

	@classmethod
	def from_provider_payload(
		cls,
		payload: Mapping[str, Any],
		*,
		provider_id: str,
		source: str = "mcp",
	) -> "ToolDefinition":
		"""Build a definition from an external provider's tool description.

		This is deliberately narrow data parsing, not an MCP client: it lets the
		future Rust manager hand over normalized JSON.  Provider-supplied
		metadata is preserved but treated as untrusted.
		"""
		if not isinstance(payload, Mapping):
			raise ToolSchemaError("Tool payload must be a JSON object")
		name = payload.get("name")
		if not isinstance(name, str) or not name.strip():
			raise ToolSchemaError("Tool payload requires a non-empty string 'name'")
		input_schema = payload.get("inputSchema")
		if input_schema is None:
			input_schema = payload.get("input_schema")
		output_schema = payload.get("outputSchema")
		if output_schema is None:
			output_schema = payload.get("output_schema")
		if input_schema is not None and not isinstance(input_schema, Mapping):
			raise ToolSchemaError(
				"Tool payload 'inputSchema' must be a JSON object"
			)
		if output_schema is not None and not isinstance(output_schema, (Mapping, bool)):
			raise ToolSchemaError(
				"Tool payload 'outputSchema' must be a JSON object"
			)
		annotations = ToolAnnotations.from_payload(payload.get("annotations"))
		title = payload.get("title")
		metadata = payload.get("metadata")
		return cls(
			name=name.strip(),
			description=str(payload.get("description") or ""),
			input_schema=input_schema,
			output_schema=output_schema,
			provider_id=provider_id,
			source=source,
			provider_tool_name=name.strip(),
			display_title=title if isinstance(title, str) else (annotations.title if annotations else None),
			annotations=annotations,
			metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
		)


def _optional_bool(value: Any) -> bool | None:
	return value if isinstance(value, bool) else None

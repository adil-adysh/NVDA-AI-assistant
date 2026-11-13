# -*- coding: utf-8 -*-
"""Dynamic, thread-safe tool catalog with immutable generation snapshots."""
from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from ..core.canonical import Tool
from ..core.tooling import ToolArguments, ToolCall
from .definition import ToolDefinition, ToolExecutorCallable
from .errors import ToolError, UnknownToolError
from .naming import (
	disambiguate_model_tool_name,
	external_tool_name,
	native_tool_name,
)
from .provider import ToolCallContext, ToolProvider


class ToolRegistrationError(ValueError):
	"""Base class for invalid catalog mutations."""


class ToolAlreadyRegisteredError(ToolRegistrationError):
	pass


class ToolNameConflictError(ToolRegistrationError):
	pass


@dataclass(frozen=True, slots=True)
class ToolBinding:
	"""A model-facing name resolved inside one immutable catalog generation."""

	definition: ToolDefinition
	provider_id: str
	original_name: str
	model_name: str
	tool_id: str
	generation: int
	handler: ToolExecutorCallable | None = None
	backend: ToolProvider | None = None

	def invoke(self, arguments: ToolArguments, context: ToolCallContext) -> object:
		if self.backend is not None:
			return self.backend.execute(self.definition, arguments, context)
		if self.handler is not None:
			return self.handler(arguments)
		raise ToolError(
			f"Tool '{self.model_name}' has no execution backend",
			safe_message=f"Tool '{self.model_name}' is unavailable.",
		) from None


@dataclass(frozen=True, slots=True)
class ToolCatalogSnapshot:
	"""Immutable view of the enabled catalog at one generation.

	Chat turns resolve exactly one snapshot, so a later refresh cannot redirect
	an in-flight, already-authorized call to a different tool.
	"""

	generation: int
	definitions: tuple[ToolDefinition, ...] = ()
	bindings: Mapping[str, ToolBinding] = MappingProxyType({})

	def __post_init__(self) -> None:
		object.__setattr__(self, "bindings", MappingProxyType(dict(self.bindings)))

	def __len__(self) -> int:
		return len(self.definitions)

	def resolve(self, model_name: str) -> ToolBinding | None:
		return self.bindings.get(model_name)

	def require(self, model_name: str) -> ToolBinding:
		binding = self.resolve(model_name)
		if binding is None:
			raise UnknownToolError(model_name)
		return binding

	def provider_tools(self) -> list[Tool]:
		return [_to_canonical_tool(definition) for definition in self.definitions]

	def definition_for(self, model_name: str) -> ToolDefinition | None:
		binding = self.resolve(model_name)
		return binding.definition if binding is not None else None

	def enabled_names(self) -> tuple[str, ...]:
		return tuple(binding.model_name for binding in self.bindings.values())


@dataclass(frozen=True, slots=True)
class _ToolEntry:
	definition: ToolDefinition
	provider_id: str
	original_name: str
	model_name: str
	tool_id: str
	handler: ToolExecutorCallable | None = None
	backend: ToolProvider | None = None


class ToolRegistry:
	"""Registry for tool definitions and execution handlers.

	All public mutations are atomic and publish a fresh immutable snapshot.
	Reads use the published snapshot and never take the mutation lock.
	"""

	def __init__(self) -> None:
		self._lock = threading.RLock()
		self._entries: dict[str, _ToolEntry] = {}
		self._provider_available: dict[str, bool] = {}
		self._generation = 0
		self._snapshot = ToolCatalogSnapshot(generation=0)

	# ------------------------------------------------------------------
	# Registration
	# ------------------------------------------------------------------

	def register_tool(self, tool: ToolDefinition) -> None:
		"""Backwards-compatible registration of one native definition."""
		if tool.executor is None:
			raise ValueError("Tool executor is required")
		self.register(tool)

	def register(
		self,
		definition: ToolDefinition,
		handler: ToolExecutorCallable | None = None,
		*,
		backend: ToolProvider | None = None,
		replace_existing: bool = False,
	) -> ToolDefinition:
		effective_handler = handler or definition.executor
		if effective_handler is None and backend is None:
			raise ValueError("Tool executor is required")
		with self._lock:
			tool_id = definition.tool_id or ""
			existing = self._entries.get(tool_id)
			if existing is not None and not replace_existing:
				raise ToolAlreadyRegisteredError(f"Tool already registered: {definition.name}")
			used_names = self._used_names(exclude_tool_id=tool_id)
			entry = self._build_entry(
				definition=definition,
				handler=effective_handler,
				backend=backend,
				used_names=used_names,
				provider_id=definition.provider_id,
				original_name=definition.provider_tool_name or definition.name,
			)
			entries = dict(self._entries)
			entries[entry.tool_id] = entry
			self._publish(entries)
			return entry.definition

	def register_provider_tools(
		self,
		provider_id: str,
		tools: Sequence[ToolDefinition],
		*,
		backend: ToolProvider | None = None,
	) -> tuple[ToolDefinition, ...]:
		"""Add several tools from one provider in a single atomic commit."""
		with self._lock:
			entries = dict(self._entries)
			used_names = self._used_names()
			created: list[ToolDefinition] = []
			for definition in tools:
				if definition.provider_id != provider_id:
					definition = replace(definition, provider_id=provider_id, source="mcp", tool_id=None)
				effective_handler = definition.executor
				if effective_handler is None and backend is None:
					raise ValueError(
						f"Tool '{definition.name}' from provider '{provider_id}' has no backend"
					)
				tool_id = definition.tool_id or ""
				if tool_id in entries:
					raise ToolAlreadyRegisteredError(f"Tool already registered: {definition.name}")
				entry = self._build_entry(
					definition=definition,
					handler=effective_handler,
					backend=backend,
					used_names=used_names,
					provider_id=provider_id,
					original_name=definition.provider_tool_name or definition.name,
				)
				entries[entry.tool_id] = entry
				created.append(entry.definition)
			self._publish(entries)
			return tuple(created)

	def register_external_tools(
		self,
		provider_id: str,
		payloads: Sequence[Mapping[str, Any]],
		*,
		backend: ToolProvider | None = None,
	) -> tuple[ToolDefinition, ...]:
		"""Register normalized external (e.g. future MCP) tool descriptions."""
		definitions = [
			ToolDefinition.from_provider_payload(payload, provider_id=provider_id) for payload in payloads
		]
		return self.register_provider_tools(provider_id, definitions, backend=backend)

	def replace_provider_catalog(
		self,
		provider_id: str,
		tools: Sequence[ToolDefinition],
		*,
		backend: ToolProvider | None = None,
	) -> tuple[ToolDefinition, ...]:
		"""Atomically replace one provider's whole catalog.

		On any validation or naming failure the previous catalog is left intact.
		"""
		with self._lock:
			entries = {
				tool_id: entry
				for tool_id, entry in self._entries.items()
				if entry.provider_id != provider_id
			}
			used_names = self._used_names(exclude_provider_id=provider_id)
			created: list[ToolDefinition] = []
			for definition in tools:
				if definition.provider_id != provider_id:
					definition = replace(definition, provider_id=provider_id, source="mcp", tool_id=None)
				effective_handler = definition.executor
				if effective_handler is None and backend is None:
					raise ValueError(
						f"Tool '{definition.name}' from provider '{provider_id}' has no backend"
					)
				entry = self._build_entry(
					definition=definition,
					handler=effective_handler,
					backend=backend,
					used_names=used_names,
					provider_id=provider_id,
					original_name=definition.provider_tool_name or definition.name,
				)
				entries[entry.tool_id] = entry
				created.append(entry.definition)
			self._publish(entries)
			return tuple(created)

	def update(
		self,
		tool_id_or_name: str,
		*,
		definition: ToolDefinition | None = None,
		handler: ToolExecutorCallable | None = None,
		backend: ToolProvider | None = None,
		available: bool | None = None,
	) -> ToolDefinition:
		"""Replace a registered tool's metadata/handler without changing identity."""
		with self._lock:
			tool_id = self._entry_id_for(tool_id_or_name)
			existing = self._entries.get(tool_id)
			if existing is None:
				raise UnknownToolError(tool_id_or_name)
			new_definition = definition or existing.definition
			if new_definition.tool_id != tool_id:
				new_definition = replace(new_definition, tool_id=tool_id)
			effective_handler = (
				handler
				if handler is not None
				else (definition.executor if definition is not None else existing.handler)
			)
			if effective_handler is None:
				effective_handler = existing.handler
			effective_backend = backend if backend is not None else existing.backend
			if available is not None:
				new_definition = new_definition.with_availability(available)
			used_names = self._used_names(exclude_tool_id=tool_id)
			entry = self._build_entry(
				definition=new_definition,
				handler=effective_handler,
				backend=effective_backend,
				used_names=used_names,
				provider_id=existing.provider_id,
				original_name=existing.original_name,
			)
			entries = dict(self._entries)
			entries[tool_id] = entry
			self._publish(entries)
			return entry.definition

	# ------------------------------------------------------------------
	# Removal and availability
	# ------------------------------------------------------------------

	def unregister(self, tool_id_or_name: str) -> bool:
		with self._lock:
			tool_id = self._entry_id_for(tool_id_or_name)
			if tool_id is None or tool_id not in self._entries:
				return False
			entries = dict(self._entries)
			entries.pop(tool_id, None)
			self._publish(entries)
			return True

	def unregister_provider(self, provider_id: str) -> int:
		with self._lock:
			entries = {
				tool_id: entry
				for tool_id, entry in self._entries.items()
				if entry.provider_id != provider_id
			}
			removed = len(self._entries) - len(entries)
			if removed:
				self._publish(entries)
			return removed

	def set_provider_available(self, provider_id: str, available: bool) -> None:
		with self._lock:
			if self._provider_available.get(provider_id) == available:
				return
			self._provider_available[provider_id] = available
			self._publish(dict(self._entries))

	def set_tool_available(self, tool_id_or_name: str, available: bool) -> None:
		with self._lock:
			tool_id = self._entry_id_for(tool_id_or_name)
			entry = self._entries.get(tool_id) if tool_id else None
			if entry is None:
				raise UnknownToolError(tool_id_or_name)
			entries = dict(self._entries)
			entries[entry.tool_id] = replace(
				entry, definition=entry.definition.with_availability(available)
			)
			self._publish(entries)

	def is_provider_available(self, provider_id: str) -> bool:
		return self._provider_available.get(provider_id, True)

	# ------------------------------------------------------------------
	# Reads
	# ------------------------------------------------------------------

	@property
	def generation(self) -> int:
		return self._snapshot.generation

	def snapshot(self) -> ToolCatalogSnapshot:
		return self._snapshot

	def get_enabled_definitions(self) -> tuple[ToolDefinition, ...]:
		return self._snapshot.definitions

	def get_definitions(self) -> list[dict[str, Any]]:
		"""Backwards-compatible provider declaration list."""
		return [definition.to_dict() for definition in self._snapshot.definitions]

	def get_tool_names(self) -> list[str]:
		return list(self._snapshot.enabled_names())

	def resolve(self, model_name: str, snapshot: ToolCatalogSnapshot | None = None) -> ToolBinding | None:
		return (snapshot or self._snapshot).resolve(model_name)

	def diagnostics(self) -> dict[str, Any]:
		snapshot = self._snapshot
		return {
			"generation": snapshot.generation,
			"tools": len(snapshot.definitions),
			"providers": sorted({definition.provider_id for definition in snapshot.definitions}),
			"enabled_names": list(snapshot.enabled_names()),
		}

	def execute(self, tool_call: ToolCall) -> str:
		"""Deprecated direct execution path kept for compatibility.

		New code goes through ``ToolExecutor``; this method cannot enforce
		policy, budgets or timeouts.
		"""
		binding = self._snapshot.resolve(tool_call.name)
		if binding is None:
			raise ValueError(f"Unknown tool: {tool_call.name}")
		try:
			result = binding.invoke(tool_call.arguments or {}, _legacy_context(binding))
		except Exception as error:
			raise RuntimeError(f"Tool '{tool_call.name}' execution failed: {error}") from error
		return result if isinstance(result, str) else str(result)

	# ------------------------------------------------------------------
	# Internals
	# ------------------------------------------------------------------

	def _build_entry(
		self,
		*,
		definition: ToolDefinition,
		handler: ToolExecutorCallable | None,
		backend: ToolProvider | None,
		used_names: dict[str, str],
		provider_id: str,
		original_name: str,
	) -> _ToolEntry:
		tool_id = definition.tool_id or ""
		if definition.source == "native":
			try:
				candidate = native_tool_name(definition.name)
			except ValueError as error:
				raise ToolRegistrationError(str(error)) from error
		else:
			candidate = external_tool_name(provider_id, original_name)
		model_name = candidate
		owner = used_names.get(model_name)
		if owner is not None and owner != tool_id:
			if definition.source == "native":
				raise ToolNameConflictError(
					f"Tool name {model_name!r} is already registered by {owner!r}"
				)
			model_name = disambiguate_model_tool_name(candidate, tool_id)
			owner = used_names.get(model_name)
			if owner is not None and owner != tool_id:
				raise ToolNameConflictError(
					f"Unable to assign a unique model-facing name for tool {tool_id!r}"
				)
		used_names[model_name] = tool_id
		model_definition = replace(definition, name=model_name, executor=None)
		return _ToolEntry(
			definition=model_definition,
			provider_id=provider_id,
			original_name=original_name,
			model_name=model_name,
			tool_id=tool_id,
			handler=handler,
			backend=backend,
		)

	def _used_names(
		self,
		*,
		exclude_tool_id: str | None = None,
		exclude_provider_id: str | None = None,
	) -> dict[str, str]:
		used: dict[str, str] = {}
		for tool_id, entry in self._entries.items():
			if exclude_tool_id is not None and tool_id == exclude_tool_id:
				continue
			if exclude_provider_id is not None and entry.provider_id == exclude_provider_id:
				continue
			used[entry.model_name] = tool_id
		return used

	def _entry_id_for(self, tool_id_or_name: str) -> str | None:
		if tool_id_or_name in self._entries:
			return tool_id_or_name
		for tool_id, entry in self._entries.items():
			if entry.model_name == tool_id_or_name:
				return tool_id
		binding = self._snapshot.resolve(tool_id_or_name)
		return binding.tool_id if binding is not None else None

	def _publish(self, entries: Mapping[str, _ToolEntry]) -> None:
		self._entries = dict(entries)
		self._generation += 1
		generation = self._generation
		available_entries = [
			entry
			for entry in self._entries.values()
			if entry.definition.available and self._provider_available.get(entry.provider_id, True)
		]
		definitions = tuple(
			sorted(
				(entry.definition for entry in available_entries),
				key=lambda definition: definition.name,
			)
		)
		bindings = {
			entry.model_name: ToolBinding(
				definition=entry.definition,
				provider_id=entry.provider_id,
				original_name=entry.original_name,
				model_name=entry.model_name,
				tool_id=entry.tool_id,
				generation=generation,
				handler=entry.handler,
				backend=entry.backend,
			)
			for entry in available_entries
		}
		self._snapshot = ToolCatalogSnapshot(
			generation=generation,
			definitions=definitions,
			bindings=bindings,
		)


def _to_canonical_tool(definition: ToolDefinition) -> Tool:
	return Tool(
		name=definition.name,
		description=definition.description,
		input_schema=definition.input_schema,
		output_schema=definition.output_schema,
		provider_tool_name=definition.provider_tool_name,
		tool_id=definition.tool_id,
	)


def _legacy_context(binding: ToolBinding) -> ToolCallContext:
	return ToolCallContext(
		tool_id=binding.tool_id,
		tool_name=binding.model_name,
		tool_call_id=None,
		provider_id=binding.provider_id,
		timeout_seconds=None,
		cancellation_requested=lambda: False,
	)

# -*- coding: utf-8 -*-
"""Provider-neutral execution backends for native and future external tools."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..core.tooling import ToolArguments
from .definition import ToolDefinition


@dataclass(frozen=True, slots=True)
class ToolCallContext:
	"""Execution context handed to a provider backend."""

	tool_id: str
	tool_name: str
	tool_call_id: str | None
	provider_id: str
	timeout_seconds: float | None
	cancellation_requested: Callable[[], bool]

	def cancelled(self) -> bool:
		return self.cancellation_requested()


@runtime_checkable
class ToolProvider(Protocol):
	"""Backend interface implemented by native handlers and, later, MCP clients.

	A backend is bound to one provider id.  It receives only validated
	arguments and must return either a ``ToolExecutionResult`` or a JSON value
	that the executor normalizes.  Provider-specific failures should raise
	``ToolProviderError``; tool-level errors are returned as results with
	``ok=False`` so the future MCP adapter can preserve the protocol-vs-tool
	error distinction.
	"""

	provider_id: str

	def execute(
		self,
		definition: ToolDefinition,
		arguments: ToolArguments,
		context: ToolCallContext,
	) -> object:
		...


class NativeToolBackend:
	"""Adapter that turns a legacy native callable into a provider backend."""

	def __init__(self, handler: Callable[[ToolArguments], object], *, provider_id: str = "native") -> None:
		self.provider_id = provider_id
		self._handler = handler

	def execute(
		self,
		definition: ToolDefinition,
		arguments: ToolArguments,
		context: ToolCallContext,
	) -> object:
		return self._handler(arguments)


class UnavailableToolProvider:
	"""Placeholder for a provider whose transport is disconnected.

	Registering this backend keeps the tool identity reserved while ensuring new
	calls fail with a provider error instead of silently disappearing.
	"""

	def __init__(self, provider_id: str, reason: str = "provider is disconnected") -> None:
		self.provider_id = provider_id
		self.reason = reason

	def execute(
		self,
		definition: ToolDefinition,
		arguments: ToolArguments,
		context: ToolCallContext,
	) -> object:
		from .errors import ToolProviderError

		raise ToolProviderError(
			f"Tool provider '{self.provider_id}' is unavailable: {self.reason}",
			safe_message=f"Tool provider '{self.provider_id}' is unavailable.",
			uncertain=False,
		)


def backend_for(handler: Callable[[ToolArguments], object]) -> NativeToolBackend:
	return NativeToolBackend(handler)

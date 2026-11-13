# -*- coding: utf-8 -*-
"""Explicit, host-owned tool authorization policy.

External tool metadata is never authoritative: annotations supplied by an MCP
server (or any other provider) are not consulted here.  Host policy decides.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..core.tooling import ToolArguments
from .errors import ToolPermissionDenied


@runtime_checkable
class ToolPermissionPolicy(Protocol):
	"""Authorize one resolved tool binding before execution."""

	def authorize(self, binding: Any, arguments: ToolArguments) -> None:
		...


@dataclass(frozen=True, slots=True)
class DefaultToolPermissionPolicy:
	"""Deny-by-default policy with explicit host approvals.

	Allowed without an approval entry:
	- native tools whose host-authored definition is annotated read-only.

	Everything else - external tools, and native tools that may mutate state -
	requires an explicit tool id or provider id approval held by the host.  The
	approval sets are immutable and cannot be changed by tool output.
	"""

	approved_tool_ids: frozenset[str] = field(default_factory=frozenset)
	approved_provider_ids: frozenset[str] = field(default_factory=frozenset)

	def authorize(self, binding: Any, arguments: ToolArguments) -> None:
		definition = binding.definition
		if definition.tool_id in self.approved_tool_ids:
			return
		if definition.provider_id in self.approved_provider_ids:
			return
		if definition.source == "native":
			annotations = definition.annotations
			if annotations is not None and annotations.read_only_hint is True:
				return
		raise ToolPermissionDenied(definition.name)

	def with_approval(self, *, tool_id: str | None = None, provider_id: str | None = None) -> "DefaultToolPermissionPolicy":
		tools = set(self.approved_tool_ids)
		providers = set(self.approved_provider_ids)
		if tool_id:
			tools.add(tool_id)
		if provider_id:
			providers.add(provider_id)
		return DefaultToolPermissionPolicy(
			approved_tool_ids=frozenset(tools),
			approved_provider_ids=frozenset(providers),
		)


class AllowAllToolPermissionPolicy:
	"""Test/diagnostic policy.  Never wire this into the plugin composition root."""

	def authorize(self, binding: Any, arguments: Mapping[str, Any] | None = None) -> None:
		return None

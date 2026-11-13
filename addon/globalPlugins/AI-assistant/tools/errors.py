# -*- coding: utf-8 -*-
"""Tool-system exceptions and their outcome classification."""
from __future__ import annotations

from collections.abc import Sequence

from ..core.tooling import MAX_TOOL_ERROR_CHARS, ToolErrorCategory, ToolErrorSource
from .schema import SchemaViolation, format_violations


def bounded_message(message: str, limit: int = MAX_TOOL_ERROR_CHARS) -> str:
	text = " ".join(str(message).split()) if "\n" not in str(message) else str(message).strip()
	if len(text) <= limit:
		return text
	marker = "…[truncated]"
	return text[: max(0, limit - len(marker))] + marker


class ToolError(Exception):
	"""Base class for classified tool failures."""

	category: ToolErrorCategory = "execution_error"
	error_source: ToolErrorSource = "host"
	uncertain: bool = False
	termination_confirmed: bool = True

	def __init__(self, message: str, *, safe_message: str | None = None) -> None:
		super().__init__(bounded_message(message))
		self.safe_message = bounded_message(safe_message or message)


class UnknownToolError(ToolError):
	category = "unknown_tool"

	def __init__(self, name: str) -> None:
		super().__init__(
			f"Unknown tool: {name}",
			safe_message=f"Unknown tool: {name}. The tool is not available in the current catalog.",
		)


class ToolArgumentError(ToolError):
	category = "invalid_arguments"

	def __init__(self, message: str, *, violations: Sequence[SchemaViolation] = ()) -> None:
		self.violations = tuple(violations)
		detail = format_violations(self.violations) if self.violations else message
		super().__init__(
			f"Invalid tool arguments: {detail}",
			safe_message=f"Invalid tool arguments: {detail}",
		)


class ToolPermissionDenied(ToolError):
	category = "permission_denied"

	def __init__(self, tool_name: str, reason: str = "not approved by host policy") -> None:
		super().__init__(
			f"Tool '{tool_name}' is not permitted: {reason}",
			safe_message=f"Tool '{tool_name}' is not permitted: {reason}",
		)


class ToolExecutionError(ToolError):
	category = "execution_error"
	error_source = "tool"


class ToolTimeoutError(ToolError):
	category = "timeout"
	uncertain = True
	termination_confirmed = False


class ToolCancelledError(ToolError):
	category = "cancelled"

	def __init__(self, message: str, *, uncertain: bool = False) -> None:
		super().__init__(message)
		self.uncertain = uncertain
		self.termination_confirmed = not uncertain


class ToolBudgetExceeded(ToolError):
	category = "budget_exceeded"


class ToolProviderError(ToolError):
	"""Provider/transport failure (including a future MCP client failure).

	``uncertain`` must be set when the transport failed after the request was
	delivered: the tool may have run even though no result was observed.
	"""

	category = "provider_failure"
	error_source = "provider"

	def __init__(
		self,
		message: str,
		*,
		safe_message: str | None = None,
		uncertain: bool = False,
	) -> None:
		super().__init__(message, safe_message=safe_message)
		self.uncertain = uncertain
		self.termination_confirmed = not uncertain

"""MCP ToolProvider adapter routed through the private worker manager job."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..core.tooling import ToolArguments, ToolContentBlock, ToolExecutionResult
from .definition import ToolDefinition
from .errors import ToolProviderError
from .mcp_errors import manager_error_message
from .provider import ToolCallContext


McpDispatch = Callable[[dict[str, Any], float, Callable[[], bool]], Mapping[str, Any]]


class McpToolProvider:
	"""Bind one server catalog to worker commands without adding policy logic."""

	def __init__(self, provider_id: str, dispatch: McpDispatch) -> None:
		self.provider_id = provider_id
		self._dispatch = dispatch

	def execute(
		self,
		definition: ToolDefinition,
		arguments: ToolArguments,
		context: ToolCallContext,
	) -> ToolExecutionResult:
		metadata = definition.metadata
		server_id = metadata.get("server_id")
		manager_session_id = metadata.get("manager_session_id")
		server_incarnation = metadata.get("server_incarnation")
		catalog_generation = metadata.get("catalog_generation")
		tool_name = definition.provider_tool_name
		if (
			not isinstance(server_id, str)
			or not server_id
			or not isinstance(manager_session_id, str)
			or not manager_session_id
			or isinstance(server_incarnation, bool)
			or not isinstance(server_incarnation, int)
			or isinstance(catalog_generation, bool)
			or not isinstance(catalog_generation, int)
			or not isinstance(tool_name, str)
			or not tool_name
		):
			raise ToolProviderError(
				"MCP tool binding is missing its server or catalog identity",
				safe_message="This external tool catalog is out of date. Refresh the MCP server tools.",
			)
		timeout = max(0.1, min(float(context.timeout_seconds or 30.0), 300.0))
		frame = {
			"type": "mcp_invoke",
			"server_id": server_id,
			"manager_session_id": manager_session_id,
			"server_incarnation": server_incarnation,
			"catalog_generation": catalog_generation,
			"tool_name": tool_name,
			"arguments": dict(arguments),
			"tool_call_id": context.tool_call_id,
			"timeout_ms": int(timeout * 1000),
			"timeout_seconds": timeout,
		}
		try:
			response = self._dispatch(frame, timeout, context.cancellation_requested)
		except ToolProviderError:
			raise
		except Exception as error:
			raise ToolProviderError(
				f"MCP worker request failed: {type(error).__name__}",
				safe_message="The external tool connection failed.",
				uncertain=True,
			) from error
		if not isinstance(response, Mapping) or response.get("success") is not True:
			uncertain = bool(response.get("uncertain", False)) if isinstance(response, Mapping) else True
			message = response.get("error_message") if isinstance(response, Mapping) else None
			category = response.get("error_code") if isinstance(response, Mapping) else None
			raise ToolProviderError(
				str(message or "MCP manager request failed"),
				safe_message=manager_error_message(
					category,
					fallback="The external tool connection failed.",
				),
				uncertain=uncertain,
			)
		reply = response.get("reply")
		if not isinstance(reply, Mapping):
			raise ToolProviderError("MCP manager returned a malformed reply", safe_message="The external tool returned an invalid response.", uncertain=True)
		if reply.get("ok") is not True:
			error = reply.get("error")
			category = error.get("category") if isinstance(error, Mapping) else "provider_failure"
			uncertain = bool(reply.get("uncertain", False))
			safe_message = (
				"This external tool catalog is out of date. Refresh the MCP server tools."
				if category in {"stale_catalog", "stale_server"}
				else manager_error_message(category, fallback="The external tool connection failed.")
			)
			raise ToolProviderError(
				f"MCP manager rejected invocation ({category})",
				safe_message=safe_message,
				uncertain=uncertain,
			)
		content_payload = reply.get("content", [])
		if not isinstance(content_payload, list) or any(not isinstance(block, Mapping) for block in content_payload):
			raise ToolProviderError("MCP manager returned malformed content", safe_message="The external tool returned an invalid response.", uncertain=True)
		content = tuple(_content_block(block) for block in content_payload)
		is_error = reply.get("is_error") is True
		return ToolExecutionResult(
			tool_name=context.tool_name,
			tool_call_id=context.tool_call_id,
			tool_id=context.tool_id,
			provider_id=self.provider_id,
			ok=not is_error,
			content=content,
			structured_content=reply.get("structured_content"),
			error_category="execution_error" if is_error else None,
			error_message="External tool returned an error" if is_error else None,
			error_source="tool" if is_error else None,
			uncertain=bool(reply.get("uncertain", False)),
			metadata={
				"server_id": server_id,
				"manager_session_id": manager_session_id,
				"server_incarnation": server_incarnation,
				"catalog_generation": catalog_generation,
				"manager_tool_name": tool_name,
			},
		)


def _content_block(payload: Mapping[str, Any]) -> ToolContentBlock:
	"""Map rmcp content blocks into the Assistant's bounded result vocabulary."""
	block = dict(payload)
	if "mime_type" not in block and isinstance(block.get("mimeType"), str):
		block["mime_type"] = block.pop("mimeType")
	return ToolContentBlock.from_dict(block)

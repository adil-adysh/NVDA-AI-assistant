"""User-facing messages for bounded MCP manager failure categories.

The manager deliberately hides transport detail.  Both worker-level failures
(``success: false`` with an ``error_code``) and manager replies (``ok: false``
with an error category) use the same category vocabulary, so the wording lives
here instead of being duplicated by each adapter.
"""
from __future__ import annotations

MANAGER_ERROR_GUIDANCE = {
	"launch_failed": "The MCP server program could not be started. Check its executable path.",
	"startup_timeout": "The MCP server did not finish starting in time.",
	"protocol_error": (
		"The MCP server did not complete the MCP handshake. Check that the program is an MCP "
		"server and that any required environment variables are available to it."
	),
	"connection_failed": "Could not connect to the MCP server. Check the URL, token and network.",
	"connection_error": "Could not connect to the MCP server. Check the URL, token and network.",
	"version_mismatch": "The MCP server uses a protocol version this client does not support.",
	"capacity": "Too many MCP operations are active. Wait a moment and try again.",
	"message_too_large": "The MCP server response is too large to accept.",
	"cancelled": "The MCP operation was cancelled.",
	"disconnected": "The MCP server disconnected.",
}


def manager_error_message(category: object, *, fallback: str) -> str:
	"""Return actionable text for a manager/worker failure category."""
	if isinstance(category, str):
		return MANAGER_ERROR_GUIDANCE.get(category, fallback)
	return fallback

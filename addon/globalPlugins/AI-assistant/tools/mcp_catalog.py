"""Reconcile worker MCP catalogs into the Assistant's canonical tool registry."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
import logging
import copy
import threading
from typing import Any

from ..config.mcp_servers import McpServerConfig
from .definition import ToolDefinition
from .errors import ToolProviderError
from .mcp_errors import manager_error_message
from .mcp_provider import McpDispatch, McpToolProvider
from .registry import ToolRegistry

logger = logging.getLogger(__name__)

_DRAFT_7_URI = "http://json-schema.org/draft-07/schema#"
_DRAFT_7_UNTRANSLATED_ASSERTIONS = frozenset({
	"$ref", "additionalItems", "dependencies", "exclusiveMaximum", "exclusiveMinimum",
	"dependentRequired", "dependentSchemas", "maxContains", "minContains", "prefixItems",
})


class McpCatalogService:
	"""Own per-server catalog refresh, identity, and registry publication."""

	def __init__(
		self,
		registry: ToolRegistry,
		dispatch: McpDispatch,
		*,
		credential_resolver: Callable[[str], str] | None = None,
	) -> None:
		self._registry = registry
		self._dispatch = dispatch
		self._credential_resolver = credential_resolver or (lambda _reference: "")
		self._connected_servers: set[str] = set()
		self._state_lock = threading.RLock()
		self._closed = False
		self._event_stop = threading.Event()
		self._event_thread: threading.Thread | None = None
		self._refreshing_servers: set[str] = set()
		self._refresh_pending_servers: set[str] = set()
		self._server_revisions: dict[str, int] = {}
		self._blocked_servers: set[str] = set()
		self._refresh_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="McpCatalogRefresh")

	def is_connected(self, server_id: str) -> bool:
		with self._state_lock:
			return server_id in self._connected_servers

	def close(self) -> None:
		"""Fence and join the event poller before the private worker shuts down."""
		with self._state_lock:
			self._closed = True
		self._event_stop.set()
		thread = self._event_thread
		if thread is not None and thread is not threading.current_thread():
			thread.join(timeout=1.0)
		with self._state_lock:
			self._refresh_pending_servers.clear()
		self._refresh_pool.shutdown(wait=False, cancel_futures=True)

	@staticmethod
	def provider_id(server_id: str) -> str:
		if not isinstance(server_id, str) or not server_id.strip():
			raise ValueError("MCP server ID is required")
		return f"mcp:{server_id}"

	def connect_stdio(
		self,
		server_id: str,
		executable: str,
		args: Sequence[str] = (),
		env: Mapping[str, str] | None = None,
		*,
		timeout: float = 20.0,
	) -> tuple[ToolDefinition, ...]:
		return self._connect({
			"type": "mcp_connect_stdio",
			"server_id": server_id,
			"executable": executable,
			"args": list(args),
			"env": dict(env or {}),
		}, timeout=timeout)

	def connect_http(
		self,
		server_id: str,
		url: str,
		*,
		auth_token: str = "",
		timeout: float = 20.0,
	) -> tuple[ToolDefinition, ...]:
		return self._connect({
			"type": "mcp_connect_http",
			"server_id": server_id,
			"url": url,
			"auth_token": auth_token,
		}, timeout=timeout)

	def connect_config(self, server: McpServerConfig, *, timeout: float = 20.0) -> tuple[ToolDefinition, ...]:
		"""Connect one already-validated user configuration record."""
		if not isinstance(server, McpServerConfig):
			to_dict = getattr(server, "to_dict", None)
			if not callable(to_dict):
				raise TypeError("server must be an McpServerConfig")
			server = McpServerConfig.from_dict(to_dict())
		if not server.enabled:
			self._registry.set_provider_available(self.provider_id(server.server_id), False)
			return ()
		if server.transport == "stdio":
			return self.connect_stdio(
				server.server_id, server.command, server.args, timeout=timeout,
			)
		if server.transport == "streamable_http":
			auth_token = self._credential_resolver(server.credential_ref) if server.credential_ref else ""
			return self.connect_http(server.server_id, server.url, auth_token=auth_token, timeout=timeout)
		raise ValueError("Unsupported MCP transport")

	def _connect(self, command: dict[str, Any], *, timeout: float) -> tuple[ToolDefinition, ...]:
		self._ensure_open()
		provider_id = self.provider_id(command["server_id"])
		with self._state_lock:
			revision = self._server_revisions.get(command["server_id"], 0) + 1
			self._server_revisions[command["server_id"]] = revision
			self._blocked_servers.add(command["server_id"])
			self._connected_servers.discard(command["server_id"])
			self._registry.set_provider_available(provider_id, False)
		response = self._dispatch(command, timeout, lambda: False)
		self._require_manager_success(response)
		try:
			definitions = self.refresh(command["server_id"], timeout=timeout, _revision=revision, _allow_blocked=True)
		except Exception:
			self._registry.set_provider_available(self.provider_id(command["server_id"]), False)
			try:
				self._dispatch({"type": "mcp_disconnect", "server_id": command["server_id"]}, min(timeout, 5.0), lambda: False)
			except Exception:
				pass
			raise
		with self._state_lock:
			if self._closed or self._server_revisions.get(command["server_id"], 0) != revision:
				raise ToolProviderError("MCP connection changed during catalog discovery", safe_message="The external tool connection changed. Reconnect before using its tools.")
			self._blocked_servers.discard(command["server_id"])
			self._registry.set_provider_available(self.provider_id(command["server_id"]), True)
			self._connected_servers.add(command["server_id"])
		self._start_event_poller()
		return definitions

	def refresh(
		self,
		server_id: str,
		*,
		timeout: float = 20.0,
		_revision: int | None = None,
		_allow_blocked: bool = False,
	) -> tuple[ToolDefinition, ...]:
		self._ensure_open()
		provider_id = self.provider_id(server_id)
		with self._state_lock:
			revision = self._server_revisions.get(server_id, 0) if _revision is None else _revision
			if server_id in self._blocked_servers and not _allow_blocked:
				raise ToolProviderError("MCP server is disconnected", safe_message="Reconnect the MCP server before refreshing its tools.")
		response = None
		for attempt in range(3):
			response = self._dispatch({"type": "mcp_list_tools", "server_id": server_id}, timeout, self._event_stop.is_set)
			reply = response.get("reply") if isinstance(response, Mapping) else None
			error = reply.get("error") if isinstance(reply, Mapping) else None
			if not (isinstance(error, Mapping) and error.get("category") == "stale_catalog"):
				break
		else:
			raise ToolProviderError("MCP catalog changed during each bounded refresh attempt", safe_message="The external tool catalog is changing. Try refreshing again.")
		assert response is not None
		reply = self._require_manager_success(response)
		if reply.get("server_id") != server_id:
			raise ToolProviderError("MCP manager returned a mismatched server identity", safe_message="The external tool catalog could not be verified.")
		server_incarnation = reply.get("server_incarnation")
		manager_session_id = reply.get("manager_session_id")
		catalog_generation = reply.get("catalog_generation")
		tools = reply.get("tools")
		if (
			isinstance(server_incarnation, bool)
			or not isinstance(server_incarnation, int)
			or not isinstance(manager_session_id, str)
			or not manager_session_id
			or isinstance(catalog_generation, bool)
			or not isinstance(catalog_generation, int)
			or not isinstance(tools, list)
			or any(not isinstance(tool, Mapping) for tool in tools)
		):
			raise ToolProviderError("MCP manager returned an invalid catalog", safe_message="The external tool catalog could not be verified.")
		definitions = tuple(
			self._tool_definition(
				tool,
				provider_id=provider_id,
				server_id=server_id,
				server_incarnation=server_incarnation,
				manager_session_id=manager_session_id,
				catalog_generation=catalog_generation,
			)
			for tool in tools
		)
		backend = McpToolProvider(provider_id, self._dispatch)
		with self._state_lock:
			if (
				self._closed
				or self._server_revisions.get(server_id, 0) != revision
				or (server_id in self._blocked_servers and not _allow_blocked)
			):
				raise ToolProviderError("MCP catalog changed during refresh", safe_message="The external tool connection changed. Refresh its tools again.")
			return self._registry.replace_provider_catalog(provider_id, definitions, backend=backend)

	def disconnect(self, server_id: str, *, timeout: float = 5.0) -> None:
		self._ensure_open()
		provider_id = self.provider_id(server_id)
		with self._state_lock:
			self._server_revisions[server_id] = self._server_revisions.get(server_id, 0) + 1
			self._blocked_servers.add(server_id)
			self._connected_servers.discard(server_id)
			self._refresh_pending_servers.discard(server_id)
			self._registry.set_provider_available(provider_id, False)
		response = self._dispatch({"type": "mcp_disconnect", "server_id": server_id}, timeout, lambda: False)
		self._require_manager_success(response)
		self._registry.unregister_provider(provider_id)

	def refresh_connected(self, server_id: str, *, timeout: float = 10.0) -> tuple[ToolDefinition, ...]:
		"""Refresh a connected server and re-enable only its verified catalog."""
		with self._state_lock:
			if server_id not in self._connected_servers or server_id in self._blocked_servers:
				raise ToolProviderError("MCP server is not connected", safe_message="Connect the MCP server before refreshing its tools.")
			revision = self._server_revisions.get(server_id, 0)
		definitions = self.refresh(server_id, timeout=timeout, _revision=revision)
		with self._state_lock:
			if (
				self._closed
				or self._server_revisions.get(server_id, 0) != revision
				or server_id not in self._connected_servers
				or server_id in self._blocked_servers
			):
				raise ToolProviderError("MCP server disconnected during refresh", safe_message="The MCP server disconnected while its tools were refreshing.")
			self._registry.set_provider_available(self.provider_id(server_id), True)
		return definitions

	def _start_event_poller(self) -> None:
		with self._state_lock:
			if self._closed:
				return
			if self._event_thread is not None and self._event_thread.is_alive():
				return
			self._event_stop.clear()
			self._event_thread = threading.Thread(
				target=self._poll_manager_events,
				name="McpCatalogEvents",
				daemon=True,
			)
			self._event_thread.start()

	def _poll_manager_events(self) -> None:
		while not self._event_stop.is_set():
			try:
				response = self._dispatch({"type": "mcp_poll_events"}, 3.0, self._event_stop.is_set)
				reply = self._require_manager_success(response)
				if reply.get("manager_state") == "stopped":
					self._retire_all_servers()
				elif isinstance(reply.get("events"), list):
					for event in reply["events"]:
						if isinstance(event, Mapping):
							self._handle_manager_event(event)
			except Exception:
				logger.warning("MCP event poll failed; retaining current catalog state", exc_info=True)
			self._event_stop.wait(0.5)

	def _handle_manager_event(self, event: Mapping[str, Any]) -> None:
		kind = event.get("event")
		if kind == "resync_required":
			self._resynchronize()
		elif kind == "tool_list_changed":
			server_id = event.get("server_id")
			if isinstance(server_id, str) and server_id:
				self._schedule_refresh(server_id)
		elif kind in {"notification_stream_failed", "notification_stream_closed"}:
			# A dead notification stream means the set of missed changes is unknown.
			# Reconcile against manager status, then refresh every surviving server.
			self._resynchronize()

	def _resynchronize(self) -> None:
		response = self._dispatch({"type": "mcp_manager_status"}, 5.0, lambda: False)
		reply = self._require_manager_success(response)
		servers = reply.get("servers")
		if not isinstance(servers, list):
			raise ToolProviderError("MCP status omitted server list", safe_message="MCP server status could not be refreshed.")
		active = {
			item.get("server_id") for item in servers
			if isinstance(item, Mapping) and item.get("connected") is True and isinstance(item.get("server_id"), str)
		}
		with self._state_lock:
			previous = set(self._connected_servers)
			missing = previous - active
			for server_id in missing:
				self._server_revisions[server_id] = self._server_revisions.get(server_id, 0) + 1
				self._blocked_servers.add(server_id)
				self._refresh_pending_servers.discard(server_id)
			self._connected_servers.difference_update(missing)
			for server_id in active:
				if server_id not in self._blocked_servers:
					self._connected_servers.add(server_id)
		for server_id in previous - active:
			provider_id = self.provider_id(server_id)
			self._registry.set_provider_available(provider_id, False)
			self._registry.unregister_provider(provider_id)
		for server_id in active:
			self._schedule_refresh(server_id)

	def _schedule_refresh(self, server_id: str) -> None:
		with self._state_lock:
			if (self._closed or self._event_stop.is_set() or server_id in self._blocked_servers
					or server_id not in self._connected_servers):
				return
			if server_id in self._refreshing_servers:
				self._refresh_pending_servers.add(server_id)
				return
			self._refreshing_servers.add(server_id)
			revision = self._server_revisions.get(server_id, 0)
			try:
				self._refresh_pool.submit(self._run_scheduled_refresh, server_id, revision)
			except RuntimeError:
				self._refreshing_servers.discard(server_id)

	def _run_scheduled_refresh(self, server_id: str, revision: int) -> None:
			try:
				self.refresh(server_id, timeout=5.0, _revision=revision)
				with self._state_lock:
					if (not self._closed and self._server_revisions.get(server_id, 0) == revision
							and server_id in self._connected_servers and server_id not in self._blocked_servers):
						self._registry.set_provider_available(self.provider_id(server_id), True)
			except Exception:
				logger.warning("Could not refresh MCP catalog for server %s", server_id, exc_info=True)
			finally:
				with self._state_lock:
					self._refreshing_servers.discard(server_id)
					follow_up = server_id in self._refresh_pending_servers
					self._refresh_pending_servers.discard(server_id)
					if follow_up and not self._closed and not self._event_stop.is_set() \
							and server_id in self._connected_servers and server_id not in self._blocked_servers:
						self._refreshing_servers.add(server_id)
						next_revision = self._server_revisions.get(server_id, 0)
						try:
							self._refresh_pool.submit(self._run_scheduled_refresh, server_id, next_revision)
						except RuntimeError:
							self._refreshing_servers.discard(server_id)

	def _retire_all_servers(self) -> None:
		with self._state_lock:
			servers = tuple(self._connected_servers)
			for server_id in servers:
				self._server_revisions[server_id] = self._server_revisions.get(server_id, 0) + 1
				self._blocked_servers.add(server_id)
				self._refresh_pending_servers.discard(server_id)
			self._connected_servers.clear()
		for server_id in servers:
			provider_id = self.provider_id(server_id)
			self._registry.set_provider_available(provider_id, False)
			self._registry.unregister_provider(provider_id)

	def _ensure_open(self) -> None:
		with self._state_lock:
			if self._closed:
				raise ToolProviderError(
					"MCP catalog service is closed",
					safe_message="The external tool service is shutting down.",
				)

	@staticmethod
	def _tool_definition(
		payload: Mapping[str, Any],
		*,
		provider_id: str,
		server_id: str,
		server_incarnation: int,
		manager_session_id: str,
		catalog_generation: int,
	) -> ToolDefinition:
		normalized = dict(payload)
		for schema_field in ("inputSchema", "outputSchema", "input_schema", "output_schema"):
			if schema_field in normalized:
				normalized[schema_field] = _normalize_mcp_schema(normalized[schema_field], schema_field)
		metadata = normalized.get("metadata")
		if not isinstance(metadata, Mapping):
			metadata = normalized.get("_meta")
		metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
		metadata.update({
			"server_id": server_id,
			"server_incarnation": server_incarnation,
			"manager_session_id": manager_session_id,
			"catalog_generation": catalog_generation,
		})
		normalized["metadata"] = metadata
		return ToolDefinition.from_provider_payload(normalized, provider_id=provider_id)

	@staticmethod
	def _require_manager_success(response: Mapping[str, Any]) -> Mapping[str, Any]:
		if response.get("success") is not True:
			# The worker reports its own manager failures with ``error_code``
			# rather than a reply envelope.  Surface the same actionable text
			# used for manager replies instead of a generic connection error.
			raise ToolProviderError(
				str(response.get("error_message") or "MCP manager request failed"),
				safe_message=manager_error_message(
					response.get("error_code"),
					fallback="The external tool connection failed.",
				),
				uncertain=bool(response.get("uncertain", False)),
			)
		reply = response.get("reply")
		if not isinstance(reply, Mapping) or reply.get("ok") is not True:
			error = reply.get("error") if isinstance(reply, Mapping) else None
			category = error.get("category") if isinstance(error, Mapping) else "invalid_reply"
			raise ToolProviderError(
				f"MCP manager rejected catalog operation ({category})",
				safe_message=manager_error_message(
					category,
					fallback="The external tool connection or catalog could not be updated.",
				),
				uncertain=bool(reply.get("uncertain", False)) if isinstance(reply, Mapping) else True,
			)
		return reply


def _normalize_mcp_schema(value: Any, field: str) -> Any:
	"""Accept Draft 7 schemas only when their assertions match our supported profile.

	The core tool validator intentionally rejects legacy dialects. MCP peers such
	as NVDA MCP Bridge commonly emit Draft 7; this adapter removes that dialect
	marker only after rejecting known Draft 7 assertions whose semantics differ
	or are not implemented by the core validator. Shared keywords remain intact.
	"""
	if not isinstance(value, Mapping):
		return value
	result = copy.deepcopy(dict(value))
	dialect = result.get("$schema")
	if dialect != _DRAFT_7_URI:
		def reject_nested_dialect(node: Any, path: str, *, root: bool = False) -> None:
			if isinstance(node, Mapping):
				for key, child in node.items():
					if key == "$schema" and not root:
						raise ToolProviderError(
							f"MCP {field} declares a nested schema dialect",
							safe_message=f"The external tool schema declares an unsupported nested dialect at {path}.",
						)
					reject_nested_dialect(child, f"{path}.{key}")
			elif isinstance(node, list):
				for index, child in enumerate(node):
					reject_nested_dialect(child, f"{path}[{index}]")
		reject_nested_dialect(result, field, root=True)
		return result

	def inspect(node: Any, path: str) -> None:
		if isinstance(node, Mapping):
			for key, child in node.items():
				if key in _DRAFT_7_UNTRANSLATED_ASSERTIONS:
					raise ToolProviderError(
						f"MCP {field} uses Draft 7 keyword {key!r} whose semantics are not mapped",
						safe_message=f"The external tool schema uses unsupported Draft 7 validation at {path}.{key}.",
					)
				if key == "items" and isinstance(child, list):
					raise ToolProviderError(
						f"MCP {field} uses Draft 7 tuple validation",
						safe_message=f"The external tool schema uses unsupported Draft 7 tuple validation at {path}.items.",
					)
				if key == "$schema" and child != _DRAFT_7_URI:
					raise ToolProviderError(
						f"MCP {field} contains a conflicting nested schema dialect",
						safe_message=f"The external tool schema contains an unsupported nested dialect at {path}.",
					)
				inspect(child, f"{path}.{key}")
		elif isinstance(node, list):
			for index, child in enumerate(node):
				inspect(child, f"{path}[{index}]")

	inspect(result, field)
	def strip_dialect(node: Any) -> None:
		if isinstance(node, dict):
			node.pop("$schema", None)
			for child in node.values():
				strip_dialect(child)
		elif isinstance(node, list):
			for child in node:
				strip_dialect(child)
	strip_dialect(result)
	return result

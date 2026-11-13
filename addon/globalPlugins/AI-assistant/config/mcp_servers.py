"""Validated, non-secret configuration records for external MCP servers."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

_SERVER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_NAME_LENGTH = 128
MAX_COMMAND_LENGTH = 2048
MAX_ARGUMENTS = 64
MAX_ARGUMENT_LENGTH = 4096
MAX_URL_LENGTH = 2048


@dataclass(frozen=True, slots=True)
class McpServerConfig:
	"""Configuration accepted only from explicit user settings.

	Credentials and environment values are intentionally excluded from this
	serializable record; they must be resolved through a protected credential
	store before transport support is enabled.
	"""

	server_id: str
	name: str
	transport: str
	enabled: bool
	command: str = ""
	args: tuple[str, ...] = ()
	url: str = ""
	credential_ref: str | None = None

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "McpServerConfig":
		if not isinstance(value, Mapping):
			raise ValueError("MCP server configuration must be an object")
		allowed = {"server_id", "name", "transport", "enabled", "command", "args", "url", "credential_ref"}
		unknown = set(value) - allowed
		if unknown:
			raise ValueError("Unsupported MCP server configuration fields: " + ", ".join(sorted(map(str, unknown))))
		server_id = value.get("server_id")
		if not isinstance(server_id, str) or not _SERVER_ID.fullmatch(server_id):
			raise ValueError("MCP server_id must be 1 to 64 safe letters, digits, dots, underscores or hyphens")
		name = value.get("name", server_id)
		if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME_LENGTH:
			raise ValueError("MCP server name must be non-empty and at most 128 characters")
		transport = value.get("transport")
		if transport not in {"stdio", "streamable_http"}:
			raise ValueError("MCP transport must be 'stdio' or 'streamable_http'")
		enabled = value.get("enabled", True)
		if not isinstance(enabled, bool):
			raise ValueError("MCP server enabled flag must be boolean")
		credential_ref = value.get("credential_ref")
		if credential_ref is not None and (
			transport != "streamable_http"
			or not isinstance(credential_ref, str)
			or credential_ref != server_id
		):
			raise ValueError("MCP credential reference must match the server ID and use Streamable HTTP")
		if transport == "stdio":
			command = value.get("command")
			args = value.get("args", [])
			if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND_LENGTH:
				raise ValueError("stdio MCP command must be non-empty and at most 2048 characters")
			if not isinstance(args, list) or len(args) > MAX_ARGUMENTS or any(
				not isinstance(arg, str) or len(arg) > MAX_ARGUMENT_LENGTH for arg in args
			):
				raise ValueError("stdio MCP args must contain at most 64 strings of at most 4096 characters")
			return cls(server_id, name.strip(), transport, enabled, command.strip(), tuple(args))
		url = value.get("url")
		if not isinstance(url, str):
			raise ValueError("Streamable HTTP MCP URL must be a string")
		_validate_http_url(url)
		return cls(server_id, name.strip(), transport, enabled, url=url, credential_ref=credential_ref)

	def to_dict(self) -> dict[str, Any]:
		if self.transport == "stdio":
			return {
				"server_id": self.server_id,
				"name": self.name,
				"transport": self.transport,
				"enabled": self.enabled,
				"command": self.command,
				"args": list(self.args),
			}
		return {
			"server_id": self.server_id,
			"name": self.name,
			"transport": self.transport,
			"enabled": self.enabled,
			"url": self.url,
			**({"credential_ref": self.credential_ref} if self.credential_ref else {}),
		}


def _validate_http_url(value: str) -> None:
	if not value or len(value) > MAX_URL_LENGTH:
		raise ValueError("Streamable HTTP MCP URL must be non-empty and at most 2048 characters")
	try:
		parsed = urlsplit(value)
		host = parsed.hostname
		port = parsed.port
	except ValueError as error:
		raise ValueError("Streamable HTTP MCP URL is malformed") from error
	if parsed.scheme not in {"http", "https"} or not host or parsed.username is not None or parsed.password is not None:
		raise ValueError("MCP URL must use HTTPS or unauthenticated HTTP to a loopback host")
	if parsed.fragment:
		raise ValueError("MCP URL must not contain a fragment")
	if parsed.query:
		raise ValueError("MCP URL must not contain query parameters; configure credentials separately")
	if parsed.scheme == "http":
		is_loopback = host.casefold() == "localhost"
		if not is_loopback:
			try:
				is_loopback = ipaddress.ip_address(host).is_loopback
			except ValueError:
				is_loopback = False
		if not is_loopback:
			raise ValueError("Plain HTTP MCP endpoints must use localhost or a loopback IP address")
	if port is not None and not 1 <= port <= 65535:
		raise ValueError("MCP URL port must be between 1 and 65535")

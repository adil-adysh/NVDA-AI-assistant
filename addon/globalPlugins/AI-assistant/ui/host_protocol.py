# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict
from uuid import uuid4

try:
	from .host_protocol_constants import (
		COMMAND_REQUIRED_FIELD_TYPES,
		COMMAND_REQUIRED_FIELDS,
		COMMAND_NAMES,
		COMMAND_CHAT_APPEND,
		COMMAND_CHAT_SET_HISTORY,
		COMMAND_CHAT_STREAM_ABORT,
		COMMAND_CHAT_STREAM_BEGIN,
		COMMAND_CHAT_STREAM_DELTA,
		COMMAND_CHAT_STREAM_END,
		COMMAND_CHAT_UPDATE,
		EVENT_CHAT_ATTACHMENT_ADDED,
		EVENT_CHAT_CLOSED,
		EVENT_CHAT_SUBMITTED,
		EVENT_CLOSE_HOST,
		EVENT_MODEL_SELECTED,
		EVENT_PROVIDER_SELECTED,
		EVENT_THINK_MODE_TOGGLED,
		EVENT_UI_ACTION_INVOKED,
		EVENT_WINDOW_CLOSED,
	)
except ImportError:
	from host_protocol_constants import (  # type: ignore[no-redef]
		COMMAND_REQUIRED_FIELD_TYPES,
		COMMAND_REQUIRED_FIELDS,
		COMMAND_NAMES,
		COMMAND_CHAT_APPEND,
		COMMAND_CHAT_SET_HISTORY,
		COMMAND_CHAT_STREAM_ABORT,
		COMMAND_CHAT_STREAM_BEGIN,
		COMMAND_CHAT_STREAM_DELTA,
		COMMAND_CHAT_STREAM_END,
		COMMAND_CHAT_UPDATE,
		EVENT_CHAT_ATTACHMENT_ADDED,
		EVENT_CHAT_CLOSED,
		EVENT_CHAT_SUBMITTED,
		EVENT_CLOSE_HOST,
		EVENT_MODEL_SELECTED,
		EVENT_PROVIDER_SELECTED,
		EVENT_THINK_MODE_TOGGLED,
		EVENT_UI_ACTION_INVOKED,
		EVENT_WINDOW_CLOSED,
	)

# Re-exported for backward compatibility (consumers import from host_protocol).
__all__ = [
	"COMMAND_CHAT_APPEND",
	"COMMAND_CHAT_SET_HISTORY",
	"COMMAND_CHAT_STREAM_ABORT",
	"COMMAND_CHAT_STREAM_BEGIN",
	"COMMAND_CHAT_STREAM_DELTA",
	"COMMAND_CHAT_STREAM_END",
	"COMMAND_CHAT_UPDATE",
	"COMMAND_NAMES",
	"COMMAND_REQUIRED_FIELD_TYPES",
	"COMMAND_REQUIRED_FIELDS",
	"EVENT_CHAT_ATTACHMENT_ADDED",
	"EVENT_CHAT_CLOSED",
	"EVENT_CHAT_SUBMITTED",
	"EVENT_CLOSE_HOST",
	"EVENT_MODEL_SELECTED",
	"EVENT_PROVIDER_SELECTED",
	"EVENT_THINK_MODE_TOGGLED",
	"EVENT_UI_ACTION_INVOKED",
	"EVENT_WINDOW_CLOSED",
	"HostCommand",
	"HostCommandPayload",
	"HostEvent",
	"HostResponse",
	"HostUnavailableError",
]

COMMAND_TYPE = "command"
EVENT_TYPE = "event"
ACK_TYPE = "ack"
ERROR_TYPE = "error"
SCHEMA = "nvda.ui_host"
PROTOCOL_VERSION = 2
SOURCE_NVDA_ADDON = "nvda_addon"
def _matches_payload_type(value: Any, expected_type: str) -> bool:
	if expected_type == "string":
		return isinstance(value, str)
	if expected_type == "integer":
		return isinstance(value, int) and not isinstance(value, bool)
	if expected_type == "boolean":
		return isinstance(value, bool)
	if expected_type == "array":
		return isinstance(value, list)
	if expected_type == "object":
		return isinstance(value, dict)
	if expected_type == "json":
		return True
	return False


class HostCommandPayload(TypedDict, total=False):
	name: str
	payload: dict[str, Any]


class HostUnavailableError(Exception):
	"""Raised when the UI host is unavailable or cannot be reached."""


@dataclass(frozen=True, slots=True)
class HostCommand:
	name: str
	payload: dict[str, Any] = field(default_factory=dict)
	id: str = field(default_factory=lambda: str(uuid4()))
	correlation_id: str | None = None
	schema: str = field(default=SCHEMA, init=False)
	protocol_version: int = field(default=PROTOCOL_VERSION, init=False)
	source: str = field(default=SOURCE_NVDA_ADDON, init=False)
	type: str = field(default=COMMAND_TYPE, init=False)

	def __post_init__(self) -> None:
		if self.name not in COMMAND_NAMES:
			raise ValueError(f"Unsupported host command: {self.name}")
		if not isinstance(self.payload, dict):
			raise ValueError("HostCommand payload must be an object")
		missing = tuple(field for field in COMMAND_REQUIRED_FIELDS[self.name] if field not in self.payload)
		if missing:
			raise ValueError(f"HostCommand {self.name} is missing required fields: {', '.join(missing)}")
		invalid = tuple(
			(field, expected_type)
			for field, expected_type in COMMAND_REQUIRED_FIELD_TYPES[self.name].items()
			if not _matches_payload_type(self.payload[field], expected_type)
		)
		if invalid:
			details = ", ".join(f"{field} (expected {expected_type})" for field, expected_type in invalid)
			raise ValueError(f"HostCommand {self.name} has invalid field types: {details}")

	def to_json(self) -> str:
		return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

	def to_bytes(self) -> bytes:
		return f"{self.to_json()}\n".encode("utf-8")

	def to_dict(self) -> dict[str, Any]:
		return {
			"schema": self.schema,
			"version": self.protocol_version,
			"id": self.id,
			"correlation_id": self.correlation_id,
			"source": self.source,
			"type": self.type,
			"command": {
				"name": self.name,
				"payload": self.payload,
			},
		}

	@classmethod
	def from_json(cls, value: str) -> "HostCommand":
		data = json.loads(value)
		if not isinstance(data, dict):
			raise ValueError("HostCommand must be a JSON object")
		if data.get("schema") != SCHEMA:
			raise ValueError(f"Invalid HostCommand schema: {data.get('schema')}")
		if data.get("type") != COMMAND_TYPE:
			raise ValueError(f"Invalid HostCommand type: {data.get('type')}")
		protocol_version = data.get("version")
		if protocol_version != PROTOCOL_VERSION:
			raise ValueError(f"Unsupported HostCommand protocol_version: {protocol_version}")
		if not isinstance(data.get("id"), str) or not data["id"].strip():
			raise ValueError("HostCommand must contain a non-empty id")
		command = data.get("command") or {}
		if not isinstance(command, dict) or not isinstance(command.get("name"), str):
			raise ValueError("HostCommand command must contain a string name")
		payload = command.get("payload", {})
		if not isinstance(payload, dict):
			raise ValueError("HostCommand payload must be an object")
		return cls(
			name=command["name"],
			payload=payload,
			id=data["id"],
			correlation_id=data.get("correlation_id"),
		)


@dataclass(frozen=True, slots=True)
class HostResponse:
	request_id: str
	status: Literal["ack", "nack"]
	message: str | None = None
	type: str = field(default=ACK_TYPE, init=False)
	stage: str | None = None

	def to_json(self) -> str:
		payload = {
			"schema": SCHEMA,
			"version": PROTOCOL_VERSION,
			"id": str(uuid4()),
			"correlation_id": self.request_id,
			"source": "ui_host",
			"type": self.type,
		}
		if self.status == "ack":
			payload.update({"acked_id": self.request_id, "stage": self.stage or "accepted", "detail": self.message})
		else:
			payload.update({"failed_id": self.request_id, "code": "internal_error", "detail": self.message or "error", "retriable": False})
		return json.dumps(payload, ensure_ascii=False, default=str)

	@classmethod
	def from_json(cls, value: str, expected_request_id: str | None = None) -> "HostResponse":
		data = json.loads(value)
		if not isinstance(data, dict):
			raise ValueError("HostResponse must be a JSON object")
		if data.get("schema") != SCHEMA:
			raise ValueError(f"Invalid HostResponse schema: {data.get('schema')}")
		if data.get("version") != PROTOCOL_VERSION:
			raise ValueError(f"Unsupported HostResponse protocol version: {data.get('version')}")
		type_value = data.get("type")
		if type_value == ACK_TYPE:
			request_id = data.get("acked_id")
			if not isinstance(request_id, str) or not request_id.strip():
				raise ValueError("V2 ACK is missing acked_id")
			if expected_request_id is not None and request_id != expected_request_id:
				raise ValueError(
					f"Host response correlation mismatch: expected {expected_request_id}, got {request_id}"
				)
			return cls(request_id=request_id, status="ack", message=data.get("detail"), stage=data.get("stage"))
		if type_value == ERROR_TYPE:
			request_id = data.get("failed_id") or data.get("correlation_id") or ""
			if expected_request_id is not None and request_id not in {"", expected_request_id}:
				raise ValueError(
					f"Host response correlation mismatch: expected {expected_request_id}, got {request_id}"
				)
			return cls(request_id=request_id, status="nack", message=data.get("detail"), stage=None)
		raise ValueError(f"Invalid v2 HostResponse type: {type_value}")


@dataclass(frozen=True, slots=True)
class HostEvent:
	event: str
	payload: dict[str, Any]
	id: str = field(default_factory=lambda: str(uuid4()))
	correlation_id: str | None = None
	schema: str = field(default=SCHEMA, init=False)
	protocol_version: int = field(default=PROTOCOL_VERSION, init=False)
	source: str = field(default=SOURCE_NVDA_ADDON, init=False)
	type: str = field(default=EVENT_TYPE, init=False)

	def to_dict(self) -> dict[str, Any]:
		return {
			"schema": self.schema,
			"version": self.protocol_version,
			"id": self.id,
			"correlation_id": self.correlation_id,
			"source": self.source,
			"type": self.type,
			"event": {
				"name": self.event,
				"payload": self.payload,
			},
		}

	def to_json(self) -> str:
		return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

	@classmethod
	def from_json(cls, value: str) -> "HostEvent":
		data = json.loads(value)
		if not isinstance(data, dict):
			raise ValueError("HostEvent must be a JSON object")
		if data.get("schema") != SCHEMA:
			raise ValueError(f"Invalid HostEvent schema: {data.get('schema')}")
		if data.get("type") != EVENT_TYPE:
			raise ValueError(f"Invalid HostEvent type: {data.get('type')}")
		protocol_version = data.get("version")
		if protocol_version != PROTOCOL_VERSION:
			raise ValueError(f"Unsupported HostEvent protocol_version: {protocol_version}")
		if not isinstance(data.get("id"), str) or not data["id"].strip():
			raise ValueError("HostEvent must contain a non-empty id")
		event = data.get("event") or {}
		if not isinstance(event, dict) or "name" not in event:
			raise ValueError("Invalid HostEvent event object")
		payload = event.get("payload", {})
		if not isinstance(payload, dict):
			payload = {}
		return cls(
			event=event["name"],
			payload=payload,
			id=data["id"],
			correlation_id=data.get("correlation_id"),
		)

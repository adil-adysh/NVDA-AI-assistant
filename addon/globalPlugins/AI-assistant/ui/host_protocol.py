# -*- coding: utf-8 -*-
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

COMMAND_TYPE = "command"
RESPONSE_TYPE = "response"
EVENT_TYPE = "event"
ACK_TYPE = "ack"
ERROR_TYPE = "error"
SCHEMA = "nvda.ui_host"
PROTOCOL_VERSION = 2
SOURCE_NVDA_ADDON = "nvda_addon"
VALID_RESPONSE_STATUSES = {"ack", "nack"}


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

	def to_json(self) -> str:
		return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

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
		if data.get("schema") != SCHEMA:
			raise ValueError(f"Invalid HostCommand schema: {data.get('schema')}")
		if data.get("type") != COMMAND_TYPE:
			raise ValueError(f"Invalid HostCommand type: {data.get('type')}")
		protocol_version = data.get("version", PROTOCOL_VERSION)
		if protocol_version != PROTOCOL_VERSION:
			raise ValueError(f"Unsupported HostCommand protocol_version: {protocol_version}")
		command = data.get("command") or {}
		return cls(
			name=command["name"],
			payload=command.get("payload", {}),
			id=data.get("id", str(uuid4())),
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
	def from_json(cls, value: str) -> "HostResponse":
		data = json.loads(value)
		if data.get("schema") == SCHEMA:
			type_value = data.get("type")
			if type_value == ACK_TYPE:
				return cls(
					request_id=data["acked_id"],
					status="ack",
					message=data.get("detail"),
					stage=data.get("stage"),
				)
			if type_value == ERROR_TYPE:
				return cls(
					request_id=data.get("failed_id") or data.get("correlation_id") or "",
					status="nack",
					message=data.get("detail"),
					stage=None,
				)
			raise ValueError(f"Invalid v2 HostResponse type: {type_value}")
		type_value = data.get("type")
		if type_value != RESPONSE_TYPE:
			raise ValueError(f"Invalid HostResponse type: {type_value}")
		status_value = data.get("status")
		if status_value not in VALID_RESPONSE_STATUSES:
			raise ValueError(f"Invalid HostResponse status: {status_value}")
		return cls(
			request_id=data["request_id"],
			status=status_value,
			message=data.get("message"),
		)


@dataclass(frozen=True, slots=True)
class HostEvent:
	event: str
	payload: dict[str, Any]
	request_id: str | None = None
	type: str = field(default=EVENT_TYPE, init=False)

	def to_json(self) -> str:
		return json.dumps(
			dataclasses.asdict(self),
			ensure_ascii=False,
			default=str,
		)

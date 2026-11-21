"""Privacy-safe lifecycle events for diagnosing asynchronous behavior."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import time
from typing import Any
import uuid


_EVENT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_OPERATION_ID_RE = re.compile(r"^[a-fA-F0-9]{32}$")
_TASK_RE = re.compile(r"^[A-Za-z0-9 _.-]{1,80}$")
_ERROR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{0,79}$")
_NUMERIC_ATTRIBUTES = {"duration_ms", "queue_delay_ms"}


@dataclass(slots=True)
class DiagnosticEvent:
	"""A structured background event containing allowlisted metadata only."""

	event: str
	operation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
	attributes: dict[str, Any] = field(default_factory=dict)
	timestamp: float = field(default_factory=time.time)
	started_at: float | None = None
	ended_at: float | None = None
	success: bool | None = None
	error_type: str | None = None

	def to_record(self) -> dict[str, Any]:
		safe_attributes: dict[str, Any] = {}
		for key, value in self.attributes.items():
			if key == "task" and isinstance(value, str):
				task_name = value.replace(".<locals>.", ".").replace("<lambda>", "callback")
				if _TASK_RE.fullmatch(task_name):
					safe_attributes[key] = task_name
			elif key == "error_type" and isinstance(value, str) and _ERROR_RE.fullmatch(value):
				safe_attributes[key] = value
			elif key in _NUMERIC_ATTRIBUTES and isinstance(value, (int, float)) and not isinstance(value, bool):
				if math.isfinite(float(value)) and value >= 0:
					safe_attributes[key] = round(float(value), 3)
		record: dict[str, Any] = {
			"record_type": "task_event",
			"schema_version": 1,
			"timestamp": self.timestamp,
			"event": self.event if isinstance(self.event, str) and _EVENT_RE.fullmatch(self.event) else "unknown",
			"operation_id": self.operation_id if isinstance(self.operation_id, str) and _OPERATION_ID_RE.fullmatch(self.operation_id) else "unknown",
			"attributes": safe_attributes,
		}
		if isinstance(self.started_at, (int, float)) and math.isfinite(float(self.started_at)):
			ended_at = self.ended_at if isinstance(self.ended_at, (int, float)) and math.isfinite(float(self.ended_at)) else time.perf_counter()
			record["duration_ms"] = round(max(0.0, ended_at - self.started_at) * 1000, 3)
		if self.success is not None:
			record["success"] = self.success
		if isinstance(self.error_type, str) and _ERROR_RE.fullmatch(self.error_type):
			record["error_type"] = self.error_type
		return record

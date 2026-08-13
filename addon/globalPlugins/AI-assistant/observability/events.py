"""Privacy-safe lifecycle events for diagnosing asynchronous behavior."""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Any
import uuid


_SENSITIVE_ATTRIBUTE_PARTS = (
	"prompt",
	"response",
	"content",
	"credential",
	"password",
	"secret",
	"api_key",
	"token",
	"base64",
	"path",
	"url",
)


@dataclass(slots=True)
class DiagnosticEvent:
	"""A structured event that never contains prompts, responses, or secrets."""

	event: str
	operation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
	attributes: dict[str, Any] = field(default_factory=dict)
	started_at: float | None = None
	ended_at: float | None = None
	success: bool | None = None
	error_type: str | None = None

	def to_record(self) -> dict[str, Any]:
		safe_attributes: dict[str, Any] = {}
		for key, value in self.attributes.items():
			key_text = str(key)
			if any(part in key_text.lower() for part in _SENSITIVE_ATTRIBUTE_PARTS):
				continue
			if isinstance(value, (str, int, float, bool)) or value is None:
				safe_attributes[key_text] = value if not isinstance(value, str) else value[:128]
		record: dict[str, Any] = {
			"record_type": "diagnostic_event",
			"timestamp": time.time(),
			"event": self.event,
			"operation_id": self.operation_id,
			"thread": threading.current_thread().name,
			"attributes": safe_attributes,
		}
		if self.started_at is not None:
			record["duration_ms"] = round((self.ended_at or time.perf_counter()) - self.started_at, 3) * 1000
		if self.success is not None:
			record["success"] = self.success
		if self.error_type is not None:
			record["error_type"] = self.error_type
		return record

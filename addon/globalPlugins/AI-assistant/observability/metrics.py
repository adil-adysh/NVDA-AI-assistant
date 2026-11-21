"""Privacy-safe measurements for provider requests."""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}(?::[A-Za-z0-9][A-Za-z0-9._-]{0,63})?$")
_REPOSITORY_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DRIVE_RELATIVE_PATH_RE = re.compile(r"^[A-Za-z]:")
_HOST_PORT_RE = re.compile(r"^(?:localhost|(?:[A-Za-z0-9-]+\.)+[A-Za-z0-9-]+):\d{1,5}$", re.IGNORECASE)


def _safe_identifier(value: object, pattern: re.Pattern[str], fallback: str) -> str:
	if not isinstance(value, str) or not pattern.fullmatch(value) or "://" in value:
		return fallback
	return value


def _safe_model(value: object) -> str:
	if not isinstance(value, str):
		return "unknown"
	if _DRIVE_RELATIVE_PATH_RE.match(value) or _HOST_PORT_RE.fullmatch(value):
		return "unknown"
	if value.lower().endswith((".gguf", ".litert", ".litertlm", ".safetensors", ".onnx", ".bin")):
		return "unknown"
	if _MODEL_NAME_RE.fullmatch(value):
		return value
	if _REPOSITORY_MODEL_RE.fullmatch(value):
		return value
	return "unknown"


@dataclass(frozen=True, slots=True)
class RequestMetrics:
	"""Allowlisted metadata for one provider invocation; content is never accepted."""

	request_type: str
	provider: str
	model: str | None
	duration_ms: float
	success: bool
	error_type: str | None = None

	def to_log_record(self) -> dict[str, object]:
		duration = self.duration_ms if math.isfinite(self.duration_ms) and self.duration_ms >= 0 else 0.0
		record: dict[str, object] = {
			"record_type": "request_metric",
			"schema_version": 1,
			"timestamp": time.time(),
			"request_type": _safe_identifier(self.request_type, _IDENTIFIER_RE, "unknown"),
			"provider": _safe_identifier(self.provider, _IDENTIFIER_RE, "unknown"),
			"model": _safe_model(self.model) if self.model else "unknown",
			"duration_ms": round(duration, 3),
			"success": bool(self.success),
		}
		if not self.success and self.error_type:
			record["error_type"] = _safe_identifier(self.error_type, _IDENTIFIER_RE, "UnknownError")
		return record

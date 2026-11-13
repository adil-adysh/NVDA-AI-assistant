# -*- coding: utf-8 -*-
"""Provider-neutral tool-call and tool-result models.

Everything in this module is core data: it must not import the ``tools``
package or any provider adapter.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

ToolArguments = dict[str, Any]

# Outcome classification.  The first eight categories are the required core
# taxonomy; ``budget_exceeded`` and ``schema_error`` are host-side conditions
# that still have to be distinguishable from a tool failure.
ToolErrorCategory = Literal[
	"invalid_arguments",
	"unknown_tool",
	"permission_denied",
	"provider_failure",
	"execution_error",
	"timeout",
	"cancelled",
	"uncertain",
	"budget_exceeded",
	"schema_error",
]

ToolErrorSource = Literal["host", "provider", "tool"]

MAX_TOOL_RESULT_CHARS = 20_000
MAX_TOOL_ERROR_CHARS = 2_000
MAX_TOOL_RESULT_BYTES = 256 * 1024
MAX_TOOL_RESULT_BLOCKS = 64
MAX_TOOL_RESULT_BLOCK_BYTES = 128 * 1024
MAX_TOOL_RESULT_JSON_BYTES = 64 * 1024
MAX_TOOL_RESULT_MEDIA_BYTES = 128 * 1024
MAX_TOOL_RESULT_METADATA_BYTES = 16 * 1024
MAX_TOOL_RESULT_DEPTH = 32
_TOOL_ERROR_CATEGORIES = frozenset({
	"invalid_arguments", "unknown_tool", "permission_denied", "provider_failure",
	"execution_error", "timeout", "cancelled", "uncertain", "budget_exceeded", "schema_error",
})
_TOOL_ERROR_SOURCES = frozenset({"host", "provider", "tool"})


class _ToolResultLimitError(ValueError):
	"""An output value is invalid or exceeds a tool result resource limit."""


@dataclass(slots=True)
class ToolCall:
	"""One model-requested tool invocation.

	``parse_error`` records malformed provider arguments instead of silently
	substituting ``{}``.  The executor refuses to run a call whose arguments
	could not be parsed.
	"""

	name: str
	arguments: ToolArguments
	id: str | None = None
	parse_error: str | None = None
	raw_arguments: str | None = None


@dataclass(frozen=True, slots=True)
class ToolContentBlock:
	"""A single piece of tool output.

	Only ``text`` is directly representable by every current LLM provider.
	Other kinds are kept losslessly for the internal contract and are converted
	to an explicitly marked, bounded textual placeholder by adapters instead of
	being disguised as real content.
	"""

	type: Literal["text", "json", "image", "audio", "resource"]
	text: str | None = None
	json_value: Any = None
	data: str | None = None
	mime_type: str | None = None
	uri: str | None = None
	metadata: Mapping[str, Any] = field(default_factory=dict)

	@classmethod
	def text_block(cls, text: str) -> "ToolContentBlock":
		return cls(type="text", text=text)

	@classmethod
	def json_block(cls, value: Any) -> "ToolContentBlock":
		return cls(type="json", json_value=value)

	def to_model_text(self) -> str:
		"""Deterministic, provider-safe textual rendering of this block."""
		if self.type == "text":
			return self.text or ""
		if self.type == "json":
			return _serialize_json(self.json_value)
		label = self.mime_type or "data"
		if self.type == "image":
			return f"[image result omitted: {label}]"
		if self.type == "audio":
			return f"[audio result omitted: {label}]"
		if self.type == "resource":
			return f"[resource result omitted: {self.uri or label}]"
		return f"[unsupported tool content: {self.type}]"

	def to_dict(self) -> dict[str, Any]:
		payload: dict[str, Any] = {"type": self.type}
		if self.text is not None:
			payload["text"] = self.text
		if self.json_value is not None:
			payload["json"] = _json_safe(self.json_value)
		if self.data is not None:
			payload["data"] = self.data
		if self.mime_type is not None:
			payload["mime_type"] = self.mime_type
		if self.uri is not None:
			payload["uri"] = self.uri
		if self.metadata:
			payload["metadata"] = _json_safe(dict(self.metadata))
		return payload

	@classmethod
	def from_dict(cls, payload: Mapping[str, Any]) -> "ToolContentBlock":
		block_type = str(payload.get("type", "text"))
		if block_type not in {"text", "json", "image", "audio", "resource"}:
			block_type = "text"
		metadata = payload.get("metadata")
		return cls(
			type=block_type,  # type: ignore[arg-type]
			text=payload.get("text") if isinstance(payload.get("text"), str) else None,
			json_value=payload.get("json"),
			data=payload.get("data") if isinstance(payload.get("data"), str) else None,
			mime_type=payload.get("mime_type") if isinstance(payload.get("mime_type"), str) else None,
			uri=payload.get("uri") if isinstance(payload.get("uri"), str) else None,
			metadata=metadata if isinstance(metadata, Mapping) else {},
		)


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
	"""Structured outcome of one tool invocation.

	Failures are never represented as a successful result.  ``uncertain`` marks
	an outcome that could not be confirmed (timeout or lost transport); such
	calls must not be retried automatically.
	"""

	tool_name: str
	tool_call_id: str | None = None
	tool_id: str | None = None
	provider_id: str | None = None
	ok: bool = False
	content: tuple[ToolContentBlock, ...] = ()
	structured_content: Any = None
	error_category: ToolErrorCategory | None = None
	error_message: str | None = None
	error_source: ToolErrorSource | None = None
	duration_ms: float = 0.0
	cancelled: bool = False
	timed_out: bool = False
	termination_confirmed: bool = True
	uncertain: bool = False
	metadata: Mapping[str, Any] = field(default_factory=dict)

	@property
	def text(self) -> str:
		"""Bounded model-visible text assembled from the content blocks."""
		parts = [block.to_model_text() for block in self.content]
		return _bounded("\n".join(part for part in parts if part), MAX_TOOL_RESULT_CHARS)

	def is_error_result(self) -> bool:
		"""Whether this is a tool-level error, as opposed to a protocol failure."""
		return not self.ok

	def to_model_text(self, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
		"""Render everything the model needs, including tool-level error detail.

		An MCP tool can fail with structured content that explains *why* while
		``ok`` is false. Returning only ``error_message`` hid that detail, so the
		model saw "external tool returned an error" and had nothing to correct.
		"""
		parts: list[str] = []
		if self.error_message:
			parts.append(self.error_message)
		text = self.text
		if text:
			parts.append(text)
		if self.structured_content is not None and (not self.ok or not text):
			parts.append(_serialize_json(self.structured_content))
		return _bounded("\n".join(part for part in parts if part), max_chars)

	def bounded(self, max_chars: int = MAX_TOOL_RESULT_CHARS) -> "ToolExecutionResult":
		try:
			if not isinstance(self.ok, bool):
				raise _ToolResultLimitError("result outcome must be a boolean")
			if any(not isinstance(flag, bool) for flag in (self.cancelled, self.timed_out, self.termination_confirmed, self.uncertain)):
				raise _ToolResultLimitError("result flags must be booleans")
			if self.error_category is not None and self.error_category not in _TOOL_ERROR_CATEGORIES:
				raise _ToolResultLimitError("result has an unknown error category")
			if self.error_source is not None and self.error_source not in _TOOL_ERROR_SOURCES:
				raise _ToolResultLimitError("result has an unknown error source")
			if not isinstance(self.content, (list, tuple)) or len(self.content) > MAX_TOOL_RESULT_BLOCKS:
				raise _ToolResultLimitError("too many content blocks")
			content = tuple(_bound_block(block, max_chars) for block in self.content)
			structured = (
				None if self.structured_content is None
				else _bounded_json_value(self.structured_content, MAX_TOOL_RESULT_JSON_BYTES)
			)
			if not isinstance(self.metadata, Mapping):
				raise _ToolResultLimitError("result metadata must be an object")
			metadata = _bounded_json_value(self.metadata, MAX_TOOL_RESULT_METADATA_BYTES)
			message = _bounded_identity(self.error_message, MAX_TOOL_ERROR_CHARS)
			bounded_result = replace(
				self,
				tool_name=_bounded_identity(self.tool_name, 256) or "unknown tool",
				tool_call_id=_bounded_identity(self.tool_call_id, 256),
				tool_id=_bounded_identity(self.tool_id, 256),
				provider_id=_bounded_identity(self.provider_id, 256),
				content=content,
				structured_content=structured,
				error_message=message,
				metadata=metadata,
				duration_ms=_safe_duration(self.duration_ms),
			)
			if _serialized_result_size(bounded_result) > MAX_TOOL_RESULT_BYTES:
				raise _ToolResultLimitError("serialized result envelope exceeds limit")
			return bounded_result
		except (TypeError, ValueError, RecursionError, OverflowError):
			return _resource_limit_failure(self, max_chars)

	def to_dict(self) -> dict[str, Any]:
		safe_result = self.bounded()
		return _result_payload(safe_result)

	def _to_dict_unchecked(self) -> dict[str, Any]:
		payload: dict[str, Any] = {
			"tool_name": self.tool_name,
			"ok": self.ok,
			"content": [block.to_dict() for block in self.content],
		}
		if self.tool_call_id is not None:
			payload["tool_call_id"] = self.tool_call_id
		if self.tool_id is not None:
			payload["tool_id"] = self.tool_id
		if self.provider_id is not None:
			payload["provider_id"] = self.provider_id
		if self.structured_content is not None:
			payload["structured_content"] = _json_safe(self.structured_content)
		if self.error_category is not None:
			payload["error_category"] = self.error_category
		if self.error_message is not None:
			payload["error_message"] = self.error_message
		if self.error_source is not None:
			payload["error_source"] = self.error_source
		if self.duration_ms:
			payload["duration_ms"] = round(self.duration_ms, 3)
		if self.cancelled:
			payload["cancelled"] = True
		if self.timed_out:
			payload["timed_out"] = True
		if not self.termination_confirmed:
			payload["termination_confirmed"] = False
		if self.uncertain:
			payload["uncertain"] = True
		if self.metadata:
			payload["metadata"] = _json_safe(dict(self.metadata))
		return payload

	@classmethod
	def from_dict(cls, payload: Mapping[str, Any]) -> "ToolExecutionResult":
		if not isinstance(payload, Mapping):
			payload = {}
		if not isinstance(payload.get("ok"), bool):
			return _resource_limit_failure(
				cls(
					tool_name=payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else "unknown tool",
					tool_call_id=payload.get("tool_call_id") if isinstance(payload.get("tool_call_id"), str) else None,
					tool_id=payload.get("tool_id") if isinstance(payload.get("tool_id"), str) else None,
					provider_id=payload.get("provider_id") if isinstance(payload.get("provider_id"), str) else None,
				),
				MAX_TOOL_RESULT_CHARS,
			)
		content_payload = payload.get("content")
		if content_payload is not None and not isinstance(content_payload, list):
			return _invalid_result_envelope(cls, payload)
		if "metadata" in payload and not isinstance(payload["metadata"], Mapping):
			return _invalid_result_envelope(cls, payload)
		if isinstance(content_payload, list) and len(content_payload) > MAX_TOOL_RESULT_BLOCKS:
			return _invalid_result_envelope(cls, payload)
		for item in content_payload or ():
			if not isinstance(item, Mapping):
				return _invalid_result_envelope(cls, payload)
			block_type = item.get("type", "text")
			if not isinstance(block_type, str) or block_type not in {"text", "json", "image", "audio", "resource"}:
				return _invalid_result_envelope(cls, payload)
			if any(key in item and not isinstance(item[key], str) for key in ("text", "data", "mime_type", "uri")):
				return _invalid_result_envelope(cls, payload)
			if "metadata" in item and not isinstance(item["metadata"], Mapping):
				return _invalid_result_envelope(cls, payload)
		for flag in ("cancelled", "timed_out", "termination_confirmed", "uncertain"):
			if flag in payload and not isinstance(payload[flag], bool):
				return _invalid_result_envelope(cls, payload)
		duration = payload.get("duration_ms", 0.0)
		if isinstance(duration, bool) or not isinstance(duration, (int, float)):
			return _invalid_result_envelope(cls, payload)
		try:
			duration_ms = float(duration)
		except (OverflowError, ValueError):
			return _invalid_result_envelope(cls, payload)
		if not math.isfinite(duration_ms) or duration_ms < 0:
			return _invalid_result_envelope(cls, payload)
		blocks = tuple(
			ToolContentBlock.from_dict(item)
			for item in content_payload
			if isinstance(item, Mapping)
		) if isinstance(content_payload, list) else ()
		metadata = payload.get("metadata")
		restored = cls(
			tool_name=str(payload.get("tool_name", "")),
			tool_call_id=payload.get("tool_call_id") if isinstance(payload.get("tool_call_id"), str) else None,
			tool_id=payload.get("tool_id") if isinstance(payload.get("tool_id"), str) else None,
			provider_id=payload.get("provider_id") if isinstance(payload.get("provider_id"), str) else None,
			ok=bool(payload.get("ok")),
			content=blocks,
			structured_content=payload.get("structured_content"),
			error_category=payload.get("error_category") if isinstance(payload.get("error_category"), str) else None,
			error_message=payload.get("error_message") if isinstance(payload.get("error_message"), str) else None,
			error_source=payload.get("error_source") if isinstance(payload.get("error_source"), str) else None,
			duration_ms=duration_ms,
			cancelled=bool(payload.get("cancelled")),
			timed_out=bool(payload.get("timed_out")),
			termination_confirmed=payload.get("termination_confirmed") is not False,
			uncertain=bool(payload.get("uncertain")),
			metadata=metadata if isinstance(metadata, Mapping) else {},
		)
		return restored.bounded()


def _invalid_result_envelope(
	result_type: type[ToolExecutionResult], payload: Mapping[str, Any]
) -> ToolExecutionResult:
	return _resource_limit_failure(
		result_type(
			tool_name=payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else "unknown tool",
			tool_call_id=payload.get("tool_call_id") if isinstance(payload.get("tool_call_id"), str) else None,
			tool_id=payload.get("tool_id") if isinstance(payload.get("tool_id"), str) else None,
			provider_id=payload.get("provider_id") if isinstance(payload.get("provider_id"), str) else None,
		),
		MAX_TOOL_RESULT_CHARS,
	)


def _serialize_json(value: Any) -> str:
	try:
		return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	except (TypeError, ValueError):
		return repr(value)


def _bounded(text: str, limit: int) -> str:
	if limit <= 0:
		return ""
	if len(text) <= limit:
		return text
	marker = "…[truncated]"
	return text[: max(0, limit - len(marker))] + marker


def _bound_block(block: ToolContentBlock, limit: int) -> ToolContentBlock:
	if not isinstance(block, ToolContentBlock):
		raise _ToolResultLimitError("invalid content block")
	if block.type not in {"text", "json", "image", "audio", "resource"}:
		raise _ToolResultLimitError("content block has an unsupported type")
	text = block.text
	if text is not None:
		text = _bounded(text, limit)
		if len(text) > MAX_TOOL_RESULT_BLOCK_BYTES:
			raise _ToolResultLimitError("text block exceeds limit")
	json_value = (
		None if block.json_value is None
		else _bounded_json_value(block.json_value, MAX_TOOL_RESULT_JSON_BYTES)
	)
	data = block.data
	if data is not None and len(data) > MAX_TOOL_RESULT_MEDIA_BYTES:
		raise _ToolResultLimitError("encoded media block exceeds limit")
	if not isinstance(block.metadata, Mapping):
		raise _ToolResultLimitError("content block metadata must be an object")
	metadata = _bounded_json_value(block.metadata, MAX_TOOL_RESULT_METADATA_BYTES)
	for text_field in (block.mime_type, block.uri):
		if text_field is not None and len(text_field) > MAX_TOOL_RESULT_BLOCK_BYTES:
			raise _ToolResultLimitError("content block field exceeds limit")
	bounded_block = replace(block, text=text, json_value=json_value, metadata=metadata)
	if _serialized_json_size(bounded_block.to_dict()) > MAX_TOOL_RESULT_BLOCK_BYTES:
		raise _ToolResultLimitError("content block exceeds limit")
	return bounded_block


def _bounded_json_value(value: Any, limit: int) -> Any:
	"""Copy JSON data while enforcing byte and nesting budgets incrementally."""
	used = 0
	active: set[int] = set()

	def charge(amount: int) -> None:
		nonlocal used
		used += amount
		if used > limit:
			raise _ToolResultLimitError("JSON value exceeds byte limit")

	def visit(item: Any, depth: int) -> Any:
		if depth > MAX_TOOL_RESULT_DEPTH:
			raise _ToolResultLimitError("JSON value exceeds nesting limit")
		if item is None or isinstance(item, bool):
			encoded = json.dumps(item, separators=(",", ":")).encode("utf-8")
			charge(len(encoded))
			return item
		if isinstance(item, int):
			encoded = str(item).encode("ascii")
			charge(len(encoded))
			return item
		if isinstance(item, float):
			if not math.isfinite(item):
				raise _ToolResultLimitError("non-finite numbers are not valid JSON")
			encoded = json.dumps(item, allow_nan=False, separators=(",", ":")).encode("ascii")
			charge(len(encoded))
			return item
		if isinstance(item, str):
			if len(item) > limit:
				raise _ToolResultLimitError("JSON string exceeds byte limit")
			encoded = json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
			charge(len(encoded))
			return item
		if isinstance(item, Mapping):
			identity = id(item)
			if identity in active:
				raise _ToolResultLimitError("cyclic JSON object")
			active.add(identity)
			charge(2)
			result: dict[str, Any] = {}
			for index, (key, child) in enumerate(item.items()):
				if not isinstance(key, str):
					raise _ToolResultLimitError("JSON object keys must be strings")
				if index:
					charge(1)
				if len(key) > limit:
					raise _ToolResultLimitError("JSON object key exceeds byte limit")
				charge(len(json.dumps(key, ensure_ascii=False).encode("utf-8")) + 1)
				result[key] = visit(child, depth + 1)
			active.remove(identity)
			return result
		if isinstance(item, (list, tuple)):
			identity = id(item)
			if identity in active:
				raise _ToolResultLimitError("cyclic JSON array")
			active.add(identity)
			charge(2)
			result = []
			for index, child in enumerate(item):
				if index:
					charge(1)
				result.append(visit(child, depth + 1))
			active.remove(identity)
			return result
		raise _ToolResultLimitError(f"unsupported JSON value type: {type(item).__name__}")

	return visit(value, 0)


def _bounded_identity(value: Any, limit: int) -> str | None:
	if value is None:
		return None
	if not isinstance(value, str):
		return None
	if len(value) > limit:
		return _bounded(value, limit)
	return value


def _serialized_json_size(value: Any) -> int:
	return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _result_payload(result: ToolExecutionResult) -> dict[str, Any]:
	return result._to_dict_unchecked()


def _serialized_result_size(result: ToolExecutionResult) -> int:
	return _serialized_json_size(_result_payload(result))


def _resource_limit_failure(result: ToolExecutionResult, max_chars: int) -> ToolExecutionResult:
	"""Drop the full result deterministically when it cannot be bounded safely."""
	return ToolExecutionResult(
		tool_name=_bounded_identity(result.tool_name, 256) or "unknown tool",
		tool_call_id=_bounded_identity(result.tool_call_id, 256),
		tool_id=_bounded_identity(result.tool_id, 256),
		provider_id=_bounded_identity(result.provider_id, 256),
		ok=False,
		content=(ToolContentBlock.text_block(_bounded("Tool result exceeded resource limits; content was discarded.", max_chars)),),
		error_category="execution_error",
		error_message="Tool result exceeded resource limits; content was discarded.",
		error_source="host",
		duration_ms=_safe_duration(result.duration_ms),
		termination_confirmed=(result.termination_confirmed if isinstance(result.termination_confirmed, bool) else False),
		uncertain=(result.uncertain if isinstance(result.uncertain, bool) else True),
		metadata={},
	)


def _safe_duration(value: Any) -> float:
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		return 0.0
	try:
		numeric = float(value)
	except (OverflowError, ValueError):
		return 0.0
	return numeric if math.isfinite(numeric) and numeric >= 0 else 0.0


def _json_safe(value: Any) -> Any:
	"""Best-effort conversion to JSON-serializable data without losing structure."""
	try:
		json.dumps(value)
		return value
	except (TypeError, ValueError):
		pass
	if isinstance(value, Mapping):
		return {str(key): _json_safe(item) for key, item in value.items()}
	if isinstance(value, (list, tuple)):
		return [_json_safe(item) for item in value]
	return repr(value)

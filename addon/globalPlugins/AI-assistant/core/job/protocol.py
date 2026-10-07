# -*- coding: utf-8 -*-
"""Versioned Wire Protocol, Framing, and Handshake Negotiation.

Enforces Invariants A17 (versioned handshake v1.0.0), A18 (NDJSON control plane
and 12-byte hybrid binary framing), and A20 (typed error catalog).
"""

from __future__ import annotations

from enum import StrEnum
import json
import struct
from typing import Any

from .dto import HandshakeRequest, HandshakeResponse

# ---------------------------------------------------------------------------
# Protocol Constants
# ---------------------------------------------------------------------------

PROTOCOL_VERSION: str = "1.0.0"
MAGIC: bytes = b"\xAA\x55\x01\x00"
HEADER_SIZE: int = 12
MAX_FRAME_SIZE: int = 16 * 1024 * 1024  # 16 MB limit


# ---------------------------------------------------------------------------
# Typed Error Catalog (Invariant A20)
# ---------------------------------------------------------------------------


class ErrorCode(StrEnum):
	"""Comprehensive typed error code catalog for wire protocol and job execution."""

	# Protocol / Transport errors
	PROTOCOL_VERSION_MISMATCH = "PROTOCOL_VERSION_MISMATCH"
	HANDSHAKE_REJECTED = "HANDSHAKE_REJECTED"
	INVALID_FRAME = "INVALID_FRAME"
	FRAME_TOO_LARGE = "FRAME_TOO_LARGE"
	PIPE_DISCONNECTED = "PIPE_DISCONNECTED"

	# State Machine errors
	INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
	TERMINAL_STATE_MUTATION = "TERMINAL_STATE_MUTATION"
	JOB_NOT_FOUND = "JOB_NOT_FOUND"
	SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
	PREEMPTION_TIMEOUT = "PREEMPTION_TIMEOUT"

	# Job Execution errors
	DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
	CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
	EXTRACTION_FAILED = "EXTRACTION_FAILED"
	INSUFFICIENT_STORAGE = "INSUFFICIENT_STORAGE"
	MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
	INFERENCE_FAILED = "INFERENCE_FAILED"
	JOB_TIMEOUT = "JOB_TIMEOUT"

	# System / Hardware errors
	WORKER_CRASH = "WORKER_CRASH"
	OUT_OF_MEMORY = "OUT_OF_MEMORY"
	DEVICE_DISCONNECTED = "DEVICE_DISCONNECTED"
	CIRCUIT_BREAKER_TRIPPED = "CIRCUIT_BREAKER_TRIPPED"


class ProtocolError(Exception):
	"""Raised when a framing, versioning, serialization, or handshake error occurs."""

	def __init__(
		self,
		error_code: ErrorCode | str,
		message: str = "",
		retriable: bool = False,
		details: dict[str, Any] | None = None,
	) -> None:
		msg = f"[{error_code}] {message}" if message else f"[{error_code}]"
		super().__init__(msg)
		self.error_code = error_code
		self.message = message
		self.retriable = retriable
		self.details = details or {}


# ---------------------------------------------------------------------------
# NDJSON Control Plane Framing (Invariant A18)
# ---------------------------------------------------------------------------


def encode_ndjson_frame(payload: dict[str, Any] | str) -> bytes:
	"""Encode a dictionary or string payload into a newline-delimited UTF-8 JSON frame.

	Raises:
		ProtocolError: If frame length exceeds MAX_FRAME_SIZE (16 MB).
	"""
	if isinstance(payload, dict):
		content = json.dumps(payload, separators=(",", ":"))
	else:
		content = payload.rstrip("\r\n")

	raw = (content + "\n").encode("utf-8")
	if len(raw) > MAX_FRAME_SIZE:
		raise ProtocolError(
			ErrorCode.FRAME_TOO_LARGE,
			f"Frame size {len(raw)} bytes exceeds MAX_FRAME_SIZE {MAX_FRAME_SIZE} bytes",
		)
	return raw


def decode_ndjson_frame(raw_bytes: bytes) -> dict[str, Any]:
	"""Decode a newline-delimited UTF-8 JSON frame into a dictionary.

	Raises:
		ProtocolError: If frame exceeds MAX_FRAME_SIZE or is malformed JSON.
	"""
	if len(raw_bytes) > MAX_FRAME_SIZE:
		raise ProtocolError(
			ErrorCode.FRAME_TOO_LARGE,
			f"Frame size {len(raw_bytes)} bytes exceeds MAX_FRAME_SIZE {MAX_FRAME_SIZE} bytes",
		)

	stripped = raw_bytes.strip()
	if not stripped:
		raise ProtocolError(ErrorCode.INVALID_FRAME, "Cannot decode empty NDJSON frame")

	try:
		data = json.loads(stripped.decode("utf-8"))
	except (UnicodeDecodeError, json.JSONDecodeError) as exc:
		raise ProtocolError(
			ErrorCode.INVALID_FRAME, f"Failed to parse NDJSON frame: {exc}"
		) from exc

	if not isinstance(data, dict):
		raise ProtocolError(
			ErrorCode.INVALID_FRAME, "Frame payload must be a JSON object"
		)

	return data


# ---------------------------------------------------------------------------
# Streaming Plane Hybrid Binary Framing (Invariant A18)
# ---------------------------------------------------------------------------


def encode_binary_frame(metadata: dict[str, Any], binary_payload: bytes) -> bytes:
	"""Pack metadata JSON and raw binary buffer into a 12-byte header frame.

	Format:
	[4B Magic b'\xAA\x55\x01\x00'][4B JSON Len uint32-BE][4B Binary Len uint32-BE][JSON][Binary]

	Raises:
		ProtocolError: If total frame exceeds MAX_FRAME_SIZE.
	"""
	meta_bytes = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
	meta_len = len(meta_bytes)
	bin_len = len(binary_payload)
	total_len = HEADER_SIZE + meta_len + bin_len

	if total_len > MAX_FRAME_SIZE:
		raise ProtocolError(
			ErrorCode.FRAME_TOO_LARGE,
			f"Binary frame size {total_len} bytes exceeds MAX_FRAME_SIZE {MAX_FRAME_SIZE} bytes",
		)

	header = struct.pack(">4sII", MAGIC, meta_len, bin_len)
	return header + meta_bytes + binary_payload


def decode_binary_frame(raw_bytes: bytes) -> tuple[dict[str, Any], bytes]:
	"""Unpack a 12-byte header hybrid binary frame into (metadata_dict, binary_payload_bytes).

	Raises:
		ProtocolError: If magic bytes mismatch, length headers don't match payload,
		or JSON is invalid.
	"""
	if len(raw_bytes) > MAX_FRAME_SIZE:
		raise ProtocolError(
			ErrorCode.FRAME_TOO_LARGE,
			f"Binary frame size {len(raw_bytes)} bytes exceeds MAX_FRAME_SIZE {MAX_FRAME_SIZE} bytes",
		)

	if len(raw_bytes) < HEADER_SIZE:
		raise ProtocolError(
			ErrorCode.INVALID_FRAME,
			f"Frame size {len(raw_bytes)} bytes is smaller than 12-byte header",
		)

	magic, meta_len, bin_len = struct.unpack(">4sII", raw_bytes[:HEADER_SIZE])
	if magic != MAGIC:
		raise ProtocolError(
			ErrorCode.INVALID_FRAME, f"Invalid magic header: {magic!r}, expected {MAGIC!r}"
		)

	expected_len = HEADER_SIZE + meta_len + bin_len
	if len(raw_bytes) != expected_len:
		raise ProtocolError(
			ErrorCode.INVALID_FRAME,
			f"Binary frame length mismatch: header expects {expected_len} bytes, got {len(raw_bytes)}",
		)

	meta_raw = raw_bytes[HEADER_SIZE : HEADER_SIZE + meta_len]
	try:
		metadata = json.loads(meta_raw.decode("utf-8"))
	except (UnicodeDecodeError, json.JSONDecodeError) as exc:
		raise ProtocolError(
			ErrorCode.INVALID_FRAME, f"Failed to parse binary frame metadata: {exc}"
		) from exc

	if not isinstance(metadata, dict):
		raise ProtocolError(
			ErrorCode.INVALID_FRAME, "Frame payload must be a JSON object"
		)

	binary_payload = raw_bytes[HEADER_SIZE + meta_len :]
	return metadata, binary_payload


# ---------------------------------------------------------------------------
# Handshake Negotiation (Invariant A17)
# ---------------------------------------------------------------------------


def is_protocol_compatible(client_version: str, worker_version: str) -> bool:
	"""Check SemVer compatibility: major versions must be identical."""
	try:
		c_maj = client_version.split(".")[0]
		w_maj = worker_version.split(".")[0]
		return bool(c_maj and w_maj and c_maj == w_maj)
	except Exception:
		return False


def validate_handshake(
	request: HandshakeRequest,
	worker_version: str = PROTOCOL_VERSION,
	supported_capabilities: tuple[str, ...] | None = None,
	worker_pid: int = 0,
	max_frame_bytes: int = MAX_FRAME_SIZE,
) -> HandshakeResponse:
	"""Validate HandshakeRequest and generate a corresponding HandshakeResponse."""
	if not is_protocol_compatible(request.protocol_version, worker_version):
		return HandshakeResponse(
			accepted=False,
			protocol_version=worker_version,
			worker_pid=worker_pid,
			worker_version=worker_version,
			negotiated_capabilities=(),
			max_frame_bytes=max_frame_bytes,
			error_message=(
				f"Incompatible protocol version: client '{request.protocol_version}', "
				f"worker '{worker_version}'"
			),
			correlation_id=request.request_id,
		)

	if supported_capabilities is None:
		supported_capabilities = (
			"job.model_download",
			"job.model_verify",
			"job.inference",
			"session.ocr",
			"session.transcription",
		)

	supported_set = set(supported_capabilities)
	negotiated = tuple(cap for cap in request.requested_capabilities if cap in supported_set)

	return HandshakeResponse(
		accepted=True,
		protocol_version=worker_version,
		worker_pid=worker_pid,
		worker_version=worker_version,
		negotiated_capabilities=negotiated,
		max_frame_bytes=max_frame_bytes,
		error_message=None,
		correlation_id=request.request_id,
	)

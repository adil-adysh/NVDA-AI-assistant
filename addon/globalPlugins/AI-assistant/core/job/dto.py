# -*- coding: utf-8 -*-
"""Authoritative Immutable DTO Definitions for Job Domain and IPC Protocol.

Enforces Invariant A24 (frozen dataclasses with slots, immutable tuple collections,
and clean dictionary/JSON serialization).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import time
from typing import Any, Self, TypeAlias
from uuid import uuid4

# ---------------------------------------------------------------------------
# Type Identifiers & Domain Enums
# ---------------------------------------------------------------------------

JobId: TypeAlias = str


class JobStatus(StrEnum):
	"""Discrete lifecycle states of a Job (Invariant A21)."""

	SUBMITTED = "submitted"
	QUEUED = "queued"
	RUNNING = "running"
	COMPLETED = "completed"
	FAILED = "failed"
	CANCELLED = "cancelled"

	@property
	def is_terminal(self) -> bool:
		"""Return True if this state is a terminal, irreversible state."""
		return self in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)

	@property
	def is_active(self) -> bool:
		"""Return True if the job is still undergoing execution or queueing."""
		return self in (JobStatus.SUBMITTED, JobStatus.QUEUED, JobStatus.RUNNING)


# Canonical alias matching Section 15 & 16 of the architecture deliverable
JobState = JobStatus


class SessionState(StrEnum):
	"""Discrete lifecycle states of a continuous streaming session (Invariant A23)."""

	INIT = "init"
	CONFIGURING = "configuring"
	READY = "ready"
	STREAMING = "streaming"
	PAUSED = "paused"
	CLOSING = "closing"
	CLOSED = "closed"
	ERROR = "error"

	@property
	def is_terminal(self) -> bool:
		"""Return True if this session state is terminal and inactive."""
		return self in (SessionState.CLOSED, SessionState.ERROR)

	@property
	def is_active(self) -> bool:
		"""Return True if the session is alive and ready/streaming."""
		return self in (SessionState.READY, SessionState.STREAMING, SessionState.PAUSED)


class ModalityType(StrEnum):
	"""Modality types supported by Worker runtime engines."""

	DOWNLOAD = "download"
	INFERENCE = "inference"
	OCR = "ocr"
	TRANSCRIPTION = "transcription"
	EMBEDDING = "embedding"
	TTS = "tts"


# ---------------------------------------------------------------------------
# Handshake DTOs (Invariant A17)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HandshakeRequest:
	"""Initial connection and capability negotiation request sent by NVDA."""

	protocol_version: str = "1.0.0"
	client_name: str = "nvda_ai_assistant"
	client_version: str = "1.0.0"
	client_pid: int = 0
	supported_schemas: tuple[str, ...] = ("job.v1", "session.v1", "health.v1")
	requested_capabilities: tuple[str, ...] = (
		"job.model_download",
		"job.model_verify",
		"job.inference",
		"session.ocr",
		"session.transcription",
	)
	request_id: str = field(default_factory=lambda: str(uuid4()))

	def to_dict(self) -> dict[str, Any]:
		"""Serialize HandshakeRequest into a JSON-compatible dictionary."""
		return {
			"type": "handshake_request",
			"protocol_version": self.protocol_version,
			"client_name": self.client_name,
			"client_version": self.client_version,
			"client_pid": self.client_pid,
			"supported_schemas": list(self.supported_schemas),
			"requested_capabilities": list(self.requested_capabilities),
			"request_id": self.request_id,
		}

	def to_json(self) -> str:
		"""Serialize HandshakeRequest to a compact JSON string."""
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		"""Construct HandshakeRequest from a dictionary."""
		return cls(
			protocol_version=str(data.get("protocol_version", "1.0.0")),
			client_name=str(data.get("client_name", "nvda_ai_assistant")),
			client_version=str(data.get("client_version", "1.0.0")),
			client_pid=int(data.get("client_pid", 0)),
			supported_schemas=tuple(str(s) for s in data.get("supported_schemas", ())),
			requested_capabilities=tuple(str(c) for c in data.get("requested_capabilities", ())),
			request_id=str(data.get("request_id", "")),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		"""Construct HandshakeRequest from a JSON string."""
		return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True, slots=True)
class HandshakeResponse:
	"""Handshake response confirming compatibility and negotiated capabilities."""

	accepted: bool
	protocol_version: str
	worker_pid: int
	worker_version: str
	negotiated_capabilities: tuple[str, ...]
	max_frame_bytes: int = 16 * 1024 * 1024
	error_message: str | None = None
	correlation_id: str = ""

	def to_dict(self) -> dict[str, Any]:
		"""Serialize HandshakeResponse into a JSON-compatible dictionary."""
		return {
			"type": "handshake_response",
			"accepted": self.accepted,
			"protocol_version": self.protocol_version,
			"worker_pid": self.worker_pid,
			"worker_version": self.worker_version,
			"negotiated_capabilities": list(self.negotiated_capabilities),
			"max_frame_bytes": self.max_frame_bytes,
			"error_message": self.error_message,
			"correlation_id": self.correlation_id,
		}

	def to_json(self) -> str:
		"""Serialize HandshakeResponse to a compact JSON string."""
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		"""Construct HandshakeResponse from a dictionary."""
		return cls(
			accepted=bool(data.get("accepted", False)),
			protocol_version=str(data.get("protocol_version", "")),
			worker_pid=int(data.get("worker_pid", 0)),
			worker_version=str(data.get("worker_version", "")),
			negotiated_capabilities=tuple(str(c) for c in data.get("negotiated_capabilities", ())),
			max_frame_bytes=int(data.get("max_frame_bytes", 16 * 1024 * 1024)),
			error_message=str(data["error_message"]) if data.get("error_message") is not None else None,
			correlation_id=str(data.get("correlation_id", "")),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		"""Construct HandshakeResponse from a JSON string."""
		return cls.from_dict(json.loads(json_str))


# ---------------------------------------------------------------------------
# Job Domain DTOs (Invariant A21, A24)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JobFailure:
	"""Structured, typed diagnostic details for a failed job."""

	error_code: str
	error_message: str
	retriable: bool = False
	details: dict[str, Any] = field(default_factory=dict)
	traceback_summary: str | None = None

	def to_dict(self) -> dict[str, Any]:
		"""Serialize JobFailure into a dictionary."""
		return {
			"error_code": self.error_code,
			"error_message": self.error_message,
			"retriable": self.retriable,
			"details": dict(self.details),
			"traceback_summary": self.traceback_summary,
		}

	def to_json(self) -> str:
		"""Serialize JobFailure to a JSON string."""
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		"""Construct JobFailure from a dictionary."""
		return cls(
			error_code=str(data.get("error_code", "UNKNOWN_ERROR")),
			error_message=str(data.get("error_message", "")),
			retriable=bool(data.get("retriable", False)),
			details=dict(data.get("details", {})),
			traceback_summary=(
				str(data["traceback_summary"]) if data.get("traceback_summary") is not None else None
			),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		"""Construct JobFailure from a JSON string."""
		return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True, slots=True)
class JobSpec:
	"""Immutable specification of a discrete compute job to execute."""

	job_id: str
	job_type: str
	payload: dict[str, Any] = field(default_factory=dict)
	priority: int = 10
	timeout_seconds: float = 300.0
	generation: int = 1
	created_at_epoch_ms: int = field(default_factory=lambda: int(time.time() * 1000))

	def to_dict(self) -> dict[str, Any]:
		"""Serialize JobSpec into wire-format job_submission dictionary."""
		return {
			"type": "job_submission",
			"job_id": self.job_id,
			"job_type": self.job_type,
			"payload": dict(self.payload),
			"priority": self.priority,
			"timeout_seconds": self.timeout_seconds,
			"generation": self.generation,
			"created_at_epoch_ms": self.created_at_epoch_ms,
		}

	def to_json(self) -> str:
		"""Serialize JobSpec to a JSON string."""
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		"""Construct JobSpec from a dictionary."""
		return cls(
			job_id=str(data["job_id"]),
			job_type=str(data["job_type"]),
			payload=dict(data.get("payload", {})),
			priority=int(data.get("priority", 10)),
			timeout_seconds=float(data.get("timeout_seconds", 300.0)),
			generation=int(data.get("generation", 1)),
			created_at_epoch_ms=int(data.get("created_at_epoch_ms", 0)),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		"""Construct JobSpec from a JSON string."""
		return cls.from_dict(json.loads(json_str))


# Canonical alias matching Section 16 wire framing
JobSubmission = JobSpec


@dataclass(frozen=True, slots=True)
class JobProgress:
	"""Point-in-time execution progress telemetry emitted over IPC."""

	job_id: str
	status: JobStatus
	progress_pct: float = 0.0
	status_message: str = ""
	bytes_completed: int = 0
	bytes_total: int = 0
	throughput_bytes_per_sec: float = 0.0
	eta_seconds: float | None = None
	generation: int = 1
	timestamp_epoch_ms: int = field(default_factory=lambda: int(time.time() * 1000))

	def to_dict(self) -> dict[str, Any]:
		"""Serialize JobProgress into wire-format job_update dictionary."""
		return {
			"type": "job_update",
			"job_id": self.job_id,
			"status": str(self.status),
			"progress_pct": round(self.progress_pct, 2),
			"status_message": self.status_message,
			"bytes_completed": self.bytes_completed,
			"bytes_total": self.bytes_total,
			"throughput_bytes_per_sec": round(self.throughput_bytes_per_sec, 2),
			"eta_seconds": round(self.eta_seconds, 2) if self.eta_seconds is not None else None,
			"generation": self.generation,
			"timestamp_epoch_ms": self.timestamp_epoch_ms,
		}

	def to_json(self) -> str:
		"""Serialize JobProgress to a JSON string."""
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		"""Construct JobProgress from a dictionary."""
		return cls(
			job_id=str(data["job_id"]),
			status=JobStatus(data.get("status", JobStatus.RUNNING)),
			progress_pct=float(data.get("progress_pct", 0.0)),
			status_message=str(data.get("status_message", "")),
			bytes_completed=int(data.get("bytes_completed", 0)),
			bytes_total=int(data.get("bytes_total", 0)),
			throughput_bytes_per_sec=float(data.get("throughput_bytes_per_sec", 0.0)),
			eta_seconds=float(data["eta_seconds"]) if data.get("eta_seconds") is not None else None,
			generation=int(data.get("generation", 1)),
			timestamp_epoch_ms=int(data.get("timestamp_epoch_ms", 0)),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		"""Construct JobProgress from a JSON string."""
		return cls.from_dict(json.loads(json_str))


# Canonical alias matching Section 16 wire framing
JobUpdate = JobProgress


@dataclass(frozen=True, slots=True)
class JobResult:
	"""Terminal outcome of a completed, failed, or cancelled job."""

	job_id: str
	status: JobStatus
	result_data: dict[str, Any] = field(default_factory=dict)
	error_code: str | None = None
	error_message: str | None = None
	retriable: bool = False
	duration_ms: int = 0
	generation: int = 1

	def __post_init__(self) -> None:
		if not self.status.is_terminal:
			raise ValueError(
				f"JobResult status must be terminal (completed, failed, cancelled), got '{self.status}'"
			)

	def to_dict(self) -> dict[str, Any]:
		"""Serialize JobResult into wire-format job_result dictionary."""
		return {
			"type": "job_result",
			"job_id": self.job_id,
			"status": str(self.status),
			"result_data": dict(self.result_data),
			"error_code": self.error_code,
			"error_message": self.error_message,
			"retriable": self.retriable,
			"duration_ms": self.duration_ms,
			"generation": self.generation,
		}

	def to_json(self) -> str:
		"""Serialize JobResult to a JSON string."""
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		"""Construct JobResult from a dictionary."""
		return cls(
			job_id=str(data["job_id"]),
			status=JobStatus(data.get("status", JobStatus.COMPLETED)),
			result_data=dict(data.get("result_data", {})),
			error_code=str(data["error_code"]) if data.get("error_code") is not None else None,
			error_message=str(data["error_message"]) if data.get("error_message") is not None else None,
			retriable=bool(data.get("retriable", False)),
			duration_ms=int(data.get("duration_ms", 0)),
			generation=int(data.get("generation", 1)),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		"""Construct JobResult from a JSON string."""
		return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True, slots=True)
class JobSnapshot:
	"""Point-in-time immutable snapshot of job state machine and history."""

	spec: JobSpec
	state: JobStatus
	progress: JobProgress | None = None
	result: JobResult | None = None
	created_at_epoch_ms: int = 0
	updated_at_epoch_ms: int = 0

	@property
	def job_id(self) -> str:
		"""Return the unique job identifier."""
		return self.spec.job_id

	@property
	def is_terminal(self) -> bool:
		"""Return True if this job is in a terminal state."""
		return self.state.is_terminal

	@property
	def is_success(self) -> bool:
		"""Return True if the job succeeded."""
		return self.state == JobStatus.COMPLETED

	def to_dict(self) -> dict[str, Any]:
		"""Serialize snapshot into a nested dictionary."""
		return {
			"spec": self.spec.to_dict(),
			"state": str(self.state),
			"progress": self.progress.to_dict() if self.progress is not None else None,
			"result": self.result.to_dict() if self.result is not None else None,
			"created_at_epoch_ms": self.created_at_epoch_ms,
			"updated_at_epoch_ms": self.updated_at_epoch_ms,
		}

	def to_json(self) -> str:
		"""Serialize snapshot to a JSON string."""
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		"""Construct snapshot from a nested dictionary."""
		spec_data = data["spec"]
		spec = JobSpec.from_dict(spec_data)
		progress_data = data.get("progress")
		progress = JobProgress.from_dict(progress_data) if progress_data is not None else None
		result_data = data.get("result")
		result = JobResult.from_dict(result_data) if result_data is not None else None
		return cls(
			spec=spec,
			state=JobStatus(data["state"]),
			progress=progress,
			result=result,
			created_at_epoch_ms=int(data.get("created_at_epoch_ms", 0)),
			updated_at_epoch_ms=int(data.get("updated_at_epoch_ms", 0)),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		"""Construct snapshot from a JSON string."""
		return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True, slots=True)
class JobCancellationRequest:
	"""Phase 1 cooperative cancellation command sent by NVDA."""

	job_id: str
	reason: str = "user_cancelled"
	preemption_timeout_seconds: float = 3.0
	generation: int = 1

	def to_dict(self) -> dict[str, Any]:
		"""Serialize JobCancellationRequest into a dictionary."""
		return {
			"type": "job_cancellation_request",
			"job_id": self.job_id,
			"reason": self.reason,
			"preemption_timeout_seconds": self.preemption_timeout_seconds,
			"generation": self.generation,
		}

	def to_json(self) -> str:
		"""Serialize JobCancellationRequest to a JSON string."""
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		"""Construct JobCancellationRequest from a dictionary."""
		return cls(
			job_id=str(data["job_id"]),
			reason=str(data.get("reason", "user_cancelled")),
			preemption_timeout_seconds=float(data.get("preemption_timeout_seconds", 3.0)),
			generation=int(data.get("generation", 1)),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		"""Construct JobCancellationRequest from a JSON string."""
		return cls.from_dict(json.loads(json_str))


# ---------------------------------------------------------------------------
# Continuous Session DTOs (Invariant A23, A29)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionConfig:
	"""Configuration for a continuous streaming session (OCR, Audio)."""

	session_id: str
	modality: ModalityType
	config_parameters: dict[str, Any] = field(default_factory=dict)
	max_queue_depth: int = 2
	buffer_capacity_ms: int = 10000
	generation: int = 1

	def to_dict(self) -> dict[str, Any]:
		"""Serialize SessionConfig into wire-format session_config dictionary."""
		return {
			"type": "session_config",
			"session_id": self.session_id,
			"modality": str(self.modality),
			"config_parameters": dict(self.config_parameters),
			"max_queue_depth": self.max_queue_depth,
			"buffer_capacity_ms": self.buffer_capacity_ms,
			"generation": self.generation,
		}

	def to_json(self) -> str:
		"""Serialize SessionConfig to a JSON string."""
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		"""Construct SessionConfig from a dictionary."""
		return cls(
			session_id=str(data["session_id"]),
			modality=ModalityType(data.get("modality", ModalityType.OCR)),
			config_parameters=dict(data.get("config_parameters", {})),
			max_queue_depth=int(data.get("max_queue_depth", 2)),
			buffer_capacity_ms=int(data.get("buffer_capacity_ms", 10000)),
			generation=int(data.get("generation", 1)),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		"""Construct SessionConfig from a JSON string."""
		return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True, slots=True)
class StreamChunk:
	"""Continuous streaming output packet (OCR hypothesis or Whisper token)."""

	session_id: str
	sequence_number: int
	is_partial: bool
	payload_text: str
	start_ms: int = 0
	end_ms: int = 0
	confidence: float = 1.0
	bounding_boxes: tuple[dict[str, Any], ...] = ()
	dropped_frames_count: int = 0
	generation: int = 1

	def to_dict(self) -> dict[str, Any]:
		"""Serialize StreamChunk into wire-format stream_chunk dictionary."""
		return {
			"type": "stream_chunk",
			"session_id": self.session_id,
			"sequence_number": self.sequence_number,
			"is_partial": self.is_partial,
			"payload_text": self.payload_text,
			"start_ms": self.start_ms,
			"end_ms": self.end_ms,
			"confidence": round(self.confidence, 4),
			"bounding_boxes": [dict(b) for b in self.bounding_boxes],
			"dropped_frames_count": self.dropped_frames_count,
			"generation": self.generation,
		}

	def to_json(self) -> str:
		"""Serialize StreamChunk to a JSON string."""
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		"""Construct StreamChunk from a dictionary."""
		return cls(
			session_id=str(data["session_id"]),
			sequence_number=int(data["sequence_number"]),
			is_partial=bool(data.get("is_partial", False)),
			payload_text=str(data.get("payload_text", "")),
			start_ms=int(data.get("start_ms", 0)),
			end_ms=int(data.get("end_ms", 0)),
			confidence=float(data.get("confidence", 1.0)),
			bounding_boxes=tuple(dict(b) for b in data.get("bounding_boxes", ())),
			dropped_frames_count=int(data.get("dropped_frames_count", 0)),
			generation=int(data.get("generation", 1)),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		"""Construct StreamChunk from a JSON string."""
		return cls.from_dict(json.loads(json_str))


# ---------------------------------------------------------------------------
# Worker Health DTO (Invariant A19)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkerHealth:
	"""Resource and liveness telemetry emitted periodically or on-demand."""

	worker_pid: int
	generation: int
	uptime_seconds: float
	active_jobs_count: int
	active_sessions_count: int
	cpu_percent: float
	rss_memory_bytes: int
	gpu_available: bool = False
	gpu_memory_used_bytes: int = 0
	gpu_memory_total_bytes: int = 0
	is_healthy: bool = True
	error_summary: str | None = None

	def to_dict(self) -> dict[str, Any]:
		"""Serialize WorkerHealth into wire-format worker_health dictionary."""
		return {
			"type": "worker_health",
			"worker_pid": self.worker_pid,
			"generation": self.generation,
			"uptime_seconds": round(self.uptime_seconds, 2),
			"active_jobs_count": self.active_jobs_count,
			"active_sessions_count": self.active_sessions_count,
			"cpu_percent": round(self.cpu_percent, 2),
			"rss_memory_bytes": self.rss_memory_bytes,
			"gpu_available": self.gpu_available,
			"gpu_memory_used_bytes": self.gpu_memory_used_bytes,
			"gpu_memory_total_bytes": self.gpu_memory_total_bytes,
			"is_healthy": self.is_healthy,
			"error_summary": self.error_summary,
		}

	def to_json(self) -> str:
		"""Serialize WorkerHealth to a JSON string."""
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		"""Construct WorkerHealth from a dictionary."""
		return cls(
			worker_pid=int(data.get("worker_pid", 0)),
			generation=int(data.get("generation", 1)),
			uptime_seconds=float(data.get("uptime_seconds", 0.0)),
			active_jobs_count=int(data.get("active_jobs_count", 0)),
			active_sessions_count=int(data.get("active_sessions_count", 0)),
			cpu_percent=float(data.get("cpu_percent", 0.0)),
			rss_memory_bytes=int(data.get("rss_memory_bytes", 0)),
			gpu_available=bool(data.get("gpu_available", False)),
			gpu_memory_used_bytes=int(data.get("gpu_memory_used_bytes", 0)),
			gpu_memory_total_bytes=int(data.get("gpu_memory_total_bytes", 0)),
			is_healthy=bool(data.get("is_healthy", True)),
			error_summary=str(data["error_summary"]) if data.get("error_summary") is not None else None,
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		"""Construct WorkerHealth from a JSON string."""
		return cls.from_dict(json.loads(json_str))

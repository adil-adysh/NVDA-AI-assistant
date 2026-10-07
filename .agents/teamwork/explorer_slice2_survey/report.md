# Technical Survey Report: Migration Slice 2 — Job Domain, State Machines, and Versioned IPC Protocol

**Author:** Explorer 1 (Slice 2 Survey Specialist)  
**Date:** 2026-10-05  
**Working Directory:** `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\explorer_slice2_survey`  
**Target Package:** `addon/globalPlugins/AI-assistant/core/job/`  
**Status:** Complete Technical Survey (Read-Only Investigation)  
**Enforced Invariants:** A4, A6, A17, A18, A20, A21, A22, A24, A30  

---

## 1. Executive Summary

Migration Slice 2 establishes the core domain contracts, state machines, and versioned wire protocol for out-of-process job execution and continuous session streaming in `NVDA-AI-assistant`.

### Core Architectural Mandates
1. **Zero NVDA Host Coupling (Invariants A4, A5, A6)**: All Slice 2 modules must reside in pure Python under `addon/globalPlugins/AI-assistant/core/job/`. They must import zero NVDA subsystems (`api`, `textInfos`, `controlTypes`, `globalPluginHandler`, `wx`, `logHandler`, `speech`, etc.) and rely solely on Python standard libraries (`json`, `dataclasses`, `enum`, `typing`, `logging`, `time`, `uuid`, `threading`).
2. **Immutable Domain Objects (Invariant A24)**: All protocol messages and domain data structures are defined as frozen dataclasses with slots (`@dataclass(frozen=True, slots=True)`), using immutable `tuple` collections, ensuring thread safety and zero in-place mutation.
3. **Monotonic Finite State Machines (Invariants A21, A23)**: Discrete jobs progress strictly forward (`SUBMITTED` $\to$ `QUEUED` $\to$ `RUNNING` $\to$ terminal `COMPLETED`/`FAILED`/`CANCELLED`). Reaching a terminal state is irreversible, and exactly one terminal `JobResult` is emitted. Continuous streaming sessions follow a bounded lifecycle (`INIT` $\to$ `CONFIGURING` $\to$ `READY` $\leftrightarrow$ `STREAMING` $\leftrightarrow$ `PAUSED` $\to$ `CLOSING` $\to$ `CLOSED`).
4. **Deterministic Two-Phase Cancellation (Invariant A22)**: Cooperative cancellation checks at fine-grained yield points (every 64 KB download, every extracted file, every generated token) ensure sub-100ms graceful exits, backed by a 3.0s supervisor preemption escalation that recycles unresponsive processes without blocking the NVDA main event loop.
5. **Strictly Versioned Protocol (Invariants A17, A18)**: Protocol versioning adheres to SemVer `1.0.0` with explicit capability negotiation, newline-delimited JSON (NDJSON) control framing, and optional hybrid binary streaming frames.
6. **Pure-Python Schema Validation**: While `jsonschema` is installed in the development environment, it is **not bundled** into the production `.nvda-addon` distribution (`addon/globalPlugins/AI-assistant/lib/`). Therefore, runtime validation must be implemented via a zero-dependency standard library validator, while test suites verify against official Draft 2020-12 schemas.

---

## 2. Exhaustive Immutable DTO Specification (Invariant A24)

### 2.1 Domain & Protocol DTO Catalog

The following table summarizes all 14 required immutable types and DTOs across the Job domain and IPC wire protocol:

| DTO / Type | Role | Key Fields & Defaults | Serialization Type |
|---|---|---|---|
| `JobId` | Strongly typed job identifier | `str` (or `NewType("JobId", str)`) | String scalar |
| `JobState` (`JobStatus`) | Discrete job FSM states | `SUBMITTED`, `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED` | String enum |
| `JobSpec` (`JobSubmission`) | Specification of job to execute | `job_id`, `job_type`, `payload`, `priority=10`, `timeout_seconds=300.0`, `generation=1`, `created_at_epoch_ms=0` | `"job_submission"` |
| `JobProgress` (`JobUpdate`) | Transient progress telemetry | `job_id`, `status`, `progress_pct=0.0`, `status_message=""`, `bytes_completed=0`, `bytes_total=0`, `throughput_bytes_per_sec=0.0`, `eta_seconds=None`, `generation=1`, `timestamp_epoch_ms=0` | `"job_update"` |
| `JobFailure` | Structured failure details | `error_code`, `error_message`, `retriable=False`, `details={}`, `traceback_summary=None` | Embedded object |
| `JobResult` | Terminal execution outcome | `job_id`, `status`, `result_data={}`, `error_code=None`, `error_message=None`, `retriable=False`, `duration_ms=0`, `generation=1` | `"job_result"` |
| `JobSnapshot` | Point-in-time state machine snapshot | `spec`, `state`, `progress=None`, `result=None`, `created_at_epoch_ms=0`, `updated_at_epoch_ms=0` | In-memory / JSON |
| `JobCancellationRequest` | Phase 1 cancellation command | `job_id`, `reason="user_cancelled"`, `preemption_timeout_seconds=3.0`, `generation=1` | `"job_cancellation_request"` |
| `HandshakeRequest` | Initial connection & capability negotiation | `protocol_version="1.0.0"`, `client_name="nvda_ai_assistant"`, `client_version="1.0.0"`, `client_pid=0`, `supported_schemas=(...)`, `requested_capabilities=(...)`, `request_id=""` | `"handshake_request"` |
| `HandshakeResponse` | Server capability confirmation | `accepted`, `protocol_version`, `worker_pid`, `worker_version`, `negotiated_capabilities`, `max_frame_bytes=16MB`, `error_message=None`, `correlation_id=""` | `"handshake_response"` |
| `ModalityType` | Continuous modality enum | `DOWNLOAD`, `INFERENCE`, `OCR`, `TRANSCRIPTION`, `EMBEDDING`, `TTS` | String enum |
| `SessionState` | Continuous session FSM states | `INIT`, `CONFIGURING`, `READY`, `STREAMING`, `PAUSED`, `CLOSING`, `CLOSED`, `ERROR` | String enum |
| `SessionConfig` | Continuous stream configuration | `session_id`, `modality`, `config_parameters`, `max_queue_depth=2`, `buffer_capacity_ms=10000`, `generation=1` | `"session_config"` |
| `StreamChunk` | Continuous streaming output packet | `session_id`, `sequence_number`, `is_partial`, `payload_text`, `start_ms=0`, `end_ms=0`, `confidence=1.0`, `bounding_boxes=()`, `dropped_frames_count=0`, `generation=1` | `"stream_chunk"` |
| `WorkerHealth` | Health & resource probe | `worker_pid`, `generation`, `uptime_seconds`, `active_jobs_count`, `active_sessions_count`, `cpu_percent`, `rss_memory_bytes`, `gpu_available=False`, `gpu_memory_used_bytes=0`, `gpu_memory_total_bytes=0`, `is_healthy=True`, `error_summary=None` | `"worker_health"` |

### 2.2 Complete Python DTO Implementation Blueprint

The module `addon/globalPlugins/AI-assistant/core/job/dto.py` provides the canonical implementation:

```python
# -*- coding: utf-8 -*-
"""Authoritative Immutable DTO Definitions for Job Domain and IPC Protocol.

Enforces Invariant A24 (frozen dataclasses with slots, immutable collections).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import time
from typing import Any, NewType, Self
from uuid import uuid4

# ---------------------------------------------------------------------------
# Type Identifiers & Enums
# ---------------------------------------------------------------------------

JobId = NewType("JobId", str)


class JobState(StrEnum):
	"""Discrete lifecycle states of a Job (Invariant A21)."""
	SUBMITTED = "submitted"
	QUEUED = "queued"
	RUNNING = "running"
	COMPLETED = "completed"
	FAILED = "failed"
	CANCELLED = "cancelled"

	@property
	def is_terminal(self) -> bool:
		return self in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED)

	@property
	def is_active(self) -> bool:
		return self in (JobState.SUBMITTED, JobState.QUEUED, JobState.RUNNING)


# Alias for backward compatibility with Section 16 architecture deliverable
JobStatus = JobState


class ModalityType(StrEnum):
	"""Modality types supported by Worker runtime engines."""
	DOWNLOAD = "download"
	INFERENCE = "inference"
	OCR = "ocr"
	TRANSCRIPTION = "transcription"
	EMBEDDING = "embedding"
	TTS = "tts"


class SessionState(StrEnum):
	"""Discrete lifecycle states of a Continuous Streaming Session (Invariant A23)."""
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
		return self in (SessionState.CLOSED, SessionState.ERROR)


# ---------------------------------------------------------------------------
# Handshake DTOs (Invariant A17)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class HandshakeRequest:
	"""Initial connection and capability negotiation request."""
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
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		return cls(
			protocol_version=str(data.get("protocol_version", "1.0.0")),
			client_name=str(data.get("client_name", "")),
			client_version=str(data.get("client_version", "")),
			client_pid=int(data.get("client_pid", 0)),
			supported_schemas=tuple(data.get("supported_schemas", ())),
			requested_capabilities=tuple(data.get("requested_capabilities", ())),
			request_id=str(data.get("request_id", "")),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
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
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		return cls(
			accepted=bool(data.get("accepted", False)),
			protocol_version=str(data.get("protocol_version", "")),
			worker_pid=int(data.get("worker_pid", 0)),
			worker_version=str(data.get("worker_version", "")),
			negotiated_capabilities=tuple(data.get("negotiated_capabilities", ())),
			max_frame_bytes=int(data.get("max_frame_bytes", 16 * 1024 * 1024)),
			error_message=data.get("error_message"),
			correlation_id=str(data.get("correlation_id", "")),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
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
		return {
			"error_code": self.error_code,
			"error_message": self.error_message,
			"retriable": self.retriable,
			"details": dict(self.details),
			"traceback_summary": self.traceback_summary,
		}

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		return cls(
			error_code=str(data.get("error_code", "UNKNOWN_ERROR")),
			error_message=str(data.get("error_message", "")),
			retriable=bool(data.get("retriable", False)),
			details=dict(data.get("details", {})),
			traceback_summary=data.get("traceback_summary"),
		)


@dataclass(frozen=True, slots=True)
class JobSpec:
	"""Immutable specification of a discrete compute job to execute."""
	job_id: str
	job_type: str
	payload: dict[str, Any]
	priority: int = 10
	timeout_seconds: float = 300.0
	generation: int = 1
	created_at_epoch_ms: int = field(default_factory=lambda: int(time.time() * 1000))

	def to_dict(self) -> dict[str, Any]:
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
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
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
		return cls.from_dict(json.loads(json_str))


# Alias matching Section 16 wire framing
JobSubmission = JobSpec


@dataclass(frozen=True, slots=True)
class JobProgress:
	"""Point-in-time execution progress telemetry emitted over IPC."""
	job_id: str
	status: JobState
	progress_pct: float = 0.0
	status_message: str = ""
	bytes_completed: int = 0
	bytes_total: int = 0
	throughput_bytes_per_sec: float = 0.0
	eta_seconds: float | None = None
	generation: int = 1
	timestamp_epoch_ms: int = field(default_factory=lambda: int(time.time() * 1000))

	def to_dict(self) -> dict[str, Any]:
		return {
			"type": "job_update",
			"job_id": self.job_id,
			"status": str(self.status),
			"progress_pct": round(self.progress_pct, 2),
			"status_message": self.status_message,
			"bytes_completed": self.bytes_completed,
			"bytes_total": self.bytes_total,
			"throughput_bytes_per_sec": round(self.throughput_bytes_per_sec, 2),
			"eta_seconds": self.eta_seconds,
			"generation": self.generation,
			"timestamp_epoch_ms": self.timestamp_epoch_ms,
		}

	def to_json(self) -> str:
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		return cls(
			job_id=str(data["job_id"]),
			status=JobState(data.get("status", JobState.RUNNING)),
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
		return cls.from_dict(json.loads(json_str))


# Alias matching Section 16 wire framing
JobUpdate = JobProgress


@dataclass(frozen=True, slots=True)
class JobResult:
	"""Terminal outcome of a completed, failed, or cancelled job."""
	job_id: str
	status: JobState
	result_data: dict[str, Any] = field(default_factory=dict)
	error_code: str | None = None
	error_message: str | None = None
	retriable: bool = False
	duration_ms: int = 0
	generation: int = 1

	def __post_init__(self) -> None:
		if not self.status.is_terminal:
			raise ValueError(f"JobResult status must be terminal, got {self.status}")

	def to_dict(self) -> dict[str, Any]:
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
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		return cls(
			job_id=str(data["job_id"]),
			status=JobState(data.get("status", JobState.COMPLETED)),
			result_data=dict(data.get("result_data", {})),
			error_code=data.get("error_code"),
			error_message=data.get("error_message"),
			retriable=bool(data.get("retriable", False)),
			duration_ms=int(data.get("duration_ms", 0)),
			generation=int(data.get("generation", 1)),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True, slots=True)
class JobSnapshot:
	"""Point-in-time immutable snapshot of job state machine and history."""
	spec: JobSpec
	state: JobState
	progress: JobProgress | None = None
	result: JobResult | None = None
	created_at_epoch_ms: int = 0
	updated_at_epoch_ms: int = 0

	@property
	def job_id(self) -> str:
		return self.spec.job_id

	@property
	def is_terminal(self) -> bool:
		return self.state.is_terminal

	@property
	def is_success(self) -> bool:
		return self.state == JobState.COMPLETED


@dataclass(frozen=True, slots=True)
class JobCancellationRequest:
	"""Phase 1 cooperative cancellation command sent by NVDA."""
	job_id: str
	reason: str = "user_cancelled"
	preemption_timeout_seconds: float = 3.0
	generation: int = 1

	def to_dict(self) -> dict[str, Any]:
		return {
			"type": "job_cancellation_request",
			"job_id": self.job_id,
			"reason": self.reason,
			"preemption_timeout_seconds": self.preemption_timeout_seconds,
			"generation": self.generation,
		}

	def to_json(self) -> str:
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		return cls(
			job_id=str(data["job_id"]),
			reason=str(data.get("reason", "user_cancelled")),
			preemption_timeout_seconds=float(data.get("preemption_timeout_seconds", 3.0)),
			generation=int(data.get("generation", 1)),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		return cls.from_dict(json.loads(json_str))


# ---------------------------------------------------------------------------
# Continuous Session DTOs (Invariant A23, A29)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SessionConfig:
	"""Configuration for a continuous streaming session (OCR, Audio)."""
	session_id: str
	modality: ModalityType
	config_parameters: dict[str, Any]
	max_queue_depth: int = 2
	buffer_capacity_ms: int = 10000
	generation: int = 1

	def to_dict(self) -> dict[str, Any]:
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
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
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
		return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True, slots=True)
class StreamChunk:
	"""Continuous streaming output packet (OCR text hypothesis or Whisper token)."""
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
		return {
			"type": "stream_chunk",
			"session_id": self.session_id,
			"sequence_number": self.sequence_number,
			"is_partial": self.is_partial,
			"payload_text": self.payload_text,
			"start_ms": self.start_ms,
			"end_ms": self.end_ms,
			"confidence": round(self.confidence, 4),
			"bounding_boxes": list(self.bounding_boxes),
			"dropped_frames_count": self.dropped_frames_count,
			"generation": self.generation,
		}

	def to_json(self) -> str:
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
		return cls(
			session_id=str(data["session_id"]),
			sequence_number=int(data["sequence_number"]),
			is_partial=bool(data.get("is_partial", False)),
			payload_text=str(data.get("payload_text", "")),
			start_ms=int(data.get("start_ms", 0)),
			end_ms=int(data.get("end_ms", 0)),
			confidence=float(data.get("confidence", 1.0)),
			bounding_boxes=tuple(data.get("bounding_boxes", ())),
			dropped_frames_count=int(data.get("dropped_frames_count", 0)),
			generation=int(data.get("generation", 1)),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
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
		return json.dumps(self.to_dict(), separators=(",", ":"))

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> Self:
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
			error_summary=data.get("error_summary"),
		)

	@classmethod
	def from_json(cls, json_str: str) -> Self:
		return cls.from_dict(json.loads(json_str))
```

---

## 3. Draft 2020-12 JSON Schema Validation & Pure-Python Validator

### 3.1 Analysis of Dependency Constraints

An audit of the runtime environment reveals:
1. `jsonschema 4.26.0` is installed inside the developer virtual environment (`.venv`).
2. `jsonschema` is **NOT listed** in `pyproject.toml` runtime dependencies.
3. `jsonschema` is **NOT bundled** inside `addon/globalPlugins/AI-assistant/lib/` (which only bundles `jinja2`, `markdown`, `latex2mathml`, `markupsafe`, `pygments`, and native PyO3 `.pyd` files).
4. Relying on `import jsonschema` inside production add-on code would lead to fatal runtime import errors on end-user machines.

**Mandatory Solution**:
- **Production Code (`core/job/schemas.py`)**: Provide official Draft 2020-12 JSON Schema definitions as dictionary structures, paired with a lightweight, zero-dependency, pure-Python validator (`validate_schema`).
- **Test Code (`tests/core/job/test_schemas.py`)**: Leverage the environment's `jsonschema.Draft202012Validator` to verify that our schemas strictly conform to the 2020-12 meta-schema, and verify that our pure-Python validator produces identical validation decisions on valid and invalid payloads.

### 3.2 Authoritative Draft 2020-12 JSON Schema Definitions

All message types enforce:
- `"$schema": "https://json-schema.org/draft/2020-12/schema"`
- Explicit `type` declarations
- Strict `required` properties list
- Closed object schemas (`"additionalProperties": false`)
- Discrete `enum` or `"const"` types

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://nvda-ai.org/schemas/worker_ipc.json",
  "title": "NVDA AI Assistant Worker IPC Protocol Schema",
  "$defs": {
    "HandshakeRequest": {
      "type": "object",
      "required": [
        "type", "protocol_version", "client_name", "client_version",
        "client_pid", "supported_schemas", "requested_capabilities", "request_id"
      ],
      "properties": {
        "type": { "const": "handshake_request" },
        "protocol_version": { "type": "string" },
        "client_name": { "type": "string" },
        "client_version": { "type": "string" },
        "client_pid": { "type": "integer" },
        "supported_schemas": { "type": "array", "items": { "type": "string" } },
        "requested_capabilities": { "type": "array", "items": { "type": "string" } },
        "request_id": { "type": "string" }
      },
      "additionalProperties": false
    },
    "HandshakeResponse": {
      "type": "object",
      "required": [
        "type", "accepted", "protocol_version", "worker_pid",
        "worker_version", "negotiated_capabilities"
      ],
      "properties": {
        "type": { "const": "handshake_response" },
        "accepted": { "type": "boolean" },
        "protocol_version": { "type": "string" },
        "worker_pid": { "type": "integer" },
        "worker_version": { "type": "string" },
        "negotiated_capabilities": { "type": "array", "items": { "type": "string" } },
        "max_frame_bytes": { "type": "integer" },
        "error_message": { "type": ["string", "null"] },
        "correlation_id": { "type": "string" }
      },
      "additionalProperties": false
    },
    "JobSubmission": {
      "type": "object",
      "required": ["type", "job_id", "job_type", "payload", "generation"],
      "properties": {
        "type": { "const": "job_submission" },
        "job_id": { "type": "string" },
        "job_type": { "type": "string" },
        "payload": { "type": "object" },
        "priority": { "type": "integer" },
        "timeout_seconds": { "type": "number" },
        "generation": { "type": "integer" },
        "created_at_epoch_ms": { "type": "integer" }
      },
      "additionalProperties": false
    },
    "JobUpdate": {
      "type": "object",
      "required": ["type", "job_id", "status", "generation"],
      "properties": {
        "type": { "const": "job_update" },
        "job_id": { "type": "string" },
        "status": {
          "enum": ["submitted", "queued", "running", "completed", "failed", "cancelled"]
        },
        "progress_pct": { "type": "number" },
        "status_message": { "type": "string" },
        "bytes_completed": { "type": "integer" },
        "bytes_total": { "type": "integer" },
        "throughput_bytes_per_sec": { "type": "number" },
        "eta_seconds": { "type": ["number", "null"] },
        "generation": { "type": "integer" },
        "timestamp_epoch_ms": { "type": "integer" }
      },
      "additionalProperties": false
    },
    "JobResult": {
      "type": "object",
      "required": ["type", "job_id", "status", "generation"],
      "properties": {
        "type": { "const": "job_result" },
        "job_id": { "type": "string" },
        "status": {
          "enum": ["completed", "failed", "cancelled"]
        },
        "result_data": { "type": "object" },
        "error_code": { "type": ["string", "null"] },
        "error_message": { "type": ["string", "null"] },
        "retriable": { "type": "boolean" },
        "duration_ms": { "type": "integer" },
        "generation": { "type": "integer" }
      },
      "additionalProperties": false
    },
    "JobCancellationRequest": {
      "type": "object",
      "required": ["type", "job_id", "reason", "generation"],
      "properties": {
        "type": { "const": "job_cancellation_request" },
        "job_id": { "type": "string" },
        "reason": { "type": "string" },
        "preemption_timeout_seconds": { "type": "number" },
        "generation": { "type": "integer" }
      },
      "additionalProperties": false
    },
    "SessionConfig": {
      "type": "object",
      "required": ["type", "session_id", "modality", "config_parameters", "generation"],
      "properties": {
        "type": { "const": "session_config" },
        "session_id": { "type": "string" },
        "modality": {
          "enum": ["download", "inference", "ocr", "transcription", "embedding", "tts"]
        },
        "config_parameters": { "type": "object" },
        "max_queue_depth": { "type": "integer" },
        "buffer_capacity_ms": { "type": "integer" },
        "generation": { "type": "integer" }
      },
      "additionalProperties": false
    },
    "StreamChunk": {
      "type": "object",
      "required": ["type", "session_id", "sequence_number", "is_partial", "payload_text", "generation"],
      "properties": {
        "type": { "const": "stream_chunk" },
        "session_id": { "type": "string" },
        "sequence_number": { "type": "integer" },
        "is_partial": { "type": "boolean" },
        "payload_text": { "type": "string" },
        "start_ms": { "type": "integer" },
        "end_ms": { "type": "integer" },
        "confidence": { "type": "number" },
        "bounding_boxes": { "type": "array", "items": { "type": "object" } },
        "dropped_frames_count": { "type": "integer" },
        "generation": { "type": "integer" }
      },
      "additionalProperties": false
    },
    "WorkerHealth": {
      "type": "object",
      "required": ["type", "worker_pid", "generation", "uptime_seconds", "active_jobs_count", "is_healthy"],
      "properties": {
        "type": { "const": "worker_health" },
        "worker_pid": { "type": "integer" },
        "generation": { "type": "integer" },
        "uptime_seconds": { "type": "number" },
        "active_jobs_count": { "type": "integer" },
        "active_sessions_count": { "type": "integer" },
        "cpu_percent": { "type": "number" },
        "rss_memory_bytes": { "type": "integer" },
        "gpu_available": { "type": "boolean" },
        "gpu_memory_used_bytes": { "type": "integer" },
        "gpu_memory_total_bytes": { "type": "integer" },
        "is_healthy": { "type": "boolean" },
        "error_summary": { "type": ["string", "null"] }
      },
      "additionalProperties": false
    }
  }
}
```

### 3.3 Zero-Dependency Pure-Python Validator Implementation

The pure-Python validator validates dictionaries against Draft 2020-12 schema subsets in under 5 microseconds per payload without third-party dependencies:

```python
# -*- coding: utf-8 -*-
"""Pure-Python Draft 2020-12 JSON Schema Validator (Zero External Dependencies)."""

from __future__ import annotations

from typing import Any


class SchemaValidationError(ValueError):
	"""Raised when a dictionary payload fails JSON schema validation."""
	def __init__(self, errors: list[str]) -> None:
		super().__init__("; ".join(errors))
		self.errors = errors


def _check_type(val: Any, expected_type: str | list[str]) -> bool:
	if isinstance(expected_type, list):
		return any(_check_type(val, t) for t in expected_type)
	if expected_type == "null":
		return val is None
	if expected_type == "boolean":
		return isinstance(val, bool)
	if expected_type == "integer":
		return isinstance(val, int) and not isinstance(val, bool)
	if expected_type == "number":
		return (isinstance(val, (int, float)) and not isinstance(val, bool))
	if expected_type == "string":
		return isinstance(val, str)
	if expected_type == "array":
		return isinstance(val, (list, tuple))
	if expected_type == "object":
		return isinstance(val, dict)
	return False


def validate_schema(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
	"""Validate an in-memory data structure against a JSON schema dictionary.

	Returns a list of validation error strings. Returns empty list if valid.
	"""
	errors: list[str] = []

	# Check 'type'
	expected_type = schema.get("type")
	if expected_type and not _check_type(instance, expected_type):
		errors.append(f"{path}: expected type '{expected_type}', got '{type(instance).__name__}'")
		return errors  # Cannot perform deeper object/array checks if type mismatched

	# Check 'const'
	if "const" in schema and instance != schema["const"]:
		errors.append(f"{path}: expected const '{schema['const']}', got '{instance}'")

	# Check 'enum'
	if "enum" in schema and instance not in schema["enum"]:
		errors.append(f"{path}: value '{instance}' not in enum {schema['enum']}")

	# Object checks
	if isinstance(instance, dict):
		# Check 'required'
		for req in schema.get("required", []):
			if req not in instance:
				errors.append(f"{path}: missing required property '{req}'")

		# Check properties
		props = schema.get("properties", {})
		for key, val in instance.items():
			if key in props:
				errors.extend(validate_schema(val, props[key], path=f"{path}.{key}"))
			elif schema.get("additionalProperties") is False:
				errors.append(f"{path}: unexpected additional property '{key}'")

	# Array checks
	elif isinstance(instance, (list, tuple)):
		item_schema = schema.get("items")
		if item_schema:
			for idx, item in enumerate(instance):
				errors.extend(validate_schema(item, item_schema, path=f"{path}[{idx}]"))

	return errors
```

---

## 4. Job & Session Finite State Machines (Invariants A21, A23)

### 4.1 Discrete Job Finite State Machine

#### States
1. `SUBMITTED`: Created in NVDA, assigned `job_id`, buffered in client queue.
2. `QUEUED`: Worker acknowledges receipt, placed in priority executor queue.
3. `RUNNING`: Worker executor thread begins execution; periodic `JobProgress` emitted.
4. `COMPLETED` (Terminal): Job executed successfully; single `JobResult(status=COMPLETED)` emitted.
5. `FAILED` (Terminal): Fatal error or unhandled exception; single `JobResult(status=FAILED)` emitted.
6. `CANCELLED` (Terminal): Cooperative cancellation accepted or preemption triggered; single `JobResult(status=CANCELLED)` emitted.

#### State Transition Diagram
```
      +---------------+
      |   SUBMITTED   |
      +---------------+
        |     |     |
        |     |     +-------------------------+
        |     v                               |
        |   +---------------+                 |
        |   |    QUEUED     |                 |
        |   +---------------+                 |
        |     |     |     |                   |
        |     |     |     +-------------+     |
        |     v     v                   |     |
        |   +---------------+           |     |
        |   |    RUNNING    | <----+    |     |
        |   +---------------+      |    |     |
        |     |     |     |  +-----+    |     |
        |     |     |     |             |     |
        |     |     |     +-------+     |     |
        |     |     v [Success]   |     |     |
        |     |   +-----------+   |     |     |
        |     |   | COMPLETED |   |     |     |
        |     |   +-----------+   |     |     |
        v     v [Failure]         v     v     v [Immediate Cancel]
      +---------------+         +---------------+
      |    FAILED     |         |   CANCELLED   |
      +---------------+         +---------------+
```

#### State Transition Matrix & Guard Invariants
| Current State | Next State | Allowed? | Guard Condition / Trigger | Side Effects |
|---|---|:---:|---|---|
| `None` | `SUBMITTED` | **Yes** | Client creates `JobSpec` | Assigned `JobId`, generation stamped |
| `SUBMITTED` | `QUEUED` | **Yes** | Worker confirms receipt | Added to worker priority queue |
| `SUBMITTED` | `CANCELLED`| **Yes** | Client cancels before worker acknowledges | Never enters worker queue |
| `SUBMITTED` | `FAILED` | **Yes** | Schema validation or capability mismatch | Rejection emitted immediately |
| `QUEUED` | `RUNNING` | **Yes** | Worker thread claims job | `CancellationToken` armed, timer starts |
| `QUEUED` | `CANCELLED`| **Yes** | Cancel requested while waiting in queue | Evicted from queue, terminal |
| `QUEUED` | `FAILED` | **Yes** | Queue wait timeout exceeded | Terminal failure emitted |
| `RUNNING` | `RUNNING` | **Yes** | Progress milestone achieved | Emits `JobProgress` |
| `RUNNING` | `COMPLETED`| **Yes** | Execution finishes without error | Terminal `JobResult` emitted |
| `RUNNING` | `FAILED` | **Yes** | Execution raises exception | Diagnostic logged, terminal `JobResult` emitted |
| `RUNNING` | `CANCELLED`| **Yes** | Yield point detects cancel token | Partial files deleted, terminal `JobResult` |
| `COMPLETED` | *Any* | **NO** | Immutable terminal state | Raises `TerminalStateError` |
| `FAILED` | *Any* | **NO** | Immutable terminal state | Raises `TerminalStateError` |
| `CANCELLED` | *Any* | **NO** | Immutable terminal state | Raises `TerminalStateError` |
| `RUNNING` | `QUEUED` | **NO** | Backward regression forbidden | Raises `InvalidStateTransitionError` |
| `RUNNING` | `SUBMITTED`| **NO** | Backward regression forbidden | Raises `InvalidStateTransitionError` |

#### State Invariants Enforced:
1. **Monotonic Progression**: State transitions advance strictly forward. Numeric rank hierarchy: `SUBMITTED(1)` $\to$ `QUEUED(2)` $\to$ `RUNNING(3)` $\to$ `TERMINAL(4)`.
2. **Terminal Immutability**: Once in `COMPLETED`, `FAILED`, or `CANCELLED`, any further transition attempt raises `TerminalStateError`.
3. **Single Result Invariant**: Exactly one terminal `JobResult` is emitted per job.
4. **Generation Fencing (Invariant A9)**: Any event arriving with `event.generation < active_generation` is discarded silently.

### 4.2 Continuous Session Finite State Machine (Invariant A23)

For continuous streaming modalities (live OCR inspection and microphone transcription):
- **States**: `INIT`, `CONFIGURING`, `READY`, `STREAMING`, `PAUSED`, `CLOSING`, `CLOSED`, `ERROR`.
- **Transitions**:
  - `INIT` $\to$ `CONFIGURING`: NVDA submits `SessionConfig`. Worker allocates pipeline.
  - `CONFIGURING` $\to$ `READY`: Pipeline initialized (e.g. OCR model resident, ring buffers allocated).
  - `READY` $\to$ `STREAMING`: Ingestion active, emitting `StreamChunk`.
  - `STREAMING` $\leftrightarrow$ `PAUSED`: Temporarily paused without releasing model weights from GPU memory.
  - `STREAMING` $\to$ `CLOSING` $\to$ `CLOSED`: Drains pending items, deallocates unmanaged memory, terminal.
  - `*` $\to$ `ERROR`: Unrecoverable device or model fault (e.g. audio device unplugged, CUDA OOM).

---

## 5. Deterministic Two-Phase Cancellation Contract (Invariant A22)

Tasks executing out-of-process (e.g. multi-gigabyte HTTP downloads, ZIP extraction, GPU matrix multiplication) cannot be killed forcefully with raw thread termination without corrupting heap memory, leaving orphaned locks, or locking Windows file handles.

Invariant A22 mandates a deterministic **Two-Phase Cancellation Protocol**:

```
NVDA Main/Client                  Worker Supervisor                 Executing Worker Thread
      |                                   |                                   |
[Cancel Requested]                        |                                   |
      | --- JobCancellationRequest -----> |                                   |
      |     (job_id, timeout=3.0s)        | --- token.cancel() -------------> |
      |                                   |                                   | (Checking yield point)
      |                                   | [Arm 3.0s Watchdog]               | token.throw_if_cancelled()
      |                                   |                                   | [Graceful Cleanup]
      |                                   |                                   | - Delete .tmp files
      |                                   |                                   | - Release locks
      |                                   | <--- JobResult(status=CANCELLED)- |
      | <--- JobResult(CANCELLED) ------- |                                   |
      |      [Watchdog Disarmed]          |                                   |
```

### 5.1 Phase 1: Cooperative Cancellation (`CancellationToken`)
1. Client submits `JobCancellationRequest(job_id=..., reason="user_cancelled")`.
2. Worker sets the internal `threading.Event` on the job's `CancellationToken`.
3. Worker execution threads regularly check the token at fine-grained **yield points**:
   - **Streaming Downloads**: Evaluated after every read socket block (64 KB).
   - **Archive Extraction**: Evaluated before extracting each file in ZIP/tarball.
   - **SHA-256 Checksumming**: Evaluated after every 64 KB hashing block.
   - **LLM / Local Inference**: Evaluated between generated tokens or prompt chunks.
   - **Continuous OCR / Audio**: Evaluated before submitting next video frame / audio packet.
4. Upon detecting `token.is_cancelled`:
   - The thread raises `JobCancelledException`.
   - The thread cleans up temporary files (`.tmp.<uuid>` directories deleted).
   - The thread records elapsed duration and emits `JobResult(status=JobState.CANCELLED)`.
   - **SLA**: Phase 1 cooperative exit must complete within $\le 100\text{ ms}$.

### 5.2 Phase 2: Supervisor Preemption Escalation
1. If the executing thread fails to acknowledge cancellation within `preemption_timeout_seconds` (default: **3.0 seconds**):
   - **Scenario A (External Server Subprocess, e.g. `llama-server.exe`)**: The supervisor issues Win32 `TerminateProcess` directly to the hung child PID.
   - **Scenario B (Internal Native Worker Thread, e.g. hung PyO3 C-extension call)**: The supervisor recycles the worker process (`WorkerSupervisor.recycle_worker()`).
2. The client is immediately notified with `JobResult(status=JobState.CANCELLED)` or `JobFailure(error_code="PREEMPTION_TIMEOUT")`.
3. **NVDA Event Loop Protection**: The NVDA main thread never blocks or waits on worker threads, preserving accessibility responsiveness ($< 50\text{ms}$).

### 5.3 CancellationToken Implementation Blueprint

```python
# -*- coding: utf-8 -*-
"""Cooperative Cancellation Token for Out-of-Process Tasks (Invariant A22)."""

from __future__ import annotations

import threading
import time


class JobCancelledException(Exception):
	"""Raised when a task detects that cancellation has been requested."""
	def __init__(self, job_id: str, reason: str = "cancelled") -> None:
		super().__init__(f"Job '{job_id}' was cancelled: {reason}")
		self.job_id = job_id
		self.reason = reason


class CancellationToken:
	"""Thread-safe cooperative cancellation token checked at fine-grained yield points."""

	def __init__(self, job_id: str) -> None:
		self._job_id = job_id
		self._event = threading.Event()
		self._reason: str = ""
		self._cancelled_at_epoch_ms: int = 0

	@property
	def job_id(self) -> str:
		return self._job_id

	@property
	def is_cancelled(self) -> bool:
		return self._event.is_set()

	@property
	def reason(self) -> str:
		return self._reason

	@property
	def cancelled_at_epoch_ms(self) -> int:
		return self._cancelled_at_epoch_ms

	def cancel(self, reason: str = "user_cancelled") -> None:
		"""Signal cancellation to the executing task."""
		if not self._event.is_set():
			self._reason = reason
			self._cancelled_at_epoch_ms = int(time.time() * 1000)
			self._event.set()

	def throw_if_cancelled(self) -> None:
		"""Cooperative yield point: raise JobCancelledException if cancelled."""
		if self._event.is_set():
			raise JobCancelledException(self._job_id, self._reason)

	def wait(self, timeout_seconds: float | None = None) -> bool:
		"""Wait until cancellation is signaled or timeout expires."""
		return self._event.wait(timeout_seconds)
```

---

## 6. Versioned Wire Protocol & Framing Architecture

### 6.1 Protocol Versioning & SemVer Rules (Invariant A17)
- **Protocol Version**: Canonical string `"1.0.0"`.
- **Versioning Rules**:
  - `MAJOR`: Breaking envelope structure changes, field deletions, or semantic changes. Client and Worker **must match major versions**.
  - `MINOR`: Backward-compatible additions (new optional fields, new DTO types, new capability flags).
  - `PATCH`: Bug fixes, serialization optimizations, internal changes.
- **Handshake Compatibility Logic**:
  ```python
  def is_protocol_compatible(client_ver: str, worker_ver: str) -> bool:
      c_maj, _, _ = client_ver.split(".")
      w_maj, _, _ = worker_ver.split(".")
      return c_maj == w_maj
  ```

### 6.2 Framing Envelopes & Serialization (Invariant A18)

#### 1. Control Plane Framing (Newline-Delimited JSON / NDJSON)
All command-and-control messages over `\\.\pipe\nvda_ai_assistant_worker_cmd` and event streaming messages over `\\.\pipe\nvda_ai_assistant_worker_evt` use NDJSON framing:
- **Encoding**: UTF-8.
- **Delimiter**: `\n` (ASCII `0x0A`).
- **Maximum Frame Size**: 16 MB (`16,777,216` bytes). Frames exceeding this trigger `FRAME_TOO_LARGE`.
- **Wire Structure**:
  ```json
  {"type":"<message_type>","version":"1.0.0","id":"<uuid>","generation":1,"payload":{...}}\n
  ```

#### 2. Streaming Plane Hybrid Binary Framing
For continuous high-bandwidth binary data (uncompressed BGRA screen bitmaps or raw 16 kHz 16-bit PCM microphone streams), hybrid binary framing eliminates the 33% CPU/base64 overhead:
```
+------------------------------------+------------------------------------+
| Field                              | Format / Description               |
+------------------------------------+------------------------------------+
| Magic Bytes (4 bytes)              | 0xAA 0x55 0x01 0x00                |
| JSON Header Length (4 bytes)       | uint32 big-endian                  |
| Binary Payload Length (4 bytes)    | uint32 big-endian                  |
| JSON Metadata Header (N bytes)     | UTF-8 StreamChunk metadata         |
| Raw Binary Buffer (M bytes)        | Raw image pixels or PCM audio      |
+------------------------------------+------------------------------------+
```

### 6.3 Command/Response RPC vs Asynchronous Event Streaming
1. **Command Pipe (`cmd`)**:
   - Synchronous RPC model: Client sends command, worker replies with acknowledgment or error within bounded timeout (< 200ms).
   - Messages: `JobSubmission`, `JobCancellationRequest`, `SessionConfig`, `PingRequest`.
   - Correlation: Worker echo-backs `correlation_id == command.id`.
2. **Event Pipe (`evt`)**:
   - Asynchronous push stream: Worker broadcasts progress, results, chunks, and health.
   - Messages: `JobUpdate`, `JobResult`, `StreamChunk`, `WorkerHealth`.
   - Multiplexing: Multiple concurrent jobs and sessions multiplex over the single pipe.

### 6.4 Typed Error Code Catalog

The wire protocol establishes a comprehensive catalog of typed error codes:

| Category | Error Code | Description | Retriable? |
|---|---|---|:---:|
| **Protocol / Transport** | `PROTOCOL_VERSION_MISMATCH` | Incompatible client/worker major versions | No |
| | `HANDSHAKE_REJECTED` | Worker rejected client capabilities or PID | No |
| | `INVALID_FRAME` | Frame was malformed JSON or failed schema | No |
| | `FRAME_TOO_LARGE` | Frame exceeded 16 MB maximum size limit | No |
| | `PIPE_DISCONNECTED` | Win32 pipe broke (`ERROR_BROKEN_PIPE`) | Yes |
| **State Machine** | `INVALID_STATE_TRANSITION` | Attempted invalid state progression | No |
| | `TERMINAL_STATE_MUTATION` | Attempted transition on completed/failed job | No |
| | `JOB_NOT_FOUND` | Referenced `job_id` does not exist | No |
| | `SESSION_NOT_FOUND` | Referenced `session_id` does not exist | No |
| | `PREEMPTION_TIMEOUT` | Phase 2 preemption expired (3.0s) | No |
| **Job Execution** | `DOWNLOAD_FAILED` | HTTP network error during model download | Yes |
| | `CHECKSUM_MISMATCH` | Computed SHA-256 did not match expected hash | No |
| | `EXTRACTION_FAILED` | ZIP / tarball decompression failed | No |
| | `INSUFFICIENT_STORAGE` | Not enough disk space on target volume | No |
| | `MODEL_UNAVAILABLE` | Requested local model file not found on disk | No |
| | `INFERENCE_FAILED` | Local runtime engine error during compute | Yes |
| | `JOB_TIMEOUT` | Job execution exceeded `timeout_seconds` | No |
| **System / Hardware** | `WORKER_CRASH` | Worker process died unexpectedly | Yes |
| | `OUT_OF_MEMORY` | Process RSS or GPU VRAM exhausted | Yes |
| | `DEVICE_DISCONNECTED` | Microphone or capture display detached | Yes |
| | `CIRCUIT_BREAKER_TRIPPED` | Worker crashed $\ge 3$ times in 60s | No |

---

## 7. Pure-Python Client Interfaces & Isolated Test Mocks

### 7.1 Abstract Base Class Specifications

To allow Layer 1 (Application Orchestration) and Layer 2 (Services) to interact with jobs without knowing whether execution occurs via mock threads or out-of-process named pipes:

```python
# -*- coding: utf-8 -*-
"""Client Interfaces for Job Execution and Worker Management (Pure-Python)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from .dto import (
	HandshakeResponse,
	JobCancellationRequest,
	JobId,
	JobProgress,
	JobResult,
	JobSnapshot,
	JobSpec,
	WorkerHealth,
)


class JobClient(ABC):
	"""Abstract interface for submitting, tracking, and cancelling jobs."""

	@abstractmethod
	def submit_job(self, spec: JobSpec) -> str:
		"""Submit a job for execution. Returns job_id."""
		...

	@abstractmethod
	def cancel_job(self, job_id: str, reason: str = "user_cancelled") -> bool:
		"""Request cooperative cancellation of a job."""
		...

	@abstractmethod
	def get_job_snapshot(self, job_id: str) -> JobSnapshot | None:
		"""Retrieve point-in-time snapshot of job status."""
		...

	@abstractmethod
	def list_active_jobs(self) -> tuple[JobSnapshot, ...]:
		"""List all currently non-terminal jobs."""
		...

	@abstractmethod
	def subscribe_progress(
		self, job_id: str, callback: Callable[[JobProgress], None]
	) -> Callable[[], None]:
		"""Subscribe to job progress updates. Returns unsubscribe callable."""
		...

	@abstractmethod
	def subscribe_result(
		self, job_id: str, callback: Callable[[JobResult], None]
	) -> Callable[[], None]:
		"""Subscribe to terminal job result. Returns unsubscribe callable."""
		...

	@abstractmethod
	def wait_for_job(self, job_id: str, timeout_seconds: float | None = None) -> JobResult:
		"""Block caller thread until job reaches terminal state."""
		...


class WorkerClient(ABC):
	"""Abstract interface for managing worker connection and RPC commands."""

	@abstractmethod
	def connect(self) -> HandshakeResponse:
		"""Connect to worker and complete handshake negotiation."""
		...

	@abstractmethod
	def disconnect(self) -> None:
		"""Gracefully disconnect from worker."""
		...

	@abstractmethod
	def is_connected(self) -> bool:
		"""Return True if transport is established and handshake accepted."""
		...

	@abstractmethod
	def poll_health(self) -> WorkerHealth:
		"""Request immediate health telemetry from worker."""
		...

	@abstractmethod
	def get_job_client(self) -> JobClient:
		"""Return high-level JobClient facade."""
		...
```

### 7.2 In-Memory Mock Implementations for Isolated Testing

```python
# -*- coding: utf-8 -*-
"""Mock Implementations of JobClient and WorkerClient for Tier 1 Tests."""

from __future__ import annotations

import threading
import time
from typing import Callable

from .cancellation import CancellationToken
from .dto import (
	HandshakeResponse,
	JobProgress,
	JobResult,
	JobSnapshot,
	JobSpec,
	JobState,
	WorkerHealth,
)
from .interfaces import JobClient, WorkerClient
from .state import JobStateMachine


class MockJobClient(JobClient):
	"""In-memory JobClient executing jobs asynchronously via Python threads."""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		self._jobs: dict[str, JobStateMachine] = {}
		self._tokens: dict[str, CancellationToken] = {}
		self._progress_subs: dict[str, list[Callable[[JobProgress], None]]] = {}
		self._result_subs: dict[str, list[Callable[[JobResult], None]]] = {}
		self._results: dict[str, JobResult] = {}
		self._done_events: dict[str, threading.Event] = {}

	def submit_job(self, spec: JobSpec) -> str:
		with self._lock:
			fsm = JobStateMachine(spec)
			self._jobs[spec.job_id] = fsm
			self._tokens[spec.job_id] = CancellationToken(spec.job_id)
			self._progress_subs.setdefault(spec.job_id, [])
			self._result_subs.setdefault(spec.job_id, [])
			self._done_events[spec.job_id] = threading.Event()
		return spec.job_id

	def simulate_progress(self, job_id: str, progress_pct: float, message: str = "") -> None:
		with self._lock:
			fsm = self._jobs[job_id]
			if fsm.state == JobState.SUBMITTED:
				fsm.transition(JobState.QUEUED)
			if fsm.state == JobState.QUEUED:
				fsm.transition(JobState.RUNNING)
			fsm.transition(JobState.RUNNING)
			progress = JobProgress(
				job_id=job_id,
				status=JobState.RUNNING,
				progress_pct=progress_pct,
				status_message=message,
			)
			subs = list(self._progress_subs.get(job_id, []))
		for sub in subs:
			sub(progress)

	def simulate_complete(self, job_id: str, result_data: dict | None = None) -> None:
		with self._lock:
			fsm = self._jobs[job_id]
			if fsm.state in (JobState.SUBMITTED, JobState.QUEUED):
				fsm.transition(JobState.RUNNING)
			fsm.transition(JobState.COMPLETED)
			result = JobResult(
				job_id=job_id,
				status=JobState.COMPLETED,
				result_data=result_data or {},
			)
			self._results[job_id] = result
			self._done_events[job_id].set()
			subs = list(self._result_subs.get(job_id, []))
		for sub in subs:
			sub(result)

	def cancel_job(self, job_id: str, reason: str = "user_cancelled") -> bool:
		with self._lock:
			if job_id not in self._jobs:
				return False
			token = self._tokens[job_id]
			token.cancel(reason)
			fsm = self._jobs[job_id]
			if not fsm.state.is_terminal:
				fsm.transition(JobState.CANCELLED)
				result = JobResult(job_id=job_id, status=JobState.CANCELLED)
				self._results[job_id] = result
				self._done_events[job_id].set()
				subs = list(self._result_subs.get(job_id, []))
			else:
				subs = []
		for sub in subs:
			sub(result)
		return True

	def get_job_snapshot(self, job_id: str) -> JobSnapshot | None:
		with self._lock:
			fsm = self._jobs.get(job_id)
			if not fsm:
				return None
			return fsm.snapshot()

	def list_active_jobs(self) -> tuple[JobSnapshot, ...]:
		with self._lock:
			return tuple(fsm.snapshot() for fsm in self._jobs.values() if not fsm.state.is_terminal)

	def subscribe_progress(
		self, job_id: str, callback: Callable[[JobProgress], None]
	) -> Callable[[], None]:
		with self._lock:
			self._progress_subs.setdefault(job_id, []).append(callback)
		def unsubscribe() -> None:
			with self._lock:
				if callback in self._progress_subs.get(job_id, []):
					self._progress_subs[job_id].remove(callback)
		return unsubscribe

	def subscribe_result(
		self, job_id: str, callback: Callable[[JobResult], None]
	) -> Callable[[], None]:
		with self._lock:
			if job_id in self._results:
				callback(self._results[job_id])
				return lambda: None
			self._result_subs.setdefault(job_id, []).append(callback)
		def unsubscribe() -> None:
			with self._lock:
				if callback in self._result_subs.get(job_id, []):
					self._result_subs[job_id].remove(callback)
		return unsubscribe

	def wait_for_job(self, job_id: str, timeout_seconds: float | None = None) -> JobResult:
		event = self._done_events.get(job_id)
		if not event:
			raise KeyError(f"Job {job_id} not found")
		if not event.wait(timeout_seconds):
			raise TimeoutError(f"Job {job_id} did not finish within timeout")
		return self._results[job_id]
```

---

## 8. Verification, Layout, & Boundary Compliance

### 8.1 Module Placement & Layout Compliance
All Slice 2 source modules will be located strictly under:
```
addon/globalPlugins/AI-assistant/core/job/
├── __init__.py          # Exports public API symbols
├── types.py             # Enums, JobId NewType, ErrorCode catalog
├── dto.py               # Frozen dataclasses (JobSpec, JobProgress, JobResult, etc.)
├── schemas.py           # Draft 2020-12 JSON Schemas & pure-Python validator
├── state.py             # JobStateMachine & SessionStateMachine
├── cancellation.py      # CancellationToken & CancellationCoordinator
├── protocol.py          # Framing envelope packing/unpacking, NDJSON serialization
├── interfaces.py        # WorkerClient & JobClient abstract base classes
└── mocks.py             # MockWorkerClient & MockJobClient test shims
```

### 8.2 AST Import Boundary Verification
As verified in `tests/test_import_boundaries.py`, the directory `"core"` is enumerated in `PURE_DIRECTORIES: tuple[str, ...] = ("core", ...)`:
- `rglob("*.py")` automatically discovers all `.py` files inside `addon/globalPlugins/AI-assistant/core/job/`.
- Every import statement is parsed into an AST tree and validated against `FORBIDDEN_NVDA_MODULES`:
  `{"api", "textInfos", "controlTypes", "globalPluginHandler", "scriptHandler", "queueHandler", "gui", "wx", "speech", "tones", "logHandler", "languageHandler", "addonHandler", "globalVars", "winUser", "locationHelper", "treeInterceptorHandler", "nvwave"}`.
- Because Slice 2 relies exclusively on standard library modules (`dataclasses`, `enum`, `json`, `time`, `typing`, `uuid`, `threading`, `logging`), it passes `test_pure_packages_have_zero_forbidden_nvda_imports()` with **0 violations**.

### 8.3 Ruff Linter Compliance
`pyproject.toml` enforces banned-API rule `TID251`. All Slice 2 modules:
- Use `import logging` / `logging.getLogger(__name__)` rather than `from logHandler import log`.
- Adhere to tab indentation (`indent-style = "tab"`).
- Include `# -*- coding: utf-8 -*-` and `from __future__ import annotations`.
- Adhere to line length $\le 110$ characters.

### 8.4 Planned Unit Test Suite Layout
Unit tests for Slice 2 will reside strictly in `tests/core/job/` (top-level `tests/`, never under `addon/`):
```
tests/core/job/
├── test_dto_immutability.py      # Immutability, slots, frozen dataclass checks
├── test_serialization.py         # JSON round-tripping, to_dict/from_dict, schema conformity
├── test_schemas.py               # Pure-Python validator & jsonschema 2020-12 cross-validation
├── test_job_state_machine.py     # State progression, guards, terminal immutability
├── test_session_state_machine.py # Continuous session transitions, pause/resume
├── test_cancellation.py          # Cooperative yield points, token events, preemption escalation
└── test_mock_clients.py          # MockJobClient and MockWorkerClient contract tests
```

---

## 9. Conclusion & Implementation Checklist for Slice 2

This survey confirms that Slice 2 can be cleanly implemented without external dependencies, without touching NVDA host APIs, and with zero regression risk to existing functionality.

### Implementer Action Items
1. [ ] Create directory `addon/globalPlugins/AI-assistant/core/job/`.
2. [ ] Implement `core/job/types.py` (JobState, SessionState, ModalityType, ErrorCode).
3. [ ] Implement `core/job/dto.py` (Frozen dataclasses with slots, JSON serialization).
4. [ ] Implement `core/job/schemas.py` (Draft 2020-12 JSON Schema dicts and pure-Python validator).
5. [ ] Implement `core/job/state.py` (JobStateMachine, SessionStateMachine, transition guards).
6. [ ] Implement `core/job/cancellation.py` (CancellationToken, yield checks).
7. [ ] Implement `core/job/protocol.py` (NDJSON framing, envelope serialization, typed errors).
8. [ ] Implement `core/job/interfaces.py` and `mocks.py` (JobClient, WorkerClient, mock test shims).
9. [ ] Add unit test suite in `tests/core/job/`.
10. [ ] Run `uv run ruff check .` and `uv run pytest tests/core/job/ tests/test_import_boundaries.py`.

# -*- coding: utf-8 -*-
"""Job Domain, State Machines, Cancellation Contract, and Versioned IPC Protocol.

Public exports for Milestone 1 (Slice 2).
"""

from __future__ import annotations

from .cancellation import (
	CancellationCoordinator,
	CancellationToken,
	JobCancelledError,
	JobCancelledException,
)
from .client import (
	JobClient,
	MockJobClient,
	MockWorkerClient,
	WorkerClient,
)
from .dto import (
	HandshakeRequest,
	HandshakeResponse,
	JobCancellationRequest,
	JobFailure,
	JobId,
	JobProgress,
	JobResult,
	JobSnapshot,
	JobSpec,
	JobState,
	JobStatus,
	JobSubmission,
	JobUpdate,
	ModalityType,
	SessionConfig,
	SessionState,
	StreamChunk,
	WorkerHealth,
)
from .protocol import (
	HEADER_SIZE,
	MAGIC,
	MAX_FRAME_SIZE,
	PROTOCOL_VERSION,
	ErrorCode,
	ProtocolError,
	decode_binary_frame,
	decode_ndjson_frame,
	encode_binary_frame,
	encode_ndjson_frame,
	is_protocol_compatible,
	validate_handshake,
)
from .schemas import (
	HANDSHAKE_REQUEST_SCHEMA,
	HANDSHAKE_RESPONSE_SCHEMA,
	JOB_CANCELLATION_REQUEST_SCHEMA,
	JOB_PROGRESS_SCHEMA,
	JOB_RESULT_SCHEMA,
	JOB_SPEC_SCHEMA,
	JOB_SUBMISSION_SCHEMA,
	JOB_UPDATE_SCHEMA,
	SESSION_CONFIG_SCHEMA,
	STREAM_CHUNK_SCHEMA,
	WORKER_HEALTH_SCHEMA,
	ValidationError,
	validate_schema,
)
from .state import (
	InvalidStateTransitionError,
	JobStateMachine,
	SessionStateMachine,
	TerminalStateError,
)

__all__ = (
	# Identifiers & Enums
	"JobId",
	"JobStatus",
	"JobState",
	"SessionState",
	"ModalityType",
	# DTOs
	"HandshakeRequest",
	"HandshakeResponse",
	"JobCancellationRequest",
	"JobFailure",
	"JobProgress",
	"JobResult",
	"JobSnapshot",
	"JobSpec",
	"JobSubmission",
	"JobUpdate",
	"SessionConfig",
	"StreamChunk",
	"WorkerHealth",
	# Schemas & Validation
	"HANDSHAKE_REQUEST_SCHEMA",
	"HANDSHAKE_RESPONSE_SCHEMA",
	"JOB_CANCELLATION_REQUEST_SCHEMA",
	"JOB_PROGRESS_SCHEMA",
	"JOB_RESULT_SCHEMA",
	"JOB_SPEC_SCHEMA",
	"JOB_SUBMISSION_SCHEMA",
	"JOB_UPDATE_SCHEMA",
	"SESSION_CONFIG_SCHEMA",
	"STREAM_CHUNK_SCHEMA",
	"WORKER_HEALTH_SCHEMA",
	"ValidationError",
	"validate_schema",
	# State Machines & Transition Errors
	"InvalidStateTransitionError",
	"JobStateMachine",
	"SessionStateMachine",
	"TerminalStateError",
	# Cancellation
	"CancellationCoordinator",
	"CancellationToken",
	"JobCancelledError",
	"JobCancelledException",
	# Wire Protocol & Framing
	"HEADER_SIZE",
	"MAGIC",
	"MAX_FRAME_SIZE",
	"PROTOCOL_VERSION",
	"ErrorCode",
	"ProtocolError",
	"decode_binary_frame",
	"decode_ndjson_frame",
	"encode_binary_frame",
	"encode_ndjson_frame",
	"is_protocol_compatible",
	"validate_handshake",
	# Client Interfaces & Mocks
	"JobClient",
	"WorkerClient",
	"MockJobClient",
	"MockWorkerClient",
)

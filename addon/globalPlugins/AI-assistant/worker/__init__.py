# -*- coding: utf-8 -*-
"""Worker package for out-of-process execution and process isolation.

Enforces Invariant A16 (out-of-process isolation and Windows Job Object containment).
"""

from __future__ import annotations

from .job_object import (
	JobObject,
	assign_process_to_job,
	create_worker_job_object,
)
from .server import WorkerServer

__all__ = [
	"JobObject",
	"WorkerServer",
	"assign_process_to_job",
	"create_worker_job_object",
]

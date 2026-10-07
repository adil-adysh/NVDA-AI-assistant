# -*- coding: utf-8 -*-
"""Worker Download Client.

Submits model and runtime download jobs to the out-of-process Worker, translates
streaming progress and byte updates, and manages cooperative cancellation.
"""

from __future__ import annotations

import logging
from pathlib import Path
import threading
import time
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
	from collections.abc import Callable

from ...core.job.client import JobClient
from ...core.job.dto import (
	JobProgress,
	JobResult,
	JobSpec,
	JobStatus,
)
from ..interfaces import DownloadCancelledError
from .download import RuntimeDownloadError
from .model_download import ModelDownloadError

logger = logging.getLogger(__name__)


class WorkerDownloadClient:
	"""Client for executing model and runtime downloads via the Worker process."""

	def __init__(self, job_client: JobClient | None = None) -> None:
		self._job_client = job_client

	def _get_client(self) -> JobClient:
		if self._job_client is not None:
			return self._job_client
		try:
			from ...plugin.worker_supervisor import get_worker_client

			client = get_worker_client()
			if client is not None:
				return client
		except Exception as exc:
			logger.debug("Could not resolve worker client from supervisor: %s", exc)

		raise RuntimeError("Worker client is not available")

	def download_model(
		self,
		url: str,
		dest_path: Path | str,
		*,
		model_name: str | None = None,
		expected_sha256: str | None = None,
		on_progress: Callable[[JobProgress], None] | None = None,
		on_bytes_progress: Callable[[int, int], None] | None = None,
		cancel_event: threading.Event | None = None,
		timeout_seconds: float = 3600.0,
	) -> Path:
		"""Submit and execute a model download job on the worker.

		Args:
			url: Download URL.
			dest_path: Destination file path.
			model_name: Optional display name for status reporting.
			expected_sha256: Optional SHA-256 digest to verify.
			on_progress: Callback for structured JobProgress updates.
			on_bytes_progress: Callback (bytes_downloaded, total_bytes).
			cancel_event: Optional event signalling cancellation.
			timeout_seconds: Job timeout in seconds.

		Returns:
			Path to downloaded and verified model file.
		"""
		client = self._get_client()
		dest = Path(dest_path)
		name = model_name or dest.name
		job_id = f"dl_model_{uuid4().hex[:8]}"

		spec = JobSpec(
			job_id=job_id,
			job_type="model_download",
			payload={
				"url": url,
				"dest_path": str(dest),
				"model_name": name,
				"expected_sha256": expected_sha256,
			},
			timeout_seconds=timeout_seconds,
		)

		done_event = threading.Event()
		final_result: list[JobResult] = []

		def _handle_prog(prog: JobProgress) -> None:
			if on_progress:
				on_progress(prog)
			if on_bytes_progress and prog.bytes_total > 0:
				on_bytes_progress(prog.bytes_completed, prog.bytes_total)

		def _handle_result(res: JobResult) -> None:
			final_result.append(res)
			done_event.set()

		unsub_prog = client.subscribe_progress(job_id, _handle_prog)
		unsub_res = client.subscribe_result(job_id, _handle_result)

		try:
			client.submit_job(spec)

			deadline = time.time() + timeout_seconds
			while not done_event.is_set():
				if cancel_event and cancel_event.is_set():
					client.cancel_job(job_id)
					done_event.wait(timeout=2.0)
					raise DownloadCancelledError(f"Model download cancelled for {name}")

				if time.time() > deadline:
					client.cancel_job(job_id)
					raise ModelDownloadError(f"Model download timed out after {timeout_seconds}s")

				done_event.wait(timeout=0.1)

			if not final_result:
				raise ModelDownloadError("Job completed without result frame")

			res = final_result[0]
			if res.status == JobStatus.CANCELLED:
				raise DownloadCancelledError(f"Model download cancelled for {name}")
			if res.status != JobStatus.COMPLETED:
				raise ModelDownloadError(
					res.error_message or f"Download failed with status {res.status}"
				)

			out_path = Path(res.result_data.get("path", str(dest)))
			return out_path
		finally:
			if unsub_prog:
				unsub_prog()
			if unsub_res:
				unsub_res()

	def download_runtime(
		self,
		url: str,
		dest_dir: Path | str,
		*,
		runtime: str,
		version: str,
		on_progress: Callable[[JobProgress], None] | None = None,
		on_bytes_progress: Callable[[int, int], None] | None = None,
		cancel_event: threading.Event | None = None,
		timeout_seconds: float = 1800.0,
	) -> Path:
		"""Submit and execute a runtime bundle download job on the worker."""
		client = self._get_client()
		dest = Path(dest_dir)
		job_id = f"dl_runtime_{uuid4().hex[:8]}"

		spec = JobSpec(
			job_id=job_id,
			job_type="runtime_download",
			payload={
				"url": url,
				"dest_dir": str(dest),
				"runtime": runtime,
				"version": version,
			},
			timeout_seconds=timeout_seconds,
		)

		done_event = threading.Event()
		final_result: list[JobResult] = []

		def _handle_prog(prog: JobProgress) -> None:
			if on_progress:
				on_progress(prog)
			if on_bytes_progress and prog.bytes_total > 0:
				on_bytes_progress(prog.bytes_completed, prog.bytes_total)

		def _handle_result(res: JobResult) -> None:
			final_result.append(res)
			done_event.set()

		unsub_prog = client.subscribe_progress(job_id, _handle_prog)
		unsub_res = client.subscribe_result(job_id, _handle_result)

		try:
			client.submit_job(spec)

			deadline = time.time() + timeout_seconds
			while not done_event.is_set():
				if cancel_event and cancel_event.is_set():
					client.cancel_job(job_id)
					done_event.wait(timeout=2.0)
					raise DownloadCancelledError(f"Runtime download cancelled for {runtime} {version}")

				if time.time() > deadline:
					client.cancel_job(job_id)
					raise RuntimeDownloadError(
						f"Runtime download timed out after {timeout_seconds}s"
					)

				done_event.wait(timeout=0.1)

			if not final_result:
				raise RuntimeDownloadError("Job completed without result frame")

			res = final_result[0]
			if res.status == JobStatus.CANCELLED:
				raise DownloadCancelledError(f"Runtime download cancelled for {runtime} {version}")
			if res.status != JobStatus.COMPLETED:
				raise RuntimeDownloadError(
					res.error_message or f"Runtime download failed with status {res.status}"
				)

			out_path = Path(res.result_data.get("path", str(dest)))
			return out_path
		finally:
			if unsub_prog:
				unsub_prog()
			if unsub_res:
				unsub_res()

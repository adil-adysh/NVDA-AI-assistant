# -*- coding: utf-8 -*-
"""Model and Runtime Download Job Executor.

Coordinates streaming HTTP range downloads, streaming checksum validation,
and atomic file unpacking in response to JobSpec submissions.
Zero NVDA dependencies — pure standard library.
"""

from __future__ import annotations

import logging
from pathlib import Path
import tempfile
import time
from typing import TYPE_CHECKING

try:
	from ...core.job.dto import (
		JobProgress,
		JobResult,
		JobSpec,
		JobStatus,
	)
except (ImportError, ValueError):
	from core.job.dto import (  # type: ignore[no-redef]
		JobProgress,
		JobResult,
		JobSpec,
		JobStatus,
	)

from .download import (
	DownloadError,
	OperationCancelledError,
	stream_download,
)
from .unpack import UnpackError, unpack_zip
from .verify import ChecksumMismatchError, stream_sha256

if TYPE_CHECKING:
	from collections.abc import Callable
	from ...core.job.cancellation import CancellationToken

logger = logging.getLogger(__name__)


def execute_model_download_job(
	spec: JobSpec,
	token: CancellationToken,
	emit_progress: Callable[[JobProgress], None],
) -> JobResult:
	"""Execute model download job with resume and SHA-256 verification."""
	payload = spec.payload
	url = str(payload.get("url", ""))
	dest_str = str(payload.get("dest_path", ""))
	expected_sha256 = payload.get("expected_sha256")
	model_name = str(payload.get("model_name") or Path(dest_str).name)

	if not url or not dest_str:
		return JobResult(
			job_id=spec.job_id,
			status=JobStatus.FAILED,
			error_code="INVALID_ARGUMENTS",
			error_message="url and dest_path are required",
			generation=spec.generation,
		)

	dest_path = Path(dest_str)
	if dest_path.exists():
		logger.info("Model %s already exists at %s", model_name, dest_path)
		return JobResult(
			job_id=spec.job_id,
			status=JobStatus.COMPLETED,
			result_data={
				"path": str(dest_path),
				"bytes": dest_path.stat().st_size,
				"cached": True,
			},
			duration_ms=0,
			generation=spec.generation,
		)

	dest_path.parent.mkdir(parents=True, exist_ok=True)
	part_path = dest_path.parent / f"{dest_path.name}.part"
	resume_from = part_path.stat().st_size if part_path.exists() else 0

	t0 = time.perf_counter()

	def _on_dl_progress(
		downloaded: int,
		total: int,
		speed: float,
		eta: float | None,
	) -> None:
		pct = round((downloaded / total) * 100.0, 2) if total > 0 else 0.0
		msg = (
			f"Downloading {model_name} ({pct:.1f}%)"
			if total > 0
			else f"Downloading {model_name}..."
		)
		emit_progress(
			JobProgress(
				job_id=spec.job_id,
				status=JobStatus.RUNNING,
				progress_pct=pct,
				status_message=msg,
				bytes_completed=downloaded,
				bytes_total=total,
				throughput_bytes_per_sec=speed,
				eta_seconds=eta,
				generation=spec.generation,
			)
		)

	try:
		# 1. Download
		total_downloaded = stream_download(
			url,
			part_path,
			resume_from=resume_from,
			on_progress=_on_dl_progress,
			cancel_token=token,
		)

		# 2. Verify SHA-256 if provided
		if expected_sha256:
			emit_progress(
				JobProgress(
					job_id=spec.job_id,
					status=JobStatus.RUNNING,
					progress_pct=99.0,
					status_message=f"Verifying {model_name} checksum...",
					generation=spec.generation,
				)
			)
			stream_sha256(
				part_path,
				expected_sha256=expected_sha256,
				cancel_token=token,
			)

		# 3. Atomic rename .part -> final
		if dest_path.exists():
			dest_path.unlink()
		part_path.rename(dest_path)

		duration_ms = int((time.perf_counter() - t0) * 1000)
		return JobResult(
			job_id=spec.job_id,
			status=JobStatus.COMPLETED,
			result_data={
				"path": str(dest_path),
				"bytes": total_downloaded,
				"cached": False,
			},
			duration_ms=duration_ms,
			generation=spec.generation,
		)

	except OperationCancelledError:
		logger.info("Model download cancelled for %s; .part retained", model_name)
		duration_ms = int((time.perf_counter() - t0) * 1000)
		return JobResult(
			job_id=spec.job_id,
			status=JobStatus.CANCELLED,
			result_data={"part_path": str(part_path)},
			duration_ms=duration_ms,
			generation=spec.generation,
		)
	except ChecksumMismatchError as exc:
		logger.error("Checksum error for %s: %s", model_name, exc)
		if part_path.exists():
			part_path.unlink()
		duration_ms = int((time.perf_counter() - t0) * 1000)
		return JobResult(
			job_id=spec.job_id,
			status=JobStatus.FAILED,
			error_code="CHECKSUM_MISMATCH",
			error_message=str(exc),
			retriable=True,
			duration_ms=duration_ms,
			generation=spec.generation,
		)
	except Exception as exc:
		logger.error("Model download failed for %s: %s", model_name, exc, exc_info=True)
		duration_ms = int((time.perf_counter() - t0) * 1000)
		return JobResult(
			job_id=spec.job_id,
			status=JobStatus.FAILED,
			error_code="DOWNLOAD_FAILED",
			error_message=str(exc),
			retriable=True,
			duration_ms=duration_ms,
			generation=spec.generation,
		)


def execute_runtime_download_job(
	spec: JobSpec,
	token: CancellationToken,
	emit_progress: Callable[[JobProgress], None],
) -> JobResult:
	"""Execute runtime bundle download, verification, and extraction job."""
	payload = spec.payload
	url = str(payload.get("url", ""))
	dest_dir_str = str(payload.get("dest_dir", ""))
	runtime = str(payload.get("runtime", "runtime"))
	version = str(payload.get("version", ""))

	if not url or not dest_dir_str:
		return JobResult(
			job_id=spec.job_id,
			status=JobStatus.FAILED,
			error_code="INVALID_ARGUMENTS",
			error_message="url and dest_dir are required",
			generation=spec.generation,
		)

	dest_dir = Path(dest_dir_str)
	manifest_path = dest_dir / "manifest.json"
	if manifest_path.exists():
		return JobResult(
			job_id=spec.job_id,
			status=JobStatus.COMPLETED,
			result_data={"path": str(dest_dir), "cached": True},
			duration_ms=0,
			generation=spec.generation,
		)

	t0 = time.perf_counter()
	tmp_zip: Path | None = None

	try:
		with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_f:
			tmp_zip = Path(tmp_f.name)

		def _on_dl_progress(
			downloaded: int,
			total: int,
			speed: float,
			eta: float | None,
		) -> None:
			pct = round((downloaded / total) * 100.0, 2) if total > 0 else 0.0
			emit_progress(
				JobProgress(
					job_id=spec.job_id,
					status=JobStatus.RUNNING,
					progress_pct=pct * 0.7,  # Download is 70% of total job
					status_message=f"Downloading {runtime} {version} ({pct:.0f}%)...",
					bytes_completed=downloaded,
					bytes_total=total,
					throughput_bytes_per_sec=speed,
					eta_seconds=eta,
					generation=spec.generation,
				)
			)

		stream_download(
			url,
			tmp_zip,
			on_progress=_on_dl_progress,
			cancel_token=token,
		)

		def _on_unpack_progress(msg: str, pct: float) -> None:
			# Unpack represents 70% -> 100%
			overall_pct = 70.0 + (pct * 0.3)
			emit_progress(
				JobProgress(
					job_id=spec.job_id,
					status=JobStatus.RUNNING,
					progress_pct=round(overall_pct, 2),
					status_message=msg,
					generation=spec.generation,
				)
			)

		unpack_zip(
			tmp_zip,
			dest_dir,
			cancel_token=token,
			on_progress=_on_unpack_progress,
		)

		duration_ms = int((time.perf_counter() - t0) * 1000)
		return JobResult(
			job_id=spec.job_id,
			status=JobStatus.COMPLETED,
			result_data={"path": str(dest_dir), "cached": False},
			duration_ms=duration_ms,
			generation=spec.generation,
		)

	except OperationCancelledError:
		logger.info("Runtime download cancelled for %s %s", runtime, version)
		duration_ms = int((time.perf_counter() - t0) * 1000)
		return JobResult(
			job_id=spec.job_id,
			status=JobStatus.CANCELLED,
			result_data={},
			duration_ms=duration_ms,
			generation=spec.generation,
		)
	except (DownloadError, UnpackError, ChecksumMismatchError) as exc:
		logger.error("Runtime download failed for %s: %s", runtime, exc)
		duration_ms = int((time.perf_counter() - t0) * 1000)
		return JobResult(
			job_id=spec.job_id,
			status=JobStatus.FAILED,
			error_code="RUNTIME_INSTALL_FAILED",
			error_message=str(exc),
			retriable=True,
			duration_ms=duration_ms,
			generation=spec.generation,
		)
	except Exception as exc:
		logger.error("Unexpected error installing runtime %s: %s", runtime, exc, exc_info=True)
		duration_ms = int((time.perf_counter() - t0) * 1000)
		return JobResult(
			job_id=spec.job_id,
			status=JobStatus.FAILED,
			error_code="UNEXPECTED_ERROR",
			error_message=str(exc),
			retriable=False,
			duration_ms=duration_ms,
			generation=spec.generation,
		)
	finally:
		if tmp_zip and tmp_zip.exists():
			try:
				tmp_zip.unlink()
			except OSError:
				pass

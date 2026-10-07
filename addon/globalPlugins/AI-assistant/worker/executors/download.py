# -*- coding: utf-8 -*-
"""Streaming HTTP Range Downloader Executor.

Executes streaming downloads with HTTP Range resumption, exponential backoff,
throughput estimation, and cooperative cancellation token checking.
Zero NVDA dependencies — pure standard library.
"""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING
import urllib.error
import urllib.request

if TYPE_CHECKING:
	from collections.abc import Callable
	from ...core.job.cancellation import CancellationToken

logger = logging.getLogger(__name__)

_DEFAULT_CHUNK_SIZE = 64 * 1024
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_DELAYS = (1.0, 3.0, 10.0)


class DownloadError(RuntimeError):
	"""Raised when a download cannot be completed."""


class OperationCancelledError(DownloadError):
	"""Raised when a download is cooperatively cancelled via token."""


def stream_download(
	url: str,
	dest_path: Path | str,
	*,
	resume_from: int = 0,
	expected_size: int | None = None,
	on_progress: Callable[[int, int, float, float | None], None] | None = None,
	cancel_token: CancellationToken | None = None,
	chunk_size: int = _DEFAULT_CHUNK_SIZE,
	max_retries: int = _DEFAULT_MAX_RETRIES,
	retry_delays: tuple[float, ...] = _DEFAULT_RETRY_DELAYS,
) -> int:
	"""Stream URL to destination path with HTTP Range resume and retry.

	Args:
		url: HTTP/HTTPS URL to download.
		dest_path: Path to write the downloaded content.
		resume_from: Existing byte offset to resume from (sends Range header).
		expected_size: Optional total file size hint if known in advance.
		on_progress: Optional callback:
			(bytes_downloaded, total_bytes, bytes_per_sec, eta_seconds)
		cancel_token: Optional cooperative cancellation token.
		chunk_size: Bytes to read per socket chunk.
		max_retries: Maximum network retry attempts.
		retry_delays: Tuple of delays between retries in seconds.

	Returns:
		Total bytes written to destination.
	"""
	dest = Path(dest_path)
	dest.parent.mkdir(parents=True, exist_ok=True)

	retries = 0
	current_offset = max(0, resume_from)

	if dest.exists() and current_offset > 0:
		existing_size = dest.stat().st_size
		if existing_size != current_offset:
			current_offset = existing_size

	total_size = expected_size or 0

	while True:
		if cancel_token and cancel_token.is_cancelled:
			raise OperationCancelledError("Download cancelled before connection")

		try:
			req = urllib.request.Request(
				url,
				headers={
					"User-Agent": "NVDA-AI-Assistant/1.0",
				},
			)
			if current_offset > 0:
				req.add_header("Range", f"bytes={current_offset}-")

			with urllib.request.urlopen(req, timeout=30) as resp:
				status = getattr(resp, "status", 200)
				content_len_hdr = resp.headers.get("Content-Length")
				hdr_length = None
				if content_len_hdr:
					try:
						hdr_length = int(content_len_hdr)
					except ValueError:
						pass

				# Range supported: append
				if status == 206:
					mode = "ab"
					content_range = resp.headers.get("Content-Range")
					if content_range and "/" in content_range:
						try:
							total_size = int(content_range.rsplit("/", 1)[1])
						except (ValueError, IndexError):
							pass
					elif hdr_length is not None:
						total_size = current_offset + hdr_length
				else:
					# Server does not support Range (200 OK) -> write fresh
					mode = "wb"
					current_offset = 0
					if hdr_length is not None:
						total_size = hdr_length

				bytes_downloaded = current_offset
				start_time = time.perf_counter()
				last_progress_time = start_time
				last_progress_bytes = bytes_downloaded

				with open(dest, mode) as out_f:
					while True:
						if cancel_token and cancel_token.is_cancelled:
							raise OperationCancelledError("Download cancelled during transfer")

						chunk = resp.read(chunk_size)
						if not chunk:
							break

						out_f.write(chunk)
						bytes_downloaded += len(chunk)
						current_offset = bytes_downloaded

						now = time.perf_counter()
						if on_progress and (now - last_progress_time >= 0.25):
							elapsed = now - last_progress_time
							delta_bytes = bytes_downloaded - last_progress_bytes
							speed = delta_bytes / elapsed if elapsed > 0 else 0.0
							eta = None
							if total_size > bytes_downloaded and speed > 0:
								eta = (total_size - bytes_downloaded) / speed

							on_progress(bytes_downloaded, total_size, speed, eta)
							last_progress_time = now
							last_progress_bytes = bytes_downloaded

				# Final progress tick
				if on_progress:
					now = time.perf_counter()
					total_elapsed = now - start_time
					overall_speed = (
						(bytes_downloaded - resume_from) / total_elapsed
						if total_elapsed > 0
						else 0.0
					)
					on_progress(bytes_downloaded, total_size or bytes_downloaded, overall_speed, 0.0)

				return bytes_downloaded

		except OperationCancelledError:
			raise
		except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
			if cancel_token and cancel_token.is_cancelled:
				raise OperationCancelledError("Download cancelled during network interruption") from exc

			retries += 1
			if retries > max_retries:
				raise DownloadError(
					f"Download failed after {max_retries} retries: {exc}"
				) from exc

			delay = retry_delays[min(retries - 1, len(retry_delays) - 1)]
			logger.warning(
				"Download error for %s (attempt %d/%d): %s; retrying in %.1fs",
				url,
				retries,
				max_retries,
				exc,
				delay,
			)

			deadline = time.time() + delay
			while time.time() < deadline:
				if cancel_token and cancel_token.is_cancelled:
					raise OperationCancelledError("Download cancelled during retry delay")
				time.sleep(0.1)

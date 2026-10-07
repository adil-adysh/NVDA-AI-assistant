# -*- coding: utf-8 -*-
"""Streaming Checksum Verifier Executor.

Computes SHA-256 digests in chunks to avoid high RAM consumption on large model
files (1GB–10GB), checking cancellation tokens cooperatively.
Zero NVDA dependencies — pure standard library.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from collections.abc import Callable
	from ...core.job.cancellation import CancellationToken

from .download import OperationCancelledError

logger = logging.getLogger(__name__)

_DEFAULT_VERIFY_CHUNK = 1024 * 1024  # 1 MB


class ChecksumMismatchError(ValueError):
	"""Raised when computed SHA-256 does not match expected digest."""


def stream_sha256(
	file_path: Path | str,
	expected_sha256: str | None = None,
	*,
	chunk_size: int = _DEFAULT_VERIFY_CHUNK,
	on_progress: Callable[[int, int], None] | None = None,
	cancel_token: CancellationToken | None = None,
) -> str:
	"""Compute SHA-256 hex digest for a file incrementally.

	Args:
		file_path: File to hash.
		expected_sha256: Optional expected hex digest to verify against.
		chunk_size: Size in bytes of each read chunk.
		on_progress: Optional callback (bytes_hashed, total_bytes).
		cancel_token: Optional cooperative cancellation token.

	Returns:
		Lower-case SHA-256 hex digest string.

	Raises:
		FileNotFoundError: If file does not exist.
		OperationCancelledError: If cancelled during hashing.
		ChecksumMismatchError: If expected_sha256 does not match.
	"""
	p = Path(file_path)
	if not p.exists():
		raise FileNotFoundError(f"File to verify does not exist: {p}")

	total_size = p.stat().st_size
	hasher = hashlib.sha256()
	bytes_read = 0
	last_progress_time = time.perf_counter()

	with open(p, "rb") as f:
		while True:
			if cancel_token and cancel_token.is_cancelled:
				raise OperationCancelledError("Checksum calculation cancelled")

			chunk = f.read(chunk_size)
			if not chunk:
				break

			hasher.update(chunk)
			bytes_read += len(chunk)

			now = time.perf_counter()
			if on_progress and (now - last_progress_time >= 0.25):
				on_progress(bytes_read, total_size)
				last_progress_time = now

	if on_progress:
		on_progress(bytes_read, total_size)

	digest = hasher.hexdigest().lower()

	if expected_sha256:
		expected_norm = expected_sha256.strip().lower()
		if digest != expected_norm:
			logger.error(
				"SHA-256 verification failed for %s: expected %s, got %s",
				p,
				expected_norm,
				digest,
			)
			raise ChecksumMismatchError(
				f"SHA-256 mismatch for {p.name}: expected {expected_norm}, got {digest}"
			)

	logger.info("SHA-256 verified for %s: %s", p.name, digest)
	return digest

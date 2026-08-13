# -*- coding: utf-8 -*-
"""On-demand model file download service.

Downloads ``.litertlm`` model files from Hugging Face (or any
configurable URL), verifies them with SHA-256 when available,
and caches them under the user's model directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from logHandler import log

from ..interfaces import ProgressCallback
from .download import DownloadCancelledError, _download_url_resume


class ModelDownloadError(RuntimeError):
	"""Raised when a model download or verification fails."""


class HuggingFaceFileNotFoundError(ModelDownloadError):
	"""Raised when a repository has no compatible model artifact."""


class ModelDownloadService:
	"""Download and cache ``.litertlm`` model files.

	Parameters:
	    cache_dir: Root directory for cached models.  Defaults to
	        ``%APPDATA%/nvda/AIAssistant/models/litert-lm/``.
	"""

	def __init__(
		self,
		cache_dir: str | Path | None = None,
	) -> None:
		self._cache_dir = Path(cache_dir) if cache_dir else _default_model_dir()

	# ── Public API ──────────────────────────────────────────────────

	@property
	def cache_dir(self) -> Path:
		"""The directory where downloaded model files are cached."""
		return self._cache_dir

	def is_downloaded(self, model_name: str) -> bool:
		"""Return ``True`` if *model_name* is already cached."""
		return self._model_path(model_name).exists()

	def model_path(self, model_name: str) -> Path:
		"""Return the expected local path for *model_name*."""
		return self._model_path(model_name)

	def download(
		self,
		model_name: str,
		url: str,
		expected_sha256: str | None = None,
		on_progress: ProgressCallback | None = None,
		on_bytes_progress: Callable[[int, int], None] | None = None,
		cancel_event: threading.Event | None = None,
	) -> Path:
		"""Download a model file to the cache directory, with resume support.

		Uses a ``.part`` file that persists across interruptions.  On the
		next attempt the existing partial data is used to issue an HTTP
		``Range`` request.  If the server does not support range requests
		the download falls back to starting from scratch.

		Args:
		    model_name: Local filename for the model (e.g. ``"gemma-4-E2B-it.litertlm"``).
		    url: Direct download URL.
		    expected_sha256: Optional SHA-256 hex digest for verification.
		    on_progress: Optional progress callback receiving text messages.
		    on_bytes_progress: Optional callback ``(downloaded_bytes, total_bytes)``
		        — during a resume *downloaded_bytes* includes already-cached bytes.
		    cancel_event: Optional ``threading.Event``; when set the download is
		        cancelled and the partial ``.part`` file is preserved.

		Returns:
		    Path to the downloaded and verified model file.

		Raises:
		    ModelDownloadError: If the download or verification fails.
		"""
		dest = self._model_path(model_name)
		if dest.exists():
			log.info("Model %s already cached at %s", model_name, dest)
			return dest

		dest.parent.mkdir(parents=True, exist_ok=True)
		part_path = dest.parent / f"{dest.name}.part"

		# Check how much we already have
		existing_bytes = part_path.stat().st_size if part_path.exists() else 0
		is_resume = existing_bytes > 0

		if on_progress:
			msg = f"Resuming {model_name}..." if is_resume else f"Downloading {model_name}..."
			on_progress(msg)

		# Download — append if resuming, write if fresh
		try:
			_download_url_resume(
				url,
				part_path,
				resume_from=existing_bytes,
				on_bytes_progress=_make_range_aware_progress(
					on_bytes_progress,
					existing_bytes,
				)
				if on_bytes_progress
				else None,
				cancel_event=cancel_event,
			)
		except DownloadCancelledError:
			# Leave .part in place for future resume attempts.
			raise
		except Exception as exc:
			# Leave .part in place for future resume attempts
			raise ModelDownloadError(f"Failed to download {model_name} from {url}: {exc}") from exc

		# Optional SHA-256 verification
		if expected_sha256:
			if on_progress:
				on_progress(f"Verifying {model_name}...")
			actual = hashlib.sha256(part_path.read_bytes()).hexdigest()
			if actual != expected_sha256:
				_cleanup(part_path)
				raise ModelDownloadError(
					f"SHA-256 mismatch for {model_name}: expected {expected_sha256}, got {actual}"
				)

		# Atomic rename .part → final name
		part_path.rename(dest)

		size_mb = dest.stat().st_size / 1024 / 1024
		log.info("Model %s downloaded to %s (%.1f MB)", model_name, dest, size_mb)
		if on_progress:
			on_progress(f"{model_name} ready ({size_mb:.0f} MB)")

		return dest

	def download_huggingface(
		self,
		repository: str,
		revision: str,
		cache_name: str,
		*,
		extensions: tuple[str, ...],
		on_progress: ProgressCallback | None = None,
		on_bytes_progress: Callable[[int, int], None] | None = None,
		cancel_event: threading.Event | None = None,
	) -> Path:
		"""Resolve and download one model artifact from a HF repository."""
		filename = self.resolve_huggingface_file(repository, revision, extensions)
		url = (
			f"https://huggingface.co/{quote(repository, safe='/')}/resolve/"
			f"{quote(revision, safe='')}/{quote(filename, safe='/')}"
		)
		return self.download(
			model_name=cache_name,
			url=url,
			on_progress=on_progress,
			on_bytes_progress=on_bytes_progress,
			cancel_event=cancel_event,
		)

	@staticmethod
	def resolve_huggingface_file(
		repository: str,
		revision: str,
		extensions: tuple[str, ...],
	) -> str:
		"""Select a deterministic compatible artifact from a HF repository."""
		api_url = (
			f"https://huggingface.co/api/models/{quote(repository, safe='/')}/tree/"
			f"{quote(revision, safe='')}?recursive=true&expand=false"
		)
		try:
			with urllib.request.urlopen(api_url, timeout=30) as response:
				payload = json.loads(response.read().decode("utf-8"))
		except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
			raise ModelDownloadError(
				f"Could not inspect Hugging Face repository {repository}:{revision}: {exc}"
			) from exc

		if not isinstance(payload, list):
			raise ModelDownloadError(f"Unexpected Hugging Face file listing for {repository}:{revision}")
		allowed = {suffix.lower() for suffix in extensions}
		candidates = sorted(
			str(item.get("path", ""))
			for item in payload
			if isinstance(item, dict)
			and item.get("type") == "file"
			and Path(str(item.get("path", ""))).suffix.lower() in allowed
		)
		if not candidates:
			raise HuggingFaceFileNotFoundError(
				f"No compatible model file ({', '.join(sorted(allowed))}) found in "
				f"{repository}:{revision}"
			)
		return candidates[0]

	def stage_local_file(self, source: str | Path, cache_name: str) -> Path:
		"""Copy a user-owned model file into the managed cache atomically."""
		import shutil

		source_path = Path(source)
		if not source_path.is_file():
			raise ModelDownloadError(f"Model file does not exist: {source_path}")
		destination = self._model_path(cache_name)
		destination.parent.mkdir(parents=True, exist_ok=True)
		if source_path.resolve() != destination.resolve():
			shutil.copy2(source_path, destination)
		return destination

	# ── Internal helpers ────────────────────────────────────────────

	def _model_path(self, model_name: str) -> Path:
		"""Resolve *model_name* under the cache directory."""
		# Sanitise — strip any path separators to avoid traversal
		safe = model_name.replace("/", "_").replace("\\", "_")
		return self._cache_dir / safe


# ── Module-level helpers ───────────────────────────────────────────


def _default_model_dir() -> Path:
	"""``%APPDATA%/nvda/AIAssistant/models/litert-lm/``."""
	appdata = os.getenv("APPDATA")
	base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
	return base / "nvda" / "AIAssistant" / "models" / "litert-lm"


def _make_range_aware_progress(
	on_bytes_progress: Callable[[int, int], None] | None,
	existing_bytes: int,
) -> Callable[[int, int], None]:
	"""Wrap *on_bytes_progress* to offset for already-cached bytes."""
	if on_bytes_progress is None or existing_bytes == 0:
		return on_bytes_progress

	def _wrapped(downloaded: int, total: int) -> None:
		on_bytes_progress(downloaded, total)

	return _wrapped


def _cleanup(path: Path | None) -> None:
	"""Remove *path* if it exists."""
	if path is not None and path.exists():
		try:
			path.unlink()
		except OSError:
			pass

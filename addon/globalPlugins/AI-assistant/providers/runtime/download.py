# -*- coding: utf-8 -*-
"""On-demand runtime download service.

Downloads runtime ZIPs from a configurable URL, verifies SHA-256,
and extracts them to the versioned runtime directory.

Also provides a shared streaming HTTP download utility with byte-level
progress and HTTP Range resume support, used by both runtime and model
downloads.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from logHandler import log

from ..interfaces import ProgressCallback
from .config import RuntimeConfig
from .paths import get_runtime_path


class RuntimeDownloadError(RuntimeError):
	"""Raised when a runtime download or verification fails."""


def _default_url_builder(config: RuntimeConfig) -> str:
	"""Default URL builder for runtime ZIPs hosted on GitHub Releases."""
	return (
		f"https://github.com/adil-adysh/NVDA-AI-assistant/releases/download/"
		f"{config.runtime}-v{config.version}/"
		f"{config.runtime}-{config.version}-{config.platform}-runtime.zip"
	)


class RuntimeDownloadService:
	"""Downloads and verifies runtime backend bundles.

	The service fetches a ZIP from a URL (built via a configurable
	builder function), verifies its file hashes against the embedded
	``manifest.json``, and extracts it to a versioned path.

	Parameters:
	    url_builder: A callable ``(RuntimeConfig) -> str`` that returns
	        the download URL. Defaults to a GitHub Releases template.
	"""

	def __init__(
		self,
		url_builder: Callable[[RuntimeConfig], str] | None = None,
	) -> None:
		self._url_builder = url_builder or _default_url_builder

	def is_downloaded(self, runtime: str, version: str) -> bool:
		"""Check if the runtime is already present and valid."""
		runtime_path = get_runtime_path(runtime, version)
		manifest_path = runtime_path / "manifest.json"
		if not manifest_path.exists():
			return False
		try:
			manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
			return manifest.get("version") == version
		except (json.JSONDecodeError, OSError):
			return False

	def download(
		self,
		runtime: str,
		version: str,
		platform: str = "windows-x64",
		url: str | None = None,
		on_progress: ProgressCallback | None = None,
		on_bytes_progress: Callable[[int, int], None] | None = None,
	) -> Path:
		"""Download, verify, and extract a runtime bundle.

		Args:
		    runtime: Runtime identifier (e.g., ``"litert-lm"``).
		    version: Semantic version string.
		    platform: Target platform identifier.
		    url: Explicit download URL. If ``None``, built from
		        the configured ``url_builder``.
		    on_progress: Optional callback receiving status strings.
		    on_bytes_progress: Optional callback ``(downloaded_bytes, total_bytes)``
		        for byte-level progress during download.

		Returns:
		    Path to the extracted runtime directory.

		Raises:
		    RuntimeDownloadError: If download, verification, or
		        extraction fails.
		"""
		config = RuntimeConfig(runtime=runtime, version=version, platform=platform)
		runtime_path = get_runtime_path(runtime, version)

		if self.is_downloaded(runtime, version):
			log.info("Runtime %s %s already present at %s", runtime, version, runtime_path)
			return runtime_path

		if on_progress:
			on_progress(f"Downloading {runtime} {version}...")

		download_url = url or self._url_builder(config)

		# Download to a temporary file with byte-level progress
		try:
			with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
				tmp_path = tmp.name
			_download_url_resume(
				download_url,
				Path(tmp_path),
				on_bytes_progress=on_bytes_progress,
			)
		except Exception as exc:
			raise RuntimeDownloadError(
				f"Failed to download {runtime} {version} from {download_url}: {exc}"
			) from exc

		try:
			return self._extract_and_verify(tmp_path, runtime, version, platform, on_progress)
		finally:
			try:
				os.unlink(tmp_path)
			except OSError:
				pass

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _resolve_manifest_root(extract_dir: Path) -> Path:
		"""Walk *extract_dir* to find the directory holding ``manifest.json``.

		Returns the directory (could be *extract_dir* itself or a child).
		Raises ``RuntimeDownloadError`` if no manifest is found.
		"""
		candidates = [extract_dir]
		candidates.extend(extract_dir.iterdir())
		for candidate in candidates:
			if not candidate.is_dir():
				continue
			if (candidate / "manifest.json").exists():
				return candidate
		raise RuntimeDownloadError("ZIP is missing manifest.json")

	@staticmethod
	def _verify_manifest(
		manifest: Any,
		runtime: str,
		version: str,
		platform: str,
	) -> None:
		"""Validate manifest fields match expected values."""
		errors: list[str] = []
		if manifest.runtime != runtime:
			errors.append(f"expected runtime '{runtime}', got '{manifest.runtime}'")
		if manifest.version != version:
			errors.append(f"expected version '{version}', got '{manifest.version}'")
		if manifest.platform != platform:
			errors.append(f"expected platform '{platform}', got '{manifest.platform}'")
		if errors:
			raise RuntimeDownloadError(f"Manifest validation failed: {'; '.join(errors)}")

	@staticmethod
	def _verify_file_hashes(
		root: Path,
		files: dict[str, str],
	) -> None:
		"""Check every file in *files* exists under *root* and matches SHA-256."""
		for rel_path, expected_hash in files.items():
			full_path = root / rel_path
			if not full_path.exists():
				raise RuntimeDownloadError(f"Missing file in bundle: {rel_path}")
			actual_hash = hashlib.sha256(full_path.read_bytes()).hexdigest()
			if actual_hash != expected_hash:
				raise RuntimeDownloadError(
					f"SHA-256 mismatch for {rel_path}: expected {expected_hash}, got {actual_hash}"
				)

	@staticmethod
	def _atomic_move(source: Path, destination: Path) -> None:
		"""Replace *destination* with *source* atomically (best-effort)."""
		if destination.exists():
			shutil.rmtree(destination, ignore_errors=True)
		destination.parent.mkdir(parents=True, exist_ok=True)
		shutil.copytree(source, destination)

	def _extract_and_verify(
		self,
		zip_path: str,
		runtime: str,
		version: str,
		platform: str,
		on_progress: ProgressCallback | None = None,
	) -> Path:
		"""Extract ZIP and verify the manifest."""
		runtime_path = get_runtime_path(runtime, version)

		if on_progress:
			on_progress(f"Extracting {runtime} {version}...")

		with tempfile.TemporaryDirectory(prefix=f"{runtime}_extract_") as tmp_dir:
			tmp_path = Path(tmp_dir)

			with zipfile.ZipFile(zip_path, "r") as zf:
				zf.extractall(tmp_path)

			if not any(tmp_path.iterdir()):
				raise RuntimeDownloadError("ZIP was empty")

			extracted_root = self._resolve_manifest_root(tmp_path)

			manifest_data = json.loads((extracted_root / "manifest.json").read_text(encoding="utf-8"))
			manifest = _manifest_from_dict(manifest_data)

			self._verify_manifest(manifest, runtime, version, platform)

			if on_progress:
				on_progress(f"Verifying {runtime} {version}...")
			self._verify_file_hashes(extracted_root, manifest.files)

			self._atomic_move(extracted_root, runtime_path)

		if on_progress:
			on_progress(f"{runtime} {version} ready")

		log.info("Runtime %s %s extracted to %s", runtime, version, runtime_path)
		return runtime_path


# ------------------------------------------------------------------
# Module-level helpers (no class coupling needed)
# ------------------------------------------------------------------


def _manifest_from_dict(data: dict[str, Any]) -> Any:
	"""Deserialize and validate a manifest dict.

	Re-imported here instead of from ``.config`` to avoid circular
	dependency risk and keep the download module self-contained for
	the deserialisation concern.
	"""
	from .config import DownloadManifest  # noqa: PLC0415

	return DownloadManifest.from_dict(data)


# ------------------------------------------------------------------
# Shared streaming HTTP download with progress
# ------------------------------------------------------------------

_MAX_RETRIES = 3
_RETRY_DELAYS = (1, 3, 10)
_CHUNK_SIZE = 64 * 1024


def _download_url_resume(
	url: str,
	dest_path: Path,
	resume_from: int = 0,
	on_bytes_progress: Callable[[int, int], None] | None = None,
) -> None:
	"""Stream *url* into *dest_path* with HTTP Range resume and retry.

	When *resume_from* > 0 a ``Range`` header is sent.  If the server
	responds with 206 Partial Content the data is appended.  Otherwise
	(200 OK — range not supported) the file is written from scratch.

	On network failures the connection is retried up to 3 times with
	exponential backoff (1s, 3s, 10s).  Each retry picks up from the
	last byte actually written to disk.

	The *on_bytes_progress* callback receives ``(total_downloaded, total_size)``
	where *total_downloaded* includes the already-cached bytes.
	"""
	last_error: Exception | None = None

	for attempt in range(_MAX_RETRIES + 1):
		# On retry, re-check what's actually on disk
		if attempt > 0:
			resume_from = dest_path.stat().st_size if dest_path.exists() else 0
			delay = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
			log.warning(
				"Download retry %d/%d for %s after %.0fs (resuming at byte %d)",
				attempt,
				_MAX_RETRIES,
				dest_path.name,
				delay,
				resume_from,
			)
			time.sleep(delay)

		resp: Any | None = None

		try:
			req = urllib.request.Request(url)
			if resume_from > 0:
				req.add_header("Range", f"bytes={resume_from}-")

			# Closed manually in the finally block below so mid-stream retry
			# paths share a single close path.
			resp = urllib.request.urlopen(req, timeout=30)  # pylint: disable=consider-using-with

			status = resp.status
			supports_range = status == 206

			# Server doesn't support Range — restart from scratch
			if resume_from > 0 and not supports_range:
				log.info(
					"Server does not support Range for %s; re-downloading from scratch",
					url,
				)
				resume_from = 0
				dest_path.write_bytes(b"")
				resp.close()
				resp = None
				continue

			# Determine total file size for progress reporting
			content_length = resp.length
			if supports_range and content_length is not None:
				total_size = resume_from + content_length
			elif content_length is not None:
				total_size = content_length
			else:
				total_size = 0

			mode = "ab" if resume_from > 0 else "wb"
			downloaded_this_session = 0

			with open(dest_path, mode) as f:
				while True:
					try:
						chunk = resp.read(_CHUNK_SIZE)
						if not chunk:
							break
						f.write(chunk)
						downloaded_this_session += len(chunk)
						if on_bytes_progress:
							total_downloaded = resume_from + downloaded_this_session
							on_bytes_progress(
								total_downloaded,
								total_size or total_downloaded,
							)
					except Exception as read_err:
						# Mid-stream failure — retry connection from last byte
						last_error = read_err
						if attempt < _MAX_RETRIES:
							log.debug(
								"Read error on %s at byte %d: %s",
								dest_path.name,
								resume_from + downloaded_this_session,
								read_err,
							)
							break  # break inner read loop → retry outer loop
						raise

				if not chunk and not downloaded_this_session:
					# EOF right away — might be a transient 0-byte response
					if attempt < _MAX_RETRIES:
						log.debug(
							"Empty response on %s (attempt %d), retrying",
							dest_path.name,
							attempt,
						)
						continue

			# If we hit a read error and broke early, retry the connection
			if last_error is not None and attempt < _MAX_RETRIES:
				resp.close()
				resp = None
				continue

			# Success — all data read
			resp.close()
			resp = None
			return

		except urllib.request.HTTPError as exc:
			resp = None
			# 416 Range Not Satisfiable → the file is already complete
			if exc.code == 416:
				log.debug("Range 416 for %s — file already complete", dest_path.name)
				if on_bytes_progress:
					file_size = dest_path.stat().st_size
					on_bytes_progress(file_size, file_size)
				return
			last_error = exc
			if attempt >= _MAX_RETRIES:
				raise
		except Exception as exc:
			last_error = exc
			if attempt >= _MAX_RETRIES:
				raise
		finally:
			if resp is not None:
				try:
					resp.close()
				except Exception:
					pass

	# Exhausted retries
	raise RuntimeDownloadError(
		f"Download failed after {_MAX_RETRIES + 1} attempts: {last_error}"
	) from last_error

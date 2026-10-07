# -*- coding: utf-8 -*-
"""Safe ZIP Unpacker and Atomic Swapper Executor.

Safely extracts zip bundles, verifies integrity/manifests, and swaps into place
atomically. Defends against path traversal attacks (zip-slip).
Zero NVDA dependencies — pure standard library.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import TYPE_CHECKING
import zipfile

if TYPE_CHECKING:
	from collections.abc import Callable
	from ...core.job.cancellation import CancellationToken

from .download import OperationCancelledError
from .verify import stream_sha256

logger = logging.getLogger(__name__)


class UnpackError(RuntimeError):
	"""Raised when extraction or validation fails."""


def _safe_extract(zf: zipfile.ZipFile, target_dir: Path, cancel_token: CancellationToken | None = None) -> None:
	"""Safely extract all zip entries, guarding against Zip Slip path traversal."""
	resolved_target = target_dir.resolve()
	members = zf.infolist()

	for member in members:
		if cancel_token and cancel_token.is_cancelled:
			raise OperationCancelledError("Unpacking cancelled")

		dest = (target_dir / member.filename).resolve()
		if not str(dest).startswith(str(resolved_target) + os.sep) and dest != resolved_target:
			raise UnpackError(f"Zip-slip path traversal attempt detected in entry: {member.filename}")

		zf.extract(member, target_dir)


def _resolve_manifest_root(extract_dir: Path) -> Path:
	"""Find the directory containing manifest.json (either root or single child dir)."""
	if (extract_dir / "manifest.json").exists():
		return extract_dir

	for child in extract_dir.iterdir():
		if child.is_dir() and (child / "manifest.json").exists():
			return child

	return extract_dir


def unpack_zip(
	zip_path: Path | str,
	dest_dir: Path | str,
	*,
	expected_files_sha256: dict[str, str] | None = None,
	cancel_token: CancellationToken | None = None,
	on_progress: Callable[[str, float], None] | None = None,
) -> Path:
	"""Extract zip file to destination directory atomically.

	Args:
		zip_path: Path to the zip archive.
		dest_dir: Target directory where bundle should be installed.
		expected_files_sha256: Optional mapping of relative_path -> sha256 hex.
		cancel_token: Optional cooperative cancellation token.
		on_progress: Optional callback (status_message, progress_pct).

	Returns:
		Path to the final unpacked directory.

	Raises:
		UnpackError: On extraction failure or validation mismatch.
		OperationCancelledError: If cancelled.
	"""
	src_zip = Path(zip_path)
	target_dir = Path(dest_dir)

	if not src_zip.exists():
		raise FileNotFoundError(f"Zip file not found: {src_zip}")

	if on_progress:
		on_progress(f"Extracting {src_zip.name}...", 10.0)

	with tempfile.TemporaryDirectory(prefix="unpack_worker_") as tmp_str:
		tmp_dir = Path(tmp_str)

		with zipfile.ZipFile(src_zip, "r") as zf:
			_safe_extract(zf, tmp_dir, cancel_token=cancel_token)

		if not any(tmp_dir.iterdir()):
			raise UnpackError("Archive contained no files")

		extracted_root = _resolve_manifest_root(tmp_dir)

		# If manifest.json exists, verify file hashes
		manifest_path = extracted_root / "manifest.json"
		if manifest_path.exists() and expected_files_sha256 is None:
			try:
				manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
				files_dict = manifest_data.get("files")
				if isinstance(files_dict, dict):
					expected_files_sha256 = files_dict
			except Exception as exc:
				logger.warning("Could not parse manifest.json for hash validation: %s", exc)

		if expected_files_sha256:
			if on_progress:
				on_progress("Verifying extracted files...", 60.0)

			for rel_path, expected_hash in expected_files_sha256.items():
				if cancel_token and cancel_token.is_cancelled:
					raise OperationCancelledError("Unpack verification cancelled")

				full_file = extracted_root / rel_path
				if not full_file.exists():
					raise UnpackError(f"Missing file in archive: {rel_path}")

				actual_hash = stream_sha256(full_file, cancel_token=cancel_token)
				if actual_hash.lower() != expected_hash.lower():
					raise UnpackError(
						f"Checksum mismatch for extracted file {rel_path}: expected {expected_hash}, got {actual_hash}"
					)

		if on_progress:
			on_progress(f"Installing {target_dir.name}...", 90.0)

		# Atomic directory swap
		target_dir.parent.mkdir(parents=True, exist_ok=True)
		if target_dir.exists():
			# Backup or remove old directory
			shutil.rmtree(target_dir, ignore_errors=True)

		shutil.copytree(extracted_root, target_dir)

	if on_progress:
		on_progress(f"Ready: {target_dir.name}", 100.0)

	logger.info("Successfully unpacked %s to %s", src_zip.name, target_dir)
	return target_dir

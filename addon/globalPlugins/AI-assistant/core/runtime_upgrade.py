"""Verified, idempotent retirement of superseded application runtime packages."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


def finalize_litert_upgrade(target: Path, version: str, *, busy: bool = False, check_cancelled=lambda: None) -> list[str]:
	"""Verify the replacement before retiring known obsolete versions.

	Locked/in-use packages are retained and retried on the next installation.
	Only recognized package directories beneath the same runtime root are eligible.
	The model registry is outside this root and is never touched.
	"""
	target = Path(target)
	if target.is_symlink() or target.is_junction():
		raise ValueError("Runtime package must not be a filesystem link")
	root = target.parent.resolve()
	if target.resolve().parent != root or target.name != version:
		raise ValueError("Invalid runtime package directory")
	manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
	if (manifest.get("runtime"), manifest.get("version"), manifest.get("platform")) != (
		"litert-lm", version, "windows-x64"
	):
		raise ValueError("Runtime manifest identity mismatch")
	files = manifest.get("files")
	if not isinstance(files, dict) or "python.exe" not in files:
		raise ValueError("Runtime manifest has no executable checksum")
	for name, expected in files.items():
		check_cancelled()
		file = target / name
		if not file.resolve().is_relative_to(target.resolve()):
			raise ValueError("Runtime manifest path escapes package")
		with file.open("rb") as stream:
			digest = hashlib.sha256()
			while chunk := stream.read(1024 * 1024):
				check_cancelled()
				digest.update(chunk)
			actual = digest.hexdigest()
		if actual != expected:
			raise ValueError("Runtime package checksum mismatch: " + name)
	pending = []
	# Explicit migration avoids deleting arbitrary/custom runtime installations.
	for obsolete in ("0.15.0",):
		if obsolete == version:
			continue
		candidate = root / obsolete
		if not candidate.exists():
			continue
		if candidate.is_symlink() or candidate.is_junction() or candidate.resolve().parent != root:
			continue
		try:
			old = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
			if old.get("runtime") != "litert-lm" or old.get("version") != obsolete:
				continue
			if busy:
				pending.append(obsolete)
				continue
			check_cancelled()
			shutil.rmtree(candidate)
		except (OSError, ValueError):
			pending.append(obsolete)
	return pending

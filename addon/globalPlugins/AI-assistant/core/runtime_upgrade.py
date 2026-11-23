"""Verified, idempotent retirement of superseded application runtime packages."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from collections.abc import Callable, Iterator
from pathlib import Path

_RETIRED_PREFIX = ".litert-lm-retired-"
_RELEASE_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_BACKUP_DIRECTORY = re.compile(r"\.([0-9]+\.[0-9]+\.[0-9]+)\.backup-[0-9a-f]{32}")


def _package_directory(path: Path, root: Path) -> bool:
	return (
		path.is_dir() and not path.is_symlink() and not path.is_junction()
		and path.resolve().parent == root
	)


def _read_manifest(path: Path, version: str) -> dict:
	manifest_path = path / "manifest.json"
	if manifest_path.is_symlink():
		raise ValueError("Runtime manifest must not be a filesystem link")
	manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
	if not isinstance(manifest, dict) or (
		manifest.get("runtime"), manifest.get("version"), manifest.get("platform")
	) != ("litert-lm", version, "windows-x64"):
		raise ValueError("Runtime manifest identity mismatch")
	return manifest


def _previous_packages(root: Path, version: str) -> Iterator[tuple[str, Path, bool]]:
	current = tuple(map(int, version.split(".")))
	try:
		entries = sorted(root.iterdir())
	except FileNotFoundError:
		return
	for candidate in entries:
		name = candidate.name.removeprefix(_RETIRED_PREFIX)
		retired = name != candidate.name
		backup = _BACKUP_DIRECTORY.fullmatch(name)
		obsolete = backup[1] if backup else name
		if not _RELEASE_VERSION.fullmatch(obsolete):
			continue
		release = tuple(map(int, obsolete.split(".")))
		if release > current or (release == current and not backup):
			continue
		try:
			if not _package_directory(candidate, root):
				continue
			# These reserved names survive partial deletion, including removal of the manifest.
			if not retired and not backup:
				_read_manifest(candidate, obsolete)
			yield obsolete, candidate, retired
		except (OSError, ValueError):
			continue


def has_previous_litert_runtime(root: Path, current_version: str, *, installed_only: bool = False) -> bool:
	"""Detect older installations and optionally include cleanup remnants."""
	try:
		for version, path, _ in _previous_packages(root.resolve(), current_version):
			if not installed_only or (path.name == version and (path / "python.exe").is_file()):
				return True
	except (OSError, ValueError):
		pass
	return False


class InvalidLiteRTPackage(ValueError):
	"""A replacement package failed its integrity checks."""


def litert_package_checksums(path: Path, version: str) -> dict[str, str]:
	files = _read_manifest(path, version).get("files")
	if not isinstance(files, dict) or "python.exe" not in files:
		raise ValueError("Runtime manifest has no executable checksum")
	if any(not isinstance(checksum, str) for checksum in files.values()):
		raise ValueError("Runtime manifest contains an invalid checksum")
	return files


def verify_litert_package(target: Path, version: str, check_cancelled: Callable[[], None]) -> None:
	root = target.parent.resolve()
	if target.name != version or not _package_directory(target, root):
		raise ValueError("Invalid runtime package directory")
	target = target.resolve()
	try:
		for name, expected in litert_package_checksums(target, version).items():
			check_cancelled()
			file = (target / name).resolve()
			if not file.is_relative_to(target):
				raise ValueError("Runtime manifest path escapes package")
			with file.open("rb") as stream:
				digest = hashlib.sha256()
				while chunk := stream.read(1024 * 1024):
					check_cancelled()
					digest.update(chunk)
			if digest.hexdigest() != expected.lower():
				raise ValueError("Runtime package checksum mismatch: " + name)
	except (ValueError, FileNotFoundError, IsADirectoryError) as exc:
		raise InvalidLiteRTPackage(str(exc)) from exc


def _retry_read_only_unlink(operation, filename, error):
	if os.name != "nt" or operation is not os.unlink or not isinstance(error, PermissionError):
		raise error
	path = Path(filename)
	info = path.stat(follow_symlinks=False)
	attributes = info.st_file_attributes
	if (
		not stat.S_ISREG(info.st_mode)
		or info.st_nlink != 1
		or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
		or not attributes & stat.FILE_ATTRIBUTE_READONLY
	):
		raise error
	path.chmod(stat.S_IWRITE)
	path.unlink()


def finalize_litert_upgrade(
	target: Path,
	version: str,
	*,
	busy: bool = False,
	prepare_cleanup: Callable[[tuple[Path, ...]], bool] | None = None,
	check_cancelled: Callable[[], None] = lambda: None,
	on_deferred: Callable[[str], None] | None = None,
) -> list[str]:
	"""Verify the replacement and retire only recognized packages.

	Move packages out of their install paths before deleting them so a partial
	deletion can be retried even after the original manifest is gone.
	"""
	verify_litert_package(target, version, check_cancelled)
	root = target.parent.resolve()

	packages = list(_previous_packages(root, version))
	check_cancelled()
	if packages and prepare_cleanup is not None:
		busy = busy or not prepare_cleanup(tuple(path for _, path, retired in packages if not retired))
	pending = set()
	for obsolete, path, retired in packages:
		check_cancelled()
		if busy:
			pending.add(obsolete)
			if on_deferred is not None:
				on_deferred(f"{path.name}: runtime is active or its ownership could not be confirmed")
			continue
		try:
			if not retired:
				destination = root / (_RETIRED_PREFIX + path.name)
				path.rename(destination)
				path = destination
			shutil.rmtree(path, onexc=_retry_read_only_unlink)
		except OSError as exc:
			pending.add(obsolete)
			if on_deferred is not None:
				on_deferred(f"{path.name}: {exc}")
	return sorted(pending)

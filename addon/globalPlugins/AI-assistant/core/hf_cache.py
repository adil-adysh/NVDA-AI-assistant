"""Read-only inventory of GGUF artifacts in the Hugging Face cache.

A cached file is evidence that an artifact is locally readable. It is not
ownership: the cache is shared, it may change concurrently, and nothing here
writes, repairs, evicts or deletes cache entries.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import struct
from typing import Callable, Iterable

_GGUF_MAGIC = b"GGUF"
_MAX_STRING = 4 * 1024 * 1024
_MAX_ARRAY = 10_000_000
_MAX_DEPTH = 8
_DRAFT_PREFIXES = ("dflash-", "mtp-", "eagle3-", "dspark-")
_QUANT_RE = re.compile(
	r"(?i)(?:^|[-_.])((?:UD-)?(?:IQ\d+(?:_[A-Z0-9]+)*|Q\d+(?:_[A-Z0-9]+)*|"
	r"BF16|F16|F32|NVFP4|MXFP4|FP8|FP16))$"
)
_SPLIT_RE = re.compile(r"^(?P<prefix>.*)-(?P<index>\d{5})-of-(?P<total>\d{5})\.gguf$", re.IGNORECASE)


@dataclass(frozen=True)
class CachedArtifact:
	repo: str
	revision: str
	path: str
	size: int
	role: str
	architecture: str = ""
	quant: str = ""
	complete: bool = True
	parts: int = 1

	@property
	def label(self) -> str:
		return self.quant or Path(self.path).stem


@dataclass(frozen=True)
class CachedRepository:
	repo: str
	revision: str
	artifacts: tuple[CachedArtifact, ...]
	revision_confirmed: bool = True


class _Reader:
	def __init__(self, handle) -> None:
		self._handle = handle

	def exact(self, size: int) -> bytes:
		value = self._handle.read(size)
		if len(value) != size:
			raise ValueError("truncated GGUF metadata")
		return value

	def unpack(self, fmt: str):
		size = struct.calcsize(fmt)
		return struct.unpack(fmt, self.exact(size))[0]

	def string(self) -> str:
		length = self.unpack("<Q")
		if length > _MAX_STRING:
			raise ValueError("oversized GGUF string")
		return self.exact(length).decode("utf-8", "replace")


def _skip_value(reader: _Reader, value_type: int, depth: int = 0) -> None:
	if depth > _MAX_DEPTH:
		raise ValueError("nested GGUF metadata")
	sizes = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
	if value_type in sizes:
		reader.exact(sizes[value_type])
		return
	if value_type == 8:
		reader.string()
		return
	if value_type == 9:
		element_type = reader.unpack("<I")
		count = reader.unpack("<Q")
		if count > _MAX_ARRAY:
			raise ValueError("oversized GGUF array")
		for _ in range(count):
			_skip_value(reader, element_type, depth + 1)
		return
	raise ValueError(f"unknown GGUF metadata type {value_type}")


def read_gguf_metadata(path: str | Path) -> dict[str, str]:
	"""Read selected string metadata from a GGUF header.

	Malformed or truncated files raise ``ValueError``/``OSError``. Callers that
	inventory a cache must treat that as "not a usable GGUF", not as a model.
	"""
	with open(path, "rb") as handle:
		reader = _Reader(handle)
		if reader.exact(4) != _GGUF_MAGIC:
			raise ValueError("not a GGUF file")
		version = reader.unpack("<I")
		if version < 2 or version > 3:
			raise ValueError(f"unsupported GGUF version {version}")
		reader.unpack("<Q")  # tensor count
		count = reader.unpack("<Q")
		if count > _MAX_ARRAY:
			raise ValueError("oversized GGUF metadata table")
		result = {}
		wanted = {"general.architecture", "general.type", "general.name"}
		for _ in range(count):
			key = reader.string()
			value_type = reader.unpack("<I")
			if key in wanted and value_type == 8:
				result[key] = reader.string()
			else:
				_skip_value(reader, value_type)
		return result


def cache_roots(explicit: Iterable[str | Path] | None = None) -> tuple[Path, ...]:
	"""Return candidate hub cache directories, deduplicated.

	Hugging Face documents the cache root as configurable, so callers may pass
	their own roots. The environment is consulted before the conventional
	per-user location.
	"""
	if explicit is not None:
		candidates = [Path(value) for value in explicit]
	else:
		candidates = []
		home = os.getenv("HF_HOME")
		if home:
			candidates.append(Path(home) / "hub")
		for name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
			value = os.getenv(name)
			if value:
				candidates.append(Path(value))
		xdg = os.getenv("XDG_CACHE_HOME")
		candidates.append(Path(xdg) / "huggingface" / "hub" if xdg else Path.home() / ".cache" / "huggingface" / "hub")
	unique = []
	seen = set()
	for candidate in candidates:
		try:
			resolved = candidate.expanduser().resolve()
		except OSError:
			resolved = candidate.expanduser()
		key = os.path.normcase(str(resolved))
		if key not in seen:
			seen.add(key)
			unique.append(resolved)
	return tuple(unique)


def _repo_identity(directory: Path) -> str | None:
	name = directory.name
	if not name.startswith("models--"):
		return None
	parts = name.split("--", 2)
	if len(parts) != 3 or not parts[1] or not parts[2]:
		return None
	return f"{parts[1]}/{parts[2]}"


def _current_revision(repository: Path) -> tuple[str, Path, bool] | None:
	snapshots = repository / "snapshots"
	if not snapshots.is_dir():
		return None
	try:
		value = (repository / "refs" / "main").read_text(encoding="utf-8").strip()
	except OSError:
		return None
	if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
		return None
	revision = value.lower()
	for entry in snapshots.iterdir():
		if entry.name.lower() == revision and entry.is_dir():
			return revision, entry, True
	return None


def _role(path: str, metadata: dict[str, str]) -> str:
	name = Path(path).name.lower()
	kind = metadata.get("general.type", "").strip().lower()
	architecture = metadata.get("general.architecture", "").strip().lower()
	if kind in {"mmproj", "projector"} or "mmproj" in name or architecture in {"clip", "mtmd"}:
		return "projector"
	if kind in {"draft", "draft-model"} or name.startswith(_DRAFT_PREFIXES):
		return "draft"
	return "main"


def _quant(path: str) -> str:
	stem = Path(path).stem
	match = _QUANT_RE.search(stem)
	return match.group(1).upper() if match else ""


def _artifact_files(snapshot: Path, cancelled: Callable[[], bool] | None) -> list[tuple[str, Path, int]]:
	files = []
	seen = set()
	def failed(error):
		return None
	for root, _directories, names in os.walk(snapshot, followlinks=False, onerror=failed):
		if cancelled is not None and cancelled():
			return files
		for name in names:
			if not name.lower().endswith(".gguf"):
				continue
			path = Path(root) / name
			try:
				resolved = path.resolve(strict=True)
				if not resolved.is_file():
					continue
				size = resolved.stat().st_size
			except OSError:
				continue
			relative = path.relative_to(snapshot).as_posix()
			key = (relative.casefold(), os.path.normcase(str(resolved)))
			if key in seen:
				continue
			seen.add(key)
			files.append((relative, path, size))
	return files


def _group_splits(files: list[tuple[str, Path, int]]) -> list[tuple[str, Path, int, bool, int]]:
	groups: dict[str, list[tuple[str, Path, int, int, int]]] = {}
	singles = []
	for path, physical, size in files:
		match = _SPLIT_RE.match(Path(path).name)
		if not match:
			singles.append((path, physical, size, True, 1))
			continue
		key = (str(Path(path).parent), match.group("prefix").casefold(), int(match.group("total")))
		groups.setdefault(key, []).append((path, physical, size, int(match.group("index")), int(match.group("total"))))
	result = list(singles)
	for parts in groups.values():
		indexes = {part[3] for part in parts}
		total = parts[0][4]
		complete = indexes == set(range(1, total + 1))
		first = next((part for part in parts if part[3] == 1), min(parts, key=lambda part: part[3]))
		size = sum(part[2] for part in parts)
		result.append((first[0], first[1], size, complete, total))
	return result


def scan_cached_artifacts(
	roots: Iterable[str | Path] | None = None,
	*,
	cancelled: Callable[[], bool] | None = None,
) -> tuple[CachedRepository, ...]:
	"""Inventory readable GGUF artifacts below the configured cache roots.

	The scan is read-only. Broken links, missing snapshots, malformed headers and
	concurrent removals are skipped rather than repaired or reported as models.
	"""
	repositories = []
	seen_repos = set()
	for root in cache_roots(roots):
		if cancelled is not None and cancelled():
			break
		try:
			entries = list(root.iterdir())
		except OSError:
			continue
		for directory in entries:
			if cancelled is not None and cancelled():
				break
			repo = _repo_identity(directory)
			if repo is None or not directory.is_dir():
				continue
			key = (repo.casefold(), os.path.normcase(str(directory)))
			if key in seen_repos:
				continue
			seen_repos.add(key)
			current = _current_revision(directory)
			if current is None:
				continue
			revision, snapshot, confirmed = current
			raw_files = _artifact_files(snapshot, cancelled)
			artifacts = []
			for path, physical, size, complete, parts in _group_splits(raw_files):
				if cancelled is not None and cancelled():
					break
				try:
					metadata = read_gguf_metadata(physical)
				except (OSError, ValueError):
					continue
				artifacts.append(CachedArtifact(
					repo=repo,
					revision=revision,
					path=path,
					size=size,
					role=_role(path, metadata),
					architecture=metadata.get("general.architecture", ""),
					quant=_quant(path),
					complete=complete,
					parts=parts,
				))
			if artifacts:
				repositories.append(CachedRepository(
					repo=repo,
					revision=revision,
					artifacts=tuple(sorted(artifacts, key=lambda item: (item.role, item.path.casefold()))),
					revision_confirmed=confirmed,
				))
	return tuple(sorted(repositories, key=lambda item: item.repo.casefold()))


__all__ = [
	"CachedArtifact",
	"CachedRepository",
	"cache_roots",
	"read_gguf_metadata",
	"scan_cached_artifacts",
]

# -*- coding: utf-8 -*-
"""Runtime type and configuration models."""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from typing import Any


class RuntimeType(str, Enum):
	"""Known runtime backend identifiers."""

	LITERT_LM = "litert-lm"
	# Future: LLAMA_CPP = "llama-cpp"
	# Future: ONNX_GENAI = "onnx-genai"


@dataclass(frozen=True)
class RuntimeConfig:
	"""Configuration for a downloaded runtime backend.

	Attributes:
	    runtime: Backend identifier (e.g., "litert-lm").
	    version: Semantic version of the runtime (e.g., "0.15.0").
	    platform: Target platform (e.g., "windows-x64").
	    import_name: Python package name to import after path injection.
	        Falls back to runtime identifier with hyphens replaced.
	    min_python: Minimum Python version required.
	"""

	runtime: str
	version: str
	platform: str = "windows-x64"
	import_name: str = ""
	min_python: str = ">=3.10"

	@property
	def package_name(self) -> str:
		"""The Python package to import after path injection."""
		return self.import_name or self.runtime.replace("-", "_")

	@classmethod
	def for_runtime(
		cls,
		runtime: str,
		version: str,
		platform: str = "windows-x64",
	) -> RuntimeConfig:
		"""Create a RuntimeConfig with the import_name derived automatically."""
		return cls(
			runtime=runtime,
			version=version,
			platform=platform,
			import_name=runtime.replace("-", "_"),
		)


@dataclass(frozen=True)
class DownloadManifest:
	"""Expected properties of a downloadable runtime bundle.

	Serialized as manifest.json inside the runtime ZIP.
	"""

	runtime: str
	version: str
	platform: str
	python: str
	arch: str
	cpus: list[str]
	gpu: bool
	openvino: bool
	fileCount: int
	totalSizeBytes: int
	files: dict[str, str]  # relative path → sha256
	built_at: str = ""  # ISO-8601 timestamp of when the bundle was built

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> DownloadManifest:
		"""Build a DownloadManifest from a JSON-deserialized dict.

		Raises ValueError if required fields are missing or have wrong types.
		"""
		known = {f.name for f in fields(cls)}
		filtered = {k: v for k, v in data.items() if k in known}

		missing = known - set(filtered)
		if missing:
			raise ValueError(f"DownloadManifest missing required fields: {', '.join(sorted(missing))}")
		return cls(**filtered)

	def to_dict(self) -> dict[str, Any]:
		"""Serialize to a JSON-compatible dict."""
		return {
			"runtime": self.runtime,
			"version": self.version,
			"platform": self.platform,
			"python": self.python,
			"arch": self.arch,
			"cpus": list(self.cpus),
			"gpu": self.gpu,
			"openvino": self.openvino,
			"fileCount": self.fileCount,
			"totalSizeBytes": self.totalSizeBytes,
			"files": dict(self.files),
			"built_at": self.built_at,
		}


@dataclass(frozen=True)
class DefaultRuntimeConfig:
	"""Default versions for known runtimes.

	Stored in config.yaml so users can override per-runtime version.
	"""

	litert_lm: str = "0.15.0"

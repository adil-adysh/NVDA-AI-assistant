# -*- coding: utf-8 -*-
"""Multi-Modal Model Descriptors and Resource Specifications.

Defines immutable, frozen dataclasses representing model specifications,
resource demands, storage sources, and readiness states across all modalities
(CHAT, VISION, OCR, TRANSCRIPTION, EMBEDDING, TTS).
Enforces Invariant A11, A12, and A15.
Zero NVDA dependencies — pure standard library.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal


class Modality(str, Enum):
	"""Supported model interaction modalities."""

	CHAT = "chat"
	VISION = "vision"
	OCR = "ocr"
	TRANSCRIPTION = "transcription"
	EMBEDDING = "embedding"
	TTS = "tts"


class ModelReadinessStatus(str, Enum):
	"""Explicit model availability states. Enforces Invariant A14 (fail-closed)."""

	READY = "ready"
	NOT_DOWNLOADED = "not_downloaded"
	DOWNLOADING = "downloading"
	UNAVAILABLE = "unavailable"
	ERROR = "error"


@dataclass(frozen=True, slots=True)
class ModelResourceSpec:
	"""Resource requirements and hardware placement hints for a model."""

	ram_bytes: int
	vram_bytes: int = 0
	compute_target: Literal["cpu", "gpu", "npu", "universal"] = "universal"
	context_window: int | None = None

	def to_dict(self) -> dict[str, Any]:
		return {
			"ram_bytes": self.ram_bytes,
			"vram_bytes": self.vram_bytes,
			"compute_target": self.compute_target,
			"context_window": self.context_window,
		}

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> ModelResourceSpec:
		return cls(
			ram_bytes=int(data.get("ram_bytes", 0)),
			vram_bytes=int(data.get("vram_bytes", 0)),
			compute_target=data.get("compute_target", "universal"),
			context_window=data.get("context_window"),
		)


@dataclass(frozen=True, slots=True)
class ModelSourceSpec:
	"""Origin and download specification for acquiring model artifacts."""

	kind: Literal[
		"cloud_endpoint",
		"huggingface_file",
		"huggingface_repo",
		"direct_url",
		"local_file",
	]
	location: str
	filename: str
	revision: str = "main"
	sha256: str | None = None
	auth_required: bool = False

	def to_dict(self) -> dict[str, Any]:
		return {
			"kind": self.kind,
			"location": self.location,
			"filename": self.filename,
			"revision": self.revision,
			"sha256": self.sha256,
			"auth_required": self.auth_required,
		}

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> ModelSourceSpec:
		return cls(
			kind=data.get("kind", "cloud_endpoint"),
			location=str(data.get("location", "")),
			filename=str(data.get("filename", "")),
			revision=str(data.get("revision", "main")),
			sha256=data.get("sha256"),
			auth_required=bool(data.get("auth_required", False)),
		)


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
	"""Unified specification of a model across any provider or modality."""

	model_id: str
	display_name: str
	provider_id: str
	modality: Modality
	capabilities: frozenset[str]
	source: ModelSourceSpec
	resources: ModelResourceSpec
	priority: int = 100
	description: str = ""
	canonical_group_id: str | None = None

	def to_dict(self) -> dict[str, Any]:
		return {
			"model_id": self.model_id,
			"display_name": self.display_name,
			"provider_id": self.provider_id,
			"modality": self.modality.value,
			"capabilities": sorted(self.capabilities),
			"source": self.source.to_dict(),
			"resources": self.resources.to_dict(),
			"priority": self.priority,
			"description": self.description,
			"canonical_group_id": self.canonical_group_id,
		}

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> ModelDescriptor:
		return cls(
			model_id=str(data["model_id"]),
			display_name=str(data.get("display_name", data["model_id"])),
			provider_id=str(data["provider_id"]),
			modality=Modality(data.get("modality", "chat")),
			capabilities=frozenset(data.get("capabilities", ())),
			source=ModelSourceSpec.from_dict(data.get("source", {})),
			resources=ModelResourceSpec.from_dict(data.get("resources", {})),
			priority=int(data.get("priority", 100)),
			description=str(data.get("description", "")),
			canonical_group_id=data.get("canonical_group_id"),
		)

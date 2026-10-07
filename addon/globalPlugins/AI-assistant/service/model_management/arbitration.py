# -*- coding: utf-8 -*-
"""Multi-Modal Resource Arbitration and Idle Reaper.

Arbitrates system RAM and VRAM allocations across concurrent model requests
for CHAT, VISION, OCR, TRANSCRIPTION, and EMBEDDING.
Implements the multi-modal hardware tier policy and 60-second idle reaper.
Enforces Invariant A12 and A15.
Zero NVDA dependencies — pure standard library.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading
import time
from typing import Any

from .descriptors import Modality, ModelDescriptor


class HardwareTier(str, Enum):
	"""Detected system hardware capability tier."""

	LOW_END = "low_end"  # < 16GB RAM or < 2GB VRAM: strict 1 active model
	MID_RANGE = "mid_range"  # 16-32GB RAM, 4-6GB VRAM: 1 GPU LLM + 1 CPU Helper
	HIGH_END = "high_end"  # >= 32GB RAM, >= 8GB VRAM: 1 GPU LLM + 1 GPU Helper


@dataclass(frozen=True, slots=True)
class HardwareProfile:
	"""Detected system memory and accelerator profile."""

	system_ram_bytes: int
	detected_vram_bytes: int = 0
	tier: HardwareTier = HardwareTier.MID_RANGE

	@classmethod
	def detect(
		cls,
		ram_bytes: int | None = None,
		vram_bytes: int | None = None,
	) -> HardwareProfile:
		"""Construct or detect hardware profile based on available resources."""
		total_ram = ram_bytes or (16 * 1024 * 1024 * 1024)  # default 16 GB
		total_vram = vram_bytes if vram_bytes is not None else 0

		gb_ram = total_ram / (1024**3)
		gb_vram = total_vram / (1024**3)

		if gb_ram < 16.0 or gb_vram < 2.0:
			tier = HardwareTier.LOW_END
		elif gb_ram >= 32.0 and gb_vram >= 8.0:
			tier = HardwareTier.HIGH_END
		else:
			tier = HardwareTier.MID_RANGE

		return cls(
			system_ram_bytes=total_ram,
			detected_vram_bytes=total_vram,
			tier=tier,
		)


@dataclass(frozen=True, slots=True)
class AllocationDecision:
	"""Outcome of an arbitration request for model execution."""

	can_allocate: bool
	target_device: str  # "cpu", "gpu", "universal"
	models_to_evict: tuple[str, ...] = ()
	reason: str = ""


@dataclass(slots=True)
class ActiveAllocation:
	"""Tracked state of an actively allocated model."""

	model_id: str
	modality: Modality
	target_device: str
	allocated_at: float
	last_active_at: float
	is_ephemeral: bool = False  # Ephemeral models (OCR, Vision) reaped after 60s idle


class ResourceArbitrator:
	"""Thread-safe multi-modal resource allocator with hardware tier policies."""

	def __init__(
		self,
		profile: HardwareProfile | None = None,
		ephemeral_idle_timeout_seconds: float = 60.0,
	) -> None:
		self._profile = profile or HardwareProfile.detect()
		self._ephemeral_idle_timeout = ephemeral_idle_timeout_seconds
		self._allocations: dict[str, ActiveAllocation] = {}
		self._lock = threading.RLock()

	@property
	def profile(self) -> HardwareProfile:
		return self._profile

	def request_allocation(self, descriptor: ModelDescriptor) -> AllocationDecision:
		"""Evaluate whether descriptor can be loaded under current hardware constraints."""
		with self._lock:
			model_id = descriptor.model_id
			# Already allocated
			if model_id in self._allocations:
				self.record_activity(model_id)
				return AllocationDecision(
					can_allocate=True,
					target_device=self._allocations[model_id].target_device,
					models_to_evict=(),
					reason="Already allocated",
				)

			modality = descriptor.modality
			tier = self._profile.tier

			# Policy 1: Low-End Hardware (<16GB RAM or <2GB VRAM)
			# Strict exclusive locking: unload all active models before loading another
			if tier == HardwareTier.LOW_END:
				evictions = tuple(self._allocations.keys())
				target_device = "cpu"
				return AllocationDecision(
					can_allocate=True,
					target_device=target_device,
					models_to_evict=evictions,
					reason="Low-end hardware: exclusive single-model execution",
				)

			# Policy 2: Mid-Range Hardware (16-32GB RAM, 4-6GB VRAM)
			# 1 GPU LLM + 1 CPU Helper
			if tier == HardwareTier.MID_RANGE:
				if modality == Modality.CHAT:
					# Evict any other active CHAT model
					chat_evictions = tuple(
						mid
						for mid, alloc in self._allocations.items()
						if alloc.modality == Modality.CHAT
					)
					return AllocationDecision(
						can_allocate=True,
						target_device="gpu" if self._profile.detected_vram_bytes >= (4 * 1024**3) else "cpu",
						models_to_evict=chat_evictions,
						reason="Mid-range: 1 active GPU LLM",
					)
				else:
					# Helper models (OCR, Whisper, Embedding) run on CPU to protect LLM VRAM
					return AllocationDecision(
						can_allocate=True,
						target_device="cpu",
						models_to_evict=(),
						reason="Mid-range: Helper pinned to CPU to protect LLM VRAM",
					)

			# Policy 3: High-End Hardware (>=32GB RAM, >=8GB VRAM)
			# Dynamic VRAM partitioning: 70% LLM, 30% Helper
			chat_evictions = ()
			if modality == Modality.CHAT:
				chat_evictions = tuple(
					mid
					for mid, alloc in self._allocations.items()
					if alloc.modality == Modality.CHAT
				)

			return AllocationDecision(
				can_allocate=True,
				target_device="gpu",
				models_to_evict=chat_evictions,
				reason="High-end: multi-model GPU co-existence",
			)

	def commit_allocation(
		self,
		descriptor: ModelDescriptor,
		target_device: str = "cpu",
	) -> None:
		"""Commit an allocation once loading succeeds."""
		with self._lock:
			now = time.time()
			is_ephemeral = descriptor.modality in (Modality.OCR, Modality.VISION)
			self._allocations[descriptor.model_id] = ActiveAllocation(
				model_id=descriptor.model_id,
				modality=descriptor.modality,
				target_device=target_device,
				allocated_at=now,
				last_active_at=now,
				is_ephemeral=is_ephemeral,
			)

	def release_allocation(self, model_id: str) -> None:
		"""Remove an allocation when model is unloaded."""
		with self._lock:
			self._allocations.pop(model_id, None)

	def record_activity(self, model_id: str) -> None:
		"""Touch the last-active timestamp for model_id."""
		with self._lock:
			alloc = self._allocations.get(model_id)
			if alloc:
				alloc.last_active_at = time.time()

	def get_reapable_models(self, now: float | None = None) -> tuple[str, ...]:
		"""Return model_ids of idle ephemeral models exceeding idle timeout (60s)."""
		current_time = now if now is not None else time.time()
		with self._lock:
			reapable = []
			for mid, alloc in self._allocations.items():
				if alloc.is_ephemeral:
					if (current_time - alloc.last_active_at) >= self._ephemeral_idle_timeout:
						reapable.append(mid)
			return tuple(reapable)

	def list_active_allocations(self) -> tuple[dict[str, Any], ...]:
		with self._lock:
			return tuple(
				{
					"model_id": a.model_id,
					"modality": a.modality.value,
					"target_device": a.target_device,
					"allocated_at": a.allocated_at,
					"last_active_at": a.last_active_at,
					"is_ephemeral": a.is_ephemeral,
				}
				for a in self._allocations.values()
			)

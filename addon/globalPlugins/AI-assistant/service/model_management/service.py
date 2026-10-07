# -*- coding: utf-8 -*-
"""Centralized Application Model Management Service.

Coordinates model catalogs, configured-model policy, negative visibility,
multi-modal resource arbitration, and explicit availability checking.
Enforces Architectural Invariants A11, A12, A13, A14, and A15.
Zero NVDA dependencies — pure standard library.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
from typing import TYPE_CHECKING
from collections.abc import Callable

from .arbitration import AllocationDecision, ResourceArbitrator
from .descriptors import (
	Modality,
	ModelDescriptor,
	ModelReadinessStatus,
)

if TYPE_CHECKING:
	from ...core.job.client import JobClient

logger = logging.getLogger(__name__)


class ModelUnavailableError(RuntimeError):
	"""Raised when a requested model is unavailable and silent fallback is forbidden."""


class ModelManagementService:
	"""Central application service for model lifecycle, visibility, and arbitration."""

	def __init__(
		self,
		models_root_dir: Path | str | None = None,
		arbitrator: ResourceArbitrator | None = None,
		worker_client: JobClient | None = None,
		visibility_predicate: Callable[[str, str], bool] | None = None,
	) -> None:
		self._models_root = Path(models_root_dir) if models_root_dir else self._default_models_root()
		self._arbitrator = arbitrator or ResourceArbitrator()
		self._worker_client = worker_client
		self._visibility_predicate = visibility_predicate
		self._lock = threading.RLock()

		# Registered descriptors: (provider_id, model_id) -> ModelDescriptor
		self._descriptors: dict[tuple[str, str], ModelDescriptor] = {}

		# Configured active models per modality: modality -> (provider_id, model_id)
		self._configured_models: dict[Modality, tuple[str, str]] = {}

		# Explicitly hidden models (negative visibility set): set of (provider_id, model_id)
		self._hidden_models: set[tuple[str, str]] = set()

		# Catalog listeners
		self._catalog_subscribers: list[Callable[[str], None]] = []

	# ------------------------------------------------------------------
	# Storage Policy (Invariant A13)
	# ------------------------------------------------------------------

	@staticmethod
	def _default_models_root() -> Path:
		appdata = os.getenv("APPDATA")
		base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
		return base / "nvda" / "AIAssistant" / "models"

	@property
	def models_root_dir(self) -> Path:
		return self._models_root

	def get_model_storage_path(self, provider_id: str, filename_or_model_id: str) -> Path:
		"""Return standardized local file path for a model."""
		safe_provider = provider_id.replace("/", "_").replace("\\", "_")
		safe_file = filename_or_model_id.replace("/", "_").replace("\\", "_")
		return self._models_root / safe_provider / safe_file

	# ------------------------------------------------------------------
	# Descriptor Registry & Discovery (Invariant A11)
	# ------------------------------------------------------------------

	def register_model(self, descriptor: ModelDescriptor) -> None:
		"""Register or update a model descriptor in the catalog."""
		with self._lock:
			key = (descriptor.provider_id, descriptor.model_id)
			self._descriptors[key] = descriptor

		self._notify_catalog_subscribers(descriptor.provider_id)

	def unregister_model(self, provider_id: str, model_id: str) -> bool:
		"""Remove a model descriptor from the registry."""
		with self._lock:
			removed = self._descriptors.pop((provider_id, model_id), None) is not None

		if removed:
			self._notify_catalog_subscribers(provider_id)
		return removed

	def get_model(self, provider_id: str, model_id: str) -> ModelDescriptor | None:
		"""Look up a model descriptor by provider and model ID."""
		with self._lock:
			return self._descriptors.get((provider_id, model_id))

	def list_models(
		self,
		provider_id: str | None = None,
		modality: Modality | None = None,
		visible_only: bool = True,
	) -> tuple[ModelDescriptor, ...]:
		"""List registered models filtered by provider, modality, and visibility."""
		with self._lock:
			results: list[ModelDescriptor] = []
			for (pid, mid), desc in self._descriptors.items():
				if provider_id is not None and pid != provider_id:
					continue
				if modality is not None and desc.modality != modality:
					continue
				if visible_only and self.is_model_hidden(pid, mid):
					continue
				results.append(desc)
			return tuple(sorted(results, key=lambda m: (-m.priority, m.display_name)))

	# ------------------------------------------------------------------
	# Negative Visibility Policy (Preserves baseline)
	# ------------------------------------------------------------------

	def hide_model(self, provider_id: str, model_id: str) -> None:
		"""Add model to negative visibility set."""
		with self._lock:
			self._hidden_models.add((provider_id, model_id))
		self._notify_catalog_subscribers(provider_id)

	def unhide_model(self, provider_id: str, model_id: str) -> None:
		"""Remove model from negative visibility set."""
		with self._lock:
			self._hidden_models.discard((provider_id, model_id))
		self._notify_catalog_subscribers(provider_id)

	def is_model_hidden(self, provider_id: str, model_id: str) -> bool:
		"""Check if model is currently hidden."""
		with self._lock:
			if (provider_id, model_id) in self._hidden_models:
				return True
			if self._visibility_predicate is not None:
				return not self._visibility_predicate(provider_id, model_id)
			return False

	# ------------------------------------------------------------------
	# Configured-Model Policy & Explicit Availability (Invariant A14)
	# ------------------------------------------------------------------

	def configure_model(self, modality: Modality, provider_id: str, model_id: str) -> None:
		"""Set the authoritative configured model for a given modality."""
		with self._lock:
			self._configured_models[modality] = (provider_id, model_id)

	def get_configured_model(self, modality: Modality) -> tuple[str, str] | None:
		"""Get (provider_id, model_id) configured for modality."""
		with self._lock:
			return self._configured_models.get(modality)

	def check_model_readiness(
		self, provider_id: str, model_id: str
	) -> ModelReadinessStatus:
		"""Evaluate model readiness without blocking or network calls."""
		with self._lock:
			desc = self._descriptors.get((provider_id, model_id))
			if desc is None:
				return ModelReadinessStatus.UNAVAILABLE

			# Cloud endpoints are immediately ready if registered
			if desc.source.kind == "cloud_endpoint":
				return ModelReadinessStatus.READY

			# Local file or downloadable bundle
			expected_path = self.get_model_storage_path(provider_id, desc.source.filename)
			if expected_path.exists():
				return ModelReadinessStatus.READY

			part_path = expected_path.with_name(expected_path.name + ".part")
			if part_path.exists():
				return ModelReadinessStatus.DOWNLOADING

			return ModelReadinessStatus.NOT_DOWNLOADED

	def get_active_model_or_raise(self, modality: Modality) -> ModelDescriptor:
		"""Retrieve active descriptor for modality or raise ModelUnavailableError.

		Enforces Invariant A14: fail-closed policy — never silently switch models.
		"""
		with self._lock:
			configured = self._configured_models.get(modality)
			if configured is None:
				raise ModelUnavailableError(
					f"No model configured for modality '{modality.value}'"
				)

			pid, mid = configured
			desc = self._descriptors.get((pid, mid))
			if desc is None:
				raise ModelUnavailableError(
					f"Configured model '{mid}' for provider '{pid}' is not registered"
				)

			status = self.check_model_readiness(pid, mid)
			if status != ModelReadinessStatus.READY:
				raise ModelUnavailableError(
					f"Configured model '{mid}' is not ready (status: {status.value})"
				)

			return desc

	# ------------------------------------------------------------------
	# Resource Arbitration & Ephemeral Reaper (Invariant A12, A15)
	# ------------------------------------------------------------------

	@property
	def arbitrator(self) -> ResourceArbitrator:
		return self._arbitrator

	def request_activation(self, descriptor: ModelDescriptor) -> AllocationDecision:
		"""Arbitrate system resources before starting model execution."""
		decision = self._arbitrator.request_allocation(descriptor)
		if decision.can_allocate:
			self._arbitrator.commit_allocation(descriptor, decision.target_device)
		return decision

	def release_model(self, model_id: str) -> None:
		"""Release active model allocation."""
		self._arbitrator.release_allocation(model_id)

	def reap_idle_models(self) -> tuple[str, ...]:
		"""Evict expired ephemeral models (OCR/Vision) after 60s idle."""
		reapable = self._arbitrator.get_reapable_models()
		for mid in reapable:
			logger.info("Idle reaper unloading ephemeral model: %s", mid)
			self._arbitrator.release_allocation(mid)
		return reapable

	# ------------------------------------------------------------------
	# Catalog Event Subscription
	# ------------------------------------------------------------------

	def subscribe_catalog_changes(self, callback: Callable[[str], None]) -> Callable[[], None]:
		"""Subscribe to catalog changes. Returns an unsubscribe function."""
		with self._lock:
			self._catalog_subscribers.append(callback)

		def unsubscribe() -> None:
			with self._lock:
				if callback in self._catalog_subscribers:
					self._catalog_subscribers.remove(callback)

		return unsubscribe

	def _notify_catalog_subscribers(self, provider_id: str) -> None:
		with self._lock:
			subs = list(self._catalog_subscribers)
		for sub in subs:
			try:
				sub(provider_id)
			except Exception as exc:
				logger.error("Error in catalog subscriber: %s", exc)

# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from ..config.settings import (
	get_enabled_providers,
	get_provider,
	get_provider_state,
	save,
	set_litert_think,
	set_model_name,
	set_ollama_think,
	set_provider,
)
from ..config.state import ProviderState
from ..providers.registry import PROVIDER_IDS
from .provider_readiness import ProviderReadiness, ProviderReadinessService


@dataclass(frozen=True, slots=True)
class ProviderControlResult:
	provider_state: ProviderState
	readiness: ProviderReadiness


class ProviderControlService:
	# Canonical provider order/identity comes from the provider registry.
	PROVIDER_ORDER = PROVIDER_IDS

	def __init__(self, readiness_service: ProviderReadinessService | None = None) -> None:
		self._readiness_service = readiness_service or ProviderReadinessService()

	def current_state(self) -> ProviderControlResult:
		return ProviderControlResult(
			provider_state=get_provider_state(),
			readiness=self._readiness_service.evaluate_active(),
		)

	def select_provider(self, provider: str) -> ProviderControlResult:
		enabled = get_enabled_providers()
		if provider not in enabled:
			raise ValueError(
				f"Provider '{provider}' is disabled. Enabled providers: {enabled}"
			)
		set_provider(provider)
		save()
		return self.current_state()

	def cycle_provider(self) -> ProviderControlResult:
		current_provider = get_provider()
		enabled = get_enabled_providers()
		# Build cycle order from PROVIDER_ORDER, filtering to enabled providers only.
		cycle_order = [p for p in self.PROVIDER_ORDER if p in enabled]
		if not cycle_order:
			return self.current_state()
		if current_provider not in cycle_order:
			target_provider = cycle_order[0]
		else:
			idx = cycle_order.index(current_provider)
			target_provider = cycle_order[(idx + 1) % len(cycle_order)]
		return self.select_provider(target_provider)

	def select_model(self, model: str, provider: str | None = None) -> ProviderControlResult:
		if provider:
			self.select_provider(provider)
		set_model_name(model)
		save()
		return self.current_state()

	def set_think_mode(self, enabled: bool) -> ProviderControlResult:
		provider = get_provider()
		if provider == "litert-lm":
			set_litert_think(enabled)
		else:
			set_ollama_think(enabled)
		save()
		return self.current_state()


provider_control_service = ProviderControlService()

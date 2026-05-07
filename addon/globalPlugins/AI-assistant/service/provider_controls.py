# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from ..config.settings import (
	get_provider,
	get_provider_state,
	save,
	set_model_name,
	set_ollama_think,
	set_provider,
)
from ..config.state import ProviderState
from .provider_readiness import ProviderReadiness, ProviderReadinessService


@dataclass(frozen=True, slots=True)
class ProviderControlResult:
	provider_state: ProviderState
	readiness: ProviderReadiness


class ProviderControlService:
	PROVIDER_ORDER = ("ollama", "gemini", "openai")

	def __init__(self, readiness_service: ProviderReadinessService | None = None) -> None:
		self._readiness_service = readiness_service or ProviderReadinessService()

	def current_state(self) -> ProviderControlResult:
		return ProviderControlResult(
			provider_state=get_provider_state(),
			readiness=self._readiness_service.evaluate_active(),
		)

	def select_provider(self, provider: str) -> ProviderControlResult:
		set_provider(provider)
		save()
		return self.current_state()

	def cycle_provider(self) -> ProviderControlResult:
		current_provider = get_provider()
		if current_provider not in self.PROVIDER_ORDER:
			target_provider = self.PROVIDER_ORDER[0]
		else:
			target_provider = self.PROVIDER_ORDER[(self.PROVIDER_ORDER.index(current_provider) + 1) % len(self.PROVIDER_ORDER)]
		return self.select_provider(target_provider)

	def select_model(self, model: str, provider: str | None = None) -> ProviderControlResult:
		if provider:
			set_provider(provider)
		set_model_name(model)
		save()
		return self.current_state()

	def set_think_mode(self, enabled: bool) -> ProviderControlResult:
		set_ollama_think(enabled)
		save()
		return self.current_state()


provider_control_service = ProviderControlService()

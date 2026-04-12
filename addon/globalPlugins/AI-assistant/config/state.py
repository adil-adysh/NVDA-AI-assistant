# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ProviderState:
	provider: str
	model_name: str
	backend_url: str


_provider_state_listeners: list[Callable[[ProviderState], None]] = []


def get_provider_state(active_provider: Any) -> ProviderState:
	from ..providers.config import GeminiConfig, OllamaConfig

	backend_url = ""
	if isinstance(active_provider, GeminiConfig):
		backend_url = active_provider.base_url
	elif isinstance(active_provider, OllamaConfig):
		backend_url = active_provider.server_url

	return ProviderState(
		provider=active_provider.provider,
		model_name=active_provider.model_name,
		backend_url=backend_url,
	)


def subscribe_provider_state_change(listener: Callable[[ProviderState], None]) -> None:
	if listener not in _provider_state_listeners:
		_provider_state_listeners.append(listener)


def unsubscribe_provider_state_change(listener: Callable[[ProviderState], None]) -> None:
	if listener in _provider_state_listeners:
		_provider_state_listeners.remove(listener)


def _notify_provider_state_changed(get_current_state: Callable[[], ProviderState]) -> None:
	state = get_current_state()
	for listener in list(_provider_state_listeners):
		try:
			listener(state)
		except Exception:
			pass

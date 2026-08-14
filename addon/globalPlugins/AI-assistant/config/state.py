# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from logHandler import log


@dataclass(frozen=True)
class ProviderState:
	provider: str
	model_name: str
	backend_url: str


_provider_state_listeners: list[Callable[[ProviderState], None]] = []


def get_provider_state(active_provider: Any) -> ProviderState:
	backend_url = str(getattr(active_provider, "base_url", "") or "")

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
			log.exception("Error notifying provider state listener")


_litert_server_config_listeners: list[Callable[[], None]] = []

_llama_server_config_listeners: list[Callable[[], None]] = []


def subscribe_litert_server_config_change(listener: Callable[[], None]) -> None:
	"""Register *listener* to fire when LiteRT server engine settings change.

	The listener runs synchronously on the thread that persisted the
	change (typically the NVDA main thread) and must not block.
	"""
	if listener not in _litert_server_config_listeners:
		_litert_server_config_listeners.append(listener)


def unsubscribe_litert_server_config_change(listener: Callable[[], None]) -> None:
	"""Remove a previously registered *listener*."""
	if listener in _litert_server_config_listeners:
		_litert_server_config_listeners.remove(listener)


def _notify_litert_server_config_changed() -> None:
	"""Fire the LiteRT server engine-config-change event to all listeners."""
	for listener in list(_litert_server_config_listeners):
		try:
			listener()
		except Exception:
			log.exception("Error notifying LiteRT server config listener")


def subscribe_llama_server_config_change(listener: Callable[[], None]) -> None:
	if listener not in _llama_server_config_listeners:
		_llama_server_config_listeners.append(listener)


def unsubscribe_llama_server_config_change(listener: Callable[[], None]) -> None:
	if listener in _llama_server_config_listeners:
		_llama_server_config_listeners.remove(listener)


def _notify_llama_server_config_changed() -> None:
	for listener in list(_llama_server_config_listeners):
		try:
			listener()
		except Exception:
			log.exception("Error notifying llama-server config listener")

"""Bounded, non-mutating connection diagnostics for provider configuration."""
from collections.abc import Callable
from dataclasses import replace

from ..providers.config import ProviderConfig
from ..providers.factory import ProviderFactory
from ..providers.interfaces import LLMProvider


class ProviderConnectionService:
	def __init__(self, provider_factory: Callable[[ProviderConfig], LLMProvider] = ProviderFactory.create_provider) -> None:
		self._provider_factory = provider_factory

	def check(self, config: ProviderConfig) -> int:
		# Testing a form must not retry for minutes or change the active provider.
		config = replace(config, timeout_seconds=min(config.timeout_seconds, 15.0), max_retries=0)
		provider = self._provider_factory(config)
		try:
			return provider.check_connection()
		finally:
			provider.close()
